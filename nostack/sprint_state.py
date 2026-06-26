"""Sprint state management with persistence and resume capability."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any


_SPRINT_INDEX_KEY = "nostack.sprints.index"
_SPRINT_KEY_PREFIX = "nostack.sprint"
_MAX_RESULTS_LEN = 100


def _sprint_key(sprint_id: str) -> str:
    return f"{_SPRINT_KEY_PREFIX}.{sprint_id}"


def _db_save(key: str, value: str) -> None:
    from src.db import save_pref
    save_pref(key, value)


def _db_load(key: str, default: str = "") -> str:
    from src.db import load_pref
    return load_pref(key, default)


def _update_index(sprint_id: str) -> None:
    raw = _db_load(_SPRINT_INDEX_KEY, "[]")
    try:
        ids = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except (json.JSONDecodeError, TypeError):
        ids = []
    if sprint_id not in ids:
        ids.insert(0, sprint_id)
        _db_save(_SPRINT_INDEX_KEY, json.dumps(ids[:_MAX_RESULTS_LEN]))


class SprintState:
    """Persistent sprint state with resume capability."""

    def __init__(
        self,
        sprint_id: str = "",
        task: str = "",
        skills: list[str] | None = None,
        current_skill_index: int = 0,
        results: list[dict] | None = None,
        status: str = "pending",
        created_at: float | None = None,
        updated_at: float | None = None,
    ):
        self.sprint_id = sprint_id or f"sprint-{uuid.uuid4().hex[:8]}"
        self.task = task
        self.skills = skills or []
        self.current_skill_index = current_skill_index
        self.results = results or []
        self.status = status
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()

    def save(self) -> None:
        self.updated_at = time.time()
        _db_save(_sprint_key(self.sprint_id), json.dumps(self.to_dict()))
        _update_index(self.sprint_id)

    def resume(self) -> dict:
        """Load and resume from current_skill_index.

        Returns a dict with the next skill to run, or a completion message.
        """
        if self.status == "completed":
            return {"status": "completed", "message": "Sprint already completed", "sprint": self.to_dict()}
        if self.status == "cancelled":
            return {"status": "cancelled", "message": "Sprint is cancelled", "sprint": self.to_dict()}

        pending = self.pending_skills()
        if not pending:
            self.status = "completed"
            self.save()
            return {"status": "completed", "message": "All skills completed", "sprint": self.to_dict()}

        return {
            "status": self.status,
            "sprint_id": self.sprint_id,
            "task": self.task,
            "current_skill_index": self.current_skill_index,
            "next_skill": pending[0],
            "remaining_skills": pending,
            "completed_skills": self.skills[: self.current_skill_index],
            "results": [r for r in self.results if r.get("status") == "completed"],
            "sprint": self.to_dict(),
        }

    def pending_skills(self) -> list[str]:
        return self.skills[self.current_skill_index :]

    def total_skills(self) -> int:
        return len(self.skills)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sprint_id": self.sprint_id,
            "task": self.task,
            "skills": self.skills,
            "current_skill_index": self.current_skill_index,
            "results": self.results,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def create_sprint(task: str, skills: list[str]) -> SprintState:
    state = SprintState(task=task, skills=skills, status="pending")
    state.save()
    return state


def load_sprint(sprint_id: str) -> SprintState | None:
    raw = _db_load(_sprint_key(sprint_id), "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return SprintState(**data)


def resume_sprint(sprint_id: str) -> SprintState:
    state = load_sprint(sprint_id)
    if state is None:
        raise ValueError(f"Sprint not found: {sprint_id}")
    return state


def list_sprints(limit: int = 20) -> list[SprintState]:
    raw = _db_load(_SPRINT_INDEX_KEY, "[]")
    try:
        ids = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except (json.JSONDecodeError, TypeError):
        return []
    results: list[SprintState] = []
    for sid in ids[: max(1, min(limit, _MAX_RESULTS_LEN))]:
        state = load_sprint(sid)
        if state is not None:
            results.append(state)
    return results


def cancel_sprint(sprint_id: str) -> None:
    state = load_sprint(sprint_id)
    if state is None:
        raise ValueError(f"Sprint not found: {sprint_id}")
    state.status = "cancelled"
    state.save()


_SPRINT_LOCKS: dict[str, bool] = {}


def run_sprint_background(sprint_id: str, task: str, skills: list[str]) -> SprintState:
    """Run a sprint in the calling thread (intended for background use).

    Returns the final SprintState after all skills have been run.
    """
    from nostack.registry import run_skill

    state = load_sprint(sprint_id)
    if state is None:
        state = SprintState(sprint_id=sprint_id, task=task, skills=skills)

    state.status = "running"
    state.save()

    _SPRINT_LOCKS[sprint_id] = True

    context = task
    try:
        for idx in range(state.current_skill_index, len(state.skills)):
            if not _SPRINT_LOCKS.get(sprint_id, False):
                state.status = "cancelled"
                state.save()
                break

            skill_name = state.skills[idx]
            enriched_task = (
                f"Previous sprint context:\n{context[:2000]}\n\n"
                f"Now run /{skill_name} on this task: {task}"
            )

            try:
                run_result = run_skill(skill_name, task=enriched_task)
                result_content = run_result.get("result", "") if isinstance(run_result, dict) else str(run_result)
                status = "failed" if run_result.get("error") else "completed"
            except Exception as exc:
                result_content = ""
                run_result = {"error": str(exc)}
                status = "failed"

            state.results.append({
                "skill": skill_name,
                "result": result_content[:2000] if result_content else "",
                "status": status,
                "error": run_result.get("error", "") if isinstance(run_result, dict) else "",
            })
            state.current_skill_index = idx + 1

            if status == "completed" and result_content:
                context = result_content[:2000]

            state.save()

        if state.status != "cancelled":
            state.status = "completed"
            state.save()
    finally:
        _SPRINT_LOCKS.pop(sprint_id, None)

    return state


def cancel_sprint_background(sprint_id: str) -> bool:
    """Signal a running background sprint to cancel."""
    if sprint_id in _SPRINT_LOCKS:
        _SPRINT_LOCKS[sprint_id] = False
        cancel_sprint(sprint_id)
        return True
    return False
