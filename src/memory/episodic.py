"""
src/memory/episodic.py — Episodic (event-based timeline) memory stub

Episodic memory stores discrete events (tool calls, decisions, user actions)
in chronological order per session. Enables:
- "What did I do last Tuesday?" type queries
- Autonomous loop replay / audit
- Timeline-based context injection
- Memory consolidation into semantic memory

This module is a STUB — most functions raise NotImplementedError.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..memory import add_semantic_memory


@dataclass
class EpisodicEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    username: str = ""
    event_type: str = ""        # "message" | "tool_call" | "decision" | "error" | "milestone"
    summary: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    importance: float = 0.5     # 0.0 – 1.0 for salience-based retrieval


_EPISODIC_EVENTS: list[EpisodicEvent] = []
_EPISODIC_LOCK = threading.Lock()


def _event_time(event: EpisodicEvent) -> datetime:
    try:
        return datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def record_event(
    session_id: str,
    event_type: str,
    summary: str,
    payload: dict | None = None,
    username: str = "",
    importance: float = 0.5,
) -> EpisodicEvent:
    """Record and persist an episodic event in the timeline store."""
    event = EpisodicEvent(
        session_id=session_id,
        username=username,
        event_type=event_type,
        summary=summary,
        payload=payload or {},
        importance=max(0.0, min(1.0, float(importance))),
    )
    with _EPISODIC_LOCK:
        _EPISODIC_EVENTS.append(event)
    return event


def get_session_timeline(
    session_id: str,
    limit: int = 50,
    event_types: list[str] | None = None,
) -> list[EpisodicEvent]:
    """Retrieve a chronological timeline for a session."""
    safe_limit = max(1, min(int(limit or 50), 500))
    filters = {t.strip().lower() for t in (event_types or []) if str(t).strip()}
    with _EPISODIC_LOCK:
        events = [e for e in _EPISODIC_EVENTS if e.session_id == session_id]
    if filters:
        events = [e for e in events if e.event_type.lower() in filters]
    events.sort(key=_event_time)
    return events[-safe_limit:]


def search_episodes(
    username: str,
    query: str,
    limit: int = 20,
    since: str | None = None,
) -> list[EpisodicEvent]:
    """Search episodic events for a user by text match and optional cutoff."""
    safe_limit = max(1, min(int(limit or 20), 200))
    needle = (query or "").strip().lower()
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
        except Exception:
            since_dt = None

    with _EPISODIC_LOCK:
        events = [e for e in _EPISODIC_EVENTS if e.username == username]

    ranked: list[tuple[float, EpisodicEvent]] = []
    for event in events:
        if since_dt and _event_time(event) < since_dt:
            continue
        text_blob = f"{event.summary}\n{json.dumps(event.payload, ensure_ascii=False)}".lower()
        if needle and needle not in text_blob:
            continue
        relevance = 1.0
        if needle:
            relevance = (2.0 if needle in (event.summary or "").lower() else 1.0) + event.importance
        ranked.append((relevance, event))

    ranked.sort(key=lambda pair: (pair[0], _event_time(pair[1])), reverse=True)
    return [event for _, event in ranked[:safe_limit]]


def consolidate_to_semantic(
    session_id: str,
    target_memory_key: str | None = None,
) -> str:
    """Consolidate session episodes into a semantic memory summary."""
    timeline = get_session_timeline(session_id=session_id, limit=200)
    if not timeline:
        return "No episodic events found for consolidation."

    top_events = sorted(timeline, key=lambda e: e.importance, reverse=True)[:10]
    lines = [f"- [{e.event_type}] {e.summary}" for e in top_events if e.summary]
    summary = (
        f"Episodic consolidation for session '{session_id}': "
        + ("; ".join(line[2:] for line in lines[:6]) if lines else "no summarizable events")
    )
    tags = ["episodic", "session", session_id]
    if target_memory_key:
        tags.append(str(target_memory_key))
    add_semantic_memory(summary=summary, tags=tags)

    with _EPISODIC_LOCK:
        for event in _EPISODIC_EVENTS:
            if event.session_id == session_id:
                event.payload = {**(event.payload or {}), "consolidated": True}

    return summary


def prune_episodes(session_id: str, keep_important: float = 0.7) -> int:
    """Prune low-importance events for a session and return deleted count."""
    threshold = max(0.0, min(1.0, float(keep_important)))
    with _EPISODIC_LOCK:
        before = len(_EPISODIC_EVENTS)
        kept = [
            event
            for event in _EPISODIC_EVENTS
            if event.session_id != session_id or event.importance >= threshold
        ]
        _EPISODIC_EVENTS[:] = kept
        after = len(_EPISODIC_EVENTS)
    return before - after
