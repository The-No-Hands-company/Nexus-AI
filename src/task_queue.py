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

import hashlib
import heapq
import json
import threading
import time
import uuid
from collections import defaultdict
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
    dedupe: bool = True,
) -> str:
    """Submit a task to the priority queue. Returns the new task_id.

    Identical pending/running tasks are deduplicated via a distributed key,
    preventing retry storms from enqueuing duplicate work.
    """
    from .redis_state import distributed_lock, redis_get, redis_set

    dep_list = list(deps or [])
    meta = dict(metadata or {})
    # Ignore ephemeral metadata fields that should not affect task identity.
    dedup_meta = {k: v for k, v in meta.items() if not str(k).startswith("_")}
    dedup_payload = {
        "description": str(description).strip(),
        "priority": int(priority),
        "deps": sorted(str(d) for d in dep_list),
        "metadata": dedup_meta,
        "schedule_cron": str(schedule_cron or ""),
    }
    dedup_sig = hashlib.sha256(
        json.dumps(dedup_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    dedup_key = f"task:dedup:{dedup_sig}"

    # Serialise dedup checks across workers so only one task is enqueued.
    if dedupe:
        with distributed_lock(f"task-submit:{dedup_sig}", ttl=10, retry_count=30) as acquired:
            if acquired:
                existing_id = redis_get(dedup_key)
                if isinstance(existing_id, str):
                    existing = _tasks.get(existing_id)
                    if existing and existing.status in (TASK_PENDING, TASK_RUNNING):
                        return existing_id
                    persisted = get_task(existing_id)
                    if persisted and persisted.get("status") in (TASK_PENDING, TASK_RUNNING):
                        return existing_id

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    task = QueuedTask(
        task_id=task_id,
        description=description,
        priority=priority,
        dependencies=dep_list,
        metadata=meta,
        schedule_cron=schedule_cron,
    )
    task.metadata["_dedup_signature"] = dedup_sig
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
    # Keep a short-lived mapping for dedup across workers and restarts.
    if dedupe:
        redis_set(dedup_key, task_id, ex=3600)
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
            try:
                from .redis_state import redis_delete, redis_get

                dedup_sig = str(ready.metadata.get("_dedup_signature", "")).strip()
                if dedup_sig:
                    dedup_key = f"task:dedup:{dedup_sig}"
                    if redis_get(dedup_key) == ready.task_id:
                        redis_delete(dedup_key)
            except Exception:
                pass

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


def get_task_runtime_status(task_id: str) -> Optional[Dict[str, Any]]:
    """Return detailed queue/runtime status for a task, including blockers and queue position."""
    task = _tasks.get(task_id)
    if task is None:
        persisted = get_task(task_id)
        if persisted is None:
            return None
        return {
            **persisted,
            "queue_position": None,
            "blocked_by": [],
            "deps_satisfied": True,
            "worker_running": bool(_worker_thread is not None and _worker_thread.is_alive()),
            "can_cancel": str(persisted.get("status") or "") not in (TASK_DONE, TASK_FAILED, TASK_CANCELLED),
        }

    with _heap_lock:
        pending_order = sorted(
            [t for t in _tasks.values() if t.status == TASK_PENDING],
            key=lambda t: (t.priority, t.created_at),
        )
    queue_position = None
    for idx, pending in enumerate(pending_order, start=1):
        if pending.task_id == task_id:
            queue_position = idx
            break

    blocked_by = []
    for dep_id in task.dependencies:
        dep = _tasks.get(dep_id)
        dep_status = dep.status if dep else "missing"
        if dep_status != TASK_DONE:
            blocked_by.append({"task_id": dep_id, "status": dep_status})

    payload = _task_to_dict(task)
    payload.update(
        {
            "queue_position": queue_position,
            "blocked_by": blocked_by,
            "deps_satisfied": not blocked_by,
            "worker_running": bool(_worker_thread is not None and _worker_thread.is_alive()),
            "can_cancel": task.status not in (TASK_DONE, TASK_FAILED, TASK_CANCELLED),
        }
    )
    return payload


def list_task_sessions(limit: int = 200) -> List[Dict[str, Any]]:
    """Aggregate task sessions from task metadata.session_id and return counts by status."""
    sessions: Dict[str, Dict[str, Any]] = {}
    status_counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for task in _tasks.values():
        session_id = str(task.metadata.get("session_id") or "").strip()
        if not session_id:
            continue
        if session_id not in sessions:
            sessions[session_id] = {
                "session_id": session_id,
                "created_at": datetime.fromtimestamp(task.created_at, tz=timezone.utc).isoformat(),
                "latest_task_at": datetime.fromtimestamp(task.created_at, tz=timezone.utc).isoformat(),
            }
        latest = sessions[session_id].get("latest_task_at") or ""
        current = datetime.fromtimestamp(task.created_at, tz=timezone.utc).isoformat()
        if current > latest:
            sessions[session_id]["latest_task_at"] = current
        status_counters[session_id][task.status] += 1

    rows = []
    for session_id, meta in sessions.items():
        counters = status_counters.get(session_id, {})
        rows.append(
            {
                **meta,
                "counts": {
                    "pending": int(counters.get(TASK_PENDING, 0)),
                    "running": int(counters.get(TASK_RUNNING, 0)),
                    "done": int(counters.get(TASK_DONE, 0)),
                    "failed": int(counters.get(TASK_FAILED, 0)),
                    "cancelled": int(counters.get(TASK_CANCELLED, 0)),
                },
                "total_tasks": int(sum(counters.values())),
            }
        )

    rows.sort(key=lambda row: row.get("latest_task_at", ""), reverse=True)
    return rows[: max(1, limit)]


def get_session_tasks(session_id: str, status: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    """List tasks for a single session identifier."""
    sid = str(session_id or "").strip()
    if not sid:
        return []
    rows = []
    for task in _tasks.values():
        if str(task.metadata.get("session_id") or "").strip() != sid:
            continue
        if status and task.status != status:
            continue
        rows.append(_task_to_dict(task))
    rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return rows[: max(1, limit)]


def cancel_session_tasks(session_id: str, include_running: bool = True) -> Dict[str, Any]:
    """Cancel pending tasks for a session and optionally running tasks."""
    sid = str(session_id or "").strip()
    if not sid:
        return {"session_id": sid, "cancelled": 0, "task_ids": []}

    cancelled_ids: List[str] = []
    for task in _tasks.values():
        if str(task.metadata.get("session_id") or "").strip() != sid:
            continue
        if task.status == TASK_PENDING or (include_running and task.status == TASK_RUNNING):
            if cancel_task(task.task_id):
                cancelled_ids.append(task.task_id)

    return {"session_id": sid, "cancelled": len(cancelled_ids), "task_ids": cancelled_ids}
