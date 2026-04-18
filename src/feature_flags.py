"""Feature flags system for Nexus AI.

Supports:
  - DB-backed flags with per-user / per-org targeting
  - Percentage rollout (hash-based, stable per user)
  - Default value fallback
  - In-memory cache with TTL for fast evaluation
  - Admin CRUD API helpers

All flag evaluations are non-blocking and never raise; they return the default
value on any error so a bad flag never breaks production traffic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nexus.feature_flags")

_CACHE_TTL = int(os.getenv("FEATURE_FLAGS_CACHE_TTL", "30"))  # seconds

# ── In-memory cache ───────────────────────────────────────────────────────────

_cache: dict[str, tuple[Any, float]] = {}  # flag_name -> (value, expires_at)
_cache_lock = threading.Lock()


def _cache_get(flag: str) -> Any:
    with _cache_lock:
        entry = _cache.get(flag)
        if entry and time.time() < entry[1]:
            return entry[0]
    return _MISS


_MISS = object()


def _cache_set(flag: str, value: Any) -> None:
    with _cache_lock:
        _cache[flag] = (value, time.time() + _CACHE_TTL)


def invalidate_cache(flag: str | None = None) -> None:
    """Clear the flag cache. Pass None to clear all flags."""
    with _cache_lock:
        if flag is None:
            _cache.clear()
        else:
            _cache.pop(flag, None)


# ── Flag evaluation ───────────────────────────────────────────────────────────

def _load_flag(flag_name: str) -> dict | None:
    """Load a flag record from the database. Returns None if not found."""
    try:
        from .db import load_feature_flag
        return load_feature_flag(flag_name)
    except Exception as exc:
        logger.debug("feature_flag_db_error", flag=flag_name, error=str(exc))
        return None


def _percentage_bucket(flag_name: str, user_id: str) -> int:
    """Return a stable 0-99 bucket for a user/flag combination."""
    raw = f"{flag_name}:{user_id}"
    digest = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
    return int(digest[:4], 16) % 100


def is_enabled(
    flag_name: str,
    user_id: str = "",
    org_id: str = "",
    default: bool = False,
) -> bool:
    """Evaluate whether a feature flag is enabled for the given context.

    Evaluation order:
    1. Per-user override (exact match)
    2. Per-org override (exact match)
    3. Percentage rollout (hash-stable)
    4. Global enabled/disabled
    5. Default value
    """
    cache_key = f"{flag_name}:{user_id}:{org_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return bool(cached)

    try:
        record = _load_flag(flag_name)
        if record is None:
            _cache_set(cache_key, default)
            return default

        # Per-user override
        if user_id:
            user_overrides: dict = record.get("user_overrides") or {}
            if isinstance(user_overrides, str):
                user_overrides = json.loads(user_overrides)
            if user_id in user_overrides:
                result = bool(user_overrides[user_id])
                _cache_set(cache_key, result)
                return result

        # Per-org override
        if org_id:
            org_overrides: dict = record.get("org_overrides") or {}
            if isinstance(org_overrides, str):
                org_overrides = json.loads(org_overrides)
            if org_id in org_overrides:
                result = bool(org_overrides[org_id])
                _cache_set(cache_key, result)
                return result

        # Percentage rollout
        rollout_pct = int(record.get("rollout_percentage", 0) or 0)
        if rollout_pct > 0 and user_id:
            bucket = _percentage_bucket(flag_name, user_id)
            result = bucket < rollout_pct
            _cache_set(cache_key, result)
            return result

        # Global toggle
        result = bool(record.get("enabled", default))
        _cache_set(cache_key, result)
        return result

    except Exception as exc:
        logger.warning("feature_flag_eval_error", flag=flag_name, error=str(exc))
        return default


def get_flag_value(
    flag_name: str,
    user_id: str = "",
    org_id: str = "",
    default: Any = None,
) -> Any:
    """Return the flag's arbitrary payload value, or default."""
    try:
        record = _load_flag(flag_name)
        if record is None:
            return default
        return record.get("value", default)
    except Exception:
        return default


# ── Admin helpers ─────────────────────────────────────────────────────────────

def set_flag(
    flag_name: str,
    enabled: bool,
    description: str = "",
    rollout_percentage: int = 0,
    user_overrides: dict | None = None,
    org_overrides: dict | None = None,
    value: Any = None,
) -> dict:
    """Create or update a feature flag. Returns the saved record."""
    try:
        from .db import upsert_feature_flag
        record = upsert_feature_flag(
            name=flag_name,
            enabled=enabled,
            description=description,
            rollout_percentage=max(0, min(100, rollout_percentage)),
            user_overrides=json.dumps(user_overrides or {}),
            org_overrides=json.dumps(org_overrides or {}),
            value=json.dumps(value) if value is not None else "",
        )
        invalidate_cache(flag_name)
        return record
    except Exception as exc:
        logger.error("feature_flag_set_error", flag=flag_name, error=str(exc))
        return {"name": flag_name, "enabled": enabled, "error": str(exc)}


def delete_flag(flag_name: str) -> bool:
    """Delete a feature flag. Returns True if deleted."""
    try:
        from .db import delete_feature_flag
        result = delete_feature_flag(flag_name)
        invalidate_cache(flag_name)
        return result
    except Exception as exc:
        logger.error("feature_flag_delete_error", flag=flag_name, error=str(exc))
        return False


def list_flags() -> list[dict]:
    """Return all feature flags."""
    try:
        from .db import list_feature_flags
        return list_feature_flags()
    except Exception as exc:
        logger.error("feature_flag_list_error", error=str(exc))
        return []
