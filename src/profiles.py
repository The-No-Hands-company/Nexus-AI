"""
src/profiles.py — User profile layer stub

Manages per-user profile data beyond auth credentials:
preferences, usage summaries, skill level, communication style,
persona history, quota state, and personalisation signals.

This module is a STUB — most functions raise NotImplementedError.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .db import load_pref, save_pref
from .redis_state import redis_get, redis_set, redis_incr, redis_expire, redis_keys, redis_delete


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------

@dataclass
class UserProfile:
    username: str
    display_name: str = ""
    email: str = ""
    skill_level: str = "intermediate"   # beginner | intermediate | expert
    preferred_language: str = "en"
    preferred_persona: str = "general"
    communication_style: str = "balanced"  # brief | balanced | detailed
    timezone: str = "UTC"
    quota_tokens_day: int = 0           # 0 = unlimited
    quota_spent_today: int = 0
    total_messages: int = 0
    total_tokens: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Profile operations
# ---------------------------------------------------------------------------

def get_profile(username: str) -> UserProfile | None:
    """
    Load user profile from the database.

    STUB: returns a default profile with the given username.
    Implementation plan: query profiles table in db.py.
    """
    raw = load_pref(f"profile.{username}", "")
    if not raw:
        return UserProfile(username=username)
    try:
        import json as _json
        data = _json.loads(raw)
        return UserProfile(**{**UserProfile(username=username).__dict__, **data, "username": username})
    except Exception:
        return UserProfile(username=username)


def update_profile(username: str, updates: dict) -> UserProfile:
    """Update profile fields and persist them in pref storage."""
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dict")
    profile = get_profile(username) or UserProfile(username=username)
    allowed = set(profile.__dict__.keys()) - {"username", "created_at"}
    for key, value in updates.items():
        if key in allowed:
            setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc).isoformat()
    import json as _json
    save_pref(f"profile.{username}", _json.dumps(profile.__dict__, ensure_ascii=False))
    return profile


def delete_profile(username: str) -> bool:
    """Delete stored profile and profile-related preference keys."""
    save_pref(f"profile.{username}", "")
    save_pref(f"signals.{username}", "[]")
    return True


# ---------------------------------------------------------------------------
# Quota management
# ---------------------------------------------------------------------------

def get_quota_state(username: str) -> dict:
    """
    Return current quota usage for *username*.

    Returns::
        {
            "tokens_used_today": int,
            "tokens_limit_day": int,
            "requests_used_today": int,
            "requests_limit_day": int,
            "reset_at": str (ISO-8601)
        }

    Returns persisted quota limits with daily usage counters.
    """
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    next_reset = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() + 86400

    tokens_limit_key = f"quota.tokens_limit_day.{username}"
    requests_limit_key = f"quota.requests_limit_day.{username}"
    tokens_used_key = f"quota.tokens_used.{username}.{day_key}"
    requests_used_key = f"quota.requests_used.{username}.{day_key}"

    tokens_limit_day = int(redis_get(tokens_limit_key) or load_pref(tokens_limit_key, "0") or "0")
    requests_limit_day = int(redis_get(requests_limit_key) or load_pref(requests_limit_key, "0") or "0")
    tokens_used_today = int(redis_get(tokens_used_key) or load_pref(tokens_used_key, "0") or "0")
    requests_used_today = int(redis_get(requests_used_key) or load_pref(requests_used_key, "0") or "0")

    return {
        "tokens_used_today": tokens_used_today,
        "tokens_limit_day": max(0, tokens_limit_day),  # 0 = unlimited
        "requests_used_today": requests_used_today,
        "requests_limit_day": max(0, requests_limit_day),
        "reset_at": datetime.fromtimestamp(next_reset, tz=timezone.utc).isoformat(),
    }


def check_quota(username: str, tokens_requested: int = 0) -> bool:
    """
    Return True if *username* is within quota for *tokens_requested*.

    Returns True if user is inside configured daily request/token limits.
    """
    state = get_quota_state(username)
    tokens_limit = int(state.get("tokens_limit_day", 0) or 0)
    req_limit = int(state.get("requests_limit_day", 0) or 0)
    tokens_used = int(state.get("tokens_used_today", 0) or 0)
    req_used = int(state.get("requests_used_today", 0) or 0)

    if tokens_limit > 0 and (tokens_used + max(0, int(tokens_requested or 0))) > tokens_limit:
        return False
    if req_limit > 0 and (req_used + 1) > req_limit:
        return False
    return True


def consume_quota(username: str, tokens: int) -> None:
    """
    Record *tokens* consumed by *username*.

    Increment daily usage counters for requests and tokens.
    """
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    token_key = f"quota.tokens_used.{username}.{day_key}"
    req_key = f"quota.requests_used.{username}.{day_key}"

    # Redis-backed counters keep quota enforcement correct across workers.
    redis_incr(token_key, max(0, int(tokens or 0)))
    redis_expire(token_key, 2 * 86400)
    redis_incr(req_key, 1)
    redis_expire(req_key, 2 * 86400)

    # Compatibility mirror for existing pref-based tooling.
    current_tokens = int(load_pref(token_key, "0") or "0")
    current_requests = int(load_pref(req_key, "0") or "0")
    save_pref(token_key, str(max(0, current_tokens + int(tokens or 0))))
    save_pref(req_key, str(max(0, current_requests + 1)))


def set_quota(username: str, tokens_per_day: int, requests_per_day: int | None = None) -> dict:
    """
    Set the daily token quota for *username*.

    Persist daily token/request quota limits and return the updated state.
    """
    safe_tokens = max(0, int(tokens_per_day or 0))
    redis_set(f"quota.tokens_limit_day.{username}", safe_tokens)
    save_pref(f"quota.tokens_limit_day.{username}", str(safe_tokens))
    if requests_per_day is not None:
        safe_requests = max(0, int(requests_per_day or 0))
        redis_set(f"quota.requests_limit_day.{username}", safe_requests)
        save_pref(f"quota.requests_limit_day.{username}", str(safe_requests))
    return get_quota_state(username)


def reset_quota_usage(username: str) -> None:
    """Reset daily quota usage counters for a user."""
    token_keys = redis_keys(f"quota.tokens_used.{username}.*")
    req_keys = redis_keys(f"quota.requests_used.{username}.*")
    if token_keys:
        redis_delete(*token_keys)
    if req_keys:
        redis_delete(*req_keys)

    # Keep pref-store in sync for compatibility.
    for key in token_keys + req_keys:
        save_pref(key, "0")


def cleanup_stale_quota_days(days_to_keep: int = 8) -> int:
    """Delete stale daily quota keys older than the retention window."""
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days_to_keep)))).strftime("%Y-%m-%d")
    removed = 0
    for key in redis_keys("quota.*"):
        parts = key.split(".")
        if len(parts) >= 4 and parts[-1] < cutoff and ("tokens_used" in key or "requests_used" in key):
            redis_delete(key)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Personalisation signals
# ---------------------------------------------------------------------------

def record_interaction_signal(
    username: str,
    signal_type: str,
    payload: dict,
) -> None:
    """Record a personalisation signal into pref-backed event list."""
    import json as _json
    key = f"signals.{username}"
    existing = load_pref(key, "[]") or "[]"
    try:
        arr = _json.loads(existing)
        if not isinstance(arr, list):
            arr = []
    except Exception:
        arr = []
    arr.append({
        "type": signal_type,
        "payload": payload,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    arr = arr[-200:]
    save_pref(key, _json.dumps(arr, ensure_ascii=False))


def get_personalisation_context(username: str) -> dict:
    """Aggregate recent signal context for prompt personalisation."""
    import json as _json
    key = f"signals.{username}"
    raw = load_pref(key, "[]") or "[]"
    try:
        arr = _json.loads(raw)
        if not isinstance(arr, list):
            arr = []
    except Exception:
        arr = []
    recent = arr[-20:]
    by_type: dict[str, int] = {}
    for item in recent:
        t = str(item.get("type", "unknown"))
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "signal_count": len(recent),
        "signal_types": by_type,
        "recent_signals": recent[-5:],
    }
