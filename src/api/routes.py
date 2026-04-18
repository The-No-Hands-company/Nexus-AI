import os, uuid, json, asyncio, threading, time, hmac, secrets, hashlib, base64
import jwt as _jwt
from datetime import datetime, timezone
from fastapi import Request, HTTPException, APIRouter
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError

router = APIRouter()
from ..agent import (run_agent_task, stream_agent_task, get_providers_list, get_provider_health, get_provider_capabilities, set_provider_persona_override, get_provider_persona_override, get_config, update_config, call_llm_with_fallback, call_llm_smart, get_session_dir, set_session_token, _session_state, get_system_resources, _config, PERSONAS, activity_log, _MAX_ACTIVITY, get_session_safety_profile, set_session_safety_profile, safety_log, _push_safety_event, AllProvidersExhausted)
from ..approvals import list_tool_approvals, decide_tool_approval
from ..auth import JWT_SECRET, JWT_ALGO, JWT_EXPIRE_H, AuthManager, MULTI_USER
from ..scheduler import (
    schedule_job,
    list_jobs,
    cancel_job,
    job_to_dict,
    set_run_function,
    restore_from_db,
)
from ..gist_backup import restore_from_gist
from ..db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats, load_chat as db_load_chat, delete_chat as db_delete_chat, save_share as db_save_share, load_share as db_load_share, init_projects_table, save_project as db_save_project, load_projects as db_load_projects, delete_project as db_delete_project, assign_chat_to_project, get_project_chats, save_custom_instructions as db_save_ci, load_custom_instructions as db_load_ci, update_memory_entry as db_update_memory, delete_memory_entry as db_delete_memory, pin_chat as db_pin_chat, get_pinned_chats, search_chats as db_search_chats, get_usage_stats, get_usage_daily, init_usage_table, save_custom_persona as db_save_persona, load_custom_personas as db_load_custom_personas, delete_custom_persona as db_del_persona, load_pref as db_load_pref, save_pref as db_save_pref, save_self_review as db_save_self_review, list_self_reviews as db_list_self_reviews, load_safety_audit_entries as db_load_safety_audit_entries, list_users as db_list_users, update_user_role as db_update_user_role, get_user as db_get_user, _backend as db_backend, update_user_email as db_update_user_email, create_api_key as db_create_api_key, list_api_keys as db_list_api_keys, get_api_key_by_hash as db_get_api_key_by_hash, revoke_api_key as db_revoke_api_key, touch_api_key as db_touch_api_key, get_or_create_oauth_user as db_get_or_create_oauth_user)
from ..personas import list_personas, set_persona, get_active_persona_name, get_persona
from ..memory import (add_memory, get_memory_context, summarize_history, get_semantic_memory, add_semantic_memory, delete_all as delete_all_memory, get_all as get_all_memory)
from ..autonomy import Orchestrator, PlanningSystem, classify_subtask
from ..safety import GuardrailViolation, check_user_task, scrub_pii
from ..safety_pipeline import SAFETY_POLICY_PROFILES, get_safety_policy, screen_input, explain_prompt_injection
from ..knowledge_graph import (
    kg_store as _kg_store,
    kg_query as _kg_query,
    kg_list_entities as _kg_list,
    kg_get as _kg_get,
    kg_delete as _kg_delete,
)
from ..execution_trace import (
    list_traces as _list_traces,
    load_checkpoints as _load_checkpoints,
    get_latest_checkpoint as _get_latest_checkpoint,
    delete_trace as _delete_trace,
    save_file_diff as _save_file_diff,
    get_file_diffs as _get_file_diffs,
    get_file_diff_detail as _get_file_diff_detail,
)
from ..ensemble import get_ensemble_enabled, set_ensemble_enabled
from .schemas import *
from .state import (
    run_results,
    sessions,
    chats,
    shares,
    projects,
    _PROJECT_CONTEXT_CACHE,
    _session_requests,
    _reactions,
    _active_streams,
    autonomy_traces,
    execution_traces,
    get_rag_system,
)

# ── API helpers ─────────────────────────────────────────────────────────────

def _api_error(message: str, code: str = "invalid_request", status_code: int = 400):
    return JSONResponse({"error": message, "type": code}, status_code=status_code)


def _v1_error(message: str, err_type: str = "invalid_request_error", status_code: int = 400, code: str = "invalid_request"):
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": err_type,
                "code": code,
                "status": status_code,
            },
            "message": message,
            "type": err_type,
            "code": code,
        },
        status_code=status_code,
    )


async def _read_json_body(request: Request, err_message: str = "invalid JSON body") -> dict:
    """Parse request JSON body and raise HTTPException on malformed payloads."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail=err_message)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=err_message)
    return data


def _normalize_response_format(response_format):
    if not response_format:
        return {"mode": None, "schema": None}

    if isinstance(response_format, str):
        normalized = response_format.strip().lower()
        if normalized == "json":
            return {"mode": "json", "schema": None}
        if normalized == "json_object":
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


def _apply_response_format_hint(task: str, response_format_mode: str = "", schema: dict | None = None) -> str:
    if not response_format_mode:
        return task
    if response_format_mode == "json" and not schema:
        return task + (
            "\n\nRespond with strict JSON only. "
            "The response must be valid JSON and contain no extra prose or markdown."
        )

    if response_format_mode == "json" and schema:
        compact_schema = json.dumps(schema, separators=(",", ":"))
        return task + (
            "\n\nRespond with strict JSON only and match this JSON Schema exactly: "
            f"{compact_schema}"
        )

    return task


def _run_scheduled_task(task: str) -> str:
    """Execute a scheduled background task and return short result text."""
    sid = f"sched_{uuid.uuid4().hex[:8]}"
    result = run_agent_task(task, history=[], sid=sid)
    return str(result.get("result", ""))[:1200]


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
        stack = []
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


def _provider_capability_flags(provider: dict) -> dict:
    provider_id = str(provider.get("id", "")).lower()
    model = str(provider.get("model", "")).lower()
    openai_compat = bool(provider.get("openai_compat", False))

    vision = provider_id in {"gemini", "ollama"} or any(token in model for token in (
        "vision", "llava", "bakllava", "gpt-4o", "gemini"
    ))
    embeddings = openai_compat
    json_mode = openai_compat
    reasoning = provider_id in {"ollama", "claude", "grok", "gemini"} or any(token in model for token in (
        "r1", "reason", "think"
    ))
    tools = True
    return {
        "tools": tools,
        "vision": vision,
        "embeddings": embeddings,
        "json_mode": json_mode,
        "reasoning": reasoning,
    }


def _provider_capabilities_list(flags: dict) -> list[str]:
    return [name for name, enabled in flags.items() if enabled]


def _principal_from_request(request: Request, sid: str = "", payload_user: str = "") -> str:
    """Resolve the best-effort caller identity for quota accounting."""
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


def _load_rate_limit_settings() -> dict:
    """Read persisted rate-limit policy with safe defaults."""
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


_rate_limit_settings = _load_rate_limit_settings()
_rate_limit_lock = threading.Lock()


def _evaluate_rate_limit(principal: str) -> dict:
    """Evaluate and record quota usage for a principal.

    Returns shape:
      {"allowed": bool, "mode": "soft|hard", "limit_type": "per_minute|per_day|", ...}
    """
    now = time.time()
    minute_window = 60.0
    day_window = 86400.0

    with _rate_limit_lock:
        entry = _session_requests.get(principal, {"minute": [], "day": []})
        minute = [t for t in entry.get("minute", []) if now - t < minute_window]
        day = [t for t in entry.get("day", []) if now - t < day_window]

        minute_limit = int(_rate_limit_settings.get("per_minute", 60))
        day_limit = int(_rate_limit_settings.get("per_day", 2500))
        mode = _rate_limit_settings.get("mode", "soft")

        minute_over = len(minute) >= minute_limit
        day_over = len(day) >= day_limit
        is_over = minute_over or day_over

        if not is_over:
            minute.append(now)
            day.append(now)
            _session_requests[principal] = {"minute": minute, "day": day}
            return {
                "allowed": True,
                "mode": mode,
                "principal": principal,
                "limit_type": "",
                "limit": 0,
                "used": 0,
                "retry_after_seconds": 0,
            }

        # Soft mode records pressure but does not block user flow.
        if mode == "soft":
            minute.append(now)
            day.append(now)
            _session_requests[principal] = {"minute": minute, "day": day}
            return {
                "allowed": True,
                "mode": mode,
                "principal": principal,
                "limit_type": "per_minute" if minute_over else "per_day",
                "limit": minute_limit if minute_over else day_limit,
                "used": len(minute) if minute_over else len(day),
                "retry_after_seconds": 0,
            }

        # Hard mode blocks and does not count blocked requests against quota.
        retry_after = 1
        if minute_over and minute:
            retry_after = max(1, int(minute_window - (now - minute[0])))
        elif day_over and day:
            retry_after = max(1, int(day_window - (now - day[0])))
        _session_requests[principal] = {"minute": minute, "day": day}
        return {
            "allowed": False,
            "mode": mode,
            "principal": principal,
            "limit_type": "per_minute" if minute_over else "per_day",
            "limit": minute_limit if minute_over else day_limit,
            "used": len(minute) if minute_over else len(day),
            "retry_after_seconds": retry_after,
        }


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


JWT_REFRESH_EXPIRE_D = int(os.getenv("JWT_REFRESH_EXPIRE_D", "14"))
_revoked_access_tokens: set[str] = set()
_refresh_tokens: dict[str, dict] = {}


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
            "error": {
                "message": message,
                "type": "quota_exceeded",
                "code": "quota_exceeded",
                "status": 429,
            },
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
        status_code=429,
        headers=headers,
    )


# ── auth helpers ──────────────────────────────────────────────────────────────
def _hash_pw(password: str, salt: str = "") -> str:
    s = salt or secrets.token_hex(16)
    import binascii
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

def _make_token(username: str) -> str:
    from time import time as _t
    user = db_get_user(username)
    role = user.get("role", "user") if user else "user"
    payload = {
        "sub": username,
        "role": role,
        "exp": int(_t()) + JWT_EXPIRE_H * 3600,
        "type": "access",
        "jti": secrets.token_hex(8),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _make_refresh_token(username: str) -> str:
    from time import time as _t
    payload = {
        "sub": username,
        "exp": int(_t()) + JWT_REFRESH_EXPIRE_D * 86400,
        "type": "refresh",
        "jti": secrets.token_hex(8),
    }
    token = _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    _refresh_tokens[token] = {"username": username, "exp": payload["exp"]}
    return token

def _orchestrator_llm(prompt: str, task: str = "") -> str:
    result, _pid = call_llm_with_fallback([{"role":"user","content":prompt}], task)
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _read_token(request: Request) -> str | None:
    # 1. X-API-Key header
    raw_api_key = request.headers.get("X-API-Key", "").strip()
    if not raw_api_key:
        # Also allow Bearer nxk_... as API key
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

    # 2. Standard JWT Bearer
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    if token in _revoked_access_tokens:
        return None
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("type") not in (None, "access"):
            return None
        return payload.get("sub")
    except Exception:
        return None


def _get_request_api_key_scopes(request: Request) -> list[str]:
    """Return scopes for the API key used in this request, or [] if JWT auth."""
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
    return ["*"]  # JWT auth = all scopes

def require_auth(request: Request) -> str:
    from fastapi import HTTPException
    username = _read_token(request)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized — valid Bearer token required")
    return username


def _get_token_role(request: Request) -> str:
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


def require_admin(request: Request) -> str:
    if not MULTI_USER:
        return "nexus_admin"
    username = require_auth(request)
    role = _get_token_role(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return username

# ── auth endpoints ────────────────────────────────────────────────────────────
@router.post("/auth/register")
def auth_register(username: str = "", password: str = ""):
    from ..db import create_user, user_exists
    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)
    if len(username) < 3 or len(password) < 8:
        return JSONResponse({"error": "username min 3 chars, password min 8 chars"}, status_code=400)
    if user_exists(username):
        return JSONResponse({"error": "username already taken"}, status_code=409)
    hashed = _hash_pw(password)
    ok = create_user(username, hashed, username)
    if ok:
        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        return {"token": token, "refresh_token": refresh_token, "username": username}
    return JSONResponse({"error": "registration failed"}, status_code=500)

@router.post("/auth/login")
def auth_login(username: str = "", password: str = ""):
    from ..db import get_user
    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)
    user = get_user(username)
    if not user or not _verify_pw(password, user["password"]):
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    token = _make_token(username)
    refresh_token = _make_refresh_token(username)
    return {"token": token, "refresh_token": refresh_token, "username": username}

@router.get("/auth/me")
def auth_me(request: Request):
    username = _read_token(request)
    if not username:
        return JSONResponse({"username": None}, status_code=401)
    return {"username": username}


@router.post("/auth/logout")
async def auth_logout(request: Request):
    body = {}
    try:
        body = await _read_json_body(request)
    except HTTPException:
        body = {}

    header = request.headers.get("Authorization", "")
    has_access = header.startswith("Bearer ")
    if has_access:
        token = header[7:]
        if token:
            _revoked_access_tokens.add(token)

    refresh_token = str(body.get("refresh_token") or "").strip()
    if refresh_token:
        _refresh_tokens.pop(refresh_token, None)

    return {
        "ok": True,
        "revoked_access": has_access,
        "revoked_refresh": bool(refresh_token),
    }


@router.post("/auth/refresh")
async def auth_refresh(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    refresh_token = str(body.get("refresh_token") or "").strip()
    if not refresh_token:
        return _api_error("refresh_token is required", "validation_error", 422)

    record = _refresh_tokens.get(refresh_token)
    if not record:
        return _api_error("invalid refresh token", "unauthorized", 401)

    try:
        payload = _jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        _refresh_tokens.pop(refresh_token, None)
        return _api_error("invalid refresh token", "unauthorized", 401)

    if payload.get("type") != "refresh":
        return _api_error("invalid refresh token", "unauthorized", 401)

    username = str(payload.get("sub") or "").strip()
    if not username or record.get("username") != username:
        return _api_error("invalid refresh token", "unauthorized", 401)

    _refresh_tokens.pop(refresh_token, None)
    new_access = _make_token(username)
    new_refresh = _make_refresh_token(username)
    return {"token": new_access, "refresh_token": new_refresh, "username": username}

@router.get("/")
def home(): return FileResponse("static/index.html")


# ── Webhook trigger ─────────────────────────────────────────────────────────────
# POST /webhook/trigger  { "task": "fix the login bug", "repo": "owner/repo" }
# Runs the agent asynchronously and streams back SSE or returns a run_id for polling.
# Optional header: X-Webhook-Secret: <secret>  (validated against WEBHOOK_SECRET env var)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

@router.post("/webhook/trigger")
async def webhook_trigger(request: Request):
    secret = request.headers.get("x-webhook-secret", "")
    if WEBHOOK_SECRET and not hmac.compare_digest(secret, WEBHOOK_SECRET):
        return JSONResponse({"error": "invalid webhook secret"}, status_code=403)
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
    task = body.get("task", "")
    if not task: return JSONResponse({"error": "task field is required"}, status_code=400)
    try: task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc: return _api_error(exc.reason, exc.code, 422)
    repo = body.get("repo", "")
    run_id = "run_" + secrets.token_hex(8)
    run_results[run_id] = {"status": "running", "result": None, "error": None}
    def _run():
        try:
            from ..agent import run_agent_task
            result = run_agent_task(task, [], sid=run_id)
            run_results[run_id] = {"status": "done", "result": result, "error": None}
        except Exception as e:
            run_results[run_id] = {"status": "error", "result": None, "error": str(e)}
    threading.Thread(target=_run, daemon=True).start()
    return {"run_id": run_id, "status": "https://github.com/The-No-Hands-company/Nexus-AI#webhook-triggers"}

@router.get("/webhook/status/{run_id}")
async def webhook_status(run_id: str):
    result = run_results.get(run_id)
    if not result: return JSONResponse({"error": "run_id not found"}, status_code=404)
    return result

@router.get("/health")
def health(): return {"status":"healthy","provider":get_config()["provider"]}

@router.get("/api/system/resources")
def system_resources(): return get_system_resources()

@router.get("/providers")
def providers(): return {"providers":get_providers_list()}


@router.get("/providers/health")
def providers_health():
    """Return per-provider health status including rate limits, capabilities, and benchmarks."""
    return get_provider_health()


@router.get("/providers/status")
def providers_status():
    """Alias for /providers/health - same as /providers but with detailed health info."""
    return get_provider_health()


@router.get("/v1/models/capabilities")
def v1_models_capabilities():
    """Return capability matrix for all providers (vision, json_mode, tools, reasoning, streaming)."""
    return get_provider_capabilities()


@router.get("/v1/models/{model_id}")
def v1_get_model(model_id: str):
    """Get detailed info for a specific model."""
    from ..agent import PROVIDERS, PROVIDER_CAPABILITIES, _PROVIDER_BENCHMARKS
    # Try to find the model in providers
    for pid, cfg in PROVIDERS.items():
        if cfg["default_model"] == model_id or pid == model_id:
            benchmarks = _PROVIDER_BENCHMARKS.get(pid, {})
            return {
                "id": model_id,
                "provider": pid,
                "label": cfg["label"],
                "default_model": cfg["default_model"],
                "openai_compat": cfg.get("openai_compat", False),
                "capabilities": PROVIDER_CAPABILITIES.get(pid, {}),
                "benchmarks": {
                    "estimated_latency_ms": benchmarks.get("latency_ms", 0),
                    "quality_score": benchmarks.get("quality", 0),
                    "tier": benchmarks.get("tier", "unknown"),
                    "cost_tier": benchmarks.get("cost_tier", "unknown"),
                }
            }
    return _api_error(f"Model not found: {model_id}", "model_not_found", 404)


# ── Swarm View ────────────────────────────────────────────────────────────────

@router.get("/swarm/activity")
def swarm_activity(limit: int = 50):
    """Return the most recent swarm activity events (capped at _MAX_ACTIVITY)."""
    limit = max(1, min(limit, _MAX_ACTIVITY))
    return {"events": activity_log[-limit:], "total": len(activity_log)}


@router.post("/safety/check")
async def safety_check(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "").strip()
    if not text:
        return _api_error("text is required", "validation_error", 422)
    allow_destructive = bool(data.get("allow_destructive", False))
    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard") or "standard")
    verdict = screen_input(text, allow_destructive=allow_destructive, policy_profile=profile)
    payload = verdict.to_dict()
    payload["policy_profile"] = profile
    payload["policy"] = get_safety_policy(profile)
    payload["issues"] = [
        {
            "code": issue["code"],
            "reason": issue["reason"],
            "detail": issue["detail"],
            "severity": issue["threat"],
            "pattern": issue["pattern"],
        }
        for issue in payload["issues"]
    ]
    if not verdict.allowed:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "input_guardrail",
            "label": text[:120],
            "profile": profile,
            "verdict": payload,
        })
    elif payload.get("pii_matches"):
        _push_safety_event("pii_scrub", {
            "scope": "input",
            "profile": profile,
            "count": len(payload.get("pii_matches") or []),
            "label": text[:120],
            "findings": payload.get("pii_matches") or [],
        })
    return payload


@router.post("/safety/pii-scan")
async def pii_scan(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "")
    if not text.strip():
        return _api_error("text is required", "validation_error", 422)
    result = scrub_pii(text)
    if result.get("total_findings", 0) > 0:
        _push_safety_event("pii_scrub", {
            "scope": "scan",
            "count": result.get("total_findings", 0),
            "label": text[:120],
            "findings": result.get("findings") or [],
        })
    return result


@router.post("/safety/prompt-injection")
async def prompt_injection_scan(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "")
    if not text.strip():
        return _api_error("text is required", "validation_error", 422)

    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard") or "standard")
    explain_mode = bool(data.get("explain", False))
    verdict = screen_input(text, allow_destructive=False, policy_profile=profile)
    prompt_issues = [issue.to_dict() for issue in verdict.issues if issue.code == "prompt_injection"]
    patterns = [issue.get("pattern") for issue in prompt_issues if issue.get("pattern")]
    detected = bool(prompt_issues)

    payload = {
        "detected": detected,
        "stage": "input",
        "policy_profile": profile,
        "policy": get_safety_policy(profile),
        "action": "block" if detected else "allow",
        "threat": (prompt_issues[0].get("threat") if prompt_issues else "none"),
        "issues": [
            {
                "code": issue["code"],
                "reason": issue["reason"],
                "detail": issue["detail"],
                "severity": issue["threat"],
                "pattern": issue["pattern"],
            }
            for issue in prompt_issues
        ],
        "matches": patterns,
        "explain_mode": explain_mode,
    }

    if explain_mode:
        payload["explain"] = explain_prompt_injection(text)

    if detected:
        _push_safety_event("block", {
            "scope": "prompt_injection_scan",
            "tool": "prompt_injection_scan",
            "label": text[:120],
            "profile": profile,
            "verdict": payload,
        })

    return payload


# ── Scheduler API ─────────────────────────────────────────────────────────────

@router.get("/scheduler/jobs")
def scheduler_jobs():
    jobs = [job_to_dict(j) for j in list_jobs()]
    return {"jobs": jobs, "total": len(jobs)}


@router.post("/scheduler/jobs")
async def scheduler_create_job(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    name = (body.get("name") or "background-task").strip()
    task = (body.get("task") or "").strip()
    schedule = (body.get("schedule") or "5m").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)
    try:
        job = schedule_job(name=name, task=task, schedule=schedule)
        return {"job": job_to_dict(job)}
    except Exception as exc:
        return _api_error(f"Failed to create job: {exc}", "validation_error", 422)


@router.post("/scheduler/jobs/{job_id}/cancel")
def scheduler_cancel_job(job_id: str):
    if cancel_job(job_id):
        return {"ok": True, "job_id": job_id}
    return _api_error("job not found", "not_found", 404)


@router.post("/v1/images/generations")
async def v1_images_generations(request: Request):
    """OpenAI-compatible local image generation endpoint."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _v1_error(str(exc.detail), "invalid_request_error", exc.status_code)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _v1_error("prompt is required", "invalid_request_error", 422)

    size = str(body.get("size") or "1024x1024").strip().lower()
    width, height = 1024, 1024
    if "x" in size:
        try:
            width, height = [int(x) for x in size.split("x", 1)]
        except Exception:
            return _v1_error("size must be in WxH format", "invalid_request_error", 422)

    try:
        from ..generation import generate_image_local

        image_bytes = generate_image_local(
            prompt=prompt,
            negative_prompt=str(body.get("negative_prompt") or ""),
            width=width,
            height=height,
            steps=int(body.get("steps") or 20),
            backend=str(body.get("backend") or "ollama_flux"),
            model=str(body.get("model") or "auto"),
        )
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)

    return {
        "created": int(time.time()),
        "data": [
            {
                "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                "revised_prompt": prompt,
            }
        ],
    }


