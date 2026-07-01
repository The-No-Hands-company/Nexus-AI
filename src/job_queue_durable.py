"""
Durable Job Queue with Dead-Letter Support.

Extends the existing task_queue.py with:
- Dead-letter queue (DLQ) for jobs that fail after max retries
- Exponential backoff retry strategy
- Batch retry and batch dead-letter operations
- Job replay from dead-letter
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .db import load_pref, save_pref

logger = logging.getLogger(__name__)

# ── data models ──────────────────────────────────────────────────────


@dataclass
class DeadLetterEntry:
    id: str
    original_task_id: str
    description: str
    error: str
    retry_count: int
    max_retries: int
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


_DLQ: dict[str, DeadLetterEntry] = {}
_DLQ_LOCK = threading.Lock()

# ── retry policy ─────────────────────────────────────────────────────

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECS = 2.0  # 2s → 4s → 8s → 16s ...


def _backoff_delay(attempt: int, base: float = _DEFAULT_BASE_BACKOFF_SECS) -> float:
    """Exponential backoff: base * 2^attempt capped at 600s."""
    return min(base * (2 ** max(0, attempt)), 600.0)


# ── dead-letter queue operations ─────────────────────────────────────


def add_to_dlq(
    task_id: str,
    description: str,
    error: str,
    retry_count: int = 0,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    metadata: dict[str, Any] | None = None,
) -> DeadLetterEntry:
    entry = DeadLetterEntry(
        id=f"dlq-{uuid.uuid4().hex[:10]}",
        original_task_id=task_id,
        description=str(description),
        error=str(error),
        retry_count=retry_count,
        max_retries=max_retries,
        metadata=dict(metadata or {}),
    )
    with _DLQ_LOCK:
        _DLQ[entry.id] = entry
    _persist_dlq()
    return entry


def list_dlq(limit: int = 100) -> list[dict[str, Any]]:
    with _DLQ_LOCK:
        entries = sorted(_DLQ.values(), key=lambda e: e.created_at, reverse=True)
    return [
        {
            "id": e.id,
            "original_task_id": e.original_task_id,
            "description": e.description,
            "error": e.error,
            "retry_count": e.retry_count,
            "max_retries": e.max_retries,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e.created_at)),
            "metadata": e.metadata,
        }
        for e in entries[:limit]
    ]


def get_dlq_entry(dlq_id: str) -> dict[str, Any] | None:
    with _DLQ_LOCK:
        entry = _DLQ.get(dlq_id)
    if entry is None:
        return None
    return {
        "id": entry.id,
        "original_task_id": entry.original_task_id,
        "description": entry.description,
        "error": entry.error,
        "retry_count": entry.retry_count,
        "max_retries": entry.max_retries,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry.created_at)),
        "metadata": entry.metadata,
    }


def retry_from_dlq(dlq_id: str) -> dict[str, Any] | None:
    """Re-submit a dead-lettered task and remove from DLQ."""
    with _DLQ_LOCK:
        entry = _DLQ.pop(dlq_id, None)

    if entry is None:
        return None

    try:
        from .task_queue import submit_task

        new_task_id = submit_task(
            description=entry.description,
            priority=5,
            metadata={**entry.metadata, "_retried_from_dlq": dlq_id, "_retry_attempt": entry.retry_count + 1},
        )
    except Exception as exc:
        # Re-add to DLQ if resubmission fails
        with _DLQ_LOCK:
            _DLQ[dlq_id] = entry
        return {"error": str(exc), "dlq_id": dlq_id, "status": "re-enqueued-to-dlq"}

    _persist_dlq()
    return {"dlq_id": dlq_id, "new_task_id": new_task_id, "status": "retried"}


def purge_dlq() -> int:
    with _DLQ_LOCK:
        count = len(_DLQ)
        _DLQ.clear()
    _persist_dlq()
    return count


def delete_from_dlq(dlq_id: str) -> bool:
    with _DLQ_LOCK:
        if dlq_id in _DLQ:
            del _DLQ[dlq_id]
            _persist_dlq()
            return True
    return False


# ── retry orchestrator ───────────────────────────────────────────────


def execute_with_retry(
    task_id: str,
    description: str,
    runner_fn,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a task with exponential-backoff retry, sending failures to DLQ.

    Returns {status, result, retry_count, ...}
    """
    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            result = runner_fn(description)
            return {"status": "done", "result": str(result), "retry_count": attempt, "task_id": task_id}
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries:
                delay = _backoff_delay(attempt)
                logger.warning("job_retry task_id=%s attempt=%d/%d delay=%.1fs error=%s", task_id, attempt + 1, max_retries, delay, last_error)
                time.sleep(delay)
            else:
                logger.error("job_exhausted_retries task_id=%s attempts=%d error=%s", task_id, max_retries, last_error)

    # Send to DLQ
    add_to_dlq(task_id, description, last_error, retry_count=max_retries, max_retries=max_retries, metadata=metadata)
    return {"status": "dead_lettered", "error": last_error, "retry_count": max_retries, "task_id": task_id}


# ── persistence ──────────────────────────────────────────────────────


def _persist_dlq() -> None:
    try:
        data = [
            {
                "id": e.id,
                "original_task_id": e.original_task_id,
                "description": e.description,
                "error": e.error,
                "retry_count": e.retry_count,
                "max_retries": e.max_retries,
                "created_at": e.created_at,
                "metadata": e.metadata,
            }
            for e in _DLQ.values()
        ]
        save_pref("dead_letter_queue", json.dumps(data))
    except Exception:
        logger.warning("dlq_persist_failed", exc_info=True)


def restore_dlq() -> int:
    """Restore dead-letter queue from persistent storage."""
    global _DLQ
    try:
        raw = load_pref("dead_letter_queue", "")
        if not raw:
            return 0
        data = json.loads(raw)
        if not isinstance(data, list):
            return 0
        restored = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            entry = DeadLetterEntry(
                id=str(item.get("id", f"dlq-{uuid.uuid4().hex[:10]}")),
                original_task_id=str(item.get("original_task_id", "")),
                description=str(item.get("description", "")),
                error=str(item.get("error", "")),
                retry_count=int(item.get("retry_count", 0)),
                max_retries=int(item.get("max_retries", _DEFAULT_MAX_RETRIES)),
                created_at=float(item.get("created_at", time.time())),
                metadata=dict(item.get("metadata", {})),
            )
            _DLQ[entry.id] = entry
            restored += 1
        return restored
    except Exception:
        logger.warning("dlq_restore_failed", exc_info=True)
        return 0


def dlq_stats() -> dict[str, Any]:
    with _DLQ_LOCK:
        total = len(_DLQ)
        errors: dict[str, int] = {}
        for e in _DLQ.values():
            err_type = e.error.split(":")[0].strip()[:60] or "unknown"
            errors[err_type] = errors.get(err_type, 0) + 1

    return {
        "total_dead_letters": total,
        "error_breakdown": dict(sorted(errors.items(), key=lambda x: x[1], reverse=True)[:10]),
    }
