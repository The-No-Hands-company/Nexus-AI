from __future__ import annotations

import json
import time
from typing import Any

from ..db import add_memory_entry, delete_all_memory, load_memory_entries, prune_memory_by_age


def add_memory(content: str, tags: list[str] | None = None, persona: str | None = None, session_id: str | None = None) -> bool:
    add_memory_entry(content, list(tags or []), time.time())
    return True


def summarize_history(messages: list[dict[str, Any]], max_tokens: int = 512, **kwargs: Any) -> str:
    snippets = [str(item.get("content", "")).strip() for item in messages if item.get("content")]
    return " ".join(snippets)[: max_tokens * 4].strip()


def get_memory_context(session_id: str | None = None, query: str | None = None, limit: int = 5, **kwargs: Any) -> str:
    entries = get_semantic_memory_filtered(query or "", limit=limit)
    return "\n".join(str(item.get("summary", item.get("content", ""))) for item in entries)


def prune_old_memories(max_age_days: int = 30, min_keep: int = 5) -> int:
    cutoff = time.time() - max_age_days * 86400
    return prune_memory_by_age(cutoff, keep_min=min_keep)


def get_semantic_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
    return get_semantic_memory_filtered(query, limit=limit)


def add_semantic_memory(content: str, tags: list[str] | None = None, persona: str | None = None) -> bool:
    return add_memory(content, tags=tags, persona=persona)


def get_semantic_memory_filtered(
    query: str,
    limit: int = 5,
    date_from: float | None = None,
    date_to: float | None = None,
    tags: list[str] | None = None,
    persona: str | None = None,
) -> list[dict[str, Any]]:
    results = []
    query_lower = (query or "").lower()
    for entry in load_memory_entries(max(limit * 4, 20)):
        ts = float(entry.get("ts", 0.0) or 0.0)
        if date_from is not None and ts < date_from:
            continue
        if date_to is not None and ts > date_to:
            continue
        if tags and not set(tags).issubset(set(entry.get("tags", []))):
            continue
        if persona is not None and entry.get("persona", "") != persona:
            continue
        haystack = f"{entry.get('summary', '')} {' '.join(entry.get('tags', []))}".lower()
        if query_lower and query_lower not in haystack:
            continue
        results.append(dict(entry))
    return results[:limit]


def delete_all() -> int:
    delete_all_memory()
    return 0


def get_all(limit: int = 100) -> list[dict[str, Any]]:
    return load_memory_entries(limit)


def get_episodic_timeline(limit: int = 50) -> list[dict[str, Any]]:
    return load_memory_entries(limit)


def export_memory_bundle(limit: int = 200) -> dict[str, Any]:
    entries = get_all(limit)
    return {
        "entries": entries,
        "count": len(entries),
        "exported_at": time.time(),
    }


def import_memory_bundle(bundle: Any, source: str | None = None) -> dict[str, Any]:
    payload = bundle
    if isinstance(bundle, str):
        try:
            payload = json.loads(bundle)
        except Exception:
            payload = {}

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw_entries = payload.get("entries", [])
        if isinstance(raw_entries, list):
            items = [item for item in raw_entries if isinstance(item, dict)]
    elif isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]

    imported = 0
    for item in items:
        add_memory(
            str(item.get("summary", item.get("content", ""))),
            tags=item.get("tags", []),
            persona=item.get("persona"),
        )
        imported += 1

    return {"imported": imported, "source": source or "memory_bundle"}