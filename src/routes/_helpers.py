"""Shared helper functions for route domain modules.

These are extracted from src/api/routes.py so they can be shared
across domain-specific route modules without circular imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from urllib import request as _urlrequest
from urllib import error as _urlerror

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────

_DEFAULT_AGENT_REQUEST_TIMEOUT_S = max(30.0, float(os.getenv("AGENT_REQUEST_TIMEOUT_S", "180")))

JWT_REFRESH_EXPIRE_D = int(os.getenv("JWT_REFRESH_EXPIRE_D", "14"))


# ── Resolve helpers ────────────────────────────────────────────────────

def _resolve_request_timeout_seconds(data: dict) -> float:
    raw = data.get("request_timeout_s")
    if raw is None:
        return _DEFAULT_AGENT_REQUEST_TIMEOUT_S
    try:
        return max(10.0, min(float(raw), 600.0))
    except (TypeError, ValueError):
        return _DEFAULT_AGENT_REQUEST_TIMEOUT_S


# ── Error builders ───────────────────────────────────────────────────────

def _api_error(message: str, code: str = "invalid_request", status_code: int = 400):
    return JSONResponse({"error": message, "type": code}, status_code=status_code)


def _v1_error(message: str, err_type: str = "invalid_request_error", status_code: int = 400, code: str = "invalid_request"):
    return JSONResponse(
        {
            "error": {"message": message, "type": err_type, "code": code, "status": status_code},
            "message": message,
            "type": err_type,
            "code": code,
        },
        status_code=status_code,
    )


async def _read_json_body(request: Request, err_message: str = "invalid JSON body") -> dict:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail=err_message)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=err_message)
    return data


# ── Response helpers ─────────────────────────────────────────────────────

def _normalize_response_format(response_format):
    if not response_format:
        return {"mode": None, "schema": None}
    if isinstance(response_format, str):
        normalized = response_format.strip().lower()
        if normalized in ("json", "json_object"):
            return {"mode": "json", "schema": None}
        raise ValueError("response_format must be 'json' or an object with type='json_schema'")
    if not isinstance(response_format, dict):
        raise ValueError("response_format must be a string or object")
    fmt_type = str(response_format.get("type", "")).strip().lower()
    if fmt_type == "json_object":
        return {"mode": "json", "schema": None}
    if fmt_type != "json_schema":
        raise ValueError("response_format.type must be 'json_object' or 'json_schema'")
    json_schema_cfg = response_format.get("json_schema")
    if not isinstance(json_schema_cfg, dict):
        raise ValueError("response_format.json_schema must be an object")
    schema = json_schema_cfg.get("schema")
    if not isinstance(schema, dict):
        raise ValueError("response_format.json_schema.schema must be an object")
    return {"mode": "json", "schema": schema}


def _builtin_chat_fallback(task: str, reason: str = "timeout") -> str:
    if reason == "provider_unavailable":
        return (
            "No model provider could be reached for this turn. "
            "Please check your provider keys in Settings and retry."
        )
    return (
        "The request timed out before a response was received. "
        "Please retry — if the problem persists, try a shorter message or check provider availability."
    )


def _builtin_coding_fallback(task: str, reason: str = "timeout") -> str:
    return ""


# ── JSON validation ──────────────────────────────────────────────────────

def _json_type_matches(value, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _validate_json_schema_value(value, schema: dict, path: str = "$"):
    schema_type = schema.get("type")
    if schema_type and not _json_type_matches(value, str(schema_type)):
        raise ValueError(f"{path} expected type '{schema_type}'")
    if "enum" in schema and value not in schema.get("enum", []):
        raise ValueError(f"{path} must be one of the enum values")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            raise ValueError(f"{path} schema properties must be an object")
        if not isinstance(required, list):
            raise ValueError(f"{path} schema required must be an array")
        for key in required:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = [k for k in value.keys() if k not in properties]
            if unknown:
                raise ValueError(f"{path} has unknown keys: {', '.join(sorted(unknown))}")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                _validate_json_schema_value(value[key], child_schema, f"{path}.{key}")
    if schema_type == "array":
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_json_schema_value(item, item_schema, f"{path}[{idx}]")


def _validate_json_output(text: str, schema: dict | None = None):
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
        if schema:
            _validate_json_schema_value(parsed, schema)
        return parsed
    except Exception as exc:
        initial_error = exc
    starts = [idx for idx, ch in enumerate(candidate) if ch in "[{"]
    for start in starts:
        stack: list[str] = []
        in_string = False
        escaped = False
        for idx in range(start, len(candidate)):
            ch = candidate[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch in "[{":
                stack.append(ch)
                continue
            if ch in "]}":
                if not stack:
                    break
                opener = stack.pop()
                if (opener, ch) not in (("{", "}"), ("[", "]")):
                    break
                if not stack:
                    snippet = candidate[start:idx + 1]
                    try:
                        parsed = json.loads(snippet)
                        if schema:
                            _validate_json_schema_value(parsed, schema)
                        return parsed
                    except Exception:
                        break
    raise ValueError(str(initial_error))


# ── IP / device helpers ─────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def _device_hash(request: Request) -> str:
    ua = request.headers.get("User-Agent", "")
    ip = _client_ip(request)
    return hashlib.sha256(f"{ua}|{ip}".encode()).hexdigest()


# ── Password helpers ─────────────────────────────────────────────────────

def _hash_pw(password: str, salt: str = "") -> str:
    import binascii
    s = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), (s + "nexus_ai_salt").encode(), 200000)
    return s + "$" + binascii.hexlify(dk).decode()


def _verify_pw(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 2:
            return False
        salt, _ = parts
        return secrets.compare_digest(stored, _hash_pw(password, salt))
    except Exception:
        return False


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ── JWT and auth helpers ────────────────────────────────────────────────

def _make_token(username: str, role: str | None = None) -> str:
    from ..auth import JWT_ALGO, JWT_EXPIRE_H, JWT_SECRET
    from ..db import get_user as db_get_user

    import jwt as _jwt

    user = db_get_user(username)
    role_value = str(role or (user.get("role", "user") if user else "user"))
    payload = {
        "sub": username,
        "role": role_value,
        "exp": int(time.time()) + JWT_EXPIRE_H * 3600,
        "type": "access",
        "jti": secrets.token_hex(8),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _make_refresh_token(username: str) -> str:
    from ..auth import JWT_ALGO, JWT_SECRET

    import jwt as _jwt

    payload = {
        "sub": username,
        "exp": int(time.time()) + JWT_REFRESH_EXPIRE_D * 86400,
        "type": "refresh",
        "jti": secrets.token_hex(8),
    }
    token = _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    _redis_save_refresh(token, {"username": username, "exp": payload["exp"]}, ttl_days=JWT_REFRESH_EXPIRE_D)
    return token


def _read_token(request: Request) -> str | None:
    from ..auth import JWT_ALGO, JWT_SECRET
    from ..db import get_api_key_by_hash as db_get_api_key_by_hash, touch_api_key as db_touch_api_key

    import jwt as _jwt

    raw_api_key = request.headers.get("X-API-Key", "").strip()
    if not raw_api_key:
        hdr = request.headers.get("Authorization", "")
        if hdr.startswith("Bearer nxk_"):
            raw_api_key = hdr[7:]
    if raw_api_key and raw_api_key.startswith("nxk_"):
        key_hash = _hash_api_key(raw_api_key)
        key_record = db_get_api_key_by_hash(key_hash)
        if key_record:
            db_touch_api_key(key_record["id"], time.time())
            return key_record["username"]
        return None

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    if _redis_is_revoked(token):
        return None
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("type") not in (None, "access"):
            return None
        return payload.get("sub")
    except Exception:
        return None


def _get_request_api_key_scopes(request: Request) -> list[str]:
    from ..db import get_api_key_by_hash as db_get_api_key_by_hash

    raw_api_key = request.headers.get("X-API-Key", "").strip()
    if not raw_api_key:
        hdr = request.headers.get("Authorization", "")
        if hdr.startswith("Bearer nxk_"):
            raw_api_key = hdr[7:]
    if raw_api_key and raw_api_key.startswith("nxk_"):
        key_hash = _hash_api_key(raw_api_key)
        key_record = db_get_api_key_by_hash(key_hash)
        if key_record:
            return list(key_record.get("scopes") or [])
    return ["*"]


def _get_token_role(request: Request) -> str:
    from ..auth import JWT_ALGO, JWT_SECRET, MULTI_USER

    import jwt as _jwt

    if not MULTI_USER:
        return "admin"
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return "guest"
    token = header[7:]
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload.get("role", "user")
    except Exception:
        return "guest"


def require_auth(request: Request) -> str:
    username = _read_token(request)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized — valid Bearer token required")
    return username


def require_admin(request: Request) -> str:
    from ..auth import MULTI_USER

    if not MULTI_USER:
        return "nexus_admin"
    username = require_auth(request)
    role = _get_token_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return username


def _principal_from_request(request: Request, sid: str = "", payload_user: str = "") -> str:
    token_user = _read_token(request)
    if token_user:
        return f"user:{token_user}"
    if payload_user:
        return f"openai_user:{str(payload_user).strip()[:80]}"
    if sid:
        return f"session:{sid}"
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "anonymous"


# ── Redis helpers with in-process fallback ───────────────────────────────

_revoked_access_tokens: set[str] = set()
_refresh_tokens: dict[str, dict] = {}
_active_user_sessions: dict[str, list[dict]] = {}
_active_user_sessions_lock = threading.Lock()


def _redis_revoke_token(token: str, ttl_seconds: int = 0) -> None:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        key = f"nexus:revoked:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
        r.set(key, "1", ex=ttl_seconds or (86400 * 14))
    except Exception:
        _revoked_access_tokens.add(token)


def _redis_is_revoked(token: str) -> bool:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        key = f"nexus:revoked:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
        if r.get(key):
            return True
    except Exception:
        pass
    return token in _revoked_access_tokens


def _redis_save_refresh(token: str, data: dict, ttl_days: int = 14) -> None:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        r.set(f"nexus:refresh:{token}", json.dumps(data), ex=ttl_days * 86400)
    except Exception:
        _refresh_tokens[token] = data


def _redis_get_refresh(token: str) -> dict | None:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        raw = r.get(f"nexus:refresh:{token}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return _refresh_tokens.get(token)


def _redis_delete_refresh(token: str) -> None:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        r.set(f"nexus:refresh:{token}", "", ex=1)
    except Exception:
        pass
    _refresh_tokens.pop(token, None)


def _redis_track_session(username: str, record: dict, max_sessions: int) -> list[str]:
    import json as _json

    revoked_tokens: list[str] = []
    try:
        from ..redis_state import get_redis
        r = get_redis()
        score = float(record.get("issued_at", time.time()))
        r.set(f"nexus:sessions:{username}:v:{score}", _json.dumps(record), ex=JWT_REFRESH_EXPIRE_D * 86400)
        members_key = f"nexus:session_list:{username}"
        members_raw = r.get(members_key)
        sessions: list[dict] = _json.loads(members_raw) if members_raw else []
        sessions.append(record)
        sessions.sort(key=lambda x: float(x.get("issued_at", 0)))
        while len(sessions) > max_sessions:
            oldest = sessions.pop(0)
            old_access = str(oldest.get("access") or "")
            old_refresh = str(oldest.get("refresh") or "")
            if old_access:
                revoked_tokens.append(old_access)
                _redis_revoke_token(old_access)
            if old_refresh:
                _redis_delete_refresh(old_refresh)
        r.set(members_key, _json.dumps(sessions), ex=JWT_REFRESH_EXPIRE_D * 86400)
        return revoked_tokens
    except Exception:
        pass
    with _active_user_sessions_lock:
        sessions = _active_user_sessions.get(username, [])
        sessions.append(record)
        sessions.sort(key=lambda x: float(x.get("issued_at", 0.0)))
        while len(sessions) > max_sessions:
            oldest = sessions.pop(0)
            old_access = str(oldest.get("access") or "")
            old_refresh = str(oldest.get("refresh") or "")
            if old_access:
                revoked_tokens.append(old_access)
                _revoked_access_tokens.add(old_access)
            if old_refresh:
                _refresh_tokens.pop(old_refresh, None)
        _active_user_sessions[username] = sessions
    return revoked_tokens


def _detect_suspicious_login(username: str, device_hash: str, ip: str) -> bool:
    try:
        from ..redis_state import get_redis
        r = get_redis()
        known_key = f"nexus:known_devices:{username}"
        last_ip_key = f"nexus:last_ip:{username}"
        known_devices_raw = r.get(known_key)
        known_devices: set[str] = set(json.loads(known_devices_raw)) if known_devices_raw else set()
        last_ip = (r.get(last_ip_key) or "").strip()

        is_new_device = device_hash not in known_devices

        def _subnet(addr: str) -> str:
            parts = addr.split(".")
            return ".".join(parts[:2]) if len(parts) == 4 else addr

        is_new_subnet = bool(last_ip) and _subnet(last_ip) != _subnet(ip)
        suspicious = is_new_device and is_new_subnet

        known_devices.add(device_hash)
        if len(known_devices) > 20:
            known_devices = set(list(known_devices)[-20:])
        r.set(known_key, json.dumps(list(known_devices)), ex=86400 * 90)
        r.set(last_ip_key, ip, ex=86400 * 90)
        return suspicious
    except Exception:
        return False


def _register_user_session(username: str, access_token: str, refresh_token: str, request: Request) -> None:
    max_sessions = int(os.getenv("MAX_SESSIONS_PER_USER", "5"))
    if max_sessions < 1:
        return
    record = {
        "access": access_token,
        "refresh": refresh_token,
        "issued_at": time.time(),
        "ip": _client_ip(request),
        "device_hash": _device_hash(request),
    }
    _redis_track_session(username, record, max_sessions)


# ── Rate limiting ────────────────────────────────────────────────────────

# In-memory request tracking (fallback when Redis is unavailable)
_session_requests: dict[str, dict] = {}

_rate_limit_settings: dict = {}
_rate_limit_lock = threading.Lock()


def _load_rate_limit_settings() -> dict:
    from ..db import load_pref as db_load_pref

    defaults = {"mode": "soft", "per_minute": 60, "per_day": 2500}
    raw = db_load_pref("rate_limit_settings", "")
    if not raw:
        return dict(defaults)
    try:
        parsed = json.loads(raw)
    except Exception:
        return dict(defaults)
    mode = str(parsed.get("mode", defaults["mode"])).lower().strip()
    per_minute = int(parsed.get("per_minute", defaults["per_minute"]))
    per_day = int(parsed.get("per_day", defaults["per_day"]))
    if mode not in ("soft", "hard"):
        mode = defaults["mode"]
    per_minute = max(1, min(per_minute, 100000))
    per_day = max(1, min(per_day, 10000000))
    return {"mode": mode, "per_minute": per_minute, "per_day": per_day}


def _evaluate_rate_limit(principal: str, tokens_requested: int = 0) -> dict:
    now = time.time()
    minute_limit = int(_rate_limit_settings.get("per_minute", 60))
    day_limit = int(_rate_limit_settings.get("per_day", 2500))
    mode = _rate_limit_settings.get("mode", "soft")
    minute_bucket = str(int(now // 60))
    day_bucket = str(int(now // 86400))

    # Per-user quota check (only for user principals)
    username = ""
    if principal.startswith("user:"):
        username = principal[5:]
        try:
            from ..profiles import check_quota

            if not check_quota(username, tokens_requested):
                return {
                    "allowed": False, "mode": "hard", "principal": principal,
                    "limit_type": "daily_quota",
                    "limit": 0, "used": 0,
                    "retry_after_seconds": 3600,
                    "quota_exceeded": True,
                }
        except Exception:
            pass

    try:
        from ..redis_state import get_rate_counter, incr_rate_counter

        current_minute = get_rate_counter(principal, f"m:{minute_bucket}")
        current_day = get_rate_counter(principal, f"d:{day_bucket}")
        minute_over = current_minute >= minute_limit
        day_over = current_day >= day_limit

        if minute_over or day_over:
            if mode == "hard":
                return {
                    "allowed": False, "mode": mode, "principal": principal,
                    "limit_type": "per_minute" if minute_over else "per_day",
                    "limit": minute_limit if minute_over else day_limit,
                    "used": current_minute if minute_over else current_day,
                    "retry_after_seconds": 60 if minute_over else 3600,
                }
            new_minute = incr_rate_counter(principal, f"m:{minute_bucket}", 120)
            new_day = incr_rate_counter(principal, f"d:{day_bucket}", 172800)
            # Still consume quota even in soft-over mode
            if username:
                _consume_user_quota(username, tokens_requested)
            return {
                "allowed": True, "mode": mode, "principal": principal,
                "limit_type": "per_minute" if minute_over else "per_day",
                "limit": minute_limit if minute_over else day_limit,
                "used": new_minute if minute_over else new_day,
                "retry_after_seconds": 0,
            }

        incr_rate_counter(principal, f"m:{minute_bucket}", 120)
        incr_rate_counter(principal, f"d:{day_bucket}", 172800)
        if username:
            _consume_user_quota(username, tokens_requested)
        return {
            "allowed": True, "mode": mode, "principal": principal,
            "limit_type": "", "limit": 0, "used": 0, "retry_after_seconds": 0,
        }
    except Exception:
        minute_window = 60.0
        day_window = 86400.0
        with _rate_limit_lock:
            entry = _session_requests.get(principal, {"minute": [], "day": []})
            minute = [t for t in entry.get("minute", []) if now - t < minute_window]
            day = [t for t in entry.get("day", []) if now - t < day_window]
            minute_over = len(minute) >= minute_limit
            day_over = len(day) >= day_limit
            is_over = minute_over or day_over

            if not is_over:
                minute.append(now)
                day.append(now)
                _session_requests[principal] = {"minute": minute, "day": day}
                if username:
                    _consume_user_quota(username, tokens_requested)
                return {"allowed": True, "mode": mode, "principal": principal,
                        "limit_type": "", "limit": 0, "used": 0, "retry_after_seconds": 0}

            if mode == "soft":
                minute.append(now)
                day.append(now)
                _session_requests[principal] = {"minute": minute, "day": day}
                if username:
                    _consume_user_quota(username, tokens_requested)
                return {
                    "allowed": True, "mode": mode, "principal": principal,
                    "limit_type": "per_minute" if minute_over else "per_day",
                    "limit": minute_limit if minute_over else day_limit,
                    "used": len(minute) if minute_over else len(day),
                    "retry_after_seconds": 0,
                }

            retry_after = 1
            if minute_over and minute:
                retry_after = max(1, int(minute_window - (now - minute[0])))
            elif day_over and day:
                retry_after = max(1, int(day_window - (now - day[0])))
            _session_requests[principal] = {"minute": minute, "day": day}
            return {
                "allowed": False, "mode": mode, "principal": principal,
                "limit_type": "per_minute" if minute_over else "per_day",
                "limit": minute_limit if minute_over else day_limit,
                "used": len(minute) if minute_over else len(day),
                "retry_after_seconds": retry_after,
            }


def _consume_user_quota(username: str, tokens: int = 0) -> None:
    """Record quota consumption for a user (best-effort, swallows errors)."""
    try:
        from ..profiles import consume_quota

        consume_quota(username, tokens)
    except Exception:
        pass


def _quota_error_response(limit_result: dict) -> JSONResponse:
    body = {
        "error": "Quota exceeded for this user",
        "type": "quota_exceeded",
        "quota": {
            "mode": limit_result.get("mode", "hard"),
            "principal": limit_result.get("principal", "anonymous"),
            "limit_type": limit_result.get("limit_type", "per_minute"),
            "limit": limit_result.get("limit", 0),
            "used": limit_result.get("used", 0),
            "retry_after_seconds": limit_result.get("retry_after_seconds", 1),
        },
    }
    retry = str(limit_result.get("retry_after_seconds", 1))
    limit = str(limit_result.get("limit", 0))
    remaining = str(max(0, int(limit_result.get("limit", 0)) - int(limit_result.get("used", 0))))
    headers = {
        "Retry-After": retry,
        "X-RateLimit-Limit": limit,
        "X-RateLimit-Remaining": remaining,
        "X-RateLimit-Reset": str(int(time.time()) + int(limit_result.get("retry_after_seconds", 1))),
        "X-RateLimit-Policy": limit_result.get("limit_type", "per_minute"),
    }
    return JSONResponse(body, status_code=429, headers=headers)


def _v1_quota_error_response(limit_result: dict) -> JSONResponse:
    message = "Quota exceeded for this user"
    retry = str(limit_result.get("retry_after_seconds", 1))
    limit = str(limit_result.get("limit", 0))
    remaining = str(max(0, int(limit_result.get("limit", 0)) - int(limit_result.get("used", 0))))
    headers = {
        "Retry-After": retry,
        "X-RateLimit-Limit": limit,
        "X-RateLimit-Remaining": remaining,
        "X-RateLimit-Reset": str(int(time.time()) + int(limit_result.get("retry_after_seconds", 1))),
        "X-RateLimit-Policy": limit_result.get("limit_type", "per_minute"),
    }
    return JSONResponse(
        {
            "error": {"message": message, "type": "quota_exceeded", "code": "quota_exceeded", "status": 429},
            "message": message,
            "type": "quota_exceeded",
            "code": "quota_exceeded",
            "quota": {
                "mode": limit_result.get("mode", "hard"),
                "principal": limit_result.get("principal", "anonymous"),
                "limit_type": limit_result.get("limit_type", "per_minute"),
                "limit": limit_result.get("limit", 0),
                "used": limit_result.get("used", 0),
                "retry_after_seconds": limit_result.get("retry_after_seconds", 1),
            },
        },
        status_code=429, headers=headers,
    )


# ── Provider capability helpers ──────────────────────────────────────────

def _provider_capability_flags(provider: dict) -> dict:
    provider_id = str(provider.get("id", "")).lower()
    model = str(provider.get("model", "")).lower()
    openai_compat = bool(provider.get("openai_compat", False))
    vision = provider_id in {"gemini", "ollama"} or any(token in model for token in (
        "vision", "llava", "bakllava", "gpt-4o", "gemini"))
    return {
        "tools": True,
        "vision": vision,
        "embeddings": openai_compat,
        "json_mode": openai_compat,
        "reasoning": provider_id in {"ollama", "claude", "grok", "gemini"} or any(
            token in model for token in ("r1", "reason", "think")),
    }


def _provider_capabilities_list(flags: dict) -> list[str]:
    return [name for name, enabled in flags.items() if enabled]


# ── Generic helpers used by domain route modules ────────────────────────

def _safe_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _is_truthy_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _http_json_request(
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict:
    data = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update({str(k): str(v) for k, v in headers.items()})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = _urlrequest.Request(url=url, data=data, method=method.upper(), headers=req_headers)
    try:
        with _urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = {}
            if body:
                try:
                    parsed = json.loads(body)
                except Exception:
                    parsed = {"raw": body}
            return {"ok": True, "status": int(resp.getcode()), "json": parsed, "text": body}
    except _urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        parsed = {}
        if body:
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
        return {"ok": False, "status": int(exc.code), "json": parsed, "text": body}
    except Exception as exc:
        return {"ok": False, "status": 0, "json": {}, "text": str(exc)}
