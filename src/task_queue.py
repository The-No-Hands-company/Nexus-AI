"""
Nexus AI Task Queue — priority queue, DAG dependency scheduling,
background worker, task cancellation, cross-task memory sharing,
and cron-triggered re-run integration.

Public API
----------
submit_task(description, priority, deps, metadata, schedule_cron) -> task_id
cancel_task(task_id) -> bool
get_task(task_id) -> dict | None
list_tasks(status, limit) -> list[dict]
get_shared_memory(key) -> Any
set_shared_memory(key, value) -> None
start_worker() / stop_worker()
"""

from __future__ import annotations

import heapq
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .db import (
    db_delete_shared_memory,
    db_get_shared_memory,
    db_list_shared_memory,
    db_save_task_job,
    db_set_shared_memory,
    db_list_task_jobs,
)

# ─────────────────────────────────────────────────────────────────────────────
# Task data model
# ─────────────────────────────────────────────────────────────────────────────

TASK_PENDING   = "pending"
TASK_RUNNING   = "running"
TASK_DONE      = "done"
TASK_FAILED    = "failed"
TASK_CANCELLED = "cancelled"


@dataclass
class QueuedTask:
    task_id:       str
    description:   str
    priority:      int          # lower = higher priority (like heap)
    dependencies:  List[str]    # task_ids that must be DONE before this runs
    metadata:      Dict[str, Any]
    schedule_cron: str          # empty = run once; cron expr = re-enqueue on trigger
    status:        str          = TASK_PENDING
    result:        str          = ""
    error:         str          = ""
    created_at:    float        = field(default_factory=time.time)
    started_at:    Optional[float] = None
    finished_at:   Optional[float] = None
    cancel_event:  threading.Event = field(default_factory=threading.Event)

    # Heap comparison (lower priority int = runs first)
    def __lt__(self, other: "QueuedTask") -> bool:
        return self.priority < other.priority


# ─────────────────────────────────────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────────────────────────────────────

_tasks: Dict[str, QueuedTask] = {}       # task_id → QueuedTask
_heap:  List[QueuedTask]      = []       # min-heap ordered by priority
_heap_lock = threading.Lock()
_new_task_event = threading.Event()

# Cross-task shared memory (key-value store visible to all tasks)
_shared_memory: Dict[str, Any] = {}
_shared_memory_lock = threading.RLock()

# Background worker thread
_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

# Runner function (injected at startup to avoid circular imports)
_task_runner: Optional[Callable[[str, str, threading.Event], str]] = None


def _restore_tasks_from_db() -> None:
    """Rehydrate non-terminal tasks from persistent storage into the live worker heap."""
    persisted = db_list_task_jobs(limit=1000)
    with _heap_lock:
        for row in persisted:
            task_id = str(row.get("task_id") or "")
            if not task_id or task_id in _tasks:
                continue
            status = str(row.get("status") or TASK_PENDING)
            if status in (TASK_DONE, TASK_FAILED, TASK_CANCELLED):
                continue
            task = QueuedTask(
                task_id=task_id,
                description=str(row.get("description") or ""),
                priority=int(row.get("priority") or 5),
                dependencies=list(row.get("dependencies") or []),
                metadata=dict(row.get("metadata") or {}),
                schedule_cron=str(row.get("schedule_cron") or ""),
                status=TASK_PENDING,
                result=str(row.get("result") or ""),
                error=str(row.get("error") or ""),
                created_at=float(row.get("created_at") or time.time()),
                started_at=None,
                finished_at=float(row.get("finished_at")) if row.get("finished_at") else None,
            )
            _tasks[task_id] = task
            heapq.heappush(_heap, task)


# ─────────────────────────────────────────────────────────────────────────────
# Shared memory
# ─────────────────────────────────────────────────────────────────────────────

def get_shared_memory(key: str) -> Any:
    with _shared_memory_lock:
        if key in _shared_memory:
            return _shared_memory.get(key)
    value = db_get_shared_memory(key)
    if value is not None:
        with _shared_memory_lock:
            _shared_memory[key] = value
    return value


def set_shared_memory(key: str, value: Any) -> None:
    with _shared_memory_lock:
        _shared_memory[key] = value
    db_set_shared_memory(key, value)