@router.post("/generation/video")
async def generation_video(request: Request):
    """Generate local video bytes and return base64 payload."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _api_error("prompt is required", "validation_error", 422)

    try:
        from ..generation import generate_video

        video_bytes = generate_video(
            prompt=prompt,
            duration_seconds=float(body.get("duration_seconds") or 4.0),
            fps=int(body.get("fps") or 8),
            width=int(body.get("width") or 512),
            height=int(body.get("height") or 512),
            backend=str(body.get("backend") or "wan_local"),
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)
    except Exception as exc:
        return _api_error(str(exc), "generation_error", 500)

    return {
        "mime_type": "video/mp4",
        "duration_seconds": float(body.get("duration_seconds") or 4.0),
        "video_b64": base64.b64encode(video_bytes).decode("ascii"),
    }


@router.post("/vision/understand")
async def vision_understand(request: Request):
    """Describe an image using local vision flow."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    image_b64 = str(body.get("image_b64") or "").strip()
    image_url = str(body.get("image_url") or "").strip()
    prompt = str(body.get("prompt") or "Describe this image in detail.")
    mime_type = str(body.get("mime_type") or "image/png")

    if not image_b64 and not image_url:
        return _api_error("image_b64 or image_url is required", "validation_error", 422)

    try:
        from ..vision import describe_image, capture_screenshot

        if image_b64:
            image_bytes = base64.b64decode(image_b64)
        else:
            image_bytes = capture_screenshot(image_url)
            mime_type = "image/png"

        description = describe_image(image_bytes=image_bytes, mime_type=mime_type, prompt=prompt)
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)
    except Exception as exc:
        return _api_error(str(exc), "vision_error", 500)

    return {
        "description": description,
        "mime_type": mime_type,
        "prompt": prompt,
    }


