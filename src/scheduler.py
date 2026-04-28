from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable


_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}
_run_function: Callable[[str], Any] | None = None


class Job:
    """Scheduler job with attribute and dict-style access."""

    __slots__ = (
        "id", "name", "task", "schedule", "metadata",
        "max_retries", "retry_backoff_secs", "status",
        "created_at", "updated_at", "last_result", "next_run", "run_count",
    )

    def __init__(self, data: dict[str, Any]) -> None:
        for k in self.__slots__:
            setattr(self, k, data.get(k))

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def set_run_function(fn: Callable[[str], Any]) -> None:
    global _run_function
    _run_function = fn


def _persist(job: Job) -> None:
    try:
        from .db import upsert_scheduled_job
        upsert_scheduled_job(job.to_dict())
    except Exception:
        pass


def schedule_job(
    name: str,
    task: str,
    schedule: str,
    metadata: dict[str, Any] | None = None,
    max_retries: int = 0,
    retry_backoff_secs: int = 60,
) -> Job:
    job_id = uuid.uuid4().hex
    data = {
        "id": job_id,
        "name": name,
        "task": task,
        "schedule": schedule,
        "metadata": metadata or {},
        "max_retries": max_retries,
        "retry_backoff_secs": retry_backoff_secs,
        "status": "scheduled",
        "created_at": time.time(),
        "updated_at": time.time(),
        "last_result": None,
        "next_run": None,
        "run_count": 0,
    }
    job = Job(data)
    with _lock:
        _jobs[job_id] = job
    _persist(job)
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(str(job_id))


def list_jobs() -> list[Job]:
    with _lock:
        return list(_jobs.values())


def cancel_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        job.status = "cancelled"
        job.updated_at = time.time()
    _persist(job)
    return True


def delete_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.pop(job_id, None)
    if job is None:
        return False
    try:
        from .db import delete_scheduled_job
        delete_scheduled_job(job_id)
    except Exception:
        pass
    return True


def job_to_dict(job: Job) -> dict[str, Any]:
    return job.to_dict()


def restore_from_db() -> list[Job]:
    try:
        from .db import load_scheduled_jobs
        rows = load_scheduled_jobs()
    except Exception:
        return []
    restored: list[Job] = []
    with _lock:
        for row in rows:
            job = Job(row)
            if job.id:
                _jobs[job.id] = job
                restored.append(job)
    return restored


def run_job_now(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if _run_function is None:
        result = ""
    else:
        result = _run_function(job.task)
    job.status = "done"
    job.updated_at = time.time()
    job.last_result = result
    _persist(job)
    return job.to_dict()


def _background_runner(job_id: str) -> None:
    try:
        run_job_now(job_id)
    except Exception as exc:
        with _lock:
            job = _jobs.get(job_id)
        if job is not None:
            job.status = "failed"
            job.last_result = str(exc)
            job.updated_at = time.time()
            _persist(job)


def schedule_background_run(job_id: str) -> None:
    threading.Thread(target=_background_runner, args=(job_id,), daemon=True).start()
