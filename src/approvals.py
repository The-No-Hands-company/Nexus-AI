import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import (
    clear_hitl_approvals,
    consume_hitl_approval,
    create_hitl_approval,
    list_hitl_approvals,
    load_hitl_approval,
    update_hitl_approval_decision,
)


pending_approvals: Dict[str, Dict[str, Any]] = {}


def _hydrate_cache_from_db() -> None:
    try:
        for item in list_hitl_approvals():
            pending_approvals[item.get("id", "")] = item
    except Exception:
        # Never fail import because persistence is unavailable.
        pass


def approval_action_signature(action: Dict[str, Any]) -> str:
    normalized = dict(action or {})
    normalized.pop("approval_id", None)
    try:
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(normalized)


def create_tool_approval(sid: str, action: Dict[str, Any]) -> str:
    approval_id = f"appr_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "id": approval_id,
        "session_id": sid or "",
        "action": dict(action or {}),
        "signature": approval_action_signature(action),
        "status": "pending",
        "note": "",
        "created_at": now,
        "updated_at": now,
    }
    pending_approvals[approval_id] = record
    try:
        create_hitl_approval(
            approval_id=approval_id,
            session_id=record["session_id"],
            action=record["action"],
            signature=record["signature"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
    except Exception:
        pass
    return approval_id


def list_tool_approvals(sid: str = "") -> List[Dict[str, Any]]:
    try:
        items = list_hitl_approvals(session_id=sid or "")
        for item in items:
            if item.get("id"):
                pending_approvals[item["id"]] = item
        return items
    except Exception:
        items = list(pending_approvals.values())
        if sid:
            items = [item for item in items if item.get("session_id") == sid]
        return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def decide_tool_approval(approval_id: str, approved: bool, note: str = "") -> Optional[Dict[str, Any]]:
    record = pending_approvals.get(approval_id)
    if not record:
        try:
            record = load_hitl_approval(approval_id)
        except Exception:
            record = None
    if not record:
        return None
    status = "approved" if approved else "rejected"
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record["status"] = status
    record["note"] = note
    record["updated_at"] = updated_at
    pending_approvals[approval_id] = dict(record)
    try:
        persisted = update_hitl_approval_decision(approval_id, status, note, updated_at)
        if persisted:
            pending_approvals[approval_id] = dict(persisted)
            return dict(persisted)
    except Exception:
        pass
    return dict(record)


def consume_approved_action(approval_id: str, sid: str, action: Dict[str, Any]) -> bool:
    if not approval_id:
        return False
    record = pending_approvals.get(approval_id)
    if not record:
        try:
            record = load_hitl_approval(approval_id)
        except Exception:
            record = None
    if not record:
        return False
    if record.get("status") != "approved":
        return False
    if (record.get("session_id") or "") != (sid or ""):
        return False
    if record.get("signature") != approval_action_signature(action):
        return False
    record["status"] = "consumed"
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record["updated_at"] = updated_at
    pending_approvals[approval_id] = dict(record)
    try:
        consume_hitl_approval(approval_id, updated_at)
    except Exception:
        pass
    return True


def clear_tool_approvals() -> None:
    pending_approvals.clear()
    try:
        clear_hitl_approvals()
    except Exception:
        pass


_hydrate_cache_from_db()