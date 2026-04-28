"""
src/evals/human_eval_pipeline.py — Human evaluation pipeline for AI outputs

Routes a configurable percentage of AI outputs to human raters for quality
judgment. Supports:
  - Pairwise preference comparisons (A vs B)
  - Absolute quality ratings (1–5 Likert scale)
  - Safety labeling (safe / borderline / unsafe)

Human eval tasks are stored in DB and surfaced via the /admin/human-eval API.
Results feed back into A/B experiment scoring and model quality metrics.

Environment variables:
    HUMAN_EVAL_SAMPLE_RATE  — fraction of requests to sample for human eval (default: 0.01 = 1%)
    HUMAN_EVAL_QUEUE_MAX    — maximum pending tasks before new ones are dropped (default: 1000)
    HUMAN_EVAL_EXPIRE_HOURS — hours before an uncompleted task expires (default: 72)
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("nexus.evals.human_eval")

_SAMPLE_RATE = float(os.getenv("HUMAN_EVAL_SAMPLE_RATE", "0.01"))
_QUEUE_MAX = int(os.getenv("HUMAN_EVAL_QUEUE_MAX", "1000"))
_EXPIRE_HOURS = int(os.getenv("HUMAN_EVAL_EXPIRE_HOURS", "72"))


@dataclass
class HumanEvalTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    task_type: str = "absolute"         # "absolute" | "pairwise" | "safety"
    prompt: str = ""
    response_a: str = ""
    response_b: str = ""                # only for pairwise
    context: dict = field(default_factory=dict)
    status: str = "pending"            # pending | completed | expired | skipped
    rating: Any = None                 # int (1-5) | "A" | "B" | "tie" | "safe" | "unsafe"
    rater_id: str = ""
    rater_notes: str = ""
    experiment_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    expires_at: str = field(default_factory=lambda: (
        datetime.now(timezone.utc) + timedelta(hours=int(os.getenv("HUMAN_EVAL_EXPIRE_HOURS", "72")))
    ).isoformat())


# ── Sampling decision ─────────────────────────────────────────────────────────

def should_sample(request_id: str) -> bool:
    """Deterministically decide if a request should be sampled for human eval."""
    h = int(hashlib.md5(request_id.encode()).hexdigest()[:8], 16)
    return (h / (2**32)) < _SAMPLE_RATE


# ── Task management ───────────────────────────────────────────────────────────

def _save_task(task: HumanEvalTask) -> None:
    try:
        from src.db import load_pref, save_pref  # type: ignore
        tasks = load_pref("human_eval:tasks") or {}
        tasks[task.task_id] = {
            "task_id": task.task_id, "task_type": task.task_type,
            "prompt": task.prompt[:2000], "response_a": task.response_a[:2000],
            "response_b": task.response_b[:2000], "context": task.context,
            "status": task.status, "rating": task.rating,
            "rater_id": task.rater_id, "rater_notes": task.rater_notes,
            "experiment_id": task.experiment_id,
            "created_at": task.created_at, "completed_at": task.completed_at,
            "expires_at": task.expires_at,
        }
        # Enforce queue max by dropping oldest completed tasks
        if len(tasks) > _QUEUE_MAX:
            completed = [k for k, v in tasks.items() if v.get("status") != "pending"]
            for k in completed[:len(tasks) - _QUEUE_MAX]:
                tasks.pop(k, None)
        save_pref("human_eval:tasks", tasks)
    except Exception as exc:
        logger.debug("save human eval task: %s", exc)


def create_eval_task(
    task_type: str,
    prompt: str,
    response_a: str,
    response_b: str = "",
    context: dict | None = None,
    experiment_id: str = "",
) -> HumanEvalTask:
    """Create and enqueue a new human evaluation task."""
    task = HumanEvalTask(
        task_type=task_type, prompt=prompt,
        response_a=response_a, response_b=response_b,
        context=context or {}, experiment_id=experiment_id,
    )
    _save_task(task)
    return task


def submit_rating(
    task_id: str,
    rating: Any,
    rater_id: str,
    notes: str = "",
) -> bool:
    """Submit a human rating for a task.

    For absolute tasks: rating is int 1–5.
    For pairwise tasks: rating is "A", "B", or "tie".
    For safety tasks: rating is "safe", "borderline", or "unsafe".
    """
    try:
        from src.db import load_pref, save_pref  # type: ignore
        tasks = load_pref("human_eval:tasks") or {}
        task = tasks.get(task_id)
        if not task:
            return False
        if task.get("status") != "pending":
            return False
        task["status"] = "completed"
        task["rating"] = rating
        task["rater_id"] = rater_id
        task["rater_notes"] = notes
        task["completed_at"] = datetime.now(timezone.utc).isoformat()
        tasks[task_id] = task
        save_pref("human_eval:tasks", tasks)

        # Feed result back to A/B experiment if linked
        exp_id = task.get("experiment_id")
        if exp_id:
            _record_to_ab(exp_id, task)
        return True
    except Exception as exc:
        logger.error("submit_rating: %s", exc)
        return False


def _record_to_ab(experiment_id: str, task: dict) -> None:
    """Forward completed human eval rating to A/B testing module."""
    try:
        from src.evals.ab_testing import record_observation  # type: ignore
        rating = task.get("rating")
        if isinstance(rating, int):
            metric_value = (rating - 1) / 4.0  # normalize 1-5 to 0-1
        elif rating == "A":
            metric_value = 1.0
        elif rating == "B":
            metric_value = 0.0
        elif rating == "tie":
            metric_value = 0.5
        elif rating == "safe":
            metric_value = 1.0
        elif rating == "borderline":
            metric_value = 0.5
        elif rating == "unsafe":
            metric_value = 0.0
        else:
            return
        record_observation(
            experiment_id=experiment_id,
            variant_id=task.get("context", {}).get("variant_id", "unknown"),
            user_id=task.get("rater_id", "human"),
            metric_value=metric_value,
        )
    except Exception:
        pass


def get_pending_tasks(limit: int = 20) -> list[dict]:
    """Return pending human eval tasks for the review UI."""
    try:
        from src.db import load_pref  # type: ignore
        tasks = load_pref("human_eval:tasks") or {}
        now_str = datetime.now(timezone.utc).isoformat()
        pending = [
            t for t in tasks.values()
            if t.get("status") == "pending" and t.get("expires_at", "9999") > now_str
        ]
        return sorted(pending, key=lambda t: t.get("created_at", ""))[:limit]
    except Exception:
        return []


def get_eval_stats() -> dict:
    """Return aggregated human eval statistics."""
    try:
        from src.db import load_pref  # type: ignore
        tasks = load_pref("human_eval:tasks") or {}
        total = len(tasks)
        completed = [t for t in tasks.values() if t.get("status") == "completed"]
        pending = [t for t in tasks.values() if t.get("status") == "pending"]
        ratings = [t.get("rating") for t in completed if t.get("rating") is not None]
        numeric_ratings = [r for r in ratings if isinstance(r, (int, float))]
        avg_rating = sum(numeric_ratings) / len(numeric_ratings) if numeric_ratings else None
        return {
            "total_tasks": total,
            "completed": len(completed),
            "pending": len(pending),
            "completion_rate": round(len(completed) / total, 3) if total else 0.0,
            "average_rating": round(avg_rating, 2) if avg_rating is not None else None,
        }
    except Exception:
        return {}


def maybe_sample_for_eval(
    request_id: str,
    prompt: str,
    response: str,
    experiment_id: str = "",
    context: dict | None = None,
) -> HumanEvalTask | None:
    """Sample and enqueue a human eval task if this request is selected.

    Returns the created task, or None if not sampled.
    """
    if not should_sample(request_id):
        return None
    return create_eval_task(
        task_type="absolute",
        prompt=prompt,
        response_a=response,
        context=context or {"request_id": request_id},
        experiment_id=experiment_id,
    )
