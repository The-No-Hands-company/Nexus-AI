"""Task-to-task lineage graph tracking for agentic execution.

Stores parent/child provenance links and exposes graph/query helpers.
Persistence uses preference storage so lineage survives restarts.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from .db import load_pref, save_pref


_LINEAGE_PREF_KEY = "agent_lineage_graph_v1"
_MAX_EDGES = 20_000

_lock = threading.Lock()
_edges: list[dict[str, Any]] = []
_loaded = False


def _load() -> None:
    global _loaded, _edges
    if _loaded:
        return
    try:
        raw = load_pref(_LINEAGE_PREF_KEY, "[]")
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            _edges = [dict(item) for item in parsed if isinstance(item, dict)]
    except Exception:
        _edges = []
    _loaded = True


def _persist() -> None:
    try:
        save_pref(_LINEAGE_PREF_KEY, json.dumps(_edges[-_MAX_EDGES:]))
    except Exception:
        pass


def record_lineage_edge(
    parent_task_id: str,
    child_task_id: str,
    relation: str = "depends_on",
    source: str = "api",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parent = str(parent_task_id or "").strip()
    child = str(child_task_id or "").strip()
    if not parent or not child:
        raise ValueError("parent_task_id and child_task_id are required")

    edge = {
        "parent_task_id": parent,
        "child_task_id": child,
        "relation": str(relation or "depends_on").strip() or "depends_on",
        "source": str(source or "api").strip() or "api",
        "metadata": dict(metadata or {}),
        "ts": time.time(),
    }

    with _lock:
        _load()
        _edges.append(edge)
        if len(_edges) > _MAX_EDGES:
            del _edges[:-_MAX_EDGES]
        _persist()
    return edge


def query_lineage(task_id: str, direction: str = "both", limit: int = 500) -> list[dict[str, Any]]:
    target = str(task_id or "").strip()
    if not target:
        return []
    mode = str(direction or "both").strip().lower()
    safe_limit = max(1, min(int(limit), 10_000))

    with _lock:
        _load()
        rows = []
        for edge in reversed(_edges):
            parent = str(edge.get("parent_task_id") or "")
            child = str(edge.get("child_task_id") or "")
            if mode == "upstream" and child == target:
                rows.append(edge)
            elif mode == "downstream" and parent == target:
                rows.append(edge)
            elif mode == "both" and (parent == target or child == target):
                rows.append(edge)
            if len(rows) >= safe_limit:
                break
        return list(reversed(rows))


def get_lineage_graph(root_task_id: str, depth: int = 3, limit: int = 2000) -> dict[str, Any]:
    root = str(root_task_id or "").strip()
    if not root:
        return {"root_task_id": root, "nodes": [], "edges": []}

    safe_depth = max(1, min(int(depth), 10))
    safe_limit = max(1, min(int(limit), 10_000))

    with _lock:
        _load()
        all_edges = list(_edges)

    by_parent: dict[str, list[dict[str, Any]]] = {}
    by_child: dict[str, list[dict[str, Any]]] = {}
    for edge in all_edges:
        parent = str(edge.get("parent_task_id") or "")
        child = str(edge.get("child_task_id") or "")
        if not parent or not child:
            continue
        by_parent.setdefault(parent, []).append(edge)
        by_child.setdefault(child, []).append(edge)

    visited_nodes: set[str] = {root}
    visited_edges: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque([(root, 0)])

    while queue and len(visited_edges) < safe_limit:
        node, d = queue.popleft()
        if d >= safe_depth:
            continue

        downstream = by_parent.get(node, [])
        upstream = by_child.get(node, [])
        for edge in downstream + upstream:
            parent = str(edge.get("parent_task_id") or "")
            child = str(edge.get("child_task_id") or "")
            if not parent or not child:
                continue
            if edge not in visited_edges:
                visited_edges.append(edge)
            if parent not in visited_nodes:
                visited_nodes.add(parent)
                queue.append((parent, d + 1))
            if child not in visited_nodes:
                visited_nodes.add(child)
                queue.append((child, d + 1))
            if len(visited_edges) >= safe_limit:
                break

    nodes = [{"task_id": task_id} for task_id in sorted(visited_nodes)]
    return {
        "root_task_id": root,
        "depth": safe_depth,
        "nodes": nodes,
        "edges": visited_edges,
    }


def clear_lineage() -> int:
    with _lock:
        _load()
        count = len(_edges)
        _edges.clear()
        _persist()
        return count
