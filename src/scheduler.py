"""src/scheduler.py — Autonomous background job scheduler for Nexus AI.

Supports simple interval schedules (30s, 5m, 2h, 1d) and basic cron expressions
(5 fields: min hour dom mon dow, with */N, specific values, and '*' wildcards).

Jobs are stored in-memory (lost on restart). Each job runs the agent task string
via a provided callable — callers inject the run function to avoid circular imports.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ── Job model ─────────────────────────────────────────────────────────────────

@dataclass
class JobLog:
    run_at: str
    status: str          # "ok" | "error"
    summary: str         # first 300 chars of agent output / error message


@dataclass
class ScheduledJob:
    id: str
    name: str
    task: str            # natural-language task string sent to the agent
    schedule: str        # "5m" | "1h" | "30s" | "1d" or basic cron "*/5 * * * *"
    status: str          # "active" | "paused" | "cancelled"
    created_at: str
    interval_secs: Optional[int] = None   # resolved seconds between runs
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    run_count: int = 0
    logs: List[JobLog] = field(default_factory=list)


# ── Registry ──────────────────────────────────────────────────────────────────

_jobs: Dict[str, ScheduledJob] = {}
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_running = False
_run_fn: Optional[Callable[[str], str]] = None   # injected by routes.py


def set_run_function(fn: Callable[[str], str]) -> None:
    """Inject the function used to execute a scheduled task (avoids circular imports)."""
    global _run_fn
    _run_fn = fn


# ── Schedule parsing ──────────────────────────────────────────────────────────

def _parse_interval_secs(schedule: str) -> Optional[int]:
    """Parse '30s', '5m', '2h', '1d' → seconds.  Returns None if not an interval."""
    s = schedule.strip().lower()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    for suffix, mult in multipliers.items():
        if s.endswith(suffix) and s[:-1].isdigit():
            return int(s[:-1]) * mult
    return None


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Return True if *dt* matches the 5-field cron expression.

    Supports: '*', '*/N' (step), comma-separated values, single integers.
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts

        def field_ok(spec: str, value: int) -> bool:
            if spec == "*":
                return True
            if spec.startswith("*/"):
                step = int(spec[2:])
                return value % step == 0
            # Comma-separated list
            return value in {int(x) for x in spec.split(",")}

        return (
            field_ok(minute, dt.minute)
            and field_ok(hour, dt.hour)
            and field_ok(dom, dt.day)
            and field_ok(month, dt.month)
            and field_ok(dow, dt.weekday())
        )
    except Exception:
        return False


def _schedule_is_cron(schedule: str) -> bool:
    return len(schedule.strip().split()) == 5


# ── Public API ────────────────────────────────────────────────────────────────

def schedule_job(name: str, task: str, schedule: str) -> ScheduledJob:
    """Create and register a new scheduled job.  Starts the runner if not running."""
    interval = _parse_interval_secs(schedule)
    if interval is None and not _schedule_is_cron(schedule):
        raise ValueError(
            f"Invalid schedule '{schedule}'. "
            "Use an interval like '5m', '1h', '30s', '1d' or a 5-field cron expression."
        )

    now = datetime.now(timezone.utc)
    job = ScheduledJob(
        id=str(uuid.uuid4())[:8],
        name=name,
        task=task,
        schedule=schedule,
        status="active",
        created_at=now.isoformat(),
        interval_secs=interval,
        next_run=_compute_next_run(schedule, interval, now),
    )
    with _lock:
        _jobs[job.id] = job
    _ensure_runner()
    return job


def list_jobs() -> List[ScheduledJob]:
    with _lock:
        return list(_jobs.values())


def get_job(job_id: str) -> Optional[ScheduledJob]:
    with _lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        job.status = "cancelled"
        return True


def pause_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        job.status = "paused"
        return True


def resume_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        job.status = "active"
        return True


def delete_job(job_id: str) -> bool:
    with _lock:
        if job_id in _jobs:
            del _jobs[job_id]
            return True
        return False


# ── Runner internals ──────────────────────────────────────────────────────────

def _compute_next_run(schedule: str, interval_secs: Optional[int], after: datetime) -> str:
    import datetime as _dt
    if interval_secs:
        return (after + _dt.timedelta(seconds=interval_secs)).isoformat()
    # For cron: scan the next 60 minutes at 1-minute resolution
    t = after.replace(second=0, microsecond=0)
    for _ in range(1441):
        t = t + _dt.timedelta(minutes=1)
        if _cron_matches(schedule, t):
            return t.isoformat()
    return after.isoformat()   # fallback (shouldn't happen with valid cron)


def _run_job(job: ScheduledJob) -> None:
    """Execute a single job invocation in the current thread."""
    run_at = datetime.now(timezone.utc).isoformat()
    try:
        if _run_fn:
            result = _run_fn(job.task)
            summary = str(result)[:300]
            log_status = "ok"
        else:
            summary = "No run function injected — task queued but not executed."
            log_status = "error"
    except Exception as exc:
        summary = f"Error: {exc}"
        log_status = "error"

    with _lock:
        job.last_run = run_at
        job.run_count += 1
        job.logs.append(JobLog(run_at=run_at, status=log_status, summary=summary))
        # Keep last 50 log entries
        if len(job.logs) > 50:
            job.logs = job.logs[-50:]
        # Compute next run
        now = datetime.now(timezone.utc)
        job.next_run = _compute_next_run(job.schedule, job.interval_secs, now)
        if log_status == "error":
            job.status = "error"


def _scheduler_loop() -> None:
    global _running
    while _running:
        now = datetime.now(timezone.utc)
        with _lock:
            due = [
                j for j in _jobs.values()
                if j.status == "active" and j.next_run and j.next_run <= now.isoformat()
            ]
        for job in due:
            # Run in a daemon thread so the scheduler loop doesn't block
            t = threading.Thread(target=_run_job, args=(job,), daemon=True)
            t.start()
        time.sleep(10)  # check every 10 seconds


def _ensure_runner() -> None:
    global _thread, _running
    if _running and _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name="nexus-scheduler")
    _thread.start()


def stop_runner() -> None:
    global _running
    _running = False


# ── Serialisation helpers ─────────────────────────────────────────────────────

def job_to_dict(job: ScheduledJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "task": job.task,
        "schedule": job.schedule,
        "status": job.status,
        "created_at": job.created_at,
        "next_run": job.next_run,
        "last_run": job.last_run,
        "run_count": job.run_count,
        "logs": [{"run_at": l.run_at, "status": l.status, "summary": l.summary}
                 for l in job.logs[-10:]],  # last 10 in summary view
    }
