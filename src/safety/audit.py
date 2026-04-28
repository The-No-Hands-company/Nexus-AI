"""
src/safety/audit.py — Safety audit log

All safety events are persisted to the DB via src/db.py (add_safety_audit_entry /
_load_json_pref with hash-chain integrity). This replaces the previous /tmp flat-file
approach which was wiped on every container restart.

The hash-chain maintained by db.add_safety_audit_entry provides tamper evidence:
each entry includes the SHA-256 hash of its content + the previous entry's hash,
allowing offline verification via db.verify_safety_audit_entries().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditEvent:
    event_type: str         # "input_blocked" | "output_blocked" | "injection_detected" | "pii_detected"
    session_id: str
    username: str
    severity: str           # "info" | "warn" | "critical"
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def log_event(event: AuditEvent) -> None:
    """Persist *event* to the DB-backed hash-chained audit log.

    Uses src/db.add_safety_audit_entry which stores entries in the user_prefs
    table with SHA-256 hash chaining for tamper evidence. Never raises — a
    failure to log must not abort the request pipeline.
    """
    try:
        from src.db import add_safety_audit_entry
        add_safety_audit_entry({
            "event_type":  event.event_type,
            "session_id":  event.session_id,
            "username":    event.username,
            "severity":    event.severity,
            "details":     event.details,
            "created_at":  event.timestamp,
        })
    except Exception:
        pass


def query_audit_log(
    event_type: str | None = None,
    username: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query safety audit events from the DB.

    Filters by event_type, username, or since (ISO-8601 timestamp).
    Returns most-recent-first up to *limit* entries.
    """
    from src.db import db_query_safety_events
    return db_query_safety_events(
        event_type=event_type,
        username=username,
        since=since,
        limit=limit,
    )


def verify_integrity() -> dict:
    """Verify the hash-chain integrity of the audit log.

    Returns {"ok": bool, "checked": int, "broken_at": int | None, "head_hash": str | None}.
    """
    from src.db import verify_safety_audit_entries
    return verify_safety_audit_entries()
