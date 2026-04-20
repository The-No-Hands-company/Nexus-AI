"""Organisation / tenant model for Nexus AI.

Provides:
  - Org entity CRUD (create, get, list, update, delete)
  - Org membership management (add/remove members, role assignment)
  - Org-scoped API keys
  - Org-level quota enforcement
  - Invite flow (create invite token, accept invite)
  - Data isolation helpers
  - GDPR / org deletion cascade

Database tables used: orgs, org_members, org_invites  (defined in db.py)
"""

from __future__ import annotations

import json
from .observability import get_logger
import os
import secrets
import time
from typing import Any

logger = get_logger("nexus.orgs")

_ORG_INVITE_TTL = int(os.getenv("ORG_INVITE_TTL_HOURS", "72")) * 3600


# ── Org CRUD ──────────────────────────────────────────────────────────────────

def create_org(
    name: str,
    owner_username: str,
    plan: str = "free",
    metadata: dict | None = None,
) -> dict:
    """Create a new organisation and add the owner as admin."""
    if not name or not name.strip():
        raise ValueError("org name is required")
    if not owner_username:
        raise ValueError("owner_username is required")

    from .db import db_create_org, db_add_org_member
    org = db_create_org(
        name=name.strip()[:100],
        owner=owner_username,
        plan=plan,
        metadata=json.dumps(metadata or {}),
    )
    db_add_org_member(org["id"], owner_username, role="admin")
    logger.info("org_created org_id=%s owner=%s", org["id"], owner_username)
    return org


def get_org(org_id: str) -> dict | None:
    from .db import db_get_org
    return db_get_org(org_id)


def get_org_by_name(name: str) -> dict | None:
    from .db import db_get_org_by_name
    return db_get_org_by_name(name)


def list_orgs(owner: str = "", limit: int = 100) -> list[dict]:
    from .db import db_list_orgs
    return db_list_orgs(owner=owner, limit=limit)


