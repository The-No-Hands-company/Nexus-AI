"""
src/safety/audit.py — Safety audit log stub

Appends structured safety events to the audit log for compliance
and incident review. All safety decisions (allow/warn/block) can be logged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


AUDIT_LOG_PATH = os.environ.get("SAFETY_AUDIT_LOG", "/tmp/nexus_safety_audit.jsonl")


@dataclass
class AuditEvent:
    event_type: str         # "input_blocked" | "output_blocked" | "injection_detected" | "pii_detected"
    session_id: str
    username: str
    severity: str           # "info" | "warn" | "critical"
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def log_event(event: AuditEvent) -> None:
    """
    Append *event* to the safety audit log (JSONL format).

    FUNCTIONAL: basic file append.
    Implementation plan: replace with structured DB logging + alerting on critical severity.
    """
    try:
        record = {
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "session_id": event.session_id,
            "username": event.username,
            "severity": event.severity,
            "details": event.details,
        }
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # never crash the request pipeline due to audit failure


def query_audit_log(
    event_type: str | None = None,
    username: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Query the audit log.

    STUB: raises NotImplementedError.
    Implementation plan: read from DB (not flat file) with indexed query.
    """
    raise NotImplementedError(
        "query_audit_log is not yet implemented. "
        "Planned: DB-backed query with indexed event_type, username, timestamp."
    )