def delete_shared_memory(key: str) -> bool:
    with _shared_memory_lock:
        if key in _shared_memory:
            del _shared_memory[key]
            db_delete_shared_memory(key)
            return True
    return db_delete_shared_memory(key)


def list_shared_memory() -> Dict[str, Any]:
    with _shared_memory_lock:
        merged = dict(db_list_shared_memory())
        merged.update(_shared_memory)
        return merged


# ─────────────────────────────────────────────────────────────────────────────
# Task submission and management
# ─────────────────────────────────────────────────────────────────────────────

def submit_task(
    description: str,
    priority: int = 5,
    deps: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    schedule_cron: str = "",
) -> str:
    """Submit a task to the priority queue. Returns the new task_id."""
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    task = QueuedTask(
        task_id=task_id,
        description=description,
        priority=priority,
        dependencies=list(deps or []),
        metadata=dict(metadata or {}),
        schedule_cron=schedule_cron,
    )
    _tasks[task_id] = task
    db_save_task_job(
        task_id=task.task_id,
        description=task.description,
        priority=task.priority,
        dependencies=task.dependencies,
        metadata=task.metadata,
        schedule_cron=task.schedule_cron,
        status=task.status,
        result=task.result,
        error=task.error,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )
    with _heap_lock:
        heapq.heappush(_heap, task)
    _new_task_event.set()
    return task_id


def cancel_task(task_id: str) -> bool:
    """Cancel a pending or running task."""
    task = _tasks.get(task_id)
    if task is None:
        return False
    if task.status in (TASK_DONE, TASK_FAILED, TASK_CANCELLED):
        return False
    task.cancel_event.set()
    task.status = TASK_CANCELLED
    task.finished_at = time.time()
    db_save_task_job(
        task_id=task.task_id,
        description=task.description,
        priority=task.priority,
        dependencies=task.dependencies,
        metadata=task.metadata,
        schedule_cron=task.schedule_cron,
        status=task.status,
        result=task.result,
        error=task.error,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )
    return True


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    task = _tasks.get(task_id)
    if task:
        return _task_to_dict(task)
    for persisted in db_list_task_jobs(limit=500):
        if persisted.get("task_id") == task_id:
            return persisted
    return None