def update_org(org_id: str, **fields) -> dict | None:
    from .db import db_update_org
    allowed = {"name", "plan", "metadata", "spend_cap_usd", "tokens_per_day"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_org(org_id)
    return db_update_org(org_id, **updates)


def delete_org(org_id: str) -> bool:
    """Delete an org and cascade-delete all associated data."""
    from .db import db_delete_org, db_delete_org_members, db_delete_org_invites
    db_delete_org_invites(org_id)
    db_delete_org_members(org_id)
    deleted = db_delete_org(org_id)
    if deleted:
        logger.info("org_deleted org_id=%s", org_id)
    return deleted


# ── Membership management ─────────────────────────────────────────────────────

def add_member(org_id: str, username: str, role: str = "member") -> dict:
    """Add a user to an org with the given role."""
    if role not in ("admin", "member", "viewer"):
        raise ValueError("role must be one of: admin, member, viewer")
    from .db import db_add_org_member
    return db_add_org_member(org_id, username, role=role)


def remove_member(org_id: str, username: str) -> bool:
    """Remove a user from an org."""
    from .db import db_remove_org_member
    result = db_remove_org_member(org_id, username)
    if result:
        logger.info("org_member_removed org_id=%s username=%s", org_id, username)
    return result


def update_member_role(org_id: str, username: str, role: str) -> bool:
    """Update a member's role within an org."""
    if role not in ("admin", "member", "viewer"):
        raise ValueError("role must be one of: admin, member, viewer")
    from .db import db_update_org_member_role
    return db_update_org_member_role(org_id, username, role)


def list_members(org_id: str) -> list[dict]:
    from .db import db_list_org_members
    return db_list_org_members(org_id)


def get_member_role(org_id: str, username: str) -> str | None:
    """Return the member's role in an org, or None if not a member."""
    from .db import db_get_org_member
    member = db_get_org_member(org_id, username)
    return member.get("role") if member else None


def is_member(org_id: str, username: str) -> bool:
    return get_member_role(org_id, username) is not None


def is_org_admin(org_id: str, username: str) -> bool:
    return get_member_role(org_id, username) == "admin"


def get_user_orgs(username: str) -> list[dict]:
    """Return all orgs a user belongs to."""
    from .db import db_get_user_orgs
    return db_get_user_orgs(username)


# ── Invite flow ───────────────────────────────────────────────────────────────

def create_invite(
    org_id: str,
    invited_by: str,
    email: str = "",
    role: str = "member",
) -> dict:
    """Create an invite token for an org. Returns the invite record."""
    if role not in ("admin", "member", "viewer"):
        raise ValueError("role must be one of: admin, member, viewer")
    token = secrets.token_urlsafe(32)
    from .db import db_create_org_invite
    invite = db_create_org_invite(
        org_id=org_id,
        token=token,
        invited_by=invited_by,
        email=email,
        role=role,
        expires_at=time.time() + _ORG_INVITE_TTL,
    )
    logger.info("org_invite_created org_id=%s invited_by=%s", org_id, invited_by)
    return invite


def accept_invite(token: str, username: str) -> dict:
    """Accept an invite token and add the user to the org."""
    from .db import db_get_org_invite, db_mark_invite_used
    invite = db_get_org_invite(token)
    if not invite:
        raise ValueError("invite not found or already used")
    if invite.get("used"):
        raise ValueError("invite has already been used")
    if invite.get("expires_at", 0) < time.time():
        raise ValueError("invite has expired")
    org_id = invite["org_id"]
    role = invite.get("role", "member")
    member = add_member(org_id, username, role=role)
    db_mark_invite_used(token, username)
    logger.info("org_invite_accepted org_id=%s username=%s", org_id, username)
    return {"org_id": org_id, "role": role, "member": member}


def list_invites(org_id: str, include_used: bool = False) -> list[dict]:
    from .db import db_list_org_invites
    return db_list_org_invites(org_id, include_used=include_used)


def revoke_invite(token: str) -> bool:
    from .db import db_revoke_org_invite
    return db_revoke_org_invite(token)


# ── Quota enforcement ─────────────────────────────────────────────────────────

def get_org_quota(org_id: str) -> dict:
    """Return the current quota state for an org."""
    org = get_org(org_id)
    if not org:
        return {"tokens_used_today": 0, "tokens_per_day": 0, "spend_cap_usd": 0}
    try:
        from .redis_state import redis_get, redis_set
        key = f"org_quota:{org_id}:{int(time.time() // 86400)}"
        tokens_used = int(redis_get(key) or 0)
    except Exception:
        tokens_used = 0
    return {
        "org_id": org_id,
        "tokens_used_today": tokens_used,
        "tokens_per_day": org.get("tokens_per_day", 0),
        "spend_cap_usd": org.get("spend_cap_usd", 0.0),
        "plan": org.get("plan", "free"),
    }


def record_org_usage(org_id: str, tokens: int) -> int:
    """Increment and return the token counter for today."""
    try:
        from .redis_state import incr_rate_counter
        day_bucket = str(int(time.time() // 86400))
        return incr_rate_counter(f"org_quota:{org_id}", day_bucket, 86400)
    except Exception:
        return 0


def check_org_quota(org_id: str, tokens_requested: int = 0) -> bool:
    """Return True if the org is within quota, False if over limit."""
    quota = get_org_quota(org_id)
    daily_limit = int(quota.get("tokens_per_day", 0))
    if daily_limit <= 0:
        return True  # no limit configured
    return quota["tokens_used_today"] + tokens_requested <= daily_limit


# ── Data isolation helper ─────────────────────────────────────────────────────

def require_org_membership(org_id: str, username: str, min_role: str = "member") -> None:
    """Raise PermissionError if the user lacks the required role in the org."""
    role = get_member_role(org_id, username)
    if role is None:
        raise PermissionError(f"User '{username}' is not a member of org '{org_id}'")
    role_ranks = {"viewer": 0, "member": 1, "admin": 2}
    if role_ranks.get(role, -1) < role_ranks.get(min_role, 0):
        raise PermissionError(
            f"User '{username}' has role '{role}' but '{min_role}' is required in org '{org_id}'"
        )


def org_health(org_id: str) -> dict:
    """Return a health summary for an org."""
    org = get_org(org_id)
    if not org:
        return {"status": "not_found"}
    members = list_members(org_id)
    quota = get_org_quota(org_id)
    return {
        "status": "ok",
        "org_id": org_id,
        "name": org.get("name"),
        "plan": org.get("plan"),
        "member_count": len(members),
        "quota": quota,
    }
