from __future__ import annotations

import time
from typing import Any


_checkpoints: dict[str, list[dict[str, Any]]] = {}
_file_diffs: dict[str, list[dict[str, Any]]] = {}


def save_checkpoint(trace_id: str, step: int, state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"trace_id": trace_id, "step": step, "state": state, "ts": time.time()}
    if isinstance(state, dict):
        item.update(state)
    _checkpoints.setdefault(trace_id, []).append(item)
    return item


def list_traces(limit: int | None = None) -> list[dict[str, Any]]:
    traces = [{"trace_id": trace_id, "count": len(items)} for trace_id, items in _checkpoints.items()]
    traces.reverse()
    if limit is None:
        return traces
    return traces[: max(0, int(limit))]


def load_checkpoints(trace_id: str) -> list[dict[str, Any]]:
    return list(_checkpoints.get(trace_id, []))


def get_latest_checkpoint(trace_id: str) -> dict[str, Any] | None:
    items = _checkpoints.get(trace_id, [])
    return items[-1] if items else None


def delete_trace(trace_id: str) -> bool:
    removed = trace_id in _checkpoints
    _checkpoints.pop(trace_id, None)
    _file_diffs.pop(trace_id, None)
    return removed


def save_file_diff(trace_id: str, path: str, before: str, after: str) -> dict[str, Any]:
    import difflib
    diff_lines = list(difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    diff_text = "".join(diff_lines)
    additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
    item = {
        "id": f"{trace_id}:{len(_file_diffs.get(trace_id, []))}",
        "trace_id": trace_id,
        "file_path": path,
        "path": path,
        "before_text": before,
        "after_text": after,
        "before": before,
        "after": after,
        "diff_text": diff_text,
        "additions": additions,
        "deletions": deletions,
        "ts": time.time(),
    }
    _file_diffs.setdefault(trace_id, []).append(item)
    return item


def get_file_diffs(trace_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    if trace_id is not None:
        items = list(_file_diffs.get(trace_id, []))
    else:
        items = [item for sublist in _file_diffs.values() for item in sublist]
    if limit is not None:
        items = items[:max(0, int(limit))]
    return items


def get_file_diff_detail(diff_id: str | int, trace_id: str | None = None) -> dict[str, Any] | None:
    str_id = str(diff_id)
    if trace_id is not None:
        for item in _file_diffs.get(trace_id, []):
            if str(item.get("id")) == str_id:
                return item
        return None
    for items in _file_diffs.values():
        for item in items:
            if str(item.get("id")) == str_id:
                return item
    return None