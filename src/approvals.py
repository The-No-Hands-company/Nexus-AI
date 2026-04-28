from __future__ import annotations

import time
import uuid
from typing import Any

from .db import (
    consume_hitl_approval,
    create_hitl_approval,
    list_hitl_approvals,
    load_hitl_approval,
    update_hitl_approval_decision,
)


pending_approvals: dict[str, dict[str, Any]] = {}
_approval_store: dict[str, dict[str, Any]] = {}


def create_tool_approval(session_id: str, action: dict[str, Any]) -> str:
    approval_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "id": approval_id,
        "session_id": session_id,
        "action": dict(action),
        "signature": "",
        "status": "pending",
        "note": "",
        "created_at": now,
        "updated_at": now,
    }
    pending_approvals[approval_id] = record
    _approval_store[approval_id] = dict(record)
    try:
        create_hitl_approval(approval_id, session_id, action, "", now, now)
    except Exception:
        pass
    return approval_id


def list_tool_approvals(session_id: str | None = None) -> list[dict[str, Any]]:
    try:
        items = list_hitl_approvals(session_id or "")
    except Exception:
        items = []
    if not items:
        items = list(_approval_store.values())
        if session_id is not None:
            items = [item for item in items if item.get("session_id") == session_id]
    return [dict(item) for item in sorted(items, key=lambda item: item.get("created_at", 0.0), reverse=True)]


def decide_tool_approval(approval_id: str, approved: bool, note: str = "") -> dict[str, Any] | None:
    record = _approval_store.get(approval_id)
    status = "approved" if approved else "rejected"
    updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    persisted = None
    try:
        persisted = update_hitl_approval_decision(approval_id, status, note, updated_at)
    except Exception:
        persisted = None
    if persisted is None:
        if record is None:
            try:
                record = load_hitl_approval(approval_id)
            except Exception:
                record = None
        if record is None:
            return None
        record = dict(record)
        record["status"] = status
        record["note"] = note
        record["updated_at"] = updated_at
        persisted = record
    _approval_store[approval_id] = dict(persisted)
    if approval_id in pending_approvals:
        pending_approvals[approval_id].update(persisted)
    return dict(persisted)


def consume_approved_action(approval_id: str, session_id: str | None = None, action: dict[str, Any] | None = None) -> bool:
    record = _approval_store.get(approval_id)
    if record is None:
        try:
            record = load_hitl_approval(approval_id)
        except Exception:
            record = None
    if record is None:
        return False
    if session_id is not None and record.get("session_id") != session_id:
        return False
    if action is not None and record.get("action") != action:
        return False
    if record.get("status") != "approved":
        return False
    updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        persisted = consume_hitl_approval(approval_id, updated_at)
        if persisted:
            record = dict(persisted)
    except Exception:
        record["status"] = "consumed"
        record["updated_at"] = updated_at
    _approval_store[approval_id] = dict(record)
    pending_approvals.pop(approval_id, None)
    return True