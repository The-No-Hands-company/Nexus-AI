"""Organisation service backed by database primitives."""
from __future__ import annotations

import secrets
import time
from typing import Any

from .db import (
    db_add_org_member,
    db_create_org,
    db_create_org_invite,
    db_delete_org,
    db_delete_org_invites,
    db_delete_org_members,
    db_get_org,
    db_get_org_by_name,
    db_get_org_invite,
    db_get_org_member,
    db_get_user_orgs,
    db_list_org_members,
    db_mark_invite_used,
    db_remove_org_member,
    db_update_org,
)


class OrgNotFound(Exception):
    """Raised when an organisation does not exist."""


class PermissionDenied(Exception):
    """Raised when membership/role checks fail."""


_ROLE_RANK = {
    "viewer": 10,
    "member": 20,
    "editor": 30,
    "admin": 40,
    "owner": 50,
}


def _normalize_org(org: dict[str, Any] | None) -> dict[str, Any] | None:
    if not org:
        return None
    normalized = dict(org)
    owner = str(normalized.get("owner") or normalized.get("owner_id") or "")
    if owner:
        normalized["owner"] = owner
        normalized["owner_id"] = owner
    return normalized


def _normalize_member(member: dict[str, Any] | None) -> dict[str, Any] | None:
    if not member:
        return None
    normalized = dict(member)
    username = str(normalized.get("username") or normalized.get("user_id") or "")
    if username:
        normalized["username"] = username
        normalized["user_id"] = username
    normalized["role"] = str(normalized.get("role") or "member").lower()
    return normalized


def _assert_role(role: str) -> str:
    normalized = str(role or "member").strip().lower()
    if normalized not in _ROLE_RANK:
        raise ValueError(f"invalid role '{role}'")
    return normalized


def _has_required_role(member_role: str, min_role: str) -> bool:
    return _ROLE_RANK.get(member_role, 0) >= _ROLE_RANK.get(min_role, 0)


def create_org(name: str, owner_id: str, **kwargs: Any) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    owner = str(owner_id or "").strip()
    if not clean_name:
        raise ValueError("org name is required")
    if not owner:
        raise ValueError("owner_id is required")
    if db_get_org_by_name(clean_name):
        raise ValueError("organisation name already exists")

    plan = str(kwargs.get("plan", "free") or "free")
    metadata = kwargs.get("metadata", "{}")
    if not isinstance(metadata, str):
        metadata = str(metadata)
    org = db_create_org(clean_name, owner, plan=plan, metadata=metadata)
    db_add_org_member(org["id"], owner, role="owner")
    return _normalize_org(org) or {"id": org.get("id", "")}


def get_org(org_id: str) -> dict[str, Any]:
    return _normalize_org(db_get_org(org_id))


def get_user_orgs(user_id: str) -> list[dict[str, Any]]:
    rows = db_get_user_orgs(str(user_id or "").strip())
    orgs: list[dict[str, Any]] = []
    for row in rows:
        orgs.append({
            "id": row.get("org_id"),
            "org_id": row.get("org_id"),
            "name": row.get("name"),
            "plan": row.get("plan"),
            "owner": row.get("owner"),
            "owner_id": row.get("owner"),
            "role": row.get("role", "member"),
            "joined_at": row.get("joined_at"),
        })
    return orgs


def update_org(org_id: str, **fields: Any) -> dict[str, Any]:
    if not db_get_org(org_id):
        return None
    allowed_fields = {"name", "plan", "metadata", "tokens_per_day", "spend_cap_usd"}
    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    if "name" in updates:
        updates["name"] = str(updates["name"] or "").strip()
        if not updates["name"]:
            raise ValueError("name cannot be empty")
    updated = db_update_org(org_id, **updates)
    return _normalize_org(updated)


def delete_org(org_id: str) -> bool:
    if not db_get_org(org_id):
        return False
    db_delete_org_invites(org_id)
    db_delete_org_members(org_id)
    return bool(db_delete_org(org_id))


