import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


pending_approvals: Dict[str, Dict[str, Any]] = {}


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
    pending_approvals[approval_id] = {
        "id": approval_id,
        "session_id": sid or "",
        "action": dict(action or {}),
        "signature": approval_action_signature(action),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    return approval_id


def list_tool_approvals(sid: str = "") -> List[Dict[str, Any]]:
    items = list(pending_approvals.values())
    if sid:
        items = [item for item in items if item.get("session_id") == sid]
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def decide_tool_approval(approval_id: str, approved: bool, note: str = "") -> Optional[Dict[str, Any]]:
    record = pending_approvals.get(approval_id)
    if not record:
        return None
    record["status"] = "approved" if approved else "rejected"
    record["note"] = note
    record["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return dict(record)


def consume_approved_action(approval_id: str, sid: str, action: Dict[str, Any]) -> bool:
    if not approval_id:
        return False
    record = pending_approvals.get(approval_id)
    if not record:
        return False
    if record.get("status") != "approved":
        return False
    if (record.get("session_id") or "") != (sid or ""):
        return False
    if record.get("signature") != approval_action_signature(action):
        return False
    record["status"] = "consumed"
    record["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return True