def list_tasks(status: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    persisted = db_list_task_jobs(status=status, limit=limit)
    live_tasks = list(_tasks.values())
    if status:
        live_tasks = [t for t in live_tasks if t.status == status]
    live_tasks.sort(key=lambda t: t.created_at, reverse=True)
    merged = {t["task_id"]: t for t in persisted}
    for task in live_tasks:
        merged[task.task_id] = _task_to_dict(task)
    result = list(merged.values())
    result.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return result[:limit]


def _task_to_dict(task: QueuedTask) -> Dict[str, Any]:
    return {
        "task_id":       task.task_id,
        "description":   task.description,
        "priority":      task.priority,
        "dependencies":  task.dependencies,
        "status":        task.status,
        "result":        task.result,
        "error":         task.error,
        "metadata":      task.metadata,
        "schedule_cron": task.schedule_cron,
        "created_at":    datetime.fromtimestamp(task.created_at, tz=timezone.utc).isoformat(),
        "started_at":    datetime.fromtimestamp(task.started_at, tz=timezone.utc).isoformat()
                         if task.started_at else None,
        "finished_at":   datetime.fromtimestamp(task.finished_at, tz=timezone.utc).isoformat()
                         if task.finished_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DAG dependency resolution
# ─────────────────────────────────────────────────────────────────────────────

def _deps_satisfied(task: QueuedTask) -> bool:
    """Return True if all dependencies are in TASK_DONE state."""
    for dep_id in task.dependencies:
        dep = _tasks.get(dep_id)
        if dep is None or dep.status != TASK_DONE:
            return False
    return True


def get_dag_status() -> Dict[str, Any]:
    """Return DAG state: which tasks are blocked, ready, running, done."""
    result: Dict[str, List[str]] = {
        "blocked": [], "ready": [], "running": [], "done": [],
        "failed": [], "cancelled": [],
    }
    for task in _tasks.values():
        if task.status in (TASK_DONE, TASK_FAILED, TASK_CANCELLED, TASK_RUNNING):
            result[task.status].append(task.task_id)
        elif task.status == TASK_PENDING:
            if _deps_satisfied(task):
                result["ready"].append(task.task_id)
            else:
                result["blocked"].append(task.task_id)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Background worker
# ─────────────────────────────────────────────────────────────────────────────

def set_task_runner(fn: Callable[[str, str, threading.Event], str]) -> None:
    """Inject the task runner function (avoids circular import from agent.py)."""
    global _task_runner
    _task_runner = fn


def _worker_loop() -> None:
    while not _stop_event.is_set():
        _new_task_event.wait(timeout=2.0)
        _new_task_event.clear()

        with _heap_lock:
            # Find the highest-priority ready task (deps satisfied, not cancelled)
            ready: Optional[QueuedTask] = None
            skipped: List[QueuedTask] = []
            while _heap:
                candidate = heapq.heappop(_heap)
                if candidate.status == TASK_CANCELLED:
                    continue
                if candidate.status != TASK_PENDING:
                    continue
                if _deps_satisfied(candidate):
                    ready = candidate
                    break
                else:
                    skipped.append(candidate)
            for s in skipped:
                heapq.heappush(_heap, s)
            if skipped:
                _new_task_event.set()   # re-check later

        if ready is None:
            continue

        # Run the task
        ready.status = TASK_RUNNING
        ready.started_at = time.time()
        db_save_task_job(
            task_id=ready.task_id,
            description=ready.description,
            priority=ready.priority,
            dependencies=ready.dependencies,
            metadata=ready.metadata,
            schedule_cron=ready.schedule_cron,
            status=ready.status,
            result=ready.result,
            error=ready.error,
            created_at=ready.created_at,
            started_at=ready.started_at,
            finished_at=ready.finished_at,
        )
        try:
            if _task_runner is None:
                raise RuntimeError("No task runner registered. Call set_task_runner() at startup.")
            # Inject cross-task shared memory into metadata
            shared_snapshot = list_shared_memory()
            ready.metadata["_shared_memory_snapshot"] = shared_snapshot
            result = _task_runner(ready.task_id, ready.description, ready.cancel_event)
            if ready.cancel_event.is_set():
                ready.status = TASK_CANCELLED
            else:
                ready.status = TASK_DONE
                ready.result = str(result)
                # Persist result to shared memory under task_id
                set_shared_memory(f"task_result:{ready.task_id}", result)
        except Exception as exc:
            ready.status = TASK_FAILED
            ready.error = str(exc)
        finally:
            ready.finished_at = time.time()
            db_save_task_job(
                task_id=ready.task_id,
                description=ready.description,
                priority=ready.priority,
                dependencies=ready.dependencies,
                metadata=ready.metadata,
                schedule_cron=ready.schedule_cron,
                status=ready.status,
                result=ready.result,
                error=ready.error,
                created_at=ready.created_at,
                started_at=ready.started_at,
                finished_at=ready.finished_at,
            )

        # Re-enqueue if this is a scheduled (cron) task
        if ready.schedule_cron and ready.status == TASK_DONE:
            # Simple re-submit — the scheduler integration decides actual timing
            new_id = submit_task(
                description=ready.description,
                priority=ready.priority,
                deps=[],   # re-runs have no deps
                metadata={k: v for k, v in ready.metadata.items()
                          if not k.startswith("_")},
                schedule_cron=ready.schedule_cron,
            )
            # Mark the new task as pending-cron so caller can track lineage
            if new_task := _tasks.get(new_id):
                new_task.metadata["parent_task_id"] = ready.task_id

        _new_task_event.set()   # wake up for next task


def start_worker() -> None:
    """Start the background task worker thread (idempotent)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _restore_tasks_from_db()
    _worker_thread = threading.Thread(target=_worker_loop, name="task-queue-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    """Stop the background worker thread."""
    _stop_event.set()
    _new_task_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=5)


def worker_status() -> Dict[str, Any]:
    return {
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "queue_depth": len([t for t in _tasks.values() if t.status == TASK_PENDING]),
        "active": len([t for t in _tasks.values() if t.status == TASK_RUNNING]),
        "total_tasks": len(_tasks),
    }