def require_org_membership(
    org_id: str,
    user_id: str,
    role: str | None = None,
    min_role: str | None = None,
) -> dict[str, Any]:
    org = get_org(org_id)
    if not org:
        raise PermissionError(f"org {org_id} not found")

    member = _normalize_member(db_get_org_member(org_id, str(user_id or "").strip()))
    if member is None:
        raise PermissionError(f"User {user_id} is not a member of org {org_id}")

    required = min_role or role
    if required:
        required_role = _assert_role(required)
        if not _has_required_role(member.get("role", "member"), required_role):
            raise PermissionError(f"User {user_id} does not have role {required_role} in org {org_id}")
    return org


def list_members(org_id: str) -> list[dict[str, Any]]:
    if not db_get_org(org_id):
        raise ValueError("org not found")
    return [m for m in (_normalize_member(row) for row in db_list_org_members(org_id)) if m]


def add_member(org_id: str, user_id: str, role: str = "member") -> dict[str, Any]:
    if not db_get_org(org_id):
        raise ValueError("org not found")
    username = str(user_id or "").strip()
    if not username:
        raise ValueError("username is required")
    normalized_role = _assert_role(role)
    created = db_add_org_member(org_id, username, role=normalized_role)
    return _normalize_member(created) or {"username": username, "role": normalized_role}


def remove_member(org_id: str, user_id: str) -> bool:
    org = get_org(org_id)
    if not org:
        return False
    username = str(user_id or "").strip()
    if username == str(org.get("owner") or ""):
        raise ValueError("cannot remove org owner")
    return bool(db_remove_org_member(org_id, username))


def get_org_quota(org_id: str) -> dict[str, Any]:
    org = get_org(org_id)
    if not org:
        raise ValueError("org not found")
    members = db_list_org_members(org_id)
    return {
        "org_id": org_id,
        "max_members": int(org.get("max_members") or 100),
        "current_members": len(members),
        "max_storage_gb": int(org.get("max_storage_gb") or 10),
        "tokens_per_day": int(org.get("tokens_per_day") or 0),
        "spend_cap_usd": float(org.get("spend_cap_usd") or 0.0),
    }


def create_invite(
    org_id: str,
    invited_by: str,
    email: str = "",
    role: str = "member",
    expires_in_seconds: int = 7 * 24 * 60 * 60,
) -> dict[str, Any]:
    if not db_get_org(org_id):
        raise ValueError("org not found")
    normalized_role = _assert_role(role)
    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = now + max(60, int(expires_in_seconds))
    invite = db_create_org_invite(
        org_id=org_id,
        token=token,
        invited_by=str(invited_by or "").strip(),
        email=str(email or "").strip(),
        role=normalized_role,
        expires_at=expires_at,
    )
    return {
        "token": invite.get("token", token),
        "org_id": invite.get("org_id", org_id),
        "invited_by": invite.get("invited_by", invited_by),
        "email": invite.get("email", email),
        "role": invite.get("role", normalized_role),
        "expires_at": float(invite.get("expires_at") or expires_at),
        "status": "pending",
        "created_at": float(invite.get("created_at") or now),
    }


def accept_invite(invite_id: str, user_id: str) -> dict[str, Any]:
    invite = db_get_org_invite(str(invite_id or "").strip())
    if not invite:
        raise ValueError("invite not found")
    if bool(invite.get("used")):
        raise ValueError("invite already used")
    expires_at = float(invite.get("expires_at") or 0.0)
    if expires_at > 0 and time.time() > expires_at:
        raise ValueError("invite expired")

    member = add_member(str(invite.get("org_id") or ""), str(user_id or ""), role=str(invite.get("role") or "member"))
    db_mark_invite_used(str(invite.get("token") or ""), str(user_id or ""))
    return {
        "token": invite.get("token"),
        "org_id": invite.get("org_id"),
        "accepted_by": str(user_id or ""),
        "role": member.get("role", "member"),
        "status": "accepted",
    }