@router.post("/integrations/tunnel")
async def integrations_tunnel(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    try:
        from ..integrations import NexusTunnelConfig, connect_tunnel, get_tunnel_status
        config = NexusTunnelConfig(
            endpoint=str(body.get("endpoint") or "").strip(),
            auth_token=str(body.get("auth_token") or "").strip(),
            local_port=int(body.get("local_port") or 8000),
            subdomain=str(body.get("subdomain") or "").strip(),
            auto_reconnect=bool(body.get("auto_reconnect", True)),
        )
        public_url = connect_tunnel(config)
        return {"public_url": public_url, "status": get_tunnel_status()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/integrations/guardian")
async def integrations_guardian(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    try:
        from ..integrations import GuardianConfig, get_guardian_status, register_with_guardian
        config = GuardianConfig(
            endpoint=str(body.get("endpoint") or "").strip(),
            api_key=str(body.get("api_key") or "").strip(),
            organisation_id=str(body.get("organisation_id") or "").strip(),
            enforce_policies=bool(body.get("enforce_policies", True)),
        )
        instance_id = register_with_guardian(config)
        return {"instance_id": instance_id, "status": get_guardian_status()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/integrations/edge")
async def integrations_edge(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    try:
        from ..integrations import EdgeNodeConfig, get_edge_status, register_edge_node
        config = EdgeNodeConfig(
            node_id=str(body.get("node_id") or "").strip(),
            orchestrator_url=str(body.get("orchestrator_url") or "").strip(),
            model_ids=list(body.get("model_ids") or []),
            heartbeat_interval_s=int(body.get("heartbeat_interval_s") or 30),
            max_concurrent_requests=int(body.get("max_concurrent_requests") or 4),
            api_key=str(body.get("api_key") or "").strip(),
        )
        node_id = register_edge_node(config)
        return {"node_id": node_id, "status": get_edge_status()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/collab/rooms")
async def collab_create_room(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    owner = str(body.get("owner") or "").strip()
    if not owner:
        return _api_error("owner is required", "validation_error", 422)

    try:
        from ..collab import create_room
        room = create_room(owner=owner, name=str(body.get("name") or ""), session_id=body.get("session_id"))
        return {"room": room.to_dict()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/collab/rooms")
def collab_list_rooms(username: str = ""):
    from ..collab import list_rooms
    rooms = list_rooms(username=username or None)
    return {"rooms": [room.to_dict() for room in rooms], "total": len(rooms)}


@router.get("/collab/rooms/{room_id}")
def collab_get_room(room_id: str):
    from ..collab import get_room
    room = get_room(room_id)
    if not room:
        return _api_error("room not found", "not_found", 404)
    return {"room": room.to_dict()}


@router.post("/collab/rooms/{room_id}/join")
async def collab_join(room_id: str, request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    username = str(body.get("username") or "").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    try:
        from ..collab import join_room
        room = join_room(room_id=room_id, username=username)
        return {"room": room.to_dict()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/collab/rooms/{room_id}/leave")
async def collab_leave(room_id: str, request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    username = str(body.get("username") or "").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    from ..collab import leave_room
    room_empty = leave_room(room_id=room_id, username=username)
    return {"ok": True, "room_empty": room_empty}


@router.delete("/collab/rooms/{room_id}")
def collab_close(room_id: str):
    from ..collab import close_room
    if not close_room(room_id):
        return _api_error("room not found", "not_found", 404)
    return {"ok": True, "room_id": room_id}


@router.post("/benchmark/eval-suite")
async def benchmark_eval_suite(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    model = str(body.get("model") or "").strip()
    if not model:
        return _api_error("model is required", "validation_error", 422)

    try:
        from ..eval_pipeline import run_eval_suite
        result = run_eval_suite(
            model=model,
            provider=str(body.get("provider") or "ollama"),
            suites=list(body.get("suites") or []),
            n_samples=int(body.get("n_samples") or 20),
            adapter_id=body.get("adapter_id"),
        )
        return {
            **{k: v for k, v in result.items() if k != "jobs"},
            "jobs": [job.__dict__ for job in result["jobs"]],
        }
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/benchmark/regression")
async def benchmark_regression(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    model = str(body.get("model") or "").strip()
    if not model:
        return _api_error("model is required", "validation_error", 422)

    try:
        from ..eval_pipeline import run_regression_benchmark
        return run_regression_benchmark(
            model=model,
            provider=str(body.get("provider") or "ollama"),
            suites=list(body.get("suites") or []),
            threshold=float(body.get("threshold") or 0.05),
            n_samples=int(body.get("n_samples") or 20),
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/compute/contributed/register")
async def contributed_register(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    try:
        from ..hardware import register_contributed_compute
        registration = register_contributed_compute(
            endpoint=str(body.get("endpoint") or "").strip(),
            api_key=str(body.get("api_key") or "").strip(),
            max_concurrent=int(body.get("max_concurrent") or 1),
        )
        return registration
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/compute/contributed/nodes")
def contributed_nodes():
    from ..hardware import list_contributed_compute_nodes
    nodes = list_contributed_compute_nodes()
    return {"nodes": nodes, "total": len(nodes)}


@router.delete("/compute/contributed/{node_id}")
def contributed_deregister(node_id: str):
    from ..hardware import deregister_contributed_compute
    removed = deregister_contributed_compute(node_id)
    if not removed:
        return _api_error("node not found", "not_found", 404)
    return {"ok": True, "node_id": node_id}


# ── OpenAI-compatible API (v1) ────────────────────────────────────────────────
# Allows Nexusclaw, Nexus Computer, and any OpenAI-compatible client to use
# Nexus AI as a drop-in API engine.  Set base_url to http://<host>:<port>/v1.
#
# Endpoints:
#   GET  /v1/models                  – list available models
#   GET  /v1/models/{model}          – retrieve model metadata
#   POST /v1/chat/completions        – synchronous or streaming chat


def _v1_models_catalog() -> list[dict]:
    providers = get_providers_list()
    provider_models = []
    for provider in providers:
        if isinstance(provider, dict):
            provider_id = str(provider.get("id", "")).strip()
        else:
            provider_id = str(provider).strip()
        if not provider_id:
            continue
        provider_models.append(
            {
                "id": f"nexus-ai/{provider_id}",
                "object": "model",
                "created": 0,
                "owned_by": "nexus-systems",
            }
        )

    return [
        {"id": "nexus-ai", "object": "model", "created": 0, "owned_by": "nexus-systems"},
        {"id": "nexus-ai/auto", "object": "model", "created": 0, "owned_by": "nexus-systems"},
    ] + provider_models

@router.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": _v1_models_catalog(),
    }

@router.get("/v1/models/capabilities")
def v1_model_capabilities():
    providers = get_providers_list()
    return {
        "object": "list",
        "data": [
            {
                "id": f"nexus-ai/{provider['id']}",
                "object": "model",
                "label": provider["label"],
                "provider": provider["id"],
                "model": provider["model"],
                "openai_compat": provider.get("openai_compat", False),
                "keyless": provider.get("keyless", False),
                "available": provider.get("available", False),
                "rate_limited": provider.get("rate_limited", False),
                **_provider_capability_flags(provider),
                "capabilities": _provider_capabilities_list(_provider_capability_flags(provider)),
            }
            for provider in providers
        ],
    }


@router.get("/v1/models/{model_id:path}")
def v1_model_retrieve(model_id: str):
    requested_id = model_id
    if not requested_id.startswith("nexus-ai"):
        requested_id = f"nexus-ai/{requested_id}"

    for model in _v1_models_catalog():
        if model["id"] == requested_id:
            return model

    return _v1_error(
        f"Model '{requested_id}' not found",
        "not_found_error",
        404,
        "model_not_found",
    )


@router.get("/v1/capabilities")
def v1_capabilities():
    """Return platform-level capability metadata for OpenAI-compatible clients."""
    providers = get_providers_list()
    flags = [_provider_capability_flags(provider) for provider in providers]
    return {
        "object": "capabilities",
        "provider_count": len(providers),
        "tools": any(flag["tools"] for flag in flags),
        "vision": any(flag["vision"] for flag in flags),
        "embeddings": any(flag["embeddings"] for flag in flags),
        "json_mode": any(flag["json_mode"] for flag in flags),
        "reasoning": any(flag["reasoning"] for flag in flags),
    }


def _normalize_embeddings_input(raw_input):
    if isinstance(raw_input, str):
        text = raw_input
        return [text], max(1, len(text.split()))

    if not isinstance(raw_input, list) or not raw_input:
        raise ValueError("input is required")

    if all(isinstance(item, str) for item in raw_input):
        texts = raw_input
        token_count = sum(max(1, len(item.split())) for item in texts)
        return texts, token_count

    if all(isinstance(item, int) for item in raw_input):
        token_ids = raw_input
        return [" ".join(str(token) for token in token_ids)], max(1, len(token_ids))

    if all(isinstance(item, list) and all(isinstance(token, int) for token in item) for item in raw_input):
        token_batches = raw_input
        texts = [" ".join(str(token) for token in token_batch) for token_batch in token_batches]
        token_count = sum(max(1, len(token_batch)) for token_batch in token_batches)
        return texts, token_count

    raise ValueError("input must be a string, list of strings, token array, or list of token arrays")


def _estimate_text_tokens(text: str) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    return len(normalized.split())

@router.post("/v1/embeddings")
async def v1_embeddings(request: Request):
    try:
        payload = V1EmbeddingsRequest(**(await request.json()))
    except ValidationError:
        return _v1_error("Invalid embeddings request", "validation_error", 422, "validation_error")

    try:
        inputs, prompt_tokens = _normalize_embeddings_input(payload.input)
    except ValueError as exc:
        return _v1_error(str(exc), "validation_error", 422, "validation_error")

    try:
        embeddings = get_rag_system().embedding_model.embed_batch(inputs)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
    except Exception as exc:
        return _v1_error(f"Failed to generate embeddings: {exc}", "model_error", 500, "model_error")

    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": list(vec), "index": idx}
            for idx, vec in enumerate(embeddings)
        ],
        "model": payload.model,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "total_tokens": prompt_tokens,
        },
    }

@router.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    try:
        payload = V1ChatCompletionsRequest(**(await request.json()))
    except ValidationError:
        return _v1_error("Invalid chat completions request", "validation_error", 422, "validation_error")

    messages = payload.messages
    stream = payload.stream
    model = payload.model
    response_format = payload.response_format
    payload_user = payload.user or ""

    principal = _principal_from_request(request, payload_user=payload_user)
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _v1_quota_error_response(rate_result)

    if not messages:
        return _v1_error("messages is required", "validation_error", 422, "validation_error")

    # Separate system messages from conversation turns
    system_parts = [m.content for m in messages if m.role == "system"]
    turns = [m for m in messages if m.role != "system"]

    if not turns or turns[-1].role != "user":
        return _v1_error("Last message must be role=user", "validation_error", 422, "validation_error")

    # Extract the task (last user message — may be a string or content array)
    raw_task = turns[-1].content
    if isinstance(raw_task, list):
        task = " ".join(
            part.get("text", "") for part in raw_task if part.get("type") == "text"
        )
    else:
        task = str(raw_task)

    # Prepend system instructions if present
    if system_parts:
        task = "[System instructions: " + " ".join(system_parts) + "]\n\n" + task

    try:
        task = check_user_task(task)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "v1_chat_completions",
            "label": task[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _v1_error(exc.reason, exc.code, 422, exc.code)

    try:
        response_format_cfg = _normalize_response_format(response_format)
    except ValueError as exc:
        return _v1_error(str(exc), "validation_error", 422, "validation_error")

    response_format_mode = response_format_cfg.get("mode")
    response_schema = response_format_cfg.get("schema")
    task = _apply_response_format_hint(task, response_format_mode or "", response_schema)

    # History = all turns except the last user message, in Nexus AI internal format
    history = [{"role": m.role, "content": m.content if isinstance(m.content, str)
                else " ".join(p.get("text", "") for p in m.content if p.get("type") == "text")}
               for m in turns[:-1]]

    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if stream:
        # Stream SSE in OpenAI delta format
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop_evt = threading.Event()

        def _run():
            try:
                for evt in stream_agent_task(task, history, [], stop_evt):
                    loop.call_soon_threadsafe(queue.put_nowait, evt)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_run, daemon=True).start()

        async def _generate():
            full_content = ""
            try:
                while True:
                    evt = await queue.get()
                    if evt is None:
                        break
                    etype = evt.get("type", "")
                    delta_text = None
                    finish = None

                    if etype == "done":
                        content = evt.get("content", "")
                        if response_format_mode == "json":
                            try:
                                validated = _validate_json_output(content, response_schema)
                                delta_text = json.dumps(validated)
                            except ValueError as exc:
                                delta_text = json.dumps({
                                    "error": {
                                        "message": f"response_format=json required valid JSON but model output failed to parse: {exc}",
                                        "type": "invalid_response_format",
                                        "code": "invalid_response_format",
                                        "status": 422,
                                    }
                                })
                            finish = "stop"
                        else:
                            delta_text = content
                            finish = "stop"
                    elif etype == "think":
                        delta_text = f"<think>{evt.get('thought', '')}</think>"
                    elif etype == "tool":
                        delta_text = f"\n[{evt.get('icon', '🔧')} {evt.get('action', 'tool')}]\n"
                    elif etype == "error":
                        delta_text = f"\nError: {evt.get('message', '')}"
                        finish = "stop"

                    if delta_text is not None:
                        chunk = {
                            "id": cid, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": finish}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

            except asyncio.CancelledError:
                stop_evt.set()
            yield "data: [DONE]\n\n"

        return StreamingResponse(_generate(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Non-streaming ──
    sid = f"v1-{uuid.uuid4().hex[:8]}"
    result = run_agent_task(task, history, [], sid=sid)
    output = result.get("result", "")
    if response_format_mode == "json":
        try:
            validated = _validate_json_output(output, response_schema)
            output = json.dumps(validated)
        except ValueError:
            return _v1_error(
                "response_format=json required valid JSON but model output failed to parse",
                "invalid_response_format",
                422,
                "invalid_response_format",
            )

    prompt_tokens = _estimate_text_tokens(task)
    completion_tokens = _estimate_text_tokens(output)
    total_tokens = prompt_tokens + completion_tokens

    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": output},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "_nexus": {"provider": result.get("provider", ""), "model": result.get("model", "")},
    }


# ── settings ──────────────────────────────────────────────────────────────────
@router.get("/manifest.json")
def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")

@router.get("/sw.js")
def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})

@router.get("/personas")
def get_personas():
    return {"personas": list_personas(), "active": get_active_persona_name()}

@router.post("/personas/{persona_id}")
def switch_persona(persona_id: str):
    p = set_persona(persona_id)
    return {"active": persona_id, "persona": p}

@router.get("/settings")
def get_settings(): return get_config()

@router.post("/settings")
async def post_settings(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    prev_profile = _config.get("safety_profile", "standard")
    result = update_config(provider=data.get("provider"),
                           model=data.get("model"),
                           temperature=data.get("temperature"),
                           persona=data.get("persona"),
                           safety_profile=data.get("safety_profile"))
    new_profile = _config.get("safety_profile", "standard")
    if data.get("safety_profile") and new_profile != prev_profile:
        _push_safety_event("profile_change", {"scope": "global", "from": prev_profile, "to": new_profile})
    return result


@router.get("/settings/safety")
def get_safety_settings():
    profile = _config.get("safety_profile", "standard")
    return {
        "safety_profile": profile,
        "policy": get_safety_policy(profile),
        "available_profiles": sorted(SAFETY_POLICY_PROFILES.keys()),
    }


@router.post("/settings/safety")
async def update_safety_settings(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    profile = str(data.get("safety_profile", "standard")).lower().strip()
    if profile not in SAFETY_POLICY_PROFILES:
        allowed = ", ".join(sorted(SAFETY_POLICY_PROFILES.keys()))
        return _api_error(f"safety_profile must be one of: {allowed}", "validation_error", 422)
    prev = _config.get("safety_profile", "standard")
    update_config(safety_profile=profile)
    if profile != prev:
        _push_safety_event("profile_change", {"scope": "global", "from": prev, "to": profile})
    return {
        "safety_profile": _config.get("safety_profile", "standard"),
        "policy": get_safety_policy(_config.get("safety_profile", "standard")),
        "available_profiles": sorted(SAFETY_POLICY_PROFILES.keys()),
    }


@router.get("/settings/rate-limits")
def get_rate_limit_settings():
    return dict(_rate_limit_settings)


@router.post("/settings/rate-limits")
async def update_rate_limit_settings(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    mode = str(data.get("mode", _rate_limit_settings.get("mode", "soft"))).lower().strip()
    per_minute = data.get("per_minute", _rate_limit_settings.get("per_minute", 60))
    per_day = data.get("per_day", _rate_limit_settings.get("per_day", 2500))

    if mode not in ("soft", "hard"):
        return _api_error("mode must be one of: soft, hard", "validation_error", 422)
    try:
        per_minute = int(per_minute)
        per_day = int(per_day)
    except Exception:
        return _api_error("per_minute and per_day must be integers", "validation_error", 422)
    if per_minute < 1 or per_day < 1:
        return _api_error("per_minute and per_day must be >= 1", "validation_error", 422)

    updated = {
        "mode": mode,
        "per_minute": min(per_minute, 100000),
        "per_day": min(per_day, 10000000),
    }
    _rate_limit_settings.update(updated)
    db_save_pref("rate_limit_settings", json.dumps(updated))
    return dict(_rate_limit_settings)


@router.get("/safety/profiles")
def list_safety_profiles():
    return {
        "active": _config.get("safety_profile", "standard"),
        "profiles": {
            name: get_safety_policy(name)
            for name in sorted(SAFETY_POLICY_PROFILES.keys())
        },
    }


_SEVERITY_ORDER = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _event_severity(event: dict) -> str:
    verdict = event.get("verdict") or {}
    issue_levels = []
    for issue in verdict.get("issues", []) or []:
        level = str(issue.get("severity") or issue.get("threat") or "").lower().strip()
        if level in _SEVERITY_ORDER:
            issue_levels.append(level)

    if issue_levels:
        return max(issue_levels, key=lambda lvl: _SEVERITY_ORDER.get(lvl, 0))

    event_type = str(event.get("type") or "")
    if event_type == "block":
        return "high"
    if event_type == "pii_scrub":
        return "medium"
    if event_type == "profile_change":
        return "low"
    return "none"


@router.get("/safety/audit")
def get_safety_audit(
    limit: int = 200,
    session_id: str = "",
    event_type: str = "",
    severity: str = "",
):
    limit = max(1, min(limit, 1000))
    session_id = (session_id or "").strip()
    event_type = (event_type or "").strip()
    severity = (severity or "").strip().lower()
    if severity and severity not in _SEVERITY_ORDER:
        allowed = ", ".join(_SEVERITY_ORDER.keys())
        return _api_error(f"severity must be one of: {allowed}", "validation_error", 422)

    # Prefer persisted entries from the database; fall back to in-memory for entries
    # that may not yet have been flushed (e.g., very recent push within the same request).
    try:
        db_entries = db_load_safety_audit_entries(limit=5000, session_id=session_id, event_type=event_type)
    except Exception:
        db_entries = []

    # Merge: db already filters by session_id/event_type; supplement with any in-memory events
    # that are not yet persisted (i.e., more recent than the newest db entry's ts).
    newest_db_ts = db_entries[-1].get("ts", 0.0) if db_entries else 0.0
    fresh_in_memory = [
        ev for ev in safety_log
        if float(ev.get("ts", 0)) > newest_db_ts
        and (not session_id or str(ev.get("session") or ev.get("session_id") or "") == session_id)
        and (not event_type or ev.get("type") == event_type)
    ]
    filtered: list = db_entries + fresh_in_memory

    events_with_severity = []
    for event in filtered:
        level = _event_severity(event)
        entry = dict(event)
        entry["severity"] = level
        events_with_severity.append(entry)

    if severity:
        threshold = _SEVERITY_ORDER[severity]
        events_with_severity = [
            event for event in events_with_severity
            if _SEVERITY_ORDER.get(event.get("severity", "none"), 0) >= threshold
        ]

    events = events_with_severity[-limit:]
    return {
        "events": events,
        "total": len(events_with_severity),
        "session_id": session_id or None,
        "event_type": event_type or None,
        "severity": severity or None,
        "filtered": bool(session_id or event_type or severity),
    }

@router.get("/personas")
def list_personas():
    active = _config["persona"]
    return {"personas": [
        {"id": k, "label": v["label"], "emoji": v["emoji"],
         "description": v["description"], "active": k == active}
        for k, v in PERSONAS.items()
    ]}


# ── memory ────────────────────────────────────────────────────────────────────
@router.get("/memory")
def list_memory(): return {"memories": get_all_memory()}

@router.delete("/memory")
def clear_memory(): delete_all_memory(); return {"cleared":True}

@router.post("/memory/prune")
async def prune_memory_endpoint(request: Request):
    """Delete memory entries older than max_age_days (default: MEMORY_MAX_AGE_DAYS env var).
    Always keeps at least min_keep most-recent entries.
    Returns the number of deleted entries."""
    data = await request.json()
    max_age_days = data.get("max_age_days")
    min_keep     = data.get("min_keep")
    try:
        from ..memory import prune_old_memories
        deleted = prune_old_memories(
            max_age_days=int(max_age_days) if max_age_days is not None else None,
            min_keep=int(min_keep) if min_keep is not None else None,
        )
        return {"deleted": deleted}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/memory/semantic")
def get_semantic_mem():
    try:
        from ..memory import get_semantic_memory
        return {"memories": get_semantic_memory("", 5)}
    except Exception as e:
        return {"memories": [], "note": str(e)}

@router.post("/memory/semantic")
async def add_semantic_mem(request: Request):
    data = await request.json()
    try:
        from ..memory import add_semantic_memory
        add_semantic_memory(data.get("summary", ""), data.get("tags", []))
        return {"added": True}
    except Exception as e:
        return {"error": str(e)}


# ── Benchmark endpoints ────────────────────────────────────────────────────────
_BENCHMARK_PROBES = [
    ("arithmetic",  "What is 17 * 23?"),
    ("reasoning",   "If all roses are flowers and some flowers fade quickly, can we conclude that some roses fade quickly?"),
    ("coding",      "Write a one-line Python expression to reverse a string."),
]

@router.post("/benchmark/run")
async def benchmark_run(request: Request):
    """Run a lightweight probe suite against all available providers and store results.

    Returns per-provider latency and response length for each probe.
    POST body is optional; set ``providers`` (list) to limit which providers to benchmark.
    """
    import time as _t
    from ..db import save_benchmark_result
    from ..agent import _call_single, _has_key, PROVIDERS, _is_rate_limited

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    requested_providers = body.get("providers") or []
    available = [
        pid for pid, cfg in PROVIDERS.items()
        if _has_key(cfg) and not _is_rate_limited(pid)
    ]
    target_providers = [p for p in requested_providers if p in available] or available

    results = []
    for pid in target_providers:
        for probe_name, probe_text in _BENCHMARK_PROBES:
            t0 = _t.time()
            try:
                resp = _call_single(pid, [{"role": "user", "content": probe_text}])
                latency_ms = (_t.time() - t0) * 1000
                text = resp.get("content") or str(resp)
                save_benchmark_result(pid, probe_name, latency_ms, len(text))
                results.append({
                    "provider": pid, "probe": probe_name,
                    "latency_ms": round(latency_ms, 1), "response_len": len(text),
                    "ok": True,
                })
            except Exception as exc:
                results.append({
                    "provider": pid, "probe": probe_name,
                    "latency_ms": None, "response_len": 0,
                    "ok": False, "error": str(exc)[:120],
                })
    return {"results": results}


@router.get("/benchmark/results")
def benchmark_results():
    """Return stored benchmark results (most recent first)."""
    from ..db import load_benchmark_results
    return {"results": load_benchmark_results()}


# ── Consensus reasoning endpoint ──────────────────────────────────────────────
@router.post("/reason/consensus")
async def reason_consensus(request: Request):
    """Run a task through multiple providers and return a reconciled consensus answer.

    POST body: {"task": "...", "providers": [...optional list...]}
    """
    from ..ensemble import call_llm_consensus
    from ..agent import (
        _call_single, _has_key, _is_rate_limited, _mark_rate_limited,
        _smart_order, get_system_resources,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        consensus_text, winning_pid, meta = call_llm_consensus(
            messages=[{"role": "user", "content": task}],
            task=task,
            providers_fn=lambda t: _smart_order(t, get_system_resources()),
            call_single_fn=_call_single,
            is_rate_limited_fn=_is_rate_limited,
            mark_rate_limited_fn=_mark_rate_limited,
        )
        from ..ensemble import explain_consensus
        explanation = explain_consensus(
            chosen={"action": "respond", "content": consensus_text},
            winning_pid=winning_pid,
            unanimous=meta.get("unanimous", True),
            meta=meta,
        )
        return {
            "consensus": consensus_text,
            "provider":  winning_pid,
            "ensemble":  meta.get("ensemble", False),
            "unanimous": meta.get("unanimous"),
            "polled":    meta.get("polled", []),
            "explanation": explanation,
        }
    except Exception as exc:
        return _api_error(str(exc), "consensus_error", 500)


def _extract_citation_urls(text: str) -> list[str]:
    import re as _re

    source = text or ""
    urls = []

    # Markdown links: [label](https://...)
    for m in _re.finditer(r"\[[^\]]+\]\((https?://[^)\s]+)\)", source):
        urls.append(m.group(1))

    # Bare URLs
    for m in _re.finditer(r"\bhttps?://[^\s)]+", source):
        urls.append(m.group(0))

    # Preserve order and uniqueness
    unique = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _score_citation_confidence(answer: str, expected_sources: list[str] | None = None) -> dict:
    from urllib.parse import urlparse as _urlparse

    citations = _extract_citation_urls(answer)
    expected = [str(s).strip() for s in (expected_sources or []) if str(s).strip()]

    if not citations:
        return {
            "score": 0.1 if expected else 0.25,
            "citations": [],
            "matched_expected_sources": [],
            "expected_source_coverage": 0.0,
        }

    if not expected:
        score = min(0.9, 0.35 + 0.12 * len(citations))
        return {
            "score": round(score, 3),
            "citations": citations,
            "matched_expected_sources": [],
            "expected_source_coverage": None,
        }

    expected_domains = {(_urlparse(u).netloc or u).lower() for u in expected}
    citation_domains = [(_urlparse(u).netloc or u).lower() for u in citations]

    matched = []
    for domain in expected_domains:
        if any(domain in cd or cd in domain for cd in citation_domains):
            matched.append(domain)

    coverage = len(matched) / max(1, len(expected_domains))
    score = 0.35 + 0.65 * coverage
    return {
        "score": round(min(1.0, score), 3),
        "citations": citations,
        "matched_expected_sources": matched,
        "expected_source_coverage": round(coverage, 3),
    }


@router.post("/reason/generator-critic")
async def reason_generator_critic(request: Request):
    """Generator-critic research flow with citation confidence scoring.

    POST body:
      {"task": "...", "sources": ["https://...", ...]}
    """
    from ..thinking import build_critique_prompt, parse_critique_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    sources = body.get("sources") or []
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        safe_task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "reason_generator_critic",
            "label": task[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    generator_task = (
        safe_task
        + "\n\nProvide a concise research answer. Include citations as markdown links when available."
    )
    generated_resp, generator_provider = call_llm_with_fallback(
        [{"role": "user", "content": generator_task}],
        generator_task,
    )
    generated_answer = generated_resp.get("content") or str(generated_resp)

    critique_prompt = build_critique_prompt(generated_answer, task) + (
        "\n\nEnsure the revised answer preserves or improves citation quality with source links."
    )
    critic_resp, critic_provider = call_llm_with_fallback(
        [{"role": "user", "content": critique_prompt}],
        task,
    )
    critic_raw = critic_resp.get("content") or str(critic_resp)
    critique_data = parse_critique_response(critic_raw)

    revised_answer = (critique_data.get("revised") or "").strip() or generated_answer
    critique_text = (critique_data.get("critique") or "").strip()
    try:
        confidence = float(critique_data.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    citation_meta = _score_citation_confidence(revised_answer, expected_sources=sources)

    return {
        "task": task,
        "generated_answer": generated_answer,
        "critique": critique_text,
        "revised_answer": revised_answer,
        "confidence": round(confidence, 3),
        "citation_confidence": citation_meta.get("score", 0.0),
        "citations": citation_meta.get("citations", []),
        "expected_source_coverage": citation_meta.get("expected_source_coverage"),
        "matched_expected_sources": citation_meta.get("matched_expected_sources", []),
        "providers": {
            "generator": generator_provider,
            "critic": critic_provider,
        },
    }


# ── Adaptive confidence routing helper ────────────────────────────────────

_ADAPTIVE_ROUTING_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "confidence_threshold": 0.6,
    "escalation_tries": 2,
}
_adaptive_routing_config: Dict[str, Any] = dict(_ADAPTIVE_ROUTING_DEFAULTS)

# High-quality provider tiers used for escalation — ordered strongest-first.
_ESCALATION_PROVIDERS = ["claude", "openai", "groq", "cerebras", "gemini", "mistral"]


def _call_llm_adaptive(messages: List[Dict], task: str = "") -> tuple:
    """Call LLM with confidence-aware adaptive escalation.

    If the first response has confidence below the configured threshold,
    retry up to ``escalation_tries`` times, preferring stronger providers.

    Returns:
        (result_dict, provider_id, escalated: bool, final_confidence: float)
    """
    cfg = _adaptive_routing_config
    threshold = float(cfg.get("confidence_threshold", 0.6))
    tries = int(cfg.get("escalation_tries", 2))
    enabled = bool(cfg.get("enabled", True))

    result, provider = call_llm_with_fallback(messages, task)

    # Extract confidence from result if present
    confidence = 1.0
    content = result.get("content", "")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            confidence = float(parsed.get("confidence", 1.0))
        except Exception:
            confidence = 1.0

    if not enabled or confidence >= threshold or tries <= 0:
        return result, provider, False, confidence

    # Escalate to stronger providers
    escalated = False
    for attempt in range(tries):
        # Try escalation providers not already used
        escalation_order = [p for p in _ESCALATION_PROVIDERS if p != provider]
        if not escalation_order:
            break
        try:
            better_result, better_provider = call_llm_with_fallback(
                messages,
                task,
            )
            better_content = better_result.get("content", "")
            better_confidence = 1.0
            if isinstance(better_content, str):
                try:
                    parsed2 = json.loads(better_content)
                    better_confidence = float(parsed2.get("confidence", 1.0))
                except Exception:
                    better_confidence = 1.0

            if better_confidence > confidence:
                result, provider, confidence = better_result, better_provider, better_confidence
                escalated = True

            if confidence >= threshold:
                break
        except Exception:
            break

    return result, provider, escalated, confidence


@router.get("/settings/adaptive-routing")
def get_adaptive_routing():
    """Return the current adaptive confidence routing configuration."""
    return dict(_adaptive_routing_config)


@router.post("/settings/adaptive-routing")
async def update_adaptive_routing(request: Request):
    """Update adaptive confidence routing settings.

    POST body (all optional):
      {
        "enabled": true,
        "confidence_threshold": 0.6,
        "escalation_tries": 2
      }
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if "enabled" in body:
        _adaptive_routing_config["enabled"] = bool(body["enabled"])
    if "confidence_threshold" in body:
        val = float(body["confidence_threshold"])
        if not (0.0 <= val <= 1.0):
            return _api_error("confidence_threshold must be 0–1", "validation_error", 422)
        _adaptive_routing_config["confidence_threshold"] = val
    if "escalation_tries" in body:
        val = int(body["escalation_tries"])
        if not (0 <= val <= 5):
            return _api_error("escalation_tries must be 0–5", "validation_error", 422)
        _adaptive_routing_config["escalation_tries"] = val

    return dict(_adaptive_routing_config)


# ── Multi-agent debate endpoint ────────────────────────────────────────────

@router.post("/reason/debate")
async def reason_debate(request: Request):
    """Multi-agent red/blue team debate.

    POST body:
      {
        "claim":  "The earth is the best planet",
        "rounds": 2,
        "model_a": "",   // optional, leave blank for auto-routing
        "model_b": ""
      }

    Returns the full debate transcript + impartial judge verdict.
    """
    from ..thinking import (
        build_debate_position_prompt,
        build_debate_verdict_prompt,
        parse_debate_turn,
        parse_debate_verdict,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    claim = (body.get("claim") or "").strip()
    if not claim:
        return _api_error("claim is required", "validation_error", 422)

    try:
        safe_claim = check_user_task(claim, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input", "tool": "reason_debate",
            "label": claim[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    num_rounds = max(1, min(int(body.get("rounds", 2)), 5))
    rounds_transcript: List[Dict[str, Any]] = []
    providers_used: List[Dict[str, str]] = []

    prop_argument = ""
    crit_argument = ""

    for round_num in range(1, num_rounds + 1):
        # Proponent turn
        prop_prompt = build_debate_position_prompt(safe_claim, "proponent", prior_round=crit_argument)
        prop_resp, prop_provider = call_llm_with_fallback(
            [{"role": "user", "content": prop_prompt}], safe_claim
        )
        prop_data = parse_debate_turn(prop_resp.get("content") or str(prop_resp))
        prop_argument = prop_data["argument"]

        # Critic turn
        crit_prompt = build_debate_position_prompt(safe_claim, "critic", prior_round=prop_argument)
        crit_resp, crit_provider = call_llm_with_fallback(
            [{"role": "user", "content": crit_prompt}], safe_claim
        )
        crit_data = parse_debate_turn(crit_resp.get("content") or str(crit_resp))
        crit_argument = crit_data["argument"]

        rounds_transcript.append({
            "round": round_num,
            "proponent": prop_argument,
            "proponent_key_points": prop_data["key_points"],
            "proponent_confidence": prop_data["confidence"],
            "critic": crit_argument,
            "critic_key_points": crit_data["key_points"],
            "critic_confidence": crit_data["confidence"],
        })
        providers_used.append({"round": str(round_num), "proponent": prop_provider, "critic": crit_provider})

    # Final verdict from an impartial judge
    verdict_prompt = build_debate_verdict_prompt(safe_claim, rounds_transcript)
    verdict_resp, verdict_provider = call_llm_with_fallback(
        [{"role": "user", "content": verdict_prompt}], safe_claim
    )
    verdict_data = parse_debate_verdict(verdict_resp.get("content") or str(verdict_resp))

    return {
        "claim":                      safe_claim,
        "rounds_completed":           num_rounds,
        "transcript":                 rounds_transcript,
        "verdict":                    verdict_data.get("verdict", "inconclusive"),
        "synthesis":                  verdict_data.get("synthesis", ""),
        "strongest_proponent_point":  verdict_data.get("strongest_proponent_point", ""),
        "strongest_critic_point":     verdict_data.get("strongest_critic_point", ""),
        "confidence":                 verdict_data.get("confidence", 0.5),
        "providers":                  providers_used,
        "verdict_provider":           verdict_provider,
    }


# ── Hypothesis testing loop endpoint ──────────────────────────────────────

@router.post("/reason/hypothesis")
async def reason_hypothesis(request: Request):
    """Structured hypothesis testing loop.

    POST body:
      {
        "observation": "The server response time increased 3x after the last deploy.",
        "max_hypotheses": 4
      }

    Returns generated hypotheses, test results for each, plus a final conclusion.
    """
    from ..thinking import (
        build_hypothesis_generation_prompt,
        build_hypothesis_test_prompt,
        build_hypothesis_conclusion_prompt,
        parse_hypothesis_generation,
        parse_hypothesis_test,
        parse_hypothesis_conclusion,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    observation = (body.get("observation") or "").strip()
    if not observation:
        return _api_error("observation is required", "validation_error", 422)

    try:
        safe_obs = check_user_task(observation, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input", "tool": "reason_hypothesis",
            "label": observation[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    max_h = max(1, min(int(body.get("max_hypotheses", 4)), 8))

    # Step 1: Generate hypotheses
    gen_prompt = build_hypothesis_generation_prompt(safe_obs, max_h)
    gen_resp, gen_provider = call_llm_with_fallback(
        [{"role": "user", "content": gen_prompt}], safe_obs
    )
    hypotheses = parse_hypothesis_generation(gen_resp.get("content") or str(gen_resp))

    # Step 2: Test each hypothesis individually
    tested: List[Dict[str, Any]] = []
    test_providers: List[str] = []
    for hyp in hypotheses:
        test_prompt = build_hypothesis_test_prompt(hyp["statement"], safe_obs)
        test_resp, test_provider = call_llm_with_fallback(
            [{"role": "user", "content": test_prompt}], safe_obs
        )
        test_result = parse_hypothesis_test(test_resp.get("content") or str(test_resp))
        tested.append({
            "id":               hyp["id"],
            "statement":        hyp["statement"],
            "initial_reasoning": hyp["initial_reasoning"],
            "initial_plausibility": hyp["plausibility"],
            **test_result,
        })
        test_providers.append(test_provider)

    # Step 3: Draw final conclusion
    conc_prompt = build_hypothesis_conclusion_prompt(safe_obs, tested)
    conc_resp, conc_provider = call_llm_with_fallback(
        [{"role": "user", "content": conc_prompt}], safe_obs
    )
    conclusion = parse_hypothesis_conclusion(conc_resp.get("content") or str(conc_resp))

    return {
        "observation":         safe_obs,
        "hypotheses_tested":   tested,
        "conclusion":          conclusion.get("conclusion", ""),
        "best_hypothesis_id":  conclusion.get("best_hypothesis_id", 0),
        "uncertainty":         conclusion.get("uncertainty", ""),
        "next_steps":          conclusion.get("next_steps", []),
        "overall_confidence":  conclusion.get("overall_confidence", 0.5),
        "providers": {
            "generator":    gen_provider,
            "testers":      test_providers,
            "conclusion":   conc_provider,
        },
    }


# ── RAG endpoints ─────────────────────────────────────────────────────────
@router.post("/rag/ingest")
async def rag_ingest(request: Request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    path = (data.get("path") or "").strip()
    metadata = data.get("metadata", {}) or {}
    prefix = data.get("doc_id_prefix")

    if not text and not path:
        return JSONResponse({"error": "text or path is required"}, status_code=400)

    if path:
        try:
            full_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return JSONResponse({"error": f"Failed to read path {path}: {e}"}, status_code=400)

    try:
        count = get_rag_system().ingest(text, metadata=metadata, doc_id_prefix=prefix)
        return {"ingested_chunks": count, "status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/rag/query")
async def rag_query(request: Request):
    data = await request.json()
    query = (data.get("query") or "").strip()
    top_k = data.get("top_k")
    filter_metadata = data.get("filter_metadata")

    if not query:
        return JSONResponse({"error": "query field is required"}, status_code=400)

    try:
        results = get_rag_system().query(query, top_k=top_k, filter_metadata=filter_metadata)
        return {"query": query, "results": results}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/rag/status")
def rag_status():
    try:
        return get_rag_system().stats()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Diff viewer endpoints ─────────────────────────────────────────────────────

def _compute_diff_stats(original: str, modified: str, filename: str = "file") -> dict:
    """Compute structured diff stats between two text blobs."""
    import difflib
    orig_lines = original.splitlines(keepends=True)
    mod_lines  = modified.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="",
    ))
    unified = "\n".join(diff)
    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    chunks = sum(1 for l in diff if l.startswith("@@"))
    return {
        "filename": filename,
        "additions": additions,
        "deletions": deletions,
        "chunks": chunks,
        "unchanged": max(0, len(orig_lines) - deletions),
        "unified_diff": unified if len(unified) <= 8000 else unified[:8000] + "\n… (truncated)",
        "has_changes": bool(diff),
    }


@router.post("/diff")
async def compute_diff(request: Request):
    """Compute a structured unified diff between two text blobs.

    POST body:
      { "original": "...", "modified": "...", "filename": "app.py", "trace_id": "" }

    If trace_id is provided the diff is persisted to the file diff history.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    original = body.get("original") or ""
    modified = body.get("modified") or ""
    filename = (body.get("filename") or "file").strip()
    trace_id = (body.get("trace_id") or "").strip()

    stats = _compute_diff_stats(original, modified, filename)

    saved = None
    if trace_id and stats["has_changes"]:
        saved = _save_file_diff(trace_id, filename, original, modified)

    return {**stats, "saved": saved}


@router.get("/diff/history")
def diff_history(trace_id: str = "", limit: int = 50):
    """Return file diff history, optionally filtered by trace_id."""
    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 50
    diffs = _get_file_diffs(trace_id=trace_id, limit=limit)
    return {"diffs": diffs, "total": len(diffs)}


@router.get("/diff/{diff_id}")
def diff_detail(diff_id: int):
    """Return full diff detail (including before/after text and unified diff) by id."""
    record = _get_file_diff_detail(diff_id)
    if not record:
        return JSONResponse({"error": "diff not found"}, status_code=404)
    return record


# ── Self-improvement loop endpoints ──────────────────────────────────────────

def _build_self_review_prompt(traces: list[dict]) -> str:
    """Build an LLM prompt for analyzing agent traces and suggesting improvements."""
    if not traces:
        return "No execution traces available to review."
    lines = [
        "You are an AI self-improvement analyst. The following are summaries of recent agent "
        "execution traces. Analyze them and respond with a JSON object:\n"
        '{\n'
        '  "insights": ["<insight 1>", ...],\n'
        '  "suggestions": ["<improvement suggestion 1>", ...]\n'
        '}\n\n'
        "Include 3-7 insights (patterns you observed) and 3-5 actionable suggestions for improving "
        "agent prompts, tool selection, or task handling. Be specific.\n\n"
        "Traces:\n"
    ]
    for t in traces[:10]:
        lines.append(
            f"- trace_id={t.get('trace_id','?')} steps={t.get('steps',0)} "
            f"task={str(t.get('task',''))[:120]} started={t.get('started_at','?')[:19]}"
        )
    return "\n".join(lines)


@router.post("/agent/self-review")
async def agent_self_review(request: Request):
    """Analyze recent execution traces and generate self-improvement suggestions.

    POST body (optional):
      { "limit": 20 }
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    limit = body.get("limit", 20)
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20

    traces = _list_traces(limit=limit)
    if not traces:
        return {"review_id": None, "traces_analyzed": 0,
                "insights": [], "suggestions": [],
                "message": "No traces available to review."}

    prompt = _build_self_review_prompt(traces)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], prompt
    )
    raw = resp.get("content") or str(resp)

    # Parse JSON response
    import re as _re
    insights: list = []
    suggestions: list = []
    try:
        # Strip markdown fences if present
        cleaned = _re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        parsed = json.loads(cleaned)
        insights    = parsed.get("insights", []) or []
        suggestions = parsed.get("suggestions", []) or []
    except Exception:
        # Fallback: split raw text into lines as suggestions
        suggestions = [l.strip("- •") for l in raw.splitlines() if l.strip()][:10]

    review_id = "review_" + secrets.token_hex(6)
    db_save_self_review(
        review_id=review_id,
        traces_analyzed=len(traces),
        insights=insights,
        suggestions=suggestions,
        provider=provider,
    )

    return {
        "review_id": review_id,
        "traces_analyzed": len(traces),
        "insights": insights,
        "suggestions": suggestions,
        "provider": provider,
    }


@router.get("/agent/self-review/history")
def self_review_history(limit: int = 10):
    """Return past self-review results."""
    try:
        limit = max(1, min(int(limit), 50))
    except Exception:
        limit = 10
    reviews = db_list_self_reviews(limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


# ── Document understanding endpoints ─────────────────────────────────────────

def _extract_document_text(path: str, file_type: str = "") -> tuple[str, str]:
    """Extract text from a document file. Returns (text, detected_type)."""
    from ..tools_builtin import tool_read_pdf, tool_read_docx, tool_read_xlsx, tool_read_pptx

    ext = file_type.lower().lstrip(".") if file_type else ""
    if not ext and path:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    workdir = os.path.dirname(path) if os.path.isabs(path) else "/tmp"

    if ext in ("pdf",):
        return tool_read_pdf(path, workdir=workdir), "pdf"
    elif ext in ("docx", "doc"):
        return tool_read_docx(path, workdir=workdir), "docx"
    elif ext in ("xlsx", "xls"):
        return tool_read_xlsx(path, workdir=workdir), "xlsx"
    elif ext in ("pptx", "ppt"):
        return tool_read_pptx(path, workdir=workdir), "pptx"
    elif ext in ("txt", "md", "csv", "json", "yaml", "yml", "toml", "ini"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:8000], ext
        except Exception as e:
            return f"❌ Failed to read {path}: {e}", "text"
    return f"❌ Unsupported file type: {ext or 'unknown'}", ext


def _extract_document_segments(
    path: str,
    file_type: str = "",
    filename: str = "",
) -> list[dict]:
    """Extract document text as layout-aware segments with per-page/section metadata.

    Returns a list of dicts: {"text": str, "metadata": {"source": ..., "type": ..., ...}}
    For PDFs, each segment is one page.  For DOCX, one segment per section.
    For XLSX, one segment per sheet.  For PPTX, one segment per slide.
    """
    ext = file_type.lower().lstrip(".") if file_type else ""
    if not ext and path:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    name = filename or (path.split("/")[-1] if path else "document")
    base_meta: dict = {"source": name, "type": ext or "text"}

    if ext == "pdf":
        try:
            import pypdf
            full = path if os.path.isabs(path) else os.path.join("/tmp", path)
            reader = pypdf.PdfReader(full)
            total = len(reader.pages)
            segments = []
            for i, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                if text:
                    segments.append({
                        "text": text,
                        "metadata": {**base_meta, "page": i + 1, "total_pages": total},
                    })
            if not segments:
                return [{"text": "❌ No extractable text found (may be a scanned PDF)", "metadata": base_meta}]
            return segments
        except ImportError:
            return [{"text": "❌ pypdf not installed. Run: pip install pypdf", "metadata": base_meta}]
        except Exception as e:
            return [{"text": f"❌ PDF read failed: {e}", "metadata": base_meta}]

    if ext in ("docx", "doc"):
        try:
            from docx import Document
            full = path if os.path.isabs(path) else os.path.join("/tmp", path)
            doc = Document(full)
            segments: list[dict] = []
            current_parts: list[str] = []
            current_heading: str | None = None
            section_idx = 0

            def _flush(heading: str | None, parts: list[str], idx: int) -> None:
                text = "\n\n".join(parts).strip()
                if not text:
                    return
                meta: dict = {**base_meta, "section": idx}
                if heading:
                    meta["heading"] = heading
                segments.append({"text": text, "metadata": meta})

            for para in doc.paragraphs:
                style = para.style.name if para.style else ""
                if style.startswith("Heading ") and para.text.strip():
                    _flush(current_heading, current_parts, section_idx)
                    section_idx += 1
                    current_parts = []
                    current_heading = para.text.strip()
                    try:
                        level = int(style.split()[-1])
                    except (ValueError, IndexError):
                        level = 1
                    current_parts.append(f"{'#' * min(level, 4)} {para.text.strip()}")
                elif para.text.strip():
                    current_parts.append(para.text.strip())

            for tbl_idx, table in enumerate(doc.tables):
                rows = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    current_parts.append(f"[Table {tbl_idx + 1}]\n" + "\n".join(rows[:100]))

            _flush(current_heading, current_parts, section_idx)
            if not segments:
                return [{"text": "❌ No extractable text found in document.", "metadata": base_meta}]
            return segments
        except ImportError:
            return [{"text": "❌ python-docx not installed. Run: pip install python-docx", "metadata": base_meta}]
        except Exception as e:
            return [{"text": f"❌ DOCX read failed: {e}", "metadata": base_meta}]

    if ext in ("xlsx", "xls"):
        try:
            import openpyxl
            full = path if os.path.isabs(path) else os.path.join("/tmp", path)
            wb = openpyxl.load_workbook(full, read_only=True, data_only=True)
            segments = []
            for sheet_name in wb.sheetnames[:5]:
                ws = wb[sheet_name]
                lines = [f"### Sheet: {sheet_name}"]
                for row in ws.iter_rows(max_row=200, values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        lines.append(" | ".join(cells))
                if ws.max_row and ws.max_row > 200:
                    lines.append(f"… ({ws.max_row - 200} more rows)")
                segments.append({"text": "\n".join(lines), "metadata": {**base_meta, "sheet": sheet_name}})
            wb.close()
            return segments if segments else [{"text": "❌ No data found in workbook.", "metadata": base_meta}]
        except ImportError:
            return [{"text": "❌ openpyxl not installed. Run: pip install openpyxl", "metadata": base_meta}]
        except Exception as e:
            return [{"text": f"❌ XLSX read failed: {e}", "metadata": base_meta}]

    if ext in ("pptx", "ppt"):
        try:
            from pptx import Presentation
            full = path if os.path.isabs(path) else os.path.join("/tmp", path)
            prs = Presentation(full)
            total = len(prs.slides)
            segments = []
            for i, slide in enumerate(prs.slides):
                texts = [s.text.strip() for s in slide.shapes if hasattr(s, "text") and s.text.strip()]
                if texts:
                    segments.append({
                        "text": "\n".join(texts),
                        "metadata": {**base_meta, "slide": i + 1, "total_slides": total},
                    })
            return segments if segments else [{"text": "❌ No text found in presentation.", "metadata": base_meta}]
        except ImportError:
            return [{"text": "❌ python-pptx not installed. Run: pip install python-pptx", "metadata": base_meta}]
        except Exception as e:
            return [{"text": f"❌ PPTX read failed: {e}", "metadata": base_meta}]

    if ext in ("txt", "md", "csv", "json", "yaml", "yml", "toml", "ini"):
        try:
            full = path if os.path.isabs(path) else os.path.join("/tmp", path)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            if len(raw) <= 4000:
                return [{"text": raw, "metadata": base_meta}]
            # Split into overlapping sections for large text files
            chunk, overlap = 3000, 200
            return [
                {"text": raw[i: i + chunk], "metadata": {**base_meta, "section": idx}}
                for idx, i in enumerate(range(0, len(raw), chunk - overlap))
                if raw[i: i + chunk].strip()
            ]
        except Exception as e:
            return [{"text": f"❌ Failed to read {path}: {e}", "metadata": base_meta}]

    return [{"text": f"❌ Unsupported file type: {ext or 'unknown'}", "metadata": base_meta}]


@router.post("/documents/ingest")
async def documents_ingest(request: Request):
    """Extract text from a document and ingest it into the RAG store.

    POST body:
      { "path": "/tmp/report.pdf", "file_type": "pdf", "metadata": {} }
      OR
      { "text": "...", "filename": "report.pdf", "metadata": {} }
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    text  = (body.get("text") or "").strip()
    path  = (body.get("path") or "").strip()
    ftype = (body.get("file_type") or body.get("type") or "").strip()
    filename = (body.get("filename") or (path.split("/")[-1] if path else "document")).strip()
    metadata = body.get("metadata") or {}

    if not text and not path:
        return JSONResponse({"error": "path or text is required"}, status_code=400)

    rag = get_rag_system()
    chunks_stored = 0

    if not text and path:
        # Layout-aware extraction: each page/section ingested with positional metadata
        segments = _extract_document_segments(path, ftype, filename=filename)
        errors = [s for s in segments if s["text"].startswith("❌")]
        valid = [s for s in segments if not s["text"].startswith("❌")]
        if not valid:
            return JSONResponse({"error": errors[0]["text"] if errors else "No content extracted"}, status_code=400)
        detected_type = valid[0]["metadata"].get("type", ftype)
        total_chars = sum(len(s["text"]) for s in valid)
        for seg in valid:
            seg_meta = {**seg["metadata"], **metadata}
            try:
                chunks_stored += rag.ingest(seg["text"], metadata=seg_meta, doc_id_prefix=filename)
            except Exception:
                pass
        return {
            "filename": filename,
            "type": detected_type,
            "ingested_chunks": chunks_stored,
            "char_count": total_chars,
            "segments": len(valid),
            "status": "ok",
        }

    # Text-direct path
    if len(text) > 500_000:
        text = text[:500_000]
    doc_meta = {"source": filename, "type": ftype or "text", **metadata}
    try:
        chunks_stored = rag.ingest(text, metadata=doc_meta, doc_id_prefix=filename)
        return {
            "filename": filename,
            "type": ftype or "text",
            "ingested_chunks": chunks_stored,
            "char_count": len(text),
            "segments": 1,
            "status": "ok",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/documents/understand")
async def documents_understand(request: Request):
    """Extract text from a document and answer a question about it using an LLM.

    POST body:
      { "path": "/tmp/report.pdf", "question": "What are the key findings?", "file_type": "pdf" }
      OR
      { "text": "...", "question": "Summarise this." }

    For documents larger than ~8 000 chars, the endpoint uses a temporary RAG
    pipeline (ingest → query) to surface the most relevant sections before
    answering, rather than truncating to the first 12 000 chars.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    text     = (body.get("text") or "").strip()
    path     = (body.get("path") or "").strip()
    question = (body.get("question") or "Summarise this document.").strip()
    ftype    = (body.get("file_type") or body.get("type") or "").strip()
    filename = (body.get("filename") or (path.split("/")[-1] if path else "document")).strip()

    if not text and not path:
        return JSONResponse({"error": "path or text is required"}, status_code=400)
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)

    try:
        question = check_user_task(question, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)

    detected_type = ftype
    if not text and path:
        text, detected_type = _extract_document_text(path, ftype)
        if text.startswith("❌"):
            return JSONResponse({"error": text}, status_code=400)

    _UNDERSTAND_RAG_THRESHOLD = 8000

    rag_backed = False
    excerpt = ""

    if len(text) > _UNDERSTAND_RAG_THRESHOLD:
        # Use a fresh in-memory RAG instance so we don't pollute the global store
        try:
            from ..rag.rag_system import RAGSystem as _RAGSystem
            _tmp_rag = _RAGSystem()
            chunk, overlap = 3000, 200
            for idx, offset in enumerate(range(0, min(len(text), 90000), chunk - overlap)):
                chunk_text = text[offset: offset + chunk]
                if chunk_text.strip():
                    _tmp_rag.ingest(
                        chunk_text,
                        metadata={"source": filename, "type": detected_type or "text", "section": idx},
                        doc_id_prefix=f"_und_{filename}",
                    )
            results = _tmp_rag.query(question, top_k=5)
            if results:
                excerpt = "\n\n---\n\n".join(r["document"] for r in results)
                rag_backed = True
        except Exception:
            pass  # fall through to direct path

    if not excerpt:
        excerpt = text[:12000]

    context_label = "relevant excerpts from" if rag_backed else "the content of"
    prompt = (
        f"The following is {context_label} a document "
        f"({detected_type or 'text'}) named '{filename}':\n\n"
        f"---\n{excerpt}\n---\n\n"
        f"Question: {question}\n\n"
        "Please answer based only on the document content above."
    )

    try:
        resp, provider = call_llm_with_fallback(
            [{"role": "user", "content": prompt}], question
        )
    except AllProvidersExhausted as exc:
        return _api_error(str(exc), "no_providers", 503)
    answer = resp.get("content") or str(resp)

    return {
        "filename": filename,
        "type": detected_type,
        "question": question,
        "answer": answer,
        "provider": provider,
        "excerpt_chars": len(excerpt),
        "total_chars": len(text),
        "rag_backed": rag_backed,
    }


@router.post("/autonomy/plan")
async def autonomy_plan(request: Request):
    """Decompose a goal into a structured subtask plan without executing it."""
    data = await request.json()
    goal = (data.get("goal") or "").strip()
    if not goal:
        return JSONResponse({"error": "goal field is required"}, status_code=400)
    try:
        goal = check_user_task(goal)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "autonomy_plan",
            "label": goal[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)
    try:
        max_subtasks = int(data.get("max_subtasks", 6))
    except Exception:
        max_subtasks = 6
    trace_id = secrets.token_hex(8)
    try:
        planner = PlanningSystem(_orchestrator_llm)
        tasks   = planner.decompose(goal, max_subtasks)
        plan = {
            "trace_id":   trace_id,
            "goal":       goal,
            "steps": [
                {"id": t.task_id, "name": t.name, "description": t.description,
                 "priority": t.priority, "dependencies": t.dependencies,
                 "estimated_hours": t.estimated_hours,
                 "agent": classify_subtask(t.description)}
                for t in tasks
            ],
        }
        autonomy_traces[trace_id] = {"type": "plan", "status": "ready", **plan}
        return plan
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/autonomy/execute")
async def autonomy_execute(request: Request):
    data = await request.json()
    goal = (data.get("goal") or "").strip()
    if not goal:
        return JSONResponse({"error": "goal field is required"}, status_code=400)
    try:
        goal = check_user_task(goal)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "autonomy_execute",
            "label": goal[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)
    strategy = data.get("strategy", "parallel")
    try:
        max_subtasks = int(data.get("max_subtasks", 6))
    except Exception:
        max_subtasks = 6
    trace_id = secrets.token_hex(8)
    try:
        orchestrator = Orchestrator(_orchestrator_llm, max_parallel=2)
        result = orchestrator.execute(goal, {"strategy": strategy, "max_subtasks": max_subtasks})
        result["trace_id"] = trace_id
        autonomy_traces[trace_id] = {"type": "execution", "goal": goal, "status": "done", **result}
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/autonomy/trace/{trace_id}")
def autonomy_trace(trace_id: str):
    """Retrieve a stored plan or execution trace by its ID."""
    trace = autonomy_traces.get(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace not found"}, status_code=404)
    return trace


# ── sessions ──────────────────────────────────────────────────────────────────
@router.post("/session")
async def new_session(request: Request = None):
    pid = ""
    if request:
        try:
            body = await request.json()
            pid = body.get("project_id", "")
        except Exception:
            pass
    sid = str(uuid.uuid4())
    # Optional project context
    extra_ctx = ""
    if pid and pid in projects:
        proj_ctx = project_context(pid)
        if proj_ctx.get("summary"):
            extra_ctx = f"[PROJECT: {projects[pid].get('name','project')}] {proj_ctx['summary']}"
    memory_ctx = get_memory_context()
    parts = [p for p in [extra_ctx, memory_ctx] if p]
    if parts:
        sessions[sid] = [{"role":"user","content":"\n\n".join(parts)},
                         {"role":"assistant","content":"Understood — I have context."}]
    else:
        sessions[sid] = []
    get_session_dir(sid)
    return {"session_id":sid,"has_memory":bool(memory_ctx),"has_project":bool(extra_ctx)}

@router.delete("/session/{sid}")
def clear_session(sid: str):
    sessions.pop(sid, None)
    _session_state.pop(sid, None)
    return {"cleared":sid}


# ── token endpoint (set from UI without pasting in chat) ─────────────────────
@router.post("/session/{sid}/token")
async def set_token(sid: str, request: Request):
    data  = await request.json()
    token = data.get("token","").strip()
    if token: set_session_token(sid, token)
    return {"set": bool(token)}


# ── per-session safety profile override ──────────────────────────────────────
@router.get("/session/{sid}/safety")
def get_session_safety(sid: str):
    from ..agent import get_session_state
    session_profile = get_session_state(sid).get("safety_profile") if sid else None
    effective = get_session_safety_profile(sid)
    return {
        "session_id": sid,
        "session_profile": session_profile,   # None = not overridden
        "effective_profile": effective,
        "global_profile": _config.get("safety_profile", "standard"),
        "available_profiles": list(SAFETY_POLICY_PROFILES.keys()),
    }

@router.post("/session/{sid}/safety")
async def set_session_safety(sid: str, request: Request):
    data    = await request.json()
    profile = data.get("safety_profile")
    allowed = list(SAFETY_POLICY_PROFILES.keys())
    if profile is not None:
        profile = str(profile).lower().strip()
        if profile not in allowed:
            return _api_error(f"safety_profile must be one of: {allowed}", "validation_error", 422)
    set_session_safety_profile(sid, profile)  # None clears the override
    effective = get_session_safety_profile(sid)
    _push_safety_event("profile_change", {"scope": "session", "session_id": sid,
                                          "profile": effective, "overridden": profile is not None})
    return {
        "session_id": sid,
        "session_profile": profile,
        "effective_profile": effective,
        "global_profile": _config.get("safety_profile", "standard"),
    }


# ── chat history ──────────────────────────────────────────────────────────────
@router.get("/chats")
def list_chats():
    pinned_ids = set(get_pinned_chats())
    def _sort(ch):
        return (ch["id"] not in pinned_ids, ch["updated_at"])
    listed = sorted(chats.values(), key=_sort, reverse=True)
    return {"chats":[{"id":c["id"],"title":c["title"],"created_at":c["created_at"],
                      "updated_at":c["updated_at"],"message_count":len(c["messages"]),
                      "pinned": c["id"] in pinned_ids} for c in listed]}

@router.post("/chats")
async def save_chat(request: Request):
    data    = await request.json()
    sid     = data.get("session_id")
    history = sessions.get(sid,[]) if sid else data.get("messages",[])
    # Explicit title always wins (rename case); otherwise auto-generate
    title   = data.get("title") or (chats[cid]["title"] if cid in chats else None) or _auto_title(history)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cid     = data.get("chat_id") or str(uuid.uuid4())
    created = chats[cid]["created_at"] if cid in chats else now
    chats[cid] = {"id":cid,"title":title[:80],
                  "created_at":created,
                  "updated_at":now,"messages":history}
    # Write through to SQLite
    db_save_chat(cid, title, created, now, history)
    def _bg():
        summary = summarize_history(history, call_llm_with_fallback)
        if summary: add_memory(summary)
    threading.Thread(target=_bg, daemon=True).start()
    return {"chat_id":cid,"title":chats[cid]["title"]}

@router.get("/chats/{cid}")
def load_chat(cid: str):
    chat = chats.get(cid) or db_load_chat(cid)
    if chat and cid not in chats:
        chats[cid] = chat   # repopulate in-memory cache
    return chat if chat else {"error":"Not found"}

@router.delete("/chats/{cid}")
def delete_chat(cid: str):
    chats.pop(cid, None)
    db_delete_chat(cid)
    return {"deleted":cid}

@router.get("/chats/{cid}/export")
def export_chat(cid: str):
    chat = chats.get(cid)
    if not chat: return {"error":"Not found"}
    lines = [f"# {chat['title']}",f"*Exported from Nexus AI — {chat['updated_at'][:10]}*",""]
    for m in chat["messages"]:
        role,content = m.get("role",""),m.get("content","")
        if not isinstance(content,str): continue
        if any(content.startswith(p) for p in ["Tool result:","Continue","[MEMORY","[GITHUB","{"]):continue
        if role=="user": lines+=[f"**You:** {content}",""]
        elif role=="assistant": lines+=[f"**Assistant:** {content}",""]
    return StreamingResponse(iter(["\n".join(lines)]),media_type="text/markdown",
        headers={"Content-Disposition":f'attachment; filename="chat-{cid[:8]}.md"'})

@router.post("/chats/{cid}/share")
def share_chat(cid: str):
    chat = chats.get(cid)
    if not chat: return {"error":"Not found"}
    share_id = str(uuid.uuid4())[:8]
    share_data = {
        "title": chat["title"],
        "messages": chat["messages"],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    shares[share_id] = share_data
    db_save_share(share_id, chat["title"],
                  share_data["created_at"], chat["messages"])
    return {"share_id":share_id,"url":f"/share/{share_id}"}

@router.get("/share/{share_id}")
def view_share(share_id: str):
    chat = shares.get(share_id) or db_load_share(share_id)
    if chat and share_id not in shares:
        shares[share_id] = chat
    if not chat: return HTMLResponse("<h2>Share not found.</h2>",status_code=404)
    msgs_html=""
    for m in chat["messages"]:
        role,content=m.get("role",""),m.get("content","")
        if not isinstance(content,str):continue
        if any(content.startswith(p) for p in ["Tool result:","Continue","[MEMORY","{"]):continue
        if role=="user": msgs_html+=f'<div class="u"><strong>You</strong><p>{content}</p></div>'
        elif role=="assistant" and not content.startswith("{"): msgs_html+=f'<div class="a"><strong>Assistant</strong><p>{content}</p></div>'
    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{chat['title']} — Nexus AI</title>
<style>body{{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 20px;background:#09090e;color:#e2e8f0}}
h1{{font-size:1.3rem}}p.sub{{color:#64748b;font-size:.8rem;margin-bottom:30px}}
.u,.a{{padding:12px 16px;border-radius:12px;margin:10px 0}}
.u{{background:#7c6af7;color:#fff;margin-left:60px}}.a{{background:#111118;border:1px solid #1f1f2e;margin-right:60px}}
strong{{font-size:.75rem;opacity:.7;display:block;margin-bottom:4px}}p{{margin:0;line-height:1.6;white-space:pre-wrap}}
.brand{{text-align:center;margin-top:40px;font-size:.75rem;color:#64748b}}</style></head>
<body><h1>{chat['title']}</h1><p class="sub">Shared from Nexus AI · {chat['created_at'][:10]}</p>
{msgs_html}<div class="brand">Made with <a href="/" style="color:#7c6af7">Nexus AI</a></div></body></html>"""
    return HTMLResponse(html)


# ── projects ──────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects():
    return {"projects": list(sorted(projects.values(), key=lambda p: p["updated_at"], reverse=True))}

@router.post("/projects")
async def create_project(request: Request):
    data = await request.json()
    pid  = data.get("id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    proj = {
        "id":           pid,
        "name":         data.get("name","New Project")[:80],
        "instructions": data.get("instructions",""),
        "color":        data.get("color","#7c6af7"),
        "created_at":   projects[pid]["created_at"] if pid in projects else now,
        "updated_at":   now,
    }
    projects[pid] = proj
    db_save_project(pid, proj["name"], proj["instructions"],
                    proj["color"], proj["created_at"], proj["updated_at"])
    return proj

@router.get("/projects/{pid}")
def get_project(pid: str):
    return projects.get(pid) or {"error":"Not found"}

@router.delete("/projects/{pid}")
def del_project(pid: str):
    projects.pop(pid, None)
    db_delete_project(pid)
    return {"deleted": pid}

@router.post("/projects/{pid}/chats/{cid}")
def link_chat_to_project(pid: str, cid: str):
    assign_chat_to_project(pid, cid)
    return {"linked": cid}

@router.get("/projects/{pid}/chats")
def project_chat_list(pid: str):
    chat_ids = get_project_chats(pid)
    result   = [chats[cid] for cid in chat_ids if cid in chats]
    return {"chats": result}

@router.get("/projects/{pid}/context")
def project_context(pid: str):
    """Get full project context: instructions + recent chats + memory + repo info."""
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    # Gather from cache if fresh, otherwise build
    ctx = _PROJECT_CONTEXT_CACHE.get(pid, {})
    if not ctx or (time.time() - ctx.get("_ts", 0)) > 300:   # 5-min cache
        chat_ids = get_project_chats(pid)
        recent_msgs = []
        for cid in chat_ids[:5]:
            if cid in chats:
                for m in chats[cid]["messages"][-8:]:
                    if m.get("role") == "user":
                        text = m.get("content","")
                        if isinstance(text, str) and len(text) > 5:
                            recent_msgs.append(text[:120])
        summary = " ".join(recent_msgs) if recent_msgs else "No prior conversations."
        ctx = {
            "summary": summary[:1000],
            "instructions": proj.get("instructions", ""),
            "name": proj.get("name", ""),
            "chat_count": len(chat_ids),
            "_ts": time.time(),
        }
        _PROJECT_CONTEXT_CACHE[pid] = ctx
    return ctx

@router.post("/projects/{pid}/sessions")
def new_project_session(pid: str):
    """Start a new session pre-loaded with project context."""
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    ctx = project_context(pid) if pid in projects else {}
    memory_ctx = get_memory_context()
    project_ctx = ctx.get("summary", "")
    session_parts = []
    if project_ctx:
        session_parts.append(f"[PROJECT CONTEXT — {proj.get('name','project')}] {project_ctx}")
    if memory_ctx:
        session_parts.append(memory_ctx)
    if session_parts:
        sessions[sid] = [{"role":"user","content":"\n\n".join(session_parts)},
                         {"role":"assistant","content":"Got it — I have project context."}]
    else:
        sessions[sid] = []
    new_sid = str(uuid.uuid4())
    memory_ctx = get_memory_context()
    project_ctx = ctx.get("summary", "")
    session_parts = []
    if project_ctx:
        session_parts.append(f"[PROJECT CONTEXT — {proj.get('name','project')}] {project_ctx}")
    if memory_ctx:
        session_parts.append(memory_ctx)
    if session_parts:
        sessions[new_sid] = [{"role":"user","content":"\n\n".join(session_parts)},
                         {"role":"assistant","content":"Got it — I have project context."}]
    else:
        sessions[new_sid] = []
    get_session_dir(new_sid)
    return {"session_id": new_sid, "project_id": pid, "has_context": bool(session_parts)}

@router.post("/projects/{pid}/context")
async def update_project_context(pid: str, request: Request):
    """Update project context cache from agent output."""
    data = await request.json()
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    _PROJECT_CONTEXT_CACHE[pid] = {
        "summary": data.get("summary", ""),
        "instructions": data.get("instructions", proj.get("instructions", "")),
        "files": data.get("files", []),
        "last_session": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "_ts": time.time(),
    }
    return {"updated": pid}


# ── custom instructions ────────────────────────────────────────────────────────
@router.get("/instructions")
def get_instructions():
    return {"instructions": db_load_ci()}

@router.post("/instructions")
async def set_instructions(request: Request):
    data = await request.json()
    db_save_ci(data.get("instructions",""))
    return {"saved": True}


# ── memory CRUD ────────────────────────────────────────────────────────────────
@router.patch("/memory/{entry_id}")
async def update_memory(entry_id: int, request: Request):
    data = await request.json()
    db_update_memory(entry_id, data.get("summary",""))
    return {"updated": entry_id}

@router.delete("/memory/{entry_id}")
def delete_memory_item(entry_id: int):
    db_delete_memory(entry_id)
    return {"deleted": entry_id}


# ── usage dashboard ───────────────────────────────────────────────────────────
# Per-session rate limiting

# ── search ────────────────────────────────────────────────────────────────────
@router.get("/chats/search")
def search_chats_endpoint(q: str = ""):
    if not q.strip():
        return {"results": []}
    return {"results": db_search_chats(q)}


# ── pin ────────────────────────────────────────────────────────────────────────
@router.post("/chats/{cid}/pin")
async def pin_chat_endpoint(cid: str, request: Request):
    data   = await request.json()
    pinned = data.get("pinned", True)
    db_pin_chat(cid, pinned)
    if cid in chats:
        chats[cid]["pinned"] = pinned
    return {"pinned": pinned}


# ── custom personas ────────────────────────────────────────────────────────────
@router.get("/personas/custom")
def list_custom_personas():
    return {"personas": db_load_personas()}

@router.post("/personas/custom")
async def create_custom_persona(request: Request):
    data = await request.json()
    pid  = data.get("id") or str(uuid.uuid4())
    db_save_persona(
        pid,
        data.get("name","Custom"),
        data.get("icon","🤖"),
        data.get("description",""),
        data.get("prompt_prefix",""),
        data.get("color","#7c6af7"),
        float(data.get("temperature",0.2)),
        data.get("tier","medium"),
    )
    return {"id": pid}

@router.delete("/personas/custom/{pid}")
def delete_custom_persona_endpoint(pid: str):
    db_del_persona(pid)
    return {"deleted": pid}


# ── usage dashboard ───────────────────────────────────────────────────────────


@router.get("/usage")
def usage_stats(days: int = 7):
    try:
        from ..tools_builtin import estimate_cost, PROVIDER_COSTS
        stats = get_usage_stats(days)
        daily = get_usage_daily(days)
        # Add cost estimates per provider
        for row in stats.get("by_provider", []):
            row["est_cost_usd"] = round(
                estimate_cost(row["provider"], row.get("in_tok",0), row.get("out_tok",0)), 4
            )
        total = stats.get("total", {})
        stats["total_est_cost_usd"] = round(sum(
            r.get("est_cost_usd", 0) for r in stats.get("by_provider", [])
        ), 4)
        return {"stats": stats, "daily": daily}
    except Exception as e:
        return {"error": str(e)}


# ── provider health ────────────────────────────────────────────────────────────
@router.get("/providers/health")
async def provider_health():
    """Quick pre-flight check on each provider."""
    import asyncio, time
    from ..agent import PROVIDERS, _has_key, _is_rate_limited, _cooldowns

    results = {}
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        cooling = _is_rate_limited(pid)
        cd_left = max(0, int(_cooldowns.get(pid, 0) - time.time()))
        results[pid] = {
            "label":     cfg["label"],
            "has_key":   has_key,
            "cooling":   cooling,
            "cd_left":   cd_left,
            "available": has_key and not cooling,
        }
    return {"health": results, "ts": time.time()}


# ── message reactions ─────────────────────────────────────────────────────────

@router.post("/reactions")
async def add_reaction(request: Request):
    data = await request.json()
    rid  = str(uuid.uuid4())[:8]
    _reactions[rid] = {
        "chat_id":  data.get("chat_id"),
        "msg_idx":  data.get("msg_idx"),
        "reaction": data.get("reaction"),   # "up" or "down"
        "text":     data.get("text","")[:200],
    }
    return {"id": rid}

@router.get("/reactions")
def get_reactions(chat_id: str = ""):
    if chat_id:
        return {"reactions": {k:v for k,v in _reactions.items() if v.get("chat_id")==chat_id}}
    return {"reactions": _reactions}


# ── search ───────────────────────────────────────────────────────────────────
@router.get("/search")
def search_chats_endpoint(q: str = ""):
    if not q.strip():
        return {"results": []}
    return {"results": db_search_chats(q)}


# ── pins ──────────────────────────────────────────────────────────────────────
_pins: set = set(get_pinned_chats())

@router.post("/chats/{cid}/pin")
def pin_chat_endpoint(cid: str):
    _pins.add(cid)
    db_pin_chat(cid, True)
    return {"pinned": cid}

@router.delete("/chats/{cid}/pin")
def unpin_chat_endpoint(cid: str):
    _pins.discard(cid)
    db_pin_chat(cid, False)
    return {"unpinned": cid}

@router.get("/chats/pinned")
def get_pinned():
    result = [chats[cid] for cid in _pins if cid in chats]
    return {"chats": result}


# ── user preferences ──────────────────────────────────────────────────────────
@router.get("/prefs")
def get_prefs():
    return {
        "theme":     db_load_pref("theme", "dark"),
        "font_size": db_load_pref("font_size", "15"),
    }

@router.post("/prefs")
async def set_prefs(request: Request):
    data = await request.json()
    for key in ("theme", "font_size"):
        if key in data:
            db_save_pref(key, str(data[key]))
    return {"saved": True}


# ── agent ─────────────────────────────────────────────────────────────────────
@router.post("/agent")
async def agent_post(request: Request):
    data  = await request.json()
    task  = data.get("task","").strip()
    sid   = data.get("session_id")
    files = data.get("files",[])
    if task=="__restore__" and "_history" in data:
        if sid: sessions[sid]=data["_history"]
        return {"result":"restored","provider":"-","model":"-"}
    if not task:
        return _api_error("task is required", "validation_error", 422)

    principal = _principal_from_request(request, sid=sid or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _quota_error_response(rate_result)

    try:
        task = check_user_task(task, policy_profile=get_session_safety_profile(sid or ""))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "agent_task",
            "label": task[:120],
            "session": sid,
            "profile": get_session_safety_profile(sid or ""),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    history = sessions.get(sid,[]) if sid else []
    result  = run_agent_task(task, history, files, sid=sid or "")
    if sid: sessions[sid]=result["history"]
    return {"result":result["result"],"provider":result["provider"],"model":result["model"],"session_id":sid}


@router.post("/agent/stream")
async def agent_stream(request: Request):
    data      = await request.json()
    task      = data.get("task","").strip()
    sid       = data.get("session_id")
    files     = data.get("files",[])
    stream_id = data.get("stream_id", str(uuid.uuid4()))
    trace_id  = data.get("trace_id", str(uuid.uuid4()))
    if not task:
        return _api_error("task is required", "validation_error", 422)

    principal = _principal_from_request(request, sid=sid or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _quota_error_response(rate_result)

    try:
        task = check_user_task(task, policy_profile=get_session_safety_profile(sid or ""))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "agent_stream",
            "label": task[:120],
            "session": sid,
            "profile": get_session_safety_profile(sid or ""),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    execution_traces[trace_id] = []

    history  = sessions.get(sid,[]) if sid else []
    loop     = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_evt = threading.Event()
    _active_streams[stream_id] = stop_evt

    def run_in_thread():
        try:
            for event in stream_agent_task(task, history, files, stop_evt, sid=sid or "", trace_id=trace_id):
                if stop_evt.is_set(): break
                if event["type"]=="done" and sid:
                    sessions[sid] = event.get("history", history)
                trace_event = {k:v for k,v in event.items() if k not in ("history","workdir")}
                execution_traces[trace_id].append(trace_event)
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            error_event = {"type":"error","message":str(e)}
            execution_traces[trace_id].append(error_event)
            loop.call_soon_threadsafe(queue.put_nowait,error_event)
        finally:
            _active_streams.pop(stream_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def generate():
        try:
            while True:
                event = await queue.get()
                if event is None: break
                payload = {k:v for k,v in event.items() if k not in ("history","workdir")}
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            stop_evt.set()

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no", "X-Trace-Id": trace_id})

@router.get("/agent/trace/{trace_id}")
def get_agent_trace(trace_id: str):
    trace = execution_traces.get(trace_id)
    if trace is None:
        return _api_error("trace not found", "not_found", 404)
    return {"trace_id": trace_id, "events": trace}


@router.post("/agent/stop/{stream_id}")
def stop_stream(stream_id: str):
    evt = _active_streams.get(stream_id)
    if evt: evt.set(); return {"stopped":stream_id}
    return {"not_found":stream_id}


# ── Nexus Cloud registration ──────────────────────────────────────────────────
async def _register_with_nexus_cloud():
    """Register this AI node with Nexus Cloud (non-blocking, best-effort)."""
    import httpx
    cloud_url = os.getenv("NEXUS_CLOUD_URL", "").rstrip("/")
    if not cloud_url:
        return
    api_key   = os.getenv("NEXUS_CLOUD_API_KEY", "")
    public_url = os.getenv("PUBLIC_URL", f"http://localhost:{os.getenv('PORT', '8000')}")
    payload = {
        "id": "nexus-ai",
        "name": "Nexus AI",
        "description": "Autonomous AI assistant with multi-provider fallback, memory, and RAG",
        "upstreamUrl": public_url,
        "mode": "standalone",
        "exposed": True,
        "health": "healthy",
        "capabilities": ["ai", "chat", "rag", "memory", "autonomy", "multi-provider"],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{cloud_url}/api/v1/tools", json=payload, headers=headers)
            if res.is_success:
                print(f"[nexus-cloud] Registered with Nexus Cloud at {cloud_url}")
            else:
                print(f"[nexus-cloud] Registration rejected: {res.status_code}")
    except Exception as e:
        print(f"[nexus-cloud] Could not reach Nexus Cloud — continuing ({e})")

async def _heartbeat_loop():
    """Send a heartbeat every 30 s so Cloud knows this node is alive."""
    import httpx
    cloud_url = os.getenv("NEXUS_CLOUD_URL", "").rstrip("/")
    if not cloud_url:
        return
    api_key    = os.getenv("NEXUS_CLOUD_API_KEY", "")
    public_url = os.getenv("PUBLIC_URL", f"http://localhost:{os.getenv('PORT', '8000')}")
    headers    = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    while True:
        await asyncio.sleep(30)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{cloud_url}/api/v1/tools/nexus-ai/heartbeat",
                    json={"health": "healthy", "upstreamUrl": public_url},
                    headers=headers,
                )
        except Exception:
            pass

# ── Sprint E: filtered memory search ─────────────────────────────────────────

@router.get("/memory/search")
async def memory_search(
    request: Request,
    q: str = "",
    limit: int = 10,
    date_from: float | None = None,
    date_to: float | None = None,
    tags: str = "",
    persona: str = "",
):
    """Filtered semantic memory search.

    Query params:
      q         — search query (empty returns recency-ordered entries)
      limit     — max results (default 10)
      date_from — unix timestamp lower bound
      date_to   — unix timestamp upper bound
      tags      — comma-separated tag substrings
      persona   — exact persona name filter
        _push_safety_event("block", {
            "scope": "input",
            "tool": "webhook_trigger",
            "label": task[:120],
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
    """
    from ..memory import get_semantic_memory_filtered
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = get_semantic_memory_filtered(
        query=q,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        tags=tag_list,
        persona=persona or None,
    )
    return {"results": results, "count": len(results)}


# ── Sprint E: per-message feedback ────────────────────────────────────────────

@router.post("/feedback/{chat_id}/{message_idx}")
async def save_message_feedback(chat_id: str, message_idx: int, request: Request):
    """Store a 👍/👎 reaction for a specific message.

    POST body: {"reaction": "thumbs_up" | "thumbs_down", "provider": "...", "model": "..."}
    """
    from ..db import save_feedback as db_save_feedback
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reaction = (body.get("reaction") or "").strip()
    if reaction not in ("thumbs_up", "thumbs_down"):
        return _api_error("reaction must be 'thumbs_up' or 'thumbs_down'", "validation_error", 422)
    db_save_feedback(
        chat_id=chat_id,
        message_idx=message_idx,
        reaction=reaction,
        provider=body.get("provider", ""),
        model=body.get("model", ""),
    )
    return {"saved": True, "chat_id": chat_id, "message_idx": message_idx, "reaction": reaction}


@router.get("/feedback/export")
def feedback_export(limit: int = 5000):
    """Export all message feedback as JSON training data."""
    from ..db import load_feedback_export, get_feedback_stats
    data    = load_feedback_export(limit)
    stats   = get_feedback_stats()
    return {
        "stats":  stats,
        "count":  len(data),
        "data":   data,
    }


@router.get("/feedback/stats")
def feedback_stats():
    """Return aggregate thumbs-up / thumbs-down counts."""
    from ..db import get_feedback_stats
    return get_feedback_stats()


# ── Sprint F: Specialist Agent Library ───────────────────────────────────────

@router.get("/agents")
def list_specialist_agents():
    """Return the full catalogue of built-in specialist agents."""
    from ..agents import list_agents
    return {"agents": list_agents()}


@router.get("/architecture/hierarchy")
def architecture_hierarchy():
    """Return a live scaffold of the AI-system hierarchy.

    This endpoint is intentionally read-only for now and acts as an architecture
    planning contract for future model/agent/workflow expansion.
    """
    from ..agent import get_providers_list
    from ..agents import list_agents
    from ..architecture import build_runtime_hierarchy

    return build_runtime_hierarchy(
        providers=get_providers_list(),
        specialist_agents=list_agents(),
    )


@router.post("/architecture/blueprints")
async def create_architecture_blueprint(request: Request):
    from ..agent import get_providers_list
    from ..agents import list_agents
    from ..architecture import build_runtime_hierarchy
    from ..db import save_architecture_blueprint

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    name = str(body.get("name") or "default").strip() or "default"
    notes = str(body.get("notes") or "").strip()
    use_runtime = bool(body.get("use_runtime", True))

    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else None
    if snapshot is None and use_runtime:
        snapshot = build_runtime_hierarchy(
            providers=get_providers_list(),
            specialist_agents=list_agents(),
        )

    if snapshot is None:
        return _api_error("snapshot is required when use_runtime=false", "validation_error", 422)

    created = save_architecture_blueprint(name=name, snapshot=snapshot, notes=notes)
    return {"blueprint": created}


@router.get("/architecture/blueprints")
def list_architecture_blueprints(name: str = "", limit: int = 50):
    from ..db import list_architecture_blueprints as db_list_architecture_blueprints

    items = db_list_architecture_blueprints(name=name, limit=limit)
    return {"blueprints": items, "total": len(items)}


@router.get("/architecture/blueprints/{name}")
def get_architecture_blueprint(name: str, version: int = 0):
    from ..db import load_architecture_blueprint

    data = load_architecture_blueprint(name=name, version=version if version > 0 else None)
    if not data:
        return _api_error(f"architecture blueprint '{name}' not found", "not_found", 404)
    return data


@router.get("/architecture/registry/{name}")
def get_architecture_registry(name: str, version: int = 0):
    from ..db import load_architecture_registry

    data = load_architecture_registry(name=name, version=version if version > 0 else None)
    if not data:
        return _api_error(f"architecture registry '{name}' not found", "not_found", 404)
    return data


@router.get("/agents/{agent_id}")
def get_specialist_agent(agent_id: str):
    """Return metadata for a single specialist agent."""
    from ..agents import get_specialist
    agent = get_specialist(agent_id)
    if agent is None:
        return _api_error(f"Agent '{agent_id}' not found", "not_found", 404)
    return {
        "id":                  agent.id,
        "name":                agent.name,
        "icon":                agent.icon,
        "description":         agent.description,
        "keywords":            agent.keywords,
        "preferred_providers": agent.preferred_providers,
        "temperature":         agent.temperature,
        "tier":                agent.tier,
    }


@router.post("/agents/{agent_id}/run")
async def run_specialist_agent(agent_id: str, request: Request):
    """Run a task through a named specialist agent.

    POST body: {"task": "...", "session_id": "optional"}
    Returns the agent's response using its system prompt + preferred providers.
    """
    from ..agents import get_specialist
    from ..agent import call_llm_with_fallback, _smart_order, get_system_resources, PROVIDERS

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    agent = get_specialist(agent_id)
    if agent is None:
        return _api_error(f"Agent '{agent_id}' not found", "not_found", 404)

    session_id = str(body.get("session_id") or "")
    try:
        check_user_task(task, policy_profile=get_session_safety_profile(session_id))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": f"specialist:{agent_id}",
            "label": task[:120],
            "session": session_id or None,
            "profile": get_session_safety_profile(session_id),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    messages = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user",   "content": task},
    ]
    try:
        result, pid = call_llm_with_fallback(messages, task)
        content = result.get("content", str(result))
        return {
            "agent_id":  agent_id,
            "agent":     agent.name,
            "provider":  pid,
            "content":   content,
        }
    except Exception as exc:
        return _api_error(str(exc), "agent_error", 500)


@router.post("/agents/classify")
async def classify_task_to_agent(request: Request):
    """Classify a task description and return the best matching specialist agent."""
    from ..agents import classify_to_specialist
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)
    agent = classify_to_specialist(task)
    return {
        "agent_id":          agent.id,
        "agent_name":        agent.name,
        "icon":              agent.icon,
        "description":       agent.description,
        "match_score":       agent.matches(task),
    }


# ── Sprint F: Hierarchical Orchestration ─────────────────────────────────────

@router.post("/orchestrate/hierarchical")
async def hierarchical_orchestrate(request: Request):
    """Run the full Planner → Executor → Reviewer → Verifier pipeline.

    POST body:
        goal          — required
        max_subtasks  — optional int (default 6)
        skip_review   — optional bool (default false)
        skip_verify   — optional bool (default false)
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    goal = (body.get("goal") or "").strip()
    if not goal:
        return _api_error("goal is required", "validation_error", 422)

    try:
        goal = check_user_task(goal)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "orchestrate_hierarchical",
            "label": goal[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    max_subtasks = int(body.get("max_subtasks", 6))
    skip_review  = bool(body.get("skip_review", False))
    skip_verify  = bool(body.get("skip_verify", False))

    try:
        from ..autonomy import HierarchicalOrchestrator
        orch = HierarchicalOrchestrator(
            _orchestrator_llm,
            max_parallel=2,
            skip_review=skip_review,
            skip_verify=skip_verify,
        )
        hr = orch.run(goal, max_subtasks=max_subtasks)
        trace_id = secrets.token_hex(8)
        result = {
            "trace_id":         trace_id,
            "goal":             hr.goal,
            "plan":             hr.plan,
            "execution":        hr.execution,
            "review":           hr.review,
            "verification":     hr.verification,
            "final_output":     hr.final_output,
            "execution_time":   round(hr.execution_time, 3),
            "stages_completed": hr.stages_completed,
        }
        autonomy_traces[trace_id] = {"type": "hierarchical", "status": "done", **result}
        return result
    except Exception as exc:
        return _api_error(str(exc), "orchestration_error", 500)


@router.get("/orchestrate/hierarchical/{trace_id}")
def get_hierarchical_trace(trace_id: str):
    """Retrieve a stored hierarchical orchestration result by trace ID."""
    trace = autonomy_traces.get(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace not found"}, status_code=404)
    return trace


# ── Sprint G: Simulate Endpoint ───────────────────────────────────────────────

@router.post("/simulate")
async def run_simulation(request: Request):
    """Run a swarm prediction simulation (MiroFish-inspired).

    POST body:
        topic      — required  e.g. "Will AI replace software engineers by 2030?"
        seed       — optional context / background text
        n_personas — optional int 2-8 (default 5)
        n_rounds   — optional int 1-5 (default 3)

    Returns a SimulationResult dict including prediction, confidence, personas, rounds,
    minority_views and a full Markdown report.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    topic = (body.get("topic") or "").strip()
    if not topic:
        return _api_error("topic is required", "validation_error", 422)

    try:
        check_user_task(topic)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "simulate",
            "label": topic[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    n_personas = max(2, min(int(body.get("n_personas", 5)), 8))
    n_rounds   = max(1, min(int(body.get("n_rounds",   3)), 5))
    seed       = (body.get("seed") or "").strip()

    def _sim_llm(msgs):
        try:
            res, _ = call_llm_with_fallback(msgs, "simulation")
            if isinstance(res, dict):
                if res.get("action") == "respond":
                    return res.get("content", "")
                return json.dumps(res)
            return str(res)
        except Exception as _se:
            return f"error: {_se}"

    try:
        from ..simulation import SimulationEngine
        engine = SimulationEngine(_sim_llm, max_personas=8, max_rounds=5)
        result = engine.run(topic, seed, n_personas, n_rounds)
        return result.to_dict()
    except Exception as exc:
        return _api_error(str(exc), "simulation_error", 500)


# ── Sprint G: Agent Marketplace ───────────────────────────────────────────────

@router.get("/marketplace/agents")
def list_marketplace_agents():
    """Return all available agents (built-in + imported) from the marketplace."""
    from ..agents.registry import SPECIALIST_AGENTS
    from ..db import load_marketplace_agents

    builtin = [
        {
            "id":                  a.id,
            "name":                a.name,
            "icon":                a.icon,
            "description":         a.description,
            "keywords":            a.keywords,
            "preferred_providers": a.preferred_providers,
            "temperature":         a.temperature,
            "tier":                a.tier,
            "source":              "builtin",
        }
        for a in SPECIALIST_AGENTS
    ]
    imported = load_marketplace_agents(source="imported")
    return {"agents": builtin + imported, "total": len(builtin) + len(imported)}


@router.post("/marketplace/agents", status_code=201)
async def import_marketplace_agent(request: Request):
    """Import a custom JSON-defined agent into the marketplace.

    POST body (required fields):
        id            — unique string id
        name          — display name
        system_prompt — agent system prompt
    Optional:
        icon, description, keywords, preferred_providers, temperature, tier
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    agent_id = (body.get("id") or "").strip()
    name     = (body.get("name") or "").strip()
    prompt   = (body.get("system_prompt") or "").strip()

    if not agent_id:
        return _api_error("id is required", "validation_error", 422)
    if not name:
        return _api_error("name is required", "validation_error", 422)
    if not prompt:
        return _api_error("system_prompt is required", "validation_error", 422)

    # Sanitise / normalise
    icon                = (body.get("icon") or "🤖").strip()[:8]
    description         = (body.get("description") or "").strip()[:512]
    keywords            = body.get("keywords") or []
    preferred_providers = body.get("preferred_providers") or []
    temperature         = float(body.get("temperature", 0.7))
    tier                = (body.get("tier") or "standard").strip()

    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    if not isinstance(preferred_providers, list):
        preferred_providers = [str(preferred_providers)]

    from ..db import save_marketplace_agent
    save_marketplace_agent(
        agent_id=agent_id,
        name=name,
        icon=icon,
        description=description,
        system_prompt=prompt,
        keywords=keywords,
        preferred_providers=preferred_providers,
        temperature=temperature,
        tier=tier,
        source="imported",
    )
    return {"id": agent_id, "name": name, "status": "imported"}


@router.delete("/marketplace/agents/{agent_id}", status_code=200)
def delete_marketplace_agent(agent_id: str):
    """Delete an imported marketplace agent by id.

    Built-in agents cannot be deleted via this endpoint.
    """
    from ..db import delete_marketplace_agent as db_delete_agent
    deleted = db_delete_agent(agent_id)
    if not deleted:
        return _api_error(
            f"Agent '{agent_id}' not found or is a built-in agent",
            "not_found",
            404,
        )
    return {"id": agent_id, "status": "deleted"}


# ── Sprint G: Agent Bus ───────────────────────────────────────────────────────

# NOTE: /agents/bus/log must be registered BEFORE /agents/bus/{agent_id} so
# FastAPI doesn't capture the literal "log" path segment as an agent_id.
@router.get("/agents/bus/log")
def get_bus_log(limit: int = 50):
    """Return the recent global message bus log."""
    from ..agent_bus import recent_log, all_agents
    msgs = recent_log(limit=limit)
    return {
        "messages":      [m.to_dict() for m in msgs],
        "active_agents": all_agents(),
    }


@router.get("/agents/bus/{agent_id}")
def read_agent_inbox(
    agent_id: str,
    limit: int = 20,
    unread_only: bool = False,
):
    """Read messages in an agent's inbox.

    Query params:
        limit       — max messages to return (default 20)
        unread_only — if true, only return unread messages
    """
    from ..agent_bus import read_messages, unread_count
    msgs = read_messages(agent_id, limit=limit, unread_only=unread_only, mark_read=True)
    return {
        "agent_id":     agent_id,
        "messages":     [m.to_dict() for m in msgs],
        "unread_count": unread_count(agent_id),
    }


@router.post("/agents/bus", status_code=201)
async def post_agent_message(request: Request):
    """Post a message from one agent to another (or broadcast).

    POST body:
        from_id  — sender agent id (or "user")
        to_id    — recipient agent id (or "broadcast")
        content  — message text
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    from_id = (body.get("from_id") or "").strip()
    to_id   = (body.get("to_id")   or "").strip()
    content = (body.get("content") or "").strip()

    if not from_id:
        return _api_error("from_id is required", "validation_error", 422)
    if not to_id:
        return _api_error("to_id is required", "validation_error", 422)
    if not content:
        return _api_error("content is required", "validation_error", 422)

    from ..agent_bus import post_message
    msg = post_message(from_id, to_id, content)
    return msg.to_dict()


@router.delete("/tasks/{trace_id}")
def delete_task_trace(trace_id: str):
    deleted = _delete_trace(trace_id)
    execution_traces.pop(trace_id, None)
    if not deleted:
        return _api_error("trace not found", "not_found", 404)
    return {"deleted": trace_id, "ok": True}


# ── Ensemble settings endpoints ──────────────────────────────────────────────

@router.post("/kg/store")
async def kg_store_endpoint(request: Request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return _api_error("name is required", "validation_error", 422)
    eid = _kg_store(
        name,
        entity_type=data.get("entity_type", "concept"),
        facts=data.get("facts", {}),
        relations=data.get("relations", []),
    )
    return {"id": eid, "name": name, "ok": True}


@router.get("/kg/query")
def kg_query_endpoint(q: str = "", limit: int = 10):
    if not q:
        return _api_error("q is required", "validation_error", 422)
    results = _kg_query(q, limit=limit)
    return {"results": results, "count": len(results)}


@router.get("/kg/entities")
def kg_entities_endpoint(entity_type: str = "", limit: int = 100):
    results = _kg_list(entity_type=entity_type or None, limit=limit)
    return {"entities": results, "count": len(results)}


@router.get("/kg/entities/{name}")
def kg_entity_get_endpoint(name: str):
    entity = _kg_get(name)
    if entity is None:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return entity


@router.delete("/kg/entities/{name}")
def kg_entity_delete_endpoint(name: str):
    deleted = _kg_delete(name)
    if not deleted:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return {"deleted": name, "ok": True}


# ── Execution Trace replay/resume endpoints ──────────────────────────────────

@router.get("/tasks")
def list_tasks(limit: int = 50):
    traces = _list_traces(limit=limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/tasks/{trace_id}")
def get_task_trace(trace_id: str):
    # Check in-memory first (live traces), then SQLite checkpoints
    in_memory = execution_traces.get(trace_id)
    checkpoints = _load_checkpoints(trace_id)
    if in_memory is None and not checkpoints:
        return _api_error("trace not found", "not_found", 404)
    events = in_memory if in_memory is not None else []
    return {"trace_id": trace_id, "events": events, "checkpoints": len(checkpoints)}


@router.get("/tasks/{trace_id}/replay")
async def replay_task(trace_id: str):
    """Stream stored trace events as SSE with a short delay for visual replay."""
    import asyncio as _asyncio

    # Prefer in-memory events, fall back to last SQLite checkpoint's events
    stored_events = execution_traces.get(trace_id)
    if stored_events is None:
        cp = _get_latest_checkpoint(trace_id)
        stored_events = cp["events"] if cp else None
    if stored_events is None:
        return _api_error("trace not found", "not_found", 404)

    events_copy = list(stored_events)

    async def _stream():
        for evt in events_copy:
            yield f"data: {json.dumps(evt)}\n\n"
            await _asyncio.sleep(0.04)

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/tasks/{trace_id}/resume")
async def resume_task(trace_id: str, request: Request):
    """Resume a task from its latest checkpoint."""
    data = await request.json()
    sid = data.get("session_id", "")

    cp = _get_latest_checkpoint(trace_id)
    if not cp:
        return _api_error("no checkpoints found for this trace", "not_found", 404)

    task = cp.get("task", "")
    saved_history = cp.get("history", [])

    if not task:
        return _api_error("checkpoint has no task to resume", "invalid_request", 422)

    new_trace_id = str(uuid.uuid4())
    execution_traces[new_trace_id] = []
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_evt = threading.Event()
    new_stream_id = str(uuid.uuid4())
    _active_streams[new_stream_id] = stop_evt

    def _run_resume():
        try:
            for event in stream_agent_task(task, saved_history, [], stop_evt,
                                           sid=sid or "", trace_id=new_trace_id):
                if stop_evt.is_set():
                    break
                if event["type"] == "done" and sid:
                    sessions[sid] = event.get("history", saved_history)
                trace_event = {k: v for k, v in event.items() if k not in ("history", "workdir")}
                execution_traces[new_trace_id].append(trace_event)
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            err_event = {"type": "error", "message": str(e)}
            execution_traces[new_trace_id].append(err_event)
            loop.call_soon_threadsafe(queue.put_nowait, err_event)
        finally:
            _active_streams.pop(new_stream_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_run_resume, daemon=True).start()

    async def _generate():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                payload = {k: v for k, v in event.items() if k not in ("history", "workdir")}
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            stop_evt.set()

    return StreamingResponse(_generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Trace-Id": new_trace_id})


@router.delete("/tasks/{trace_id}")
def delete_task_trace(trace_id: str):
    deleted = _delete_trace(trace_id)
    execution_traces.pop(trace_id, None)
    if not deleted:
        return _api_error("trace not found", "not_found", 404)
    return {"deleted": trace_id, "ok": True}


# ── Ensemble settings endpoints ──────────────────────────────────────────────

@router.get("/settings/ensemble")
def get_ensemble_settings():
    return {
        "ensemble_mode":      _config.get("ensemble_mode", True),
        "ensemble_threshold": _config.get("ensemble_threshold", 0.4),
        "ensemble_enabled":   get_ensemble_enabled(),
    }


@router.post("/settings/ensemble")
async def update_ensemble_settings(request: Request):
    data = await request.json()
    kwargs = {}
    if "ensemble_mode" in data:
        kwargs["ensemble_mode"] = bool(data["ensemble_mode"])
    if "ensemble_threshold" in data:
        thr = float(data["ensemble_threshold"])
        if not 0.0 <= thr <= 1.0:
            return _api_error("ensemble_threshold must be between 0.0 and 1.0", "validation_error", 422)
        kwargs["ensemble_threshold"] = thr
    if kwargs:
        update_config(**kwargs)
    return {
        "ensemble_mode":      _config.get("ensemble_mode", True),
        "ensemble_threshold": _config.get("ensemble_threshold", 0.4),
        "ensemble_enabled":   get_ensemble_enabled(),
    }


@router.get("/settings/hitl")
def get_hitl_settings():
    return {
        "hitl_approval_mode": _config.get("hitl_approval_mode", "off"),
    }


@router.post("/settings/hitl")
async def update_hitl_settings(request: Request):
    data = await request.json()
    mode = str(data.get("hitl_approval_mode", "off")).lower().strip()
    if mode not in ("off", "warn", "block"):
        return _api_error("hitl_approval_mode must be one of: off, warn, block", "validation_error", 422)
    update_config(hitl_approval_mode=mode)
    return {"hitl_approval_mode": _config.get("hitl_approval_mode", "off")}


@router.get("/approvals")
def get_approvals(session_id: str = ""):
    return {
        "items": list_tool_approvals(session_id),
        "total": len(list_tool_approvals(session_id)),
    }


@router.post("/approvals/{approval_id}")
async def resolve_approval(approval_id: str, request: Request):
    data = await request.json()
    approved = bool(data.get("approved", False))
    note = str(data.get("note", ""))
    resolved = decide_tool_approval(approval_id, approved=approved, note=note)
    if not resolved:
        return _api_error("approval not found", "not_found", 404)
    return resolved


def _run_scheduled_task_extended(task: str) -> str:
    if task == "__internal_quota_cleanup__":
        return _quota_cleanup_task()
    return _run_scheduled_task(task)


def startup_event() -> None:
    set_run_function(_run_scheduled_task_extended)
    restore_from_db()
    _register_quota_reset_scheduler()
    asyncio.create_task(_register_with_nexus_cloud())
    asyncio.create_task(_heartbeat_loop())


# ── admin: user management ────────────────────────────────────────────────────

@router.get("/admin/users")
def admin_list_users(request: Request):
    require_admin(request)
    users = db_list_users()
    safe = [{"username": u["username"], "display_name": u.get("display_name", ""),
              "role": u.get("role", "user"), "created_at": u.get("created_at", "")}
            for u in users]
    return {"users": safe, "total": len(safe)}


@router.patch("/admin/users/{username}/role")
async def admin_update_role(username: str, request: Request):
    require_admin(request)
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    role = str(data.get("role", "")).strip().lower()
    if role not in ("admin", "user", "viewer"):
        return _api_error("role must be one of: admin, user, viewer", "validation_error", 422)
    target = db_get_user(username)
    if not target:
        return _api_error("user not found", "not_found", 404)
    ok = db_update_user_role(username, role)
    return {"username": username, "role": role, "updated": ok}


# ── auth: password reset ──────────────────────────────────────────────────────

@router.post("/auth/password-reset")
async def auth_password_reset(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    username = str(data.get("username", "")).strip()
    new_password = str(data.get("new_password", "")).strip()
    current_password = str(data.get("current_password", "")).strip()

    if not username or not new_password:
        return _api_error("username and new_password are required", "validation_error", 422)
    if len(new_password) < 8:
        return _api_error("new_password must be at least 8 characters", "validation_error", 422)

    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)

    caller = _read_token(request)
    caller_role = _get_token_role(request)
    is_self = caller == username
    is_admin = caller_role == "admin"

    if not is_self and not is_admin:
        return _api_error("Cannot reset another user's password", "forbidden", 403)

    if is_self and not is_admin:
        if not current_password or not _verify_pw(current_password, user["password"]):
            return _api_error("current_password is incorrect", "unauthorized", 401)

    new_hash = _hash_pw(new_password)
    from ..db import _sql_execute, _backend as _b
    from ..db import SQLiteBackend, PostgresBackend
    if isinstance(_b, SQLiteBackend):
        _sql_execute("UPDATE users SET password=? WHERE username=?", (new_hash, username))
    else:
        _sql_execute("UPDATE users SET password=%s WHERE username=%s", (new_hash, username))
    return {"ok": True, "username": username}


# ── admin: per-user quota dashboard ──────────────────────────────────────────

@router.get("/admin/quota")
def admin_quota_dashboard(request: Request):
    require_admin(request)
    from ..profiles import get_quota_state
    users = db_list_users()
    result = []
    for u in users:
        uname = u["username"]
        state = get_quota_state(uname)
        result.append({"username": uname, "role": u.get("role", "user"), **state})
    return {"quotas": result, "total": len(result)}


@router.post("/admin/quota/{username}")
async def admin_set_quota(username: str, request: Request):
    require_admin(request)
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)
    tokens_per_day = int(data.get("tokens_per_day", 0))
    requests_per_day = data.get("requests_per_day")
    if requests_per_day is not None:
        requests_per_day = int(requests_per_day)
    from ..profiles import set_quota
    state = set_quota(username, tokens_per_day, requests_per_day)
    return {"username": username, **state}


@router.get("/quota/me")
def my_quota(request: Request):
    if not MULTI_USER:
        username = "nexus_admin"
    else:
        username = _read_token(request)
        if not username:
            return _api_error("Unauthorized", "unauthorized", 401)
    from ..profiles import get_quota_state
    return {"username": username, **get_quota_state(username)}


# ── database backup / restore ─────────────────────────────────────────────────

@router.get("/api/backup")
def db_backup(request: Request):
    require_admin(request)
    import io, sqlite3 as _sqlite3
    from ..db import SQLiteBackend, _backend as _b
    if not isinstance(_b, SQLiteBackend):
        return _api_error("Backup only supported for SQLite backend", "not_supported", 400)
    buf = io.BytesIO()
    src = _sqlite3.connect(_b.db_path)
    dst = _sqlite3.connect(":memory:")
    src.backup(dst)
    dst_buf = io.BytesIO()
    for line in dst.iterdump():
        dst_buf.write((line + "\n").encode())
    dst_buf.seek(0)
    src.close()
    dst.close()
    from fastapi.responses import StreamingResponse
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        dst_buf,
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="nexus_backup_{ts}.sql"'},
    )


@router.post("/api/restore")
async def db_restore(request: Request):
    require_admin(request)
    from ..db import SQLiteBackend, _backend as _b
    if not isinstance(_b, SQLiteBackend):
        return _api_error("Restore only supported for SQLite backend", "not_supported", 400)
    body = await request.body()
    if not body:
        return _api_error("SQL backup body is required", "validation_error", 422)
    import sqlite3 as _sqlite3, tempfile, shutil, os as _os
    tmp_path = _b.db_path + ".restore_tmp"
    try:
        conn = _sqlite3.connect(tmp_path)
        for stmt in body.decode("utf-8").split(";\n"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass
        conn.commit()
        conn.close()
        shutil.copy2(tmp_path, _b.db_path)
        _os.remove(tmp_path)
    except Exception as e:
        try:
            _os.remove(tmp_path)
        except Exception:
            pass
        return _api_error(f"Restore failed: {e}", "restore_error", 500)
    return {"ok": True, "message": "Database restored successfully"}


# ── API key management ────────────────────────────────────────────────────────

_VALID_SCOPES = {"chat", "read", "admin", "embeddings", "tools"}


def _generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, key_hash, key_prefix)."""
    raw = "nxk_" + secrets.token_urlsafe(40)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, key_hash, prefix


@router.post("/auth/api-keys")
async def create_api_key(request: Request):
    username = require_auth(request)
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    name = str(data.get("name", "")).strip()
    if not name:
        return _api_error("name is required", "validation_error", 422)

    raw_scopes = data.get("scopes", ["chat", "read"])
    if not isinstance(raw_scopes, list):
        raw_scopes = [str(raw_scopes)]
    scopes = [s for s in raw_scopes if s in _VALID_SCOPES]
    if not scopes:
        scopes = ["chat", "read"]

    role = _get_token_role(request)
    if "admin" in scopes and role != "admin":
        return _api_error("admin scope requires admin role", "forbidden", 403)

    raw_key, key_hash, prefix = _generate_api_key()
    key_id = str(uuid.uuid4())
    ts = time.time()
    ok = db_create_api_key(key_id, username, key_hash, prefix, name, scopes, ts)
    if not ok:
        return _api_error("Failed to create API key", "server_error", 500)

    return {
        "id": key_id,
        "key": raw_key,
        "key_prefix": prefix,
        "name": name,
        "scopes": scopes,
        "created_at": ts,
        "note": "Store this key securely — it will not be shown again.",
    }


@router.get("/auth/api-keys")
def list_api_keys_endpoint(request: Request):
    username = require_auth(request)
    keys = db_list_api_keys(username)
    safe = []
    for k in keys:
        safe.append({
            "id": k["id"],
            "key_prefix": k["key_prefix"],
            "name": k["name"],
            "scopes": k["scopes"],
            "created_at": k["created_at"],
            "last_used_at": k.get("last_used_at"),
            "revoked_at": k.get("revoked_at"),
            "active": k.get("revoked_at") is None,
        })
    return {"keys": safe, "total": len(safe)}


@router.delete("/auth/api-keys/{key_id}")
def delete_api_key(key_id: str, request: Request):
    username = require_auth(request)
    ok = db_revoke_api_key(key_id, username)
    if not ok:
        return _api_error("key not found or not owned by you", "not_found", 404)
    return {"ok": True, "revoked": key_id}


# ── email verification ────────────────────────────────────────────────────────

_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_EMAIL_FROM = os.getenv("EMAIL_FROM", _SMTP_USER or "nexus@localhost")
_APP_URL = os.getenv("APP_URL", "http://localhost:8000")


def _send_verification_email(email: str, token: str, username: str) -> bool:
    link = f"{_APP_URL}/auth/verify-email?token={token}&username={username}"
    body = f"Hello {username},\n\nVerify your email:\n{link}\n\nThis link expires in 24 hours."
    if not _SMTP_HOST:
        print(f"[email-verify] Token for {username}: {token} (SMTP not configured)")
        return True
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body)
        msg["Subject"] = "Verify your Nexus AI account"
        msg["From"] = _EMAIL_FROM
        msg["To"] = email
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as s:
            s.starttls()
            if _SMTP_USER:
                s.login(_SMTP_USER, _SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"[email-verify] SMTP error: {e}")
        return False


@router.post("/auth/send-verification")
async def send_verification_email(request: Request):
    username = require_auth(request)
    try:
        data = await _read_json_body(request)
    except HTTPException:
        data = {}
    email = str(data.get("email", "")).strip().lower()
    if not email or "@" not in email:
        return _api_error("valid email required", "validation_error", 422)

    token = secrets.token_urlsafe(32)
    db_save_pref(f"email_verify_token.{username}", f"{token}:{email}")
    db_update_user_email(username, email, verified=False)
    sent = _send_verification_email(email, token, username)
    return {"ok": True, "email": email, "email_sent": sent}


@router.get("/auth/verify-email")
def verify_email(token: str = "", username: str = ""):
    if not token or not username:
        return _api_error("token and username required", "validation_error", 422)
    stored = db_load_pref(f"email_verify_token.{username}", "")
    if not stored:
        return _api_error("no pending verification for this user", "not_found", 404)
    stored_token, email = (stored.split(":", 1) + [""])[:2]
    if not secrets.compare_digest(stored_token, token):
        return _api_error("invalid or expired token", "unauthorized", 401)
    db_update_user_email(username, email, verified=True)
    db_save_pref(f"email_verify_token.{username}", "")
    return {"ok": True, "username": username, "email": email, "verified": True}


# ── OAuth2 / OIDC SSO ─────────────────────────────────────────────────────────

_OAUTH_PROVIDERS: dict[str, dict] = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",  # pragma: allowlist secret
        "scope": "openid email profile",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "client_id_env": "GITHUB_CLIENT_ID",
        "client_secret_env": "GITHUB_CLIENT_SECRET",  # pragma: allowlist secret
        "scope": "read:user user:email",
    },
}


@router.get("/auth/oauth/{provider}")
def oauth_redirect(provider: str, request: Request):
    cfg = _OAUTH_PROVIDERS.get(provider)
    if not cfg:
        return _api_error(f"Unknown provider: {provider}. Valid: {list(_OAUTH_PROVIDERS)}", "not_found", 404)
    client_id = os.getenv(cfg["client_id_env"], "")
    if not client_id:
        return _api_error(f"{provider} OAuth not configured (missing {cfg['client_id_env']})", "not_configured", 503)
    state = secrets.token_urlsafe(16)
    db_save_pref(f"oauth_state.{state}", provider)
    callback = f"{_APP_URL}/auth/oauth/{provider}/callback"
    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": callback,
        "scope": cfg["scope"],
        "response_type": "code",
        "state": state,
    })
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{cfg['auth_url']}?{params}")


@router.get("/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str = "", state: str = "", error: str = ""):
    if error:
        return _api_error(f"OAuth error: {error}", "oauth_error", 400)
    if not code:
        return _api_error("Missing authorization code", "oauth_error", 400)

    cfg = _OAUTH_PROVIDERS.get(provider)
    if not cfg:
        return _api_error(f"Unknown provider: {provider}", "not_found", 404)

    stored_provider = db_load_pref(f"oauth_state.{state}", "")
    if stored_provider != provider:
        return _api_error("Invalid OAuth state — possible CSRF", "unauthorized", 401)
    db_save_pref(f"oauth_state.{state}", "")

    client_id = os.getenv(cfg["client_id_env"], "")
    client_secret = os.getenv(cfg["client_secret_env"], "")
    callback = f"{_APP_URL}/auth/oauth/{provider}/callback"

    import httpx as _httpx
    try:
        headers = {"Accept": "application/json"}
        token_resp = _httpx.post(cfg["token_url"], data={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": callback,
            "grant_type": "authorization_code",
        }, headers=headers, timeout=10)
        token_data = token_resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            return _api_error("Failed to obtain access token", "oauth_error", 502)

        user_resp = _httpx.get(cfg["userinfo_url"],
                               headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                               timeout=10)
        user_data = user_resp.json()
    except Exception as e:
        return _api_error(f"OAuth exchange failed: {e}", "oauth_error", 502)

    if provider == "google":
        provider_id = str(user_data.get("sub", ""))
        email = str(user_data.get("email", ""))
        display_name = str(user_data.get("name", ""))
    elif provider == "github":
        provider_id = str(user_data.get("id", ""))
        email = str(user_data.get("email", "") or "")
        display_name = str(user_data.get("name", "") or user_data.get("login", ""))
    else:
        return _api_error("Unsupported provider", "not_found", 404)

    if not provider_id:
        return _api_error("Could not retrieve provider user ID", "oauth_error", 502)

    user = db_get_or_create_oauth_user(provider, provider_id, email, display_name)
    if not user:
        return _api_error("Failed to create or retrieve user", "server_error", 500)

    username = user["username"]
    jwt_token = _make_token(username)
    refresh = _make_refresh_token(username)
    return {"token": jwt_token, "refresh_token": refresh, "username": username,
            "provider": provider, "email": email}


@router.get("/auth/oauth/providers")
def list_oauth_providers():
    result = {}
    for name, cfg in _OAUTH_PROVIDERS.items():
        client_id = os.getenv(cfg["client_id_env"], "")
        result[name] = {"configured": bool(client_id), "auth_url": f"/auth/oauth/{name}"}
    return {"providers": result}


# ── quota reset scheduler ─────────────────────────────────────────────────────

def _quota_cleanup_task() -> str:
    """Purge stale daily quota pref keys older than 8 days."""
    from ..db import _backend as _b, SQLiteBackend
    from datetime import timedelta
    cutoff_day = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")
    deleted = 0
    if isinstance(_b, SQLiteBackend):
        try:
            rows = _b._conn().execute(
                "SELECT key FROM user_prefs WHERE key LIKE 'quota.%' AND key < ?",
                (f"quota.tokens_used.zzz.{cutoff_day}",)
            ).fetchall()
            for r in rows:
                key = r["key"]
                parts = key.split(".")
                if len(parts) >= 4 and parts[-1] < cutoff_day:
                    _b._conn().execute("DELETE FROM user_prefs WHERE key=?", (key,))
                    deleted += 1
            _b._conn().commit()
        except Exception as e:
            return f"quota cleanup error: {e}"
    return f"quota cleanup: removed {deleted} stale daily keys"


def _register_quota_reset_scheduler():
    """Register weekly quota cleanup job if not already registered."""
    existing = list_jobs()
    if any(j.get("name") == "quota-weekly-cleanup" for j in existing):
        return
    schedule_job(
        name="quota-weekly-cleanup",
        task="__internal_quota_cleanup__",
        schedule="0 3 * * 0",  # every Sunday at 03:00 UTC
    )


@router.post("/admin/quota/reset/{username}")
async def admin_reset_quota(username: str, request: Request):
    require_admin(request)
    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)
    from ..db import _backend as _b, SQLiteBackend, _sql_execute
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(_b, SQLiteBackend):
        _sql_execute(
            "DELETE FROM user_prefs WHERE key LIKE ?", (f"quota.tokens_used.{username}.%",)
        )
        _sql_execute(
            "DELETE FROM user_prefs WHERE key LIKE ?", (f"quota.requests_used.{username}.%",)
        )
    else:
        _sql_execute(
            "DELETE FROM user_prefs WHERE key LIKE %s", (f"quota.tokens_used.{username}.%",)
        )
        _sql_execute(
            "DELETE FROM user_prefs WHERE key LIKE %s", (f"quota.requests_used.{username}.%",)
        )
    return {"ok": True, "username": username, "reset_at": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/completions  — legacy OpenAI text completions endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/v1/completions")
async def v1_completions(request: Request):
    """Legacy OpenAI-compatible text completions (non-chat) endpoint."""
    from .schemas import CompletionRequest, CompletionChoice, CompletionResponse
    try:
        body = await request.json()
    except Exception:
        return _v1_error("invalid JSON body", "invalid_request_error", 400)

    try:
        payload = CompletionRequest(**body)
    except Exception as exc:
        return _v1_error(str(exc), "validation_error", 422)

    principal = _principal_from_request(request, payload_user=payload.user or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _v1_quota_error_response(rate_result)

    prompt = payload.prompt_text()
    if not prompt:
        return _v1_error("prompt is required", "invalid_request_error", 422)

    cid = f"cmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if payload.stream:
        stop_evt = threading.Event()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _run():
            try:
                for evt in stream_agent_task(prompt, [], [], stop_evt):
                    loop.call_soon_threadsafe(queue.put_nowait, evt)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_run, daemon=True).start()

        async def _gen():
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                etype = evt.get("type", "")
                text = None
                finish = None
                if etype == "done":
                    text = evt.get("content", "")
                    finish = "stop"
                elif etype == "think":
                    text = ""
                elif etype == "error":
                    text = evt.get("message", "")
                    finish = "stop"
                if text is not None:
                    chunk = {
                        "id": cid, "object": "text_completion",
                        "created": created, "model": payload.model,
                        "choices": [{"text": text, "index": 0, "finish_reason": finish, "logprobs": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    result = run_agent_task(prompt, [], [], sid=f"cmpl-{uuid.uuid4().hex[:8]}")
    output = result.get("result", "")
    prompt_tokens = _estimate_text_tokens(prompt)
    completion_tokens = _estimate_text_tokens(output)
    return {
        "id": cid,
        "object": "text_completion",
        "created": created,
        "model": payload.model,
        "choices": [{"text": output, "index": 0, "finish_reason": "stop", "logprobs": None}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/audio/transcriptions  — Whisper-compatible STT
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/v1/audio/transcriptions")
async def v1_audio_transcriptions(request: Request):
    """Whisper-compatible STT. Tries local faster-whisper/whisper, falls back to
    provider (OpenAI Whisper API if OPENAI_API_KEY is set)."""
    from fastapi import UploadFile
    import tempfile, os as _os

    form = await request.form()
    file_field = form.get("file")
    model = str(form.get("model", "whisper-1"))
    language = str(form.get("language", "")) or None
    response_format = str(form.get("response_format", "json"))

    if file_field is None:
        return _v1_error("file is required", "invalid_request_error", 422)

    audio_bytes = await file_field.read()  # type: ignore[union-attr]
    filename = getattr(file_field, "filename", "audio.wav")

    # Try local faster-whisper first
    try:
        from faster_whisper import WhisperModel  # type: ignore
        with tempfile.NamedTemporaryFile(suffix=_os.path.splitext(filename)[1] or ".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            wm = WhisperModel("base", device="auto", compute_type="auto")
            kwargs = {}
            if language:
                kwargs["language"] = language
            segments, info = wm.transcribe(tmp_path, **kwargs)
            transcript = " ".join(seg.text for seg in segments)
            if response_format == "text":
                return transcript
            return {"text": transcript, "language": info.language, "duration": info.duration}
        finally:
            _os.unlink(tmp_path)
    except ImportError:
        pass
    except Exception as exc:
        print(f"⚠️ local whisper failed: {exc}")

    # Fallback: OpenAI Whisper API
    openai_key = _os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        import requests as _req
        resp = _req.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {openai_key}"},
            files={"file": (filename, audio_bytes)},
            data={"model": "whisper-1", **({"language": language} if language else {})},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if response_format == "text":
            return data.get("text", "")
        return {"text": data.get("text", ""), "language": language}

    return _v1_error(
        "No local Whisper installation found and OPENAI_API_KEY is not set. "
        "Install faster-whisper (`pip install faster-whisper`) or set OPENAI_API_KEY.",
        "model_error", 503,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/audio/speech  — TTS endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/v1/audio/speech")
async def v1_audio_speech(request: Request):
    """OpenAI-compatible TTS. Tries local piper/espeak, falls back to
    provider (OpenAI TTS API if OPENAI_API_KEY is set)."""
    import os as _os, subprocess as _sp, tempfile
    try:
        body = await request.json()
    except Exception:
        return _v1_error("invalid JSON body", "invalid_request_error", 400)

    text = str(body.get("input", "")).strip()
    voice = str(body.get("voice", "alloy"))
    fmt = str(body.get("response_format", "mp3")).lower()
    speed = float(body.get("speed", 1.0))

    if not text:
        return _v1_error("input is required", "invalid_request_error", 422)

    # Try local piper-tts
    piper_bin = _os.getenv("PIPER_BIN", "piper")
    piper_model = _os.getenv("PIPER_MODEL", "")
    try:
        if piper_model:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                _sp.run(
                    [piper_bin, "--model", piper_model, "--output_file", tmp_path],
                    input=text.encode(), check=True, timeout=60,
                    capture_output=True,
                )
                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()
                return StreamingResponse(
                    iter([audio_bytes]),
                    media_type="audio/wav",
                    headers={"Content-Disposition": f'attachment; filename="speech.wav"'},
                )
            finally:
                _os.unlink(tmp_path)
    except (FileNotFoundError, _sp.CalledProcessError, _sp.TimeoutExpired):
        pass

    # Try espeak fallback (returns PCM, convert to wav header)
    try:
        result = _sp.run(
            ["espeak", "-v", "en", "--stdout", text],
            capture_output=True, timeout=30, check=True,
        )
        return StreamingResponse(
            iter([result.stdout]),
            media_type="audio/wav",
            headers={"Content-Disposition": 'attachment; filename="speech.wav"'},
        )
    except (FileNotFoundError, _sp.CalledProcessError, _sp.TimeoutExpired):
        pass

    # Fallback: OpenAI TTS API
    openai_key = _os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        import requests as _req
        resp = _req.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "tts-1", "input": text, "voice": voice,
                  "response_format": fmt, "speed": speed},
            timeout=120,
        )
        resp.raise_for_status()
        media_map = {"mp3": "audio/mpeg", "opus": "audio/opus", "aac": "audio/aac",
                     "flac": "audio/flac", "wav": "audio/wav", "pcm": "audio/pcm"}
        return StreamingResponse(
            iter([resp.content]),
            media_type=media_map.get(fmt, "audio/mpeg"),
            headers={"Content-Disposition": f'attachment; filename="speech.{fmt}"'},
        )

    return _v1_error(
        "No local TTS engine found and OPENAI_API_KEY is not set. "
        "Install piper-tts or set OPENAI_API_KEY.",
        "model_error", 503,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Files API  — OpenAI-compatible file storage (/v1/files)
# ─────────────────────────────────────────────────────────────────────────────

_FILES_DIR = os.path.join(os.getenv("DATA_DIR", "/data"), "files")


def _ensure_files_dir():
    os.makedirs(_FILES_DIR, exist_ok=True)


def _file_meta_path(file_id: str) -> str:
    return os.path.join(_FILES_DIR, f"{file_id}.meta.json")


def _load_file_meta(file_id: str) -> dict | None:
    p = _file_meta_path(file_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def _list_file_metas() -> list:
    _ensure_files_dir()
    metas = []
    for name in os.listdir(_FILES_DIR):
        if name.endswith(".meta.json"):
            try:
                with open(os.path.join(_FILES_DIR, name)) as f:
                    metas.append(json.load(f))
            except Exception:
                pass
    return sorted(metas, key=lambda m: m.get("created_at", 0), reverse=True)


@router.get("/v1/files")
def v1_list_files(request: Request, purpose: str = ""):
    _ensure_files_dir()
    metas = _list_file_metas()
    if purpose:
        metas = [m for m in metas if m.get("purpose") == purpose]
    return {"object": "list", "data": metas}


@router.post("/v1/files")
async def v1_upload_file(request: Request):
    _ensure_files_dir()
    form = await request.form()
    file_field = form.get("file")
    purpose = str(form.get("purpose", "assistants"))

    if file_field is None:
        return _v1_error("file is required", "invalid_request_error", 422)

    raw = await file_field.read()  # type: ignore[union-attr]
    filename = getattr(file_field, "filename", "upload.bin")
    file_id = f"file-{uuid.uuid4().hex[:16]}"
    created_at = int(time.time())

    data_path = os.path.join(_FILES_DIR, file_id)
    with open(data_path, "wb") as fh:
        fh.write(raw)

    meta = {
        "id": file_id,
        "object": "file",
        "bytes": len(raw),
        "created_at": created_at,
        "filename": filename,
        "purpose": purpose,
        "status": "processed",
    }
    with open(_file_meta_path(file_id), "w") as fh:
        json.dump(meta, fh)

    return meta


@router.get("/v1/files/{file_id}")
def v1_get_file(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    return meta


@router.delete("/v1/files/{file_id}")
def v1_delete_file(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    for path in (_file_meta_path(file_id), os.path.join(_FILES_DIR, file_id)):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    return {"id": file_id, "object": "file", "deleted": True}


@router.get("/v1/files/{file_id}/content")
def v1_get_file_content(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    data_path = os.path.join(_FILES_DIR, file_id)
    if not os.path.exists(data_path):
        return _v1_error("file content not found", "not_found_error", 404)
    return FileResponse(data_path, filename=meta.get("filename", file_id))


# ─────────────────────────────────────────────────────────────────────────────
# Fine-tuning API  — compatibility stub (/v1/fine-tuning/jobs)
# ─────────────────────────────────────────────────────────────────────────────

_FINETUNE_JOBS: dict = {}  # in-memory store (non-persistent stub)


@router.post("/v1/fine-tuning/jobs")
async def v1_create_fine_tuning_job(request: Request):
    """OpenAI fine-tuning API compatibility stub.
    Validates the request and returns a queued job object. Actual fine-tuning
    is not executed; this endpoint exists for API surface parity."""
    from .schemas import FineTuningRequest, FineTuningJob
    try:
        body = await request.json()
        payload = FineTuningRequest(**body)
    except Exception as exc:
        return _v1_error(str(exc), "validation_error", 422)

    if not _load_file_meta(payload.training_file):
        return _v1_error(
            f"training_file '{payload.training_file}' not found. Upload it via POST /v1/files first.",
            "invalid_request_error", 400,
        )

    job = FineTuningJob(
        model=payload.model,
        training_file=payload.training_file,
        validation_file=payload.validation_file,
        hyperparameters=payload.hyperparameters or {},
        status="queued",
    )
    _FINETUNE_JOBS[job.id] = job.model_dump()
    return job.model_dump()


@router.get("/v1/fine-tuning/jobs")
def v1_list_fine_tuning_jobs(limit: int = 20, after: str = ""):
    jobs = list(_FINETUNE_JOBS.values())
    if after:
        idx = next((i for i, j in enumerate(jobs) if j["id"] == after), -1)
        if idx >= 0:
            jobs = jobs[idx + 1:]
    return {"object": "list", "data": jobs[:limit], "has_more": len(jobs) > limit}


@router.get("/v1/fine-tuning/jobs/{job_id}")
def v1_get_fine_tuning_job(job_id: str):
    job = _FINETUNE_JOBS.get(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)
    return job


@router.post("/v1/fine-tuning/jobs/{job_id}/cancel")
def v1_cancel_fine_tuning_job(job_id: str):
    job = _FINETUNE_JOBS.get(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)
    job["status"] = "cancelled"
    return job


# ─────────────────────────────────────────────────────────────────────────────
# Ollama management endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_base() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/").removesuffix("/v1")


@router.post("/ollama/pull")
async def ollama_pull_model(request: Request):
    """Pull (download) an Ollama model on demand.
    POST body: {"model": "llama3.2:3b", "stream": false}
    """
    import requests as _req
    try:
        body = await request.json()
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)

    model = str(body.get("model", "")).strip()
    if not model:
        return _api_error("model is required", "validation_error", 422)

    stream = bool(body.get("stream", False))
    base = _ollama_base()

    if stream:
        def _pull_stream():
            try:
                r = _req.post(f"{base}/api/pull",
                              json={"name": model, "stream": True},
                              stream=True, timeout=600)
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        yield line.decode() + "\n"
            except Exception as exc:
                yield json.dumps({"error": str(exc)}) + "\n"

        return StreamingResponse(_pull_stream(), media_type="application/x-ndjson")

    try:
        r = _req.post(f"{base}/api/pull", json={"name": model, "stream": False}, timeout=600)
        r.raise_for_status()
        return {"ok": True, "model": model, "status": r.json().get("status", "success")}
    except Exception as exc:
        return _api_error(f"Ollama pull failed: {exc}", "model_error", 502)


@router.post("/ollama/benchmark")
async def ollama_benchmark(request: Request):
    """Run a latency benchmark against one or more local Ollama models.
    POST body: {"models": ["llama3.2:3b"], "prompt": "Say hello.", "runs": 3}
    """
    import requests as _req, time as _t
    try:
        body = await request.json()
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)

    models = body.get("models") or []
    if not models:
        # Default: benchmark all locally available models
        try:
            r = _req.get(f"{_ollama_base()}/v1/models", timeout=5)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
        except Exception:
            pass
    if not models:
        return _api_error("no models specified and no local models found", "validation_error", 422)

    prompt = str(body.get("prompt", "Say hello in one sentence."))
    runs = max(1, min(int(body.get("runs", 3)), 10))
    base = _ollama_base()

    results = []
    for model_name in models[:10]:  # cap at 10 models
        latencies = []
        error = None
        for _ in range(runs):
            t0 = _t.time()
            try:
                r = _req.post(
                    f"{base}/v1/chat/completions",
                    json={"model": model_name,
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 64, "stream": False},
                    timeout=60,
                )
                r.raise_for_status()
                latencies.append(round((_t.time() - t0) * 1000))
            except Exception as exc:
                error = str(exc)
                break
        results.append({
            "model": model_name,
            "runs": len(latencies),
            "avg_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            "min_ms": min(latencies, default=None),
            "max_ms": max(latencies, default=None),
            "error": error,
        })

    return {"object": "benchmark_results", "models": results, "prompt": prompt}


# ── GGUF model file management ────────────────────────────────────────────────

_GGUF_DIR = os.path.join(os.getenv("DATA_DIR", "/data"), "models")


def _ensure_gguf_dir():
    os.makedirs(_GGUF_DIR, exist_ok=True)


@router.get("/ollama/gguf")
def ollama_list_gguf():
    """List GGUF model files stored in the data/models directory."""
    _ensure_gguf_dir()
    files = []
    for name in os.listdir(_GGUF_DIR):
        if name.lower().endswith(".gguf"):
            path = os.path.join(_GGUF_DIR, name)
            stat = os.stat(path)
            files.append({
                "filename": name,
                "size_bytes": stat.st_size,
                "modified_at": int(stat.st_mtime),
                "path": path,
            })
    return {"object": "list", "data": sorted(files, key=lambda f: f["filename"])}


@router.post("/ollama/gguf/import")
async def ollama_import_gguf(request: Request):
    """Import a GGUF file into Ollama via `ollama create`.
    POST body: {"filename": "model.gguf", "name": "my-model:latest"}
    The file must already be in the data/models directory.
    """
    import subprocess as _sp
    try:
        body = await request.json()
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)

    filename = str(body.get("filename", "")).strip()
    model_name = str(body.get("name", "")).strip()
    if not filename or not model_name:
        return _api_error("filename and name are required", "validation_error", 422)

    gguf_path = os.path.join(_GGUF_DIR, filename)
    if not os.path.exists(gguf_path) or not filename.lower().endswith(".gguf"):
        return _api_error(f"GGUF file '{filename}' not found in data/models/", "not_found_error", 404)

    # Write a minimal Modelfile
    modelfile_content = f"FROM {gguf_path}\n"
    modelfile_path = gguf_path + ".Modelfile"
    try:
        with open(modelfile_path, "w") as mf:
            mf.write(modelfile_content)
        result = _sp.run(
            ["ollama", "create", model_name, "-f", modelfile_path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return _api_error(f"ollama create failed: {result.stderr}", "model_error", 502)
        return {"ok": True, "model": model_name, "gguf": filename, "output": result.stdout.strip()}
    except FileNotFoundError:
        return _api_error("ollama CLI not found in PATH", "model_error", 503)
    except Exception as exc:
        return _api_error(str(exc), "model_error", 500)
    finally:
        try:
            os.unlink(modelfile_path)
        except Exception:
            pass


@router.delete("/ollama/gguf/{filename}")
def ollama_delete_gguf(filename: str):
    """Delete a GGUF file from the data/models directory."""
    if ".." in filename or "/" in filename:
        return _api_error("invalid filename", "invalid_request_error", 400)
    path = os.path.join(_GGUF_DIR, filename)
    if not os.path.exists(path):
        return _api_error(f"GGUF file '{filename}' not found", "not_found_error", 404)
    os.unlink(path)
    return {"ok": True, "deleted": filename}


# ─────────────────────────────────────────────────────────────────────────────
# HuggingFace download + Ollama import pipeline
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/huggingface/download")
async def huggingface_download(request: Request):
    """Download a GGUF model from HuggingFace Hub and optionally import it into Ollama.

    POST body:
      {
        "repo_id":   "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "filename":  "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "ollama_name": "llama3.2-3b:q4"   // optional — if set, auto-imports after download
      }

    Requires huggingface_hub (`pip install huggingface_hub`) or wget fallback.
    """
    import subprocess as _sp
    try:
        body = await request.json()
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)

    repo_id = str(body.get("repo_id", "")).strip()
    filename = str(body.get("filename", "")).strip()
    ollama_name = str(body.get("ollama_name", "")).strip()

    if not repo_id or not filename:
        return _api_error("repo_id and filename are required", "validation_error", 422)
    if not filename.lower().endswith(".gguf"):
        return _api_error("filename must be a .gguf file", "validation_error", 422)
    if ".." in filename or "/" in filename:
        return _api_error("invalid filename", "invalid_request_error", 400)

    _ensure_gguf_dir()
    dest_path = os.path.join(_GGUF_DIR, filename)

    # Try huggingface_hub first
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
        hf_token = os.getenv("HF_TOKEN", "") or None
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=_GGUF_DIR,
            token=hf_token,
        )
    except ImportError:
        # Fallback: direct HTTPS download via requests
        import requests as _req
        hf_token = os.getenv("HF_TOKEN", "")
        url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
        try:
            with _req.get(url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=8192):
                        fh.write(chunk)
                        downloaded += len(chunk)
        except Exception as exc:
            return _api_error(f"Download failed: {exc}", "model_error", 502)
    except Exception as exc:
        return _api_error(f"HuggingFace download failed: {exc}", "model_error", 502)

    result: dict = {
        "ok": True,
        "repo_id": repo_id,
        "filename": filename,
        "path": dest_path,
        "size_bytes": os.path.getsize(dest_path),
    }

    # Auto-import into Ollama if ollama_name is provided
    if ollama_name:
        modelfile_path = dest_path + ".Modelfile"
        try:
            with open(modelfile_path, "w") as mf:
                mf.write(f"FROM {dest_path}\n")
            proc = _sp.run(
                ["ollama", "create", ollama_name, "-f", modelfile_path],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode == 0:
                result["ollama_import"] = {"ok": True, "model": ollama_name}
            else:
                result["ollama_import"] = {"ok": False, "error": proc.stderr.strip()}
        except FileNotFoundError:
            result["ollama_import"] = {"ok": False, "error": "ollama CLI not found in PATH"}
        except Exception as exc:
            result["ollama_import"] = {"ok": False, "error": str(exc)}
        finally:
            try:
                os.unlink(modelfile_path)
            except Exception:
                pass

    return result

