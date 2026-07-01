"""
Rate Limiter Middleware — per-user sliding-window enforcement.

Wires the existing `_evaluate_rate_limit()` into a FastAPI middleware
and adds per-user quota management endpoints. Supports:
- Global settings (soft/hard mode, per_minute/per_day limits)
- Per-user overrides (admin can set custom quotas per user)
- Quota state inspection and reset
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .db import load_pref, save_pref

logger = logging.getLogger(__name__)

# ── defaults & shared state ──────────────────────────────────────────

_DEFAULT_SETTINGS: dict[str, Any] = {"mode": "soft", "per_minute": 60, "per_day": 2500}


def _load_persisted_settings() -> dict[str, Any]:
    raw = load_pref("rate_limit_settings", "")
    if not raw:
        return dict(_DEFAULT_SETTINGS)
    try:
        parsed = json.loads(raw)
    except Exception:
        return dict(_DEFAULT_SETTINGS)
    mode = str(parsed.get("mode", _DEFAULT_SETTINGS["mode"])).strip().lower()
    if mode not in ("soft", "hard"):
        mode = _DEFAULT_SETTINGS["mode"]
    return {
        "mode": mode,
        "per_minute": max(1, min(int(parsed.get("per_minute", 60)), 100000)),
        "per_day": max(1, min(int(parsed.get("per_day", 2500)), 10000000)),
    }


_settings = _load_persisted_settings()

# Per-user overrides stored as JSON prefs
_per_user_overrides: dict[str, dict[str, int]] = {}


def get_settings() -> dict[str, Any]:
    return dict(_settings)


def update_settings(mode: str, per_minute: int, per_day: int) -> dict[str, Any]:
    global _settings
    _settings["mode"] = mode
    _settings["per_minute"] = per_minute
    _settings["per_day"] = per_day
    save_pref("rate_limit_settings", json.dumps(_settings))
    return dict(_settings)


# ── per-user quota overrides ─────────────────────────────────────────


def _load_user_overrides() -> dict[str, dict[str, int]]:
    raw = load_pref("rate_limit_user_overrides", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _save_user_overrides() -> None:
    save_pref("rate_limit_user_overrides", json.dumps(_per_user_overrides))


_per_user_overrides = _load_user_overrides()


def set_user_quota(username: str, per_minute: int | None, per_day: int | None) -> dict[str, Any]:
    """Set per-user quota overrides. None means 'use global default'."""
    if per_minute is not None:
        _per_user_overrides.setdefault(username, {})["per_minute"] = max(1, min(per_minute, 100000))
    if per_day is not None:
        _per_user_overrides.setdefault(username, {})["per_day"] = max(1, min(per_day, 10000000))
    _save_user_overrides()
    return get_user_quota(username)


def remove_user_override(username: str) -> bool:
    if username in _per_user_overrides:
        del _per_user_overrides[username]
        _save_user_overrides()
        return True
    return False


def get_user_quota(username: str) -> dict[str, Any]:
    """Get effective quota for a user (override or global)."""
    override = _per_user_overrides.get(username, {})
    return {
        "username": username,
        "per_minute": override.get("per_minute", _settings["per_minute"]),
        "per_day": override.get("per_day", _settings["per_day"]),
        "mode": _settings["mode"],
        "has_override": username in _per_user_overrides,
    }


def list_user_overrides() -> list[dict[str, Any]]:
    return [
        {"username": u, **o, "mode": _settings["mode"]}
        for u, o in sorted(_per_user_overrides.items())
    ]


# ── sliding-window request tracking ──────────────────────────────────

# In-process tracking: {principal: {"minute": [timestamps], "day": [timestamps]}}
_windows: dict[str, dict[str, list[float]]] = {}


def _sliding_check(principal: str, minute_limit: int, day_limit: int) -> dict[str, Any]:
    """Pure in-memory sliding-window check (no Redis dependency)."""
    now = time.time()
    entry = _windows.get(principal)
    if entry is None:
        entry = {"minute": [], "day": []}
        _windows[principal] = entry

    minute_window = 60.0
    day_window = 86400.0

    minute = [t for t in entry["minute"] if now - t < minute_window]
    day = [t for t in entry["day"] if now - t < day_window]

    minute_over = len(minute) >= minute_limit
    day_over = len(day) >= day_limit

    if not minute_over and not day_over:
        minute.append(now)
        day.append(now)
        entry["minute"] = minute
        entry["day"] = day
        return {"allowed": True, "retry_after_seconds": 0}

    limit_type = "per_minute" if minute_over else "per_day"
    limit_val = minute_limit if minute_over else day_limit
    used = len(minute) if minute_over else len(day)

    if _settings["mode"] == "soft":
        minute.append(now)
        day.append(now)
        entry["minute"] = minute
        entry["day"] = day
        return {"allowed": True, "retry_after_seconds": 0, "limit_type": limit_type, "limit": limit_val, "used": used}

    # Hard mode: blocked
    retry_after = 60 if minute_over else 3600
    if minute_over and minute:
        retry_after = max(1, int(minute_window - (now - min(minute))))
    elif day_over and day:
        retry_after = max(1, int(day_window - (now - min(day))))

    return {"allowed": False, "retry_after_seconds": retry_after, "limit_type": limit_type, "limit": limit_val, "used": used}


def check_rate_limit(principal: str) -> dict[str, Any]:
    """Evaluate rate limit for a principal. Returns {allowed, retry_after_seconds, ...}."""
    effective = get_user_quota(principal)
    minute_limit = effective["per_minute"]
    day_limit = effective["per_day"]

    # Try Redis-backed counters first
    try:
        from .redis_state import get_rate_counter, incr_rate_counter

        now = time.time()
        minute_bucket = str(int(now // 60))
        day_bucket = str(int(now // 86400))

        current_minute = get_rate_counter(principal, f"m:{minute_bucket}")
        current_day = get_rate_counter(principal, f"d:{day_bucket}")

        minute_over = current_minute >= minute_limit
        day_over = current_day >= day_limit

        if minute_over or day_over:
            limit_type = "per_minute" if minute_over else "per_day"
            limit_val = minute_limit if minute_over else day_limit
            used_val = current_minute if minute_over else current_day

            if _settings["mode"] == "hard":
                return {"allowed": False, "mode": "hard", "principal": principal, "limit_type": limit_type, "limit": limit_val, "used": used_val, "retry_after_seconds": 60 if minute_over else 3600}

            # Soft mode: record and allow
            new_minute = incr_rate_counter(principal, f"m:{minute_bucket}", 120)
            new_day = incr_rate_counter(principal, f"d:{day_bucket}", 172800)
            return {"allowed": True, "mode": "soft", "principal": principal, "limit_type": limit_type, "limit": limit_val, "used": new_minute if minute_over else new_day, "retry_after_seconds": 0}

        # Under limit: record both
        incr_rate_counter(principal, f"m:{minute_bucket}", 120)
        incr_rate_counter(principal, f"d:{day_bucket}", 172800)
        return {"allowed": True, "mode": _settings["mode"], "principal": principal, "retry_after_seconds": 0}
    except Exception:
        pass

    # Fallback: in-memory sliding window
    result = _sliding_check(principal, minute_limit, day_limit)
    result["mode"] = _settings["mode"]
    result["principal"] = principal
    return result


def get_quota_status(principal: str) -> dict[str, Any]:
    """Get current usage stats without incrementing counters."""
    effective = get_user_quota(principal)
    now = time.time()
    minute_window = 60.0
    day_window = 86400.0

    entry = _windows.get(principal, {"minute": [], "day": []})
    minute_count = len([t for t in entry["minute"] if now - t < minute_window])
    day_count = len([t for t in entry["day"] if now - t < day_window])

    return {
        "principal": principal,
        "per_minute_limit": effective["per_minute"],
        "per_day_limit": effective["per_day"],
        "used_this_minute": minute_count,
        "used_today": day_count,
        "mode": _settings["mode"],
        "allowed": minute_count < effective["per_minute"] and day_count < effective["per_day"],
    }


# ── FastAPI middleware ────────────────────────────────────────────────


class RateLimitMiddleware:
    """FastAPI ASGI middleware that enforces per-principal rate limits."""

    _SKIP_PREFIXES = ("/health", "/metrics", "/static", "/status", "/openapi.json", "/docs", "/redoc")
    _SKIP_METHODS = {"OPTIONS", "HEAD"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # Skip non-rate-limited paths
        if method in self._SKIP_METHODS or any(path.startswith(p) for p in self._SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Resolve principal
        principal = self._resolve_principal(scope)

        result = check_rate_limit(principal)
        if not result.get("allowed"):
            retry = result.get("retry_after_seconds", 60)
            from fastapi.responses import JSONResponse

            resp = JSONResponse(
                {
                    "error": "rate limit exceeded",
                    "type": "rate_limit",
                    "limit_type": result.get("limit_type", ""),
                    "limit": result.get("limit", 0),
                    "used": result.get("used", 0),
                    "retry_after_seconds": retry,
                },
                status_code=429,
                headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(result.get("limit", "")), "X-RateLimit-Remaining": "0"},
            )
            await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _resolve_principal(self, scope: dict) -> str:
        # Try auth header first
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                from .auth import resolve_token_username
                username = resolve_token_username(token)
                if username:
                    return username
            except Exception:
                pass

        # Try x-api-key header
        api_key = headers.get(b"x-api-key", b"").decode()
        if api_key:
            try:
                from .auth import lookup_api_key_owner
                owner = lookup_api_key_owner(api_key)
                if owner:
                    return owner
            except Exception:
                pass

        # Fallback: IP
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "anonymous"
