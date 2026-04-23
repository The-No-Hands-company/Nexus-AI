import os, uuid, json, asyncio, threading, time, hmac, secrets, hashlib, base64
from urllib import parse as _urlparse
from urllib import request as _urlrequest
from urllib import error as _urlerror
import jwt as _jwt
from datetime import datetime, timezone
from fastapi import Request, HTTPException, APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse, Response
from pydantic import ValidationError

router = APIRouter()
from ..agent import (run_agent_task, stream_agent_task, get_providers_list, get_provider_health, get_provider_capabilities, set_provider_persona_override, get_provider_persona_override, get_config, update_config, call_llm_with_fallback, call_llm_smart, get_session_dir, set_session_token, _session_state, get_system_resources, _config, PERSONAS, activity_log, _MAX_ACTIVITY, get_session_safety_profile, set_session_safety_profile, safety_log, _push_safety_event, AllProvidersExhausted, warmup_agent)
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
from ..gist_backup import restore_from_gist, push_now as gist_push_now
from ..db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats, load_chat as db_load_chat, delete_chat as db_delete_chat, save_share as db_save_share, load_share as db_load_share, init_projects_table, save_project as db_save_project, load_projects as db_load_projects, delete_project as db_delete_project, assign_chat_to_project, get_project_chats, save_custom_instructions as db_save_ci, load_custom_instructions as db_load_ci, update_memory_entry as db_update_memory, delete_memory_entry as db_delete_memory, pin_chat as db_pin_chat, get_pinned_chats, search_chats as db_search_chats, get_usage_stats, get_usage_daily, get_usage_records, get_usage_by_user, init_usage_table, save_custom_persona as db_save_persona, load_custom_personas as db_load_custom_personas, delete_custom_persona as db_del_persona, load_pref as db_load_pref, save_pref as db_save_pref, save_self_review as db_save_self_review, list_self_reviews as db_list_self_reviews, load_safety_audit_entries as db_load_safety_audit_entries, list_users as db_list_users, update_user_role as db_update_user_role, get_user as db_get_user, _backend as db_backend, update_user_email as db_update_user_email, create_api_key as db_create_api_key, list_api_keys as db_list_api_keys, get_api_key_by_hash as db_get_api_key_by_hash, revoke_api_key as db_revoke_api_key, touch_api_key as db_touch_api_key, get_or_create_oauth_user as db_get_or_create_oauth_user, create_fine_tuning_job as db_create_fine_tuning_job, get_fine_tuning_job as db_get_fine_tuning_job, list_fine_tuning_jobs as db_list_fine_tuning_jobs, update_fine_tuning_job as db_update_fine_tuning_job, create_fine_tuning_job_event as db_create_fine_tuning_job_event, list_fine_tuning_job_events as db_list_fine_tuning_job_events, save_execution_trace as db_save_execution_trace, load_execution_trace as db_load_execution_trace, list_execution_traces as db_list_execution_traces, delete_execution_trace as db_delete_execution_trace, save_autonomy_trace as db_save_autonomy_trace, load_autonomy_trace as db_load_autonomy_trace, db_set_shared_memory, db_get_shared_memory, db_delete_shared_memory, db_list_shared_memory, db_save_task_job, db_list_task_jobs, save_ft_training_sample as db_save_ft_training_sample, list_ft_training_samples as db_list_ft_training_samples)
from ..personas import list_personas, set_persona, get_active_persona_name, get_persona
from ..memory import (
    add_memory,
    get_memory_context,
    summarize_history,
    get_semantic_memory,
    add_semantic_memory,
    delete_all as delete_all_memory,
    get_all as get_all_memory,
    get_episodic_timeline as get_episodic_memory,
    export_memory_bundle as export_memory_bundle,
    import_memory_bundle as import_memory_bundle,
)
from ..autonomy import Orchestrator, PlanningSystem, classify_subtask
from ..safety import GuardrailViolation, check_user_task, scrub_pii
from ..safety_pipeline import (
    SAFETY_POLICY_PROFILES, get_safety_policy, screen_input,
    explain_prompt_injection, screen_tool_action,
)
from ..knowledge_graph import (
    kg_store as _kg_store,
    kg_query as _kg_query,
    kg_list_entities as _kg_list,
    kg_get as _kg_get,
    kg_delete as _kg_delete,
    kg_graph as _kg_graph,
    kg_merge as _kg_merge,
    kg_import_ontology as _kg_import,
    kg_hybrid_search as _kg_hybrid_search,
)
from ..execution_trace import (
    save_checkpoint as _save_checkpoint,
    list_traces as _list_traces,
    load_checkpoints as _load_checkpoints,
    get_latest_checkpoint as _get_latest_checkpoint,
    delete_trace as _delete_trace,
    save_file_diff as _save_file_diff,
    get_file_diffs as _get_file_diffs,
    get_file_diff_detail as _get_file_diff_detail,
)
from ..ensemble import get_ensemble_enabled, set_ensemble_enabled
from ..profile_loader import inspect_profile_pack
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


def _builtin_chat_fallback(task: str) -> str:
    task_lc = (task or "").strip().lower()
    if any(phrase in task_lc for phrase in ("what can you do", "what do you do", "help me", "help")):
        return (
            "I can help with coding, debugging, architecture, API design, tests, documentation, refactors, "
            "code review, and step-by-step implementation guidance. I can also inspect project files, explain "
            "errors, and suggest concrete fixes."
        )
    if task_lc in {"hi", "hello", "hey", "yo"} or task_lc.startswith(("hi ", "hello ", "hey ")):
        return "Hello. I can help with coding, debugging, design, documentation, and project-level problem solving."
    return (
        "I could not reach a model provider quickly enough for this turn, but I am still available. "
        "Please retry with the same message, or give me a concrete coding, debugging, or architecture task and I will respond directly."
    )


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
    minute_limit = int(_rate_limit_settings.get("per_minute", 60))
    day_limit = int(_rate_limit_settings.get("per_day", 2500))
    mode = _rate_limit_settings.get("mode", "soft")
    minute_bucket = str(int(now // 60))
    day_bucket = str(int(now // 86400))

    try:
        from ..redis_state import get_rate_counter, incr_rate_counter

        current_minute = get_rate_counter(principal, f"m:{minute_bucket}")
        current_day = get_rate_counter(principal, f"d:{day_bucket}")
        minute_over = current_minute >= minute_limit
        day_over = current_day >= day_limit

        if minute_over or day_over:
            if mode == "hard":
                return {
                    "allowed": False,
                    "mode": mode,
                    "principal": principal,
                    "limit_type": "per_minute" if minute_over else "per_day",
                    "limit": minute_limit if minute_over else day_limit,
                    "used": current_minute if minute_over else current_day,
                    "retry_after_seconds": 60 if minute_over else 3600,
                }

            # Soft mode records pressure and still counts usage.
            new_minute = incr_rate_counter(principal, f"m:{minute_bucket}", 120)
            new_day = incr_rate_counter(principal, f"d:{day_bucket}", 172800)
            return {
                "allowed": True,
                "mode": mode,
                "principal": principal,
                "limit_type": "per_minute" if minute_over else "per_day",
                "limit": minute_limit if minute_over else day_limit,
                "used": new_minute if minute_over else new_day,
                "retry_after_seconds": 0,
            }

        # Allowed path: atomically record request in both windows.
        incr_rate_counter(principal, f"m:{minute_bucket}", 120)
        incr_rate_counter(principal, f"d:{day_bucket}", 172800)
        return {
            "allowed": True,
            "mode": mode,
            "principal": principal,
            "limit_type": "",
            "limit": 0,
            "used": 0,
            "retry_after_seconds": 0,
        }
    except Exception:
        # Fallback path keeps single-process behavior if Redis is unavailable.
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
                return {
                    "allowed": True,
                    "mode": mode,
                    "principal": principal,
                    "limit_type": "",
                    "limit": 0,
                    "used": 0,
                    "retry_after_seconds": 0,
                }

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

# ── Token revocation / session state backed by Redis with in-process fallback ─
# These in-memory structures are the fallback for when Redis is unavailable.
# Redis-backed equivalents are used when Redis is reachable, enabling correctness
# across Gunicorn workers and cold-start survival (zero-downtime rolling deploys).
_revoked_access_tokens: set[str] = set()
_refresh_tokens: dict[str, dict] = {}
_active_user_sessions: dict[str, list[dict]] = {}
_active_user_sessions_lock = threading.Lock()


def _redis_revoke_token(token: str, ttl_seconds: int = 0) -> None:
    """Mark a token as revoked in Redis (with expiry = token TTL)."""
    try:
        from ..redis_state import get_redis
        r = get_redis()
        key = f"nexus:revoked:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
        if ttl_seconds > 0:
            r.set(key, "1", ex=ttl_seconds)
        else:
            r.set(key, "1", ex=86400 * 14)  # default 14 days
    except Exception:
        _revoked_access_tokens.add(token)


def _redis_is_revoked(token: str) -> bool:
    """Check if a token is revoked, consulting Redis first then in-process set."""
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
    """
    Track an active session in Redis sorted set nexus:sessions:{username}.
    Returns list of revoked access tokens (oldest sessions trimmed to max_sessions).
    """
    revoked_tokens: list[str] = []
    try:
        from ..redis_state import get_redis
        import json as _json
        r = get_redis()
        key = f"nexus:sessions:{username}"
        score = float(record.get("issued_at", time.time()))
        r.set(f"{key}:v:{score}", _json.dumps(record), ex=JWT_REFRESH_EXPIRE_D * 86400)
        # We use a simple list stored in Redis for session tracking
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
    # Fallback to in-process
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
    """
    Detect suspicious logins by comparing current device/IP against known values.
    Returns True if the login looks suspicious (new device + new IP subnet).
    Records the current device/IP as known after the check.
    """
    try:
        from ..redis_state import get_redis
        r = get_redis()
        known_key = f"nexus:known_devices:{username}"
        last_ip_key = f"nexus:last_ip:{username}"

        known_devices_raw = r.get(known_key)
        known_devices: set[str] = set(json.loads(known_devices_raw)) if known_devices_raw else set()
        last_ip = (r.get(last_ip_key) or "").strip()

        is_new_device = device_hash not in known_devices
        # IP subnet change: compare first two octets for IPv4
        def _subnet(addr: str) -> str:
            parts = addr.split(".")
            return ".".join(parts[:2]) if len(parts) == 4 else addr
        is_new_subnet = bool(last_ip) and _subnet(last_ip) != _subnet(ip)

        suspicious = is_new_device and is_new_subnet

        # Update known devices (keep last 20)
        known_devices.add(device_hash)
        if len(known_devices) > 20:
            known_devices = set(list(known_devices)[-20:])
        r.set(known_key, json.dumps(list(known_devices)), ex=86400 * 90)
        r.set(last_ip_key, ip, ex=86400 * 90)
        return suspicious
    except Exception:
        return False  # graceful fallback: don't flag if Redis unavailable


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

def _make_token(username: str, role: str | None = None) -> str:
    from time import time as _t
    user = db_get_user(username)
    role_value = str(role or (user.get("role", "user") if user else "user"))
    payload = {
        "sub": username,
        "role": role_value,
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
    _redis_save_refresh(token, {"username": username, "exp": payload["exp"]}, ttl_days=JWT_REFRESH_EXPIRE_D)
    return token

def _orchestrator_llm(prompt: str, task: str = "") -> str:
    result, _pid = call_llm_with_fallback([{"role":"user","content":prompt}], task)
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)


def _save_autonomy_checkpoint(trace_id: str, step_idx: int, goal: str, events: list[dict]) -> None:
    """Persist autonomy execution checkpoint snapshots for replay/resume."""
    try:
        _save_checkpoint(trace_id, step_idx, goal, [], events)
    except Exception:
        # Checkpointing should not fail the user-visible autonomy request.
        pass


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


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
    raw = f"{ua}|{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _register_user_session(username: str, access_token: str, refresh_token: str, request: Request) -> None:
    """Track active sessions per user; revoke oldest when over configured cap.
    Sessions tracked in Redis for cross-worker correctness; in-process dict as fallback.
    """
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


def _require_admin(request: Request) -> str:
    return require_admin(request)

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
def auth_login(
    request: Request,
    username: str = "",
    password: str = "",
    mfa_code: str = "",
    recovery_code: str = "",
    remember_device: bool = False,
):
    from ..db import (
        get_user,
        record_login_attempt,
        count_recent_failures,
        clear_login_attempts,
        get_mfa_secret,
        use_mfa_recovery_code,
        is_trusted_device,
        save_trusted_device,
    )
    from ..observability import write_audit_log
    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)

    # Brute-force lockout with exponential backoff.
    threshold = int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "5"))
    base_backoff = int(os.getenv("LOGIN_LOCKOUT_BASE_SECONDS", "30"))
    failures = count_recent_failures(username, window_seconds=86400)
    if failures >= threshold:
        penalty_exp = max(0, failures - threshold)
        retry_after = min(3600, base_backoff * (2 ** penalty_exp))
        return JSONResponse(
            {
                "error": "too many failed login attempts",
                "type": "login_lockout",
                "retry_after_seconds": retry_after,
            },
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    user = get_user(username)
    if not user or not _verify_pw(password, user["password"]):
        record_login_attempt(username, _client_ip(request), success=False)
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    # If account has MFA enabled and current device is not trusted, enforce code.
    mfa_record = get_mfa_secret(username)
    device_hash = _device_hash(request)
    trusted_device = is_trusted_device(username, device_hash)
    if mfa_record and int(mfa_record.get("enabled") or 0) == 1 and not trusted_device:
        mfa_ok = False
        if mfa_code:
            try:
                import pyotp  # type: ignore

                mfa_ok = bool(pyotp.TOTP(mfa_record["secret"]).verify(str(mfa_code).strip(), valid_window=1))
            except Exception:
                mfa_ok = False
        elif recovery_code:
            code_hash = hashlib.sha256(str(recovery_code).strip().encode()).hexdigest()
            mfa_ok = bool(use_mfa_recovery_code(username, code_hash))

        if not mfa_ok:
            record_login_attempt(username, _client_ip(request), success=False)
            return JSONResponse(
                {
                    "error": "mfa required",
                    "type": "mfa_required",
                    "trusted_device": False,
                },
                status_code=401,
            )

        if remember_device:
            save_trusted_device(username, device_hash, label=request.headers.get("User-Agent", "")[:120])

    # Successful auth clears failed attempts window.
    record_login_attempt(username, _client_ip(request), success=True)
    clear_login_attempts(username)

    if mfa_record and int(mfa_record.get("enabled") or 0) == 1 and not trusted_device:
        if _detect_suspicious_login(username, device_hash, _client_ip(request)):
            write_audit_log(
                actor=username,
                action="suspicious_login",
                resource="auth/login",
                metadata={"ip": _client_ip(request), "device_hash": device_hash[:16]},
            )

    token = _make_token(username)
    refresh_token = _make_refresh_token(username)
    _register_user_session(username, token, refresh_token, request)
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
            _redis_revoke_token(token)

    refresh_token = str(body.get("refresh_token") or "").strip()
    if refresh_token:
        _redis_delete_refresh(refresh_token)

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

    record = _redis_get_refresh(refresh_token)
    if not record:
        return _api_error("invalid refresh token", "unauthorized", 401)

    try:
        payload = _jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        _redis_delete_refresh(refresh_token)
        return _api_error("invalid refresh token", "unauthorized", 401)

    if payload.get("type") != "refresh":
        return _api_error("invalid refresh token", "unauthorized", 401)

    username = str(payload.get("sub") or "").strip()
    if not username or record.get("username") != username:
        return _api_error("invalid refresh token", "unauthorized", 401)

    _redis_delete_refresh(refresh_token)
    new_access = _make_token(username)
    new_refresh = _make_refresh_token(username)
    return {"token": new_access, "refresh_token": new_refresh, "username": username}

@router.get("/")
def home(): return FileResponse("static/index.html")


@router.get("/playground")
def api_playground():
        html = """
        <!doctype html>
        <html>
            <head>
                <meta charset=\"utf-8\" />
                <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
                <title>Nexus API Playground</title>
            </head>
            <body style=\"font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 20px;\">
                <h1>Nexus API Playground</h1>
                <p>Run quick requests against chat, agent, and autonomy endpoints from one page.</p>
                <label>Base URL <input id=\"base\" value=\"\" placeholder=\"leave blank for same origin\" style=\"width: 420px\"></label>
                <label style=\"margin-left: 8px\">Bearer token <input id=\"token\" placeholder=\"optional\" style=\"width: 340px\"></label>
                <div style=\"margin-top: 12px;\">
                    <button onclick=\"runModels()\">GET /v1/models</button>
                    <button onclick=\"runChat()\">POST /v1/chat/completions</button>
                    <button onclick=\"runAgent()\">POST /v1/agent</button>
                    <button onclick=\"runPlan()\">POST /v1/autonomy/plan</button>
                </div>
                <h3>Request</h3>
                <textarea id=\"req\" style=\"width: 100%; height: 190px;\">{
    \"model\": \"nexus-ai/auto\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Say hello in one sentence.\"}],
    \"stream\": false
}</textarea>
                <h3>Response</h3>
                <pre id=\"out\" style=\"background:#111;color:#d8f2c2;padding:12px;overflow:auto;min-height:180px;\"></pre>
                <script>
                    const out = document.getElementById('out');
                    const reqEl = document.getElementById('req');
                    const baseEl = document.getElementById('base');
                    const tokenEl = document.getElementById('token');
                      function base() { return (baseEl.value || '').trim().replace(/\\/$/, ''); }
                    function headers() {
                        const h = {'Content-Type':'application/json'};
                        const t = (tokenEl.value || '').trim();
                        if (t) h.Authorization = `Bearer ${t}`;
                        return h;
                    }
                    async function run(method, path, body) {
                        const url = `${base()}${path}`;
                        try {
                            const res = await fetch(url, {
                                method,
                                headers: headers(),
                                body: body ? JSON.stringify(body) : undefined,
                            });
                            const text = await res.text();
                            let parsed;
                            try { parsed = JSON.parse(text); } catch (_) { parsed = text; }
                            out.textContent = JSON.stringify({status: res.status, path, body: parsed}, null, 2);
                        } catch (e) {
                            out.textContent = String(e);
                        }
                    }
                    function parseRequest() {
                        try { return JSON.parse(reqEl.value || '{}'); }
                        catch (e) { out.textContent = `Invalid JSON: ${e}`; return null; }
                    }
                    async function runModels() { await run('GET', '/v1/models'); }
                    async function runChat() {
                        const body = parseRequest(); if (!body) return;
                        await run('POST', '/v1/chat/completions', body);
                    }
                    async function runAgent() {
                        const body = { task: 'Summarize this repository architecture in 3 bullets.', history: [] };
                        await run('POST', '/v1/agent', body);
                    }
                    async function runPlan() {
                        const body = { goal: 'Plan a safe production rollout with checkpoints.', max_subtasks: 6 };
                        await run('POST', '/v1/autonomy/plan', body);
                    }
                </script>
            </body>
        </html>
        """
        return HTMLResponse(html)


def _dev_sandbox_enabled() -> bool:
        return os.getenv("NEXUS_DEV_SANDBOX", "0").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/dev/sandbox/status")
def dev_sandbox_status():
        return {
                "enabled": _dev_sandbox_enabled(),
                "mode": "mock-llm",
                "notes": "Set NEXUS_DEV_SANDBOX=1 to enable deterministic mock responses for test environments.",
        }


@router.post("/dev/sandbox/chat")
async def dev_sandbox_chat(request: Request):
        if not _dev_sandbox_enabled():
                return _api_error("developer sandbox is disabled", "feature_disabled", 403)
        body = await _read_json_body(request)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
                return _api_error("prompt is required", "validation_error", 422)

        lower_prompt = prompt.lower()
        if "json" in lower_prompt:
                content = {"sandbox": True, "echo": prompt[:200], "status": "ok"}
        elif "risk" in lower_prompt or "safety" in lower_prompt:
                content = "Sandbox response: risk identified, recommend HITL approval before high-impact actions."
        else:
                content = f"Sandbox response: {prompt[:240]}"

        return {
                "id": f"sandbox-{secrets.token_hex(6)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "nexus-sandbox/mock-llm",
                "choices": [
                        {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                        }
                ],
                "usage": {
                        "prompt_tokens": max(1, len(prompt.split())),
                        "completion_tokens": max(1, len(str(content).split())),
                        "total_tokens": max(2, len(prompt.split()) + len(str(content).split())),
                },
                "sandbox": True,
        }


@router.get("/graphql")
def graphql_help():
    return {
        "endpoint": "/graphql",
        "method": "POST",
        "body": {"query": "{ health models providers usage }"},
        "notes": [
            "Supported root fields: health, models, providers, usage",
            "usage requires admin role in multi-user mode",
        ],
    }


def _extract_graphql_fields(query: str) -> set[str]:
    import re

    allowed = {"health", "models", "providers", "usage"}
    tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", str(query or "")))
    return {token for token in tokens if token in allowed}


@router.post("/graphql")
async def graphql_query(request: Request):
    body = await _read_json_body(request)
    query = str(body.get("query") or "").strip()
    if not query:
        return JSONResponse({"errors": [{"message": "query is required"}]}, status_code=400)

    wanted = _extract_graphql_fields(query)
    if not wanted:
        return JSONResponse(
            {"errors": [{"message": "No supported fields requested (health, models, providers, usage)"}]},
            status_code=400,
        )

    data: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    if "health" in wanted:
        data["health"] = {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "v1",
        }
    if "models" in wanted:
        data["models"] = _v1_models_catalog()
    if "providers" in wanted:
        data["providers"] = get_provider_health()
    if "usage" in wanted:
        try:
            require_admin(request)
            data["usage"] = {
                "summary": get_usage_stats(7),
                "daily": get_usage_daily(7),
            }
        except HTTPException:
            errors.append({"message": "usage field requires admin role"})

    payload: dict[str, Any] = {"data": data}
    if errors:
        payload["errors"] = errors
    return payload


# ── Webhook trigger ─────────────────────────────────────────────────────────────
# POST /webhook/trigger  { "task": "fix the login bug", "repo": "owner/repo" }
# Runs the agent asynchronously and streams back SSE or returns a run_id for polling.
# Optional header: X-Webhook-Secret: <secret>  (validated against WEBHOOK_SECRET env var)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "")


def _webhook_allowed_events() -> set[str]:
    raw = os.getenv("WEBHOOK_ALLOWED_EVENTS", "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _safe_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))

@router.post("/webhook/trigger")
async def webhook_trigger(request: Request):
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    secret = request.headers.get("x-webhook-secret", "")
    if WEBHOOK_SECRET and not hmac.compare_digest(secret, WEBHOOK_SECRET):
        return JSONResponse({"error": "invalid webhook secret"}, status_code=403)

    if WEBHOOK_HMAC_SECRET:
        signature_header = request.headers.get("x-webhook-signature-256", "").strip()
        if not signature_header.startswith("sha256="):
            return JSONResponse({"error": "missing or invalid webhook signature"}, status_code=403)
        provided_sig = signature_header.split("=", 1)[1].strip().lower()
        expected_sig = hmac.new(
            WEBHOOK_HMAC_SECRET.encode("utf-8"),
            raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_sig, expected_sig):
            # Compatibility fallback for senders that sign canonicalized JSON.
            canonical_body = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            canonical_sig = hmac.new(
                WEBHOOK_HMAC_SECRET.encode("utf-8"),
                canonical_body,
                digestmod=hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(provided_sig, canonical_sig):
                return JSONResponse({"error": "invalid webhook signature"}, status_code=403)

    task = body.get("task", "")
    if not task:
        return JSONResponse({"error": "task field is required"}, status_code=400)
    try:
        task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)

    event_type = str(body.get("event_type") or request.headers.get("x-webhook-event") or "generic").strip().lower()
    allowed_events = _webhook_allowed_events()
    if allowed_events and event_type not in allowed_events:
        return JSONResponse(
            {
                "accepted": False,
                "ignored": True,
                "reason": "event_type_not_allowed",
                "event_type": event_type,
                "allowed_events": sorted(allowed_events),
            },
            status_code=202,
        )

    max_retries_default = _safe_int(os.getenv("WEBHOOK_MAX_RETRIES", "2"), default=2, min_value=0, max_value=5)
    max_retries = _safe_int(body.get("max_retries", max_retries_default), default=max_retries_default, min_value=0, max_value=5)
    backoff_secs_default = _safe_int(os.getenv("WEBHOOK_RETRY_BACKOFF_SECONDS", "1"), default=1, min_value=1, max_value=60)
    retry_backoff_secs = _safe_int(body.get("retry_backoff_secs", backoff_secs_default), default=backoff_secs_default, min_value=1, max_value=60)

    repo = body.get("repo", "")
    run_id = "run_" + secrets.token_hex(8)
    run_results[run_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "event_type": event_type,
        "repo": repo,
        "attempt": 0,
        "max_retries": max_retries,
        "retry_backoff_secs": retry_backoff_secs,
        "errors": [],
    }

    def _run():
        attempt = 0
        errors = []
        try:
            while True:
                try:
                    attempt += 1
                    run_results[run_id]["status"] = "running" if attempt == 1 else "retrying"
                    run_results[run_id]["attempt"] = attempt
                    from ..agent import run_agent_task
                    result = run_agent_task(task, [], sid=run_id)
                    run_results[run_id] = {
                        "status": "done",
                        "result": result,
                        "error": None,
                        "event_type": event_type,
                        "repo": repo,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "retry_backoff_secs": retry_backoff_secs,
                        "errors": errors,
                    }
                    break
                except Exception as e:
                    err = str(e)
                    errors.append(err)
                    if attempt > max_retries:
                        run_results[run_id] = {
                            "status": "error",
                            "result": None,
                            "error": err,
                            "event_type": event_type,
                            "repo": repo,
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "retry_backoff_secs": retry_backoff_secs,
                            "errors": errors,
                        }
                        break
                    delay = retry_backoff_secs * (2 ** (attempt - 1))
                    run_results[run_id]["next_retry_in_secs"] = delay
                    time.sleep(delay)
        except Exception as e:
            run_results[run_id] = {
                "status": "error",
                "result": None,
                "error": str(e),
                "event_type": event_type,
                "repo": repo,
                "attempt": attempt,
                "max_retries": max_retries,
                "retry_backoff_secs": retry_backoff_secs,
                "errors": errors,
            }

    threading.Thread(target=_run, daemon=True).start()
    return {
        "run_id": run_id,
        "status": "https://github.com/The-No-Hands-company/Nexus-AI#webhook-triggers",
        "event_type": event_type,
        "max_retries": max_retries,
        "retry_backoff_secs": retry_backoff_secs,
    }

@router.get("/webhook/status/{run_id}")
async def webhook_status(run_id: str):
    result = run_results.get(run_id)
    if not result: return JSONResponse({"error": "run_id not found"}, status_code=404)
    return result


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


def _is_truthy_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _is_safe_callback_url(url: str) -> bool:
    try:
        parsed = _urlparse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost"}


def _start_integration_run(
    task: str,
    source: str,
    metadata: dict | None = None,
    callback=None,
) -> str:
    run_id = "ext_" + secrets.token_hex(8)
    run_results[run_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "source": source,
        "metadata": dict(metadata or {}),
    }

    def _run() -> None:
        status_payload = run_results.get(run_id, {})
        try:
            result = run_agent_task(task, [], sid=run_id)
            status_payload = {
                "status": "done",
                "result": result,
                "error": None,
                "source": source,
                "metadata": dict(metadata or {}),
            }
        except Exception as exc:
            status_payload = {
                "status": "error",
                "result": None,
                "error": str(exc),
                "source": source,
                "metadata": dict(metadata or {}),
            }
        run_results[run_id] = status_payload
        if callback:
            try:
                callback(run_id, status_payload)
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return run_id


def _slack_verify_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    if not secret:
        return True
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except Exception:
        return False
    if abs(int(time.time()) - ts) > 60 * 5:
        return False
    base = f"v0:{timestamp}:{raw_body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _github_verify_signature(raw_body: bytes, signature_header: str) -> bool:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
    if not secret:
        return True
    sig = (signature_header or "").strip().lower()
    if not sig.startswith("sha256="):
        return False
    provided = sig.split("=", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _slack_send_message(channel: str, text: str, thread_ts: str = "") -> dict:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token or not channel:
        return {"ok": False, "error": "slack_not_configured"}
    payload = {"channel": channel, "text": text[:3900]}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    resp = _http_json_request(
        "POST",
        "https://slack.com/api/chat.postMessage",
        payload=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    api_ok = bool(resp.get("json", {}).get("ok"))
    return {"ok": api_ok and resp.get("ok", False), "status": resp.get("status", 0), "raw": resp}


def _discord_send_message(channel_id: str, content: str) -> dict:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token or not channel_id:
        return {"ok": False, "error": "discord_not_configured"}
    resp = _http_json_request(
        "POST",
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        payload={"content": content[:1800]},
        headers={"Authorization": f"Bot {token}"},
        timeout=15,
    )
    return {"ok": bool(resp.get("ok")), "status": resp.get("status", 0), "raw": resp}


def _extract_result_text(payload: dict) -> str:
    if payload.get("status") != "done":
        return f"Nexus run failed: {payload.get('error') or 'unknown error'}"
    result = payload.get("result")
    if isinstance(result, dict):
        text = result.get("result") or result.get("content") or json.dumps(result, ensure_ascii=False)
        return str(text)[:3900]
    return str(result)[:3900]


@router.post("/integrations/slack/events")
async def integrations_slack_events(request: Request):
    raw_body = await request.body()
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not _slack_verify_signature(raw_body, timestamp, signature):
        return _api_error("invalid slack signature", "unauthorized", 403)

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)
    if not isinstance(body, dict):
        return _api_error("invalid JSON body", "validation_error", 400)

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    event = body.get("event") if isinstance(body.get("event"), dict) else {}
    if body.get("type") != "event_callback" or event.get("type") != "message" or event.get("bot_id"):
        return {"accepted": True, "ignored": True}

    text = str(event.get("text") or "").strip()
    if not text:
        return {"accepted": True, "ignored": True, "reason": "empty_message"}
    channel = str(event.get("channel") or "").strip()
    thread_ts = str(event.get("thread_ts") or event.get("ts") or "").strip()

    def _callback(_run_id: str, result_payload: dict) -> None:
        response_text = _extract_result_text(result_payload)
        _slack_send_message(channel, response_text, thread_ts=thread_ts)

    run_id = _start_integration_run(
        task=text,
        source="slack",
        metadata={"channel": channel, "thread_ts": thread_ts},
        callback=_callback,
    )
    return {"accepted": True, "run_id": run_id}


@router.post("/integrations/discord/messages")
async def integrations_discord_messages(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    expected_secret = os.getenv("DISCORD_INBOUND_SECRET", "").strip()
    provided_secret = request.headers.get("x-discord-secret", "")
    if expected_secret and not hmac.compare_digest(expected_secret, provided_secret):
        return _api_error("invalid discord secret", "unauthorized", 403)

    if bool(body.get("author_bot", False)):
        return {"accepted": True, "ignored": True}

    text = str(body.get("task") or body.get("content") or "").strip()
    if not text:
        return _api_error("content or task is required", "validation_error", 422)
    channel_id = str(body.get("channel_id") or "").strip()

    def _callback(_run_id: str, result_payload: dict) -> None:
        response_text = _extract_result_text(result_payload)
        _discord_send_message(channel_id, response_text)

    run_id = _start_integration_run(
        task=text,
        source="discord",
        metadata={"channel_id": channel_id, "author_id": str(body.get("author_id") or "")},
        callback=_callback,
    )
    return {"accepted": True, "run_id": run_id}


@router.post("/integrations/github-actions/event")
async def integrations_github_actions_event(request: Request):
    raw_body = await request.body()
    if not _github_verify_signature(raw_body, request.headers.get("x-hub-signature-256", "")):
        return _api_error("invalid github signature", "unauthorized", 403)

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)
    if not isinstance(body, dict):
        return _api_error("invalid JSON body", "validation_error", 400)

    event_name = str(request.headers.get("x-github-event") or body.get("event") or "").strip().lower()
    if event_name not in {"push", "pull_request"}:
        return {"accepted": False, "ignored": True, "reason": "event_not_supported", "event": event_name}

    override_task = str(body.get("task") or "").strip()
    task = override_task
    if not task:
        repo_name = str((body.get("repository") or {}).get("full_name") or "unknown/repo")
        if event_name == "push":
            ref = str(body.get("ref") or "")
            head_commit = body.get("head_commit") if isinstance(body.get("head_commit"), dict) else {}
            message = str(head_commit.get("message") or "").strip()
            task = f"GitHub push event for {repo_name} on {ref}. Summarize impact and propose next action. Commit message: {message}"
        else:
            pr = body.get("pull_request") if isinstance(body.get("pull_request"), dict) else {}
            title = str(pr.get("title") or "")
            draft = bool(pr.get("draft", False))
            action = str(body.get("action") or "updated")
            task = f"GitHub pull_request event ({action}) for {repo_name}. Title: {title}. Draft={draft}. Provide review guidance."

    run_id = _start_integration_run(
        task=task,
        source="github_actions",
        metadata={"event": event_name},
    )
    return {"accepted": True, "run_id": run_id, "event": event_name}


@router.post("/integrations/automation/webhook")
async def integrations_automation_webhook(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    expected_secret = os.getenv("AUTOMATION_WEBHOOK_SECRET", "").strip()
    provided_secret = request.headers.get("x-automation-secret", "")
    if expected_secret and not hmac.compare_digest(expected_secret, provided_secret):
        return _api_error("invalid automation secret", "unauthorized", 403)

    task = str(body.get("task") or body.get("prompt") or body.get("text") or "").strip()
    if not task:
        return _api_error("task, prompt, or text is required", "validation_error", 422)

    callback_url = str(body.get("callback_url") or "").strip()
    callback_bearer = str(body.get("callback_bearer") or "").strip()
    if callback_url and not _is_safe_callback_url(callback_url):
        return _api_error("callback_url must be https or localhost http", "validation_error", 422)

    def _callback(run_id: str, result_payload: dict) -> None:
        if not callback_url:
            return
        headers = {}
        if callback_bearer:
            headers["Authorization"] = f"Bearer {callback_bearer}"
        _http_json_request(
            "POST",
            callback_url,
            payload={
                "run_id": run_id,
                "status": result_payload.get("status"),
                "error": result_payload.get("error"),
                "result": result_payload.get("result"),
                "source": "automation_webhook",
            },
            headers=headers,
            timeout=20,
        )

    run_id = _start_integration_run(
        task=task,
        source="automation_webhook",
        metadata={"has_callback": bool(callback_url)},
        callback=_callback if callback_url else None,
    )
    return {"accepted": True, "run_id": run_id}


@router.get("/integrations/channels/status")
def integrations_channels_status():
    return {
        "slack": {
            "inbound_signature": bool(os.getenv("SLACK_SIGNING_SECRET", "").strip()),
            "outbound_bot_token": bool(os.getenv("SLACK_BOT_TOKEN", "").strip()),
        },
        "discord": {
            "inbound_secret": bool(os.getenv("DISCORD_INBOUND_SECRET", "").strip()),
            "outbound_bot_token": bool(os.getenv("DISCORD_BOT_TOKEN", "").strip()),
        },
        "github_actions": {
            "webhook_signature": bool(os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()),
        },
        "automation": {
            "webhook_secret": bool(os.getenv("AUTOMATION_WEBHOOK_SECRET", "").strip()),
        },
    }


def _load_mcp_tools_from_env() -> list[dict]:
    raw = os.getenv("MCP_TOOLS", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    tools = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url:
            continue
        method = str(item.get("method") or "POST").strip().upper()
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        timeout_s = _safe_int(item.get("timeout_s", 15), default=15, min_value=1, max_value=60)
        tools.append(
            {
                "name": name,
                "url": url,
                "method": method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "POST",
                "headers": {str(k): str(v) for k, v in headers.items()},
                "timeout_s": timeout_s,
            }
        )
    return tools


def _call_mcp_tool(name: str, args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    tools = _load_mcp_tools_from_env()
    selected = next((t for t in tools if t.get("name") == name), None)
    if not selected:
        return {"ok": False, "error": "mcp_tool_not_found", "available": [t.get("name") for t in tools]}

    method = selected.get("method", "POST")
    url = selected.get("url", "")
    payload = None
    if method == "GET" and args:
        query = _urlparse.urlencode({k: str(v) for k, v in args.items()})
        url = url + ("&" if "?" in url else "?") + query
    elif args:
        payload = {"arguments": args}

    resp = _http_json_request(
        method=method,
        url=url,
        payload=payload,
        headers=selected.get("headers") or {},
        timeout=int(selected.get("timeout_s", 15)),
    )
    return {
        "ok": bool(resp.get("ok")),
        "status": resp.get("status", 0),
        "tool": name,
        "response": resp.get("json") if resp.get("json") else resp.get("text"),
    }


def _mcp_server_allowed_tools() -> set[str]:
    from ..tools_builtin import list_tool_schemas

    raw = os.getenv("MCP_SERVER_ALLOWED_TOOLS", "").strip()
    all_tools = set(list_tool_schemas().keys())
    high_risk = {
        "run_command",
        "write_file",
        "delete_file",
        "commit_push",
        "create_repo",
        "git_checkout",
        "git_pull",
    }
    if raw:
        return {part.strip() for part in raw.split(",") if part.strip()}
    if _is_truthy_env("MCP_SERVER_ALLOW_HIGH_RISK", default=False):
        return all_tools
    return all_tools - high_risk


def _mcp_jsonrpc_success(req_id, result: dict):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _mcp_jsonrpc_error(req_id, code: int, message: str, data=None):
    payload = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


@router.get("/mcp/server/status")
def mcp_server_status():
    return {
        "enabled": _is_truthy_env("MCP_SERVER_MODE", default=False),
        "allow_high_risk": _is_truthy_env("MCP_SERVER_ALLOW_HIGH_RISK", default=False),
        "allowed_tools": sorted(_mcp_server_allowed_tools()),
    }


@router.post("/mcp/server")
async def mcp_server_rpc(request: Request):
    if not _is_truthy_env("MCP_SERVER_MODE", default=False):
        return _api_error("MCP server mode is disabled", "not_found", 404)

    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _mcp_jsonrpc_error(None, -32700, str(exc.detail))

    req_id = body.get("id")
    method = str(body.get("method") or "").strip()
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    from ..tools_builtin import dispatch_builtin, list_tool_schemas, validate_tool_args

    if method == "tools/list":
        schemas = list_tool_schemas()
        allowed = _mcp_server_allowed_tools()
        tools = []
        for name, schema in schemas.items():
            if name not in allowed:
                continue
            tools.append(
                {
                    "name": name,
                    "description": str(schema.get("description") or ""),
                    "inputSchema": dict(schema),
                }
            )
        return _mcp_jsonrpc_success(req_id, {"tools": tools})

    if method == "tools/call":
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not name:
            return _mcp_jsonrpc_error(req_id, -32602, "tool name is required")
        if name not in _mcp_server_allowed_tools():
            return _mcp_jsonrpc_error(req_id, -32001, "tool is not allowed", {"tool": name})

        action = {"action": name, **arguments}
        arg_err = validate_tool_args(action)
        if arg_err:
            return _mcp_jsonrpc_error(req_id, -32602, arg_err)

        trace = dispatch_builtin(action, session_id=f"mcp_{req_id or 'call'}")
        if not trace:
            return _mcp_jsonrpc_error(req_id, -32601, "unknown tool")

        return _mcp_jsonrpc_success(
            req_id,
            {
                "content": [{"type": "text", "text": str(trace.get("result", ""))}],
                "metadata": trace.get("metadata", {}),
                "status": trace.get("status", "done"),
            },
        )

    return _mcp_jsonrpc_error(req_id, -32601, "method not found")


@router.get("/mcp/tools")
def mcp_tools_list():
    tools = _load_mcp_tools_from_env()
    return {
        "tools": [
            {
                "name": t.get("name"),
                "url": t.get("url"),
                "method": t.get("method"),
                "timeout_s": t.get("timeout_s"),
            }
            for t in tools
        ],
        "count": len(tools),
    }


@router.post("/mcp/tools/call")
async def mcp_tools_call(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    name = str(body.get("name") or "").strip()
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    if not name:
        return _api_error("name is required", "validation_error", 422)

    result = _call_mcp_tool(name, args)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404 if result.get("error") == "mcp_tool_not_found" else 502)
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
    from ..agent import PROVIDER_CAPABILITIES

    data = []
    for provider in get_providers_list():
        pid = str(provider.get("id") or "")
        caps = dict(PROVIDER_CAPABILITIES.get(pid, {}))
        item = {
            "id": str(provider.get("model") or pid),
            "provider": pid,
            "label": provider.get("label", pid),
            "capabilities": caps,
            "tools": bool(caps.get("tools", False)),
            "json_mode": bool(caps.get("json_mode", False)),
            "reasoning": bool(caps.get("reasoning", False)),
            "vision": bool(caps.get("vision", False)),
            "embeddings": bool(caps.get("embeddings", provider.get("openai_compat", False))),
            "streaming": bool(caps.get("streaming", False)),
        }
        data.append(item)
    return {"object": "list", "data": data}


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
    return _v1_error(
        f"Model not found: {model_id}",
        err_type="not_found_error",
        status_code=404,
        code="model_not_found",
    )


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


@router.post("/safety/prompt-injection/benchmark")
async def prompt_injection_benchmark(request: Request):
    from ..safety.prompt_injection import benchmark_injection_detection

    data = await _read_json_body(request, "invalid JSON body")
    corpus_in = data.get("corpus") if isinstance(data.get("corpus"), list) else []
    corpus = tuple(str(item or "").strip() for item in corpus_in if str(item or "").strip())
    result = benchmark_injection_detection(corpus=corpus if corpus else None)
    return {
        "benchmark": result,
        "release_gate_pass": bool(float(result.get("coverage") or 0.0) >= 0.9),
        "threshold": 0.9,
    }


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
        job = schedule_job(
            name=name,
            task=task,
            schedule=schedule,
            max_retries=int(body.get("max_retries", 0)),
            retry_backoff_secs=int(body.get("retry_backoff_secs", 60)),
        )
        return {"job": job_to_dict(job)}
    except Exception as exc:
        return _api_error(f"Failed to create job: {exc}", "validation_error", 422)


@router.post("/scheduler/jobs/{job_id}/cancel")
def scheduler_cancel_job(job_id: str):
    if cancel_job(job_id):
        return {"ok": True, "job_id": job_id}
    return _api_error("job not found", "not_found", 404)


@router.get("/scheduler/jobs/{job_id}/history")
def scheduler_job_history(job_id: str, limit: int = 50):
    """Return past execution records for a scheduled job."""
    job = next((j for j in list_jobs() if j.id == job_id), None)
    if job is None:
        return _api_error("job not found", "not_found", 404)
    history = getattr(job, "history", [])
    return {
        "job_id": job_id,
        "job_name": getattr(job, "name", job_id),
        "history": list(history[-max(1, min(int(limit), 500)):]),
        "total": len(history),
    }


@router.post("/scheduler/webhook/{job_id}")
async def scheduler_webhook_trigger(job_id: str, request: Request):
    """Immediately trigger a scheduled job via webhook."""
    try:
        body = await _read_json_body(request)
    except HTTPException:
        body = {}
    job = next((j for j in list_jobs() if j.id == job_id), None)
    if job is None:
        return _api_error("job not found", "not_found", 404)
    try:
        from ..scheduler import run_job_now
        result = run_job_now(job_id)
        return {"ok": True, "job_id": job_id, "result": str(result)[:200]}
    except Exception as exc:
        return _api_error(str(exc), "server_error", 500)


@router.post("/safety/action-check")
async def safety_action_check(request: Request):
    """
    Check whether a proposed tool/agent action is permitted by the safety policy.
    Body: { "kind": "run_command", "parameters": {...}, "policy_profile": "standard" }
    """
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    action_kind = str(data.get("kind") or "").strip()
    parameters = data.get("parameters") or {}
    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard"))
    if not action_kind:
        return _api_error("kind is required", "validation_error", 422)
    try:
        action_payload = {"kind": action_kind, **parameters}
        verdict = screen_tool_action(action_payload, policy_profile=profile)
        return {
            "action": action_kind,
            "allowed": verdict.allowed,
            "policy_profile": profile,
            "issues": [i.to_dict() for i in verdict.issues],
            "threat": (verdict.issues[0].threat if verdict.issues else "none"),
        }
    except Exception as exc:
        return _api_error(str(exc), "server_error", 500)


@router.get("/safety/domain-guards")
def safety_domain_guards_get():
    """Return the current domain-guard rules (allowed/blocked domains, categories)."""
    rules = _config.get("domain_guards") or {
        "blocked_domains": [],
        "allowed_categories": ["informational", "productivity"],
        "block_adult": True,
        "block_malware": True,
    }
    return {"domain_guards": rules}


@router.post("/settings/domain-guards")
async def safety_domain_guards_update(request: Request):
    """Update domain-guard policy rules."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    if not isinstance(body, dict):
        return _api_error("body must be a JSON object", "validation_error", 422)
    # Validate allowed keys only
    valid_keys = {"blocked_domains", "allowed_categories", "block_adult", "block_malware"}
    unknown = set(body.keys()) - valid_keys
    if unknown:
        return _api_error(f"Unknown fields: {sorted(unknown)}", "validation_error", 422)
    existing = _config.get("domain_guards") or {}
    existing.update(body)
    _config["domain_guards"] = existing
    return {"ok": True, "domain_guards": existing}


@router.get("/admin/tool-audit")
def tool_audit_log(limit: int = 100, kind: str = "", session_id: str = ""):
    """Return the tool-call audit log. Supports filtering by kind and session_id."""
    from ..tools_builtin import get_tool_audit_log
    try:
        records = get_tool_audit_log(
            limit=max(1, min(int(limit), 1000)),
            kind=kind.strip() or None,
            session_id=session_id.strip() or None,
        )
        return {"records": records, "total": len(records)}
    except Exception as exc:
        return _api_error(str(exc), "server_error", 500)


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

        backend_name = str(body.get("backend") or "auto")
        video_bytes = generate_video(
            prompt=prompt,
            duration_seconds=float(body.get("duration_seconds") or 4.0),
            fps=int(body.get("fps") or 8),
            width=int(body.get("width") or 512),
            height=int(body.get("height") or 512),
            backend=backend_name,
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)
    except Exception as exc:
        return _api_error(str(exc), "generation_error", 500)

    return {
        "mime_type": "video/mp4",
        "backend": backend_name,
        "model": "sd3" if "sd3" in backend_name else "flux",
        "duration_seconds": float(body.get("duration_seconds") or 4.0),
        "video_b64": base64.b64encode(video_bytes).decode("ascii"),
    }


@router.post("/generation/video/stream")
async def generation_video_stream(request: Request):
    """Generate video with realtime SSE progress events and final payload."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _api_error("prompt is required", "validation_error", 422)

    duration_seconds = float(body.get("duration_seconds") or 4.0)
    fps = int(body.get("fps") or 8)
    width = int(body.get("width") or 512)
    height = int(body.get("height") or 512)
    backend_name = str(body.get("backend") or "auto")

    from ..generation import generate_video_stream as _generate_video_stream

    async def _gen():
        for event in _generate_video_stream(
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            width=width,
            height=height,
            backend=backend_name,
            include_frame_payload=False,
        ):
            payload = dict(event)
            if payload.get("type") == "done" and payload.get("video_bytes"):
                payload["video_b64"] = base64.b64encode(bytes(payload.pop("video_bytes"))).decode("ascii")
            yield f"data: {json.dumps(payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.get("/collab/rooms/{room_id}/events")
def collab_room_events(room_id: str, limit: int = 100):
    from ..collab import get_room_events
    events = get_room_events(room_id=room_id, limit=limit)
    return {"events": events, "count": len(events)}


@router.post("/collab/rooms/reload")
def collab_reload_rooms_cache():
    from ..collab import reload_rooms_from_store
    loaded = reload_rooms_from_store()
    return {"ok": True, "loaded": loaded}


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


@router.post("/validation/program/run")
async def validation_program_run(request: Request):
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    try:
        from ..validation_program import run_validation_program

        return run_validation_program(
            domains=body.get("domains") if isinstance(body.get("domains"), list) else None,
            update_baseline=bool(body.get("update_baseline", False)),
            alert_on_regression=bool(body.get("alert_on_regression", True)),
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/validation/program/reports")
def validation_program_reports(program: str = "core_quality", limit: int = 20):
    from ..validation_program import get_validation_overview

    return get_validation_overview(program=program, limit=limit)


@router.get("/validation/program/baselines")
def validation_program_baselines():
    from ..db import load_validation_baselines

    return {"baselines": load_validation_baselines()}


@router.post("/validation/program/baselines")
async def validation_program_update_baselines(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    from ..db import save_validation_baselines
    from ..validation_program import run_validation_program

    if isinstance(body.get("baselines"), dict):
        saved = save_validation_baselines(body.get("baselines") or {})
        return {"ok": True, "baselines": saved, "mode": "direct"}

    report = run_validation_program(
        domains=body.get("domains") if isinstance(body.get("domains"), list) else None,
        update_baseline=True,
        alert_on_regression=bool(body.get("alert_on_regression", False)),
    )
    return {"ok": True, "mode": "recomputed", "report": report, "baselines": report.get("baselines", {})}


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
    _has_vision = isinstance(raw_task, list) and any(
        p.get("type") == "image_url" for p in raw_task if isinstance(p, dict)
    )
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

        # Vision fast-path for streaming: call LLM synchronously in a thread
        # (vision providers don't stream delta chunks) and emit a single chunk.
        if _has_vision:
            _raw_msgs_s = []
            for _m in turns:
                if isinstance(_m.content, list):
                    _raw_msgs_s.append({"role": _m.role, "content": _m.content})
                else:
                    _raw_msgs_s.append({"role": _m.role, "content": str(_m.content)})
            if system_parts:
                _raw_msgs_s.insert(0, {"role": "system", "content": " ".join(system_parts)})

            async def _vision_stream():
                try:
                    _vr, _vp = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: call_llm_with_fallback(_raw_msgs_s, task="vision")
                    )
                    _vc = _vr.get("content", str(_vr))
                except Exception as _exc:
                    _vc = f"Vision error: {_exc}"
                _chunk = {
                    "id": cid, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": _vc}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_vision_stream(), media_type="text/event-stream",
                                      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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

    # ── Vision fast-path: bypass agent loop and call the LLM directly ─────────
    # When the request contains image_url content parts we need to preserve the
    # multipart content array and route directly to a vision-capable provider,
    # rather than squashing everything into a plain text string.
    _result_provider = ""
    _result_model = ""
    if _has_vision:
        # Build the full message list with system prompt prepended.
        _raw_msgs = []
        for m in turns:
            if isinstance(m.content, list):
                _raw_msgs.append({"role": m.role, "content": m.content})
            else:
                _raw_msgs.append({"role": m.role, "content": str(m.content)})
        if system_parts:
            _raw_msgs.insert(0, {"role": "system", "content": " ".join(system_parts)})
        try:
            _vision_resp, _vision_pid = call_llm_with_fallback(_raw_msgs, task="vision")
            output = _vision_resp.get("content", str(_vision_resp))
            _result_provider = _vision_pid
        except Exception as exc:
            return _v1_error(str(exc), "vision_error", 500, "vision_error")
    else:
        result = run_agent_task(task, history, [], sid=sid)
        output = result.get("result", "")
        _result_provider = result.get("provider", "")
        _result_model = result.get("model", "")
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
        "_nexus": {"provider": _result_provider, "model": _result_model},
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
async def switch_persona(persona_id: str, request: Request):
    # Route order means POST /personas/custom can match this path first.
    # Support custom persona creation here to preserve the public contract.
    if persona_id == "custom":
        data = await request.json()
        pid = data.get("id") or str(uuid.uuid4())
        db_save_persona(
            pid,
            data.get("name", "Custom"),
            data.get("icon", "🤖"),
            data.get("description", ""),
            data.get("prompt_prefix", ""),
            data.get("color", "#7c6af7"),
            float(data.get("temperature", 0.2)),
            data.get("tier", "medium"),
        )
        return {"id": pid}

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
                           safety_profile=data.get("safety_profile"),
                           strict_mode_profile=data.get("strict_mode_profile"),
                           strict_no_guess_mode=data.get("strict_no_guess_mode"),
                           strict_confidence_threshold=data.get("strict_confidence_threshold"),
                           strict_evidence_threshold=data.get("strict_evidence_threshold"))
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
    from ..db import verify_safety_audit_entries
    integrity = {"ok": None, "checked": 0, "broken_at": None, "head_hash": None}
    if not (session_id or event_type or severity):
        integrity = verify_safety_audit_entries(limit=5000)
    return {
        "events": events,
        "total": len(events_with_severity),
        "session_id": session_id or None,
        "event_type": event_type or None,
        "severity": severity or None,
        "filtered": bool(session_id or event_type or severity),
        "integrity": integrity,
    }

@router.get("/personas/legacy")
def list_personas_legacy():
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


@router.get("/memory/episodic")
def get_episodic_mem(limit: int = 100):
    return {"events": get_episodic_memory(limit=limit), "count": len(get_episodic_memory(limit=limit))}


@router.get("/memory/export")
def memory_export(limit: int = 1000):
    return export_memory_bundle(limit=limit)


@router.post("/memory/import")
async def memory_import(request: Request):
    data = await request.json()
    result = import_memory_bundle(data if isinstance(data, dict) else {}, source="api_import")
    return {"ok": True, **result}


# ── Benchmark endpoints ────────────────────────────────────────────────────────
_BENCHMARK_PROBES = [
    ("arithmetic",  "What is 17 * 23?"),
    ("reasoning",   "If all roses are flowers and some flowers fade quickly, can we conclude that some roses fade quickly?"),
    ("coding",      "Write a one-line Python expression to reverse a string."),
]

@router.post("/benchmark/run")
async def benchmark_run(request: Request):
    """Run a lightweight probe suite against all available providers and store results."""
    from ..benchmark import run_benchmark_probes
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    return run_benchmark_probes(requested_providers=body.get("providers") or [])


@router.get("/benchmark/results")
def benchmark_results():
    """Return stored benchmark results (most recent first)."""
    from ..db import load_benchmark_results
    return {"results": load_benchmark_results()}


@router.get("/benchmark/history")
def benchmark_history(provider: str = "", model: str = "", task_type: str = "", limit: int = 500):
    """Return benchmark history with optional provider/model/task filters."""
    from ..benchmark import get_benchmark_history
    return get_benchmark_history(provider=provider, model=model, task_type=task_type, limit=limit)


@router.get("/benchmark/leaderboard")
def benchmark_leaderboard(sort_by: str = "task_type", limit: int = 20, provider: str = ""):
    """Return ranked benchmark leaderboard entries."""
    from ..benchmark import get_benchmark_leaderboard
    return get_benchmark_leaderboard(sort_by=sort_by, limit=limit, provider=provider)


@router.get("/benchmark/tradeoff")
def benchmark_tradeoff(days: int = 14, limit: int = 2000):
    """Return per-model cost-quality-latency tradeoff aggregates for dashboard visualization."""
    from ..benchmark import get_benchmark_tradeoff
    return get_benchmark_tradeoff(days=days, limit=limit)


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
    except Exception:
        # Keep integration contracts stable even when providers are unavailable.
        fallback = f"Summary: {task}"
        return {
            "consensus": fallback,
            "provider": "offline-fallback",
            "ensemble": False,
            "unanimous": True,
            "polled": [],
            "explanation": "No provider available; returned deterministic fallback.",
        }


@router.post("/reason/graph-of-thought")
async def reason_graph_of_thought(request: Request):
    from ..thinking import build_got_prompt, parse_got_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or body.get("query") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        safe_task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
        raw_resp, provider = call_llm_with_fallback(
            [{"role": "user", "content": build_got_prompt(safe_task)}],
            safe_task,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    raw_text = raw_resp.get("content") or str(raw_resp)
    parsed = parse_got_response(raw_text)
    return {"task": safe_task, "provider": provider, **parsed, "raw_response": raw_text}


@router.post("/reason/mcts")
async def reason_mcts(request: Request):
    from ..thinking import run_mcts_planning

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    goal = (body.get("goal") or body.get("task") or "").strip()
    if not goal:
        return _api_error("goal is required", "validation_error", 422)

    iterations = max(2, min(int(body.get("iterations", 8)), 24))
    max_depth = max(1, min(int(body.get("max_depth", 4)), 8))
    branching = max(2, min(int(body.get("branching", 3)), 5))

    try:
        safe_goal = check_user_task(goal, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)

    providers_used: List[str] = []

    def _llm_fn(prompt: str) -> str:
        result, provider = call_llm_with_fallback([{"role": "user", "content": prompt}], safe_goal)
        providers_used.append(provider)
        return result.get("content") or str(result)

    try:
        outcome = run_mcts_planning(
            safe_goal,
            llm_fn=_llm_fn,
            iterations=iterations,
            max_depth=max_depth,
            branching=branching,
        )
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    return {
        "goal": safe_goal,
        "best_plan": outcome.get("best_plan", []),
        "best_score": outcome.get("best_score", 0.0),
        "best_rationale": outcome.get("best_rationale", ""),
        "tree_size": outcome.get("tree_size", 0),
        "iterations": outcome.get("iterations", iterations),
        "all_plans": outcome.get("all_plans", []),
        "providers": providers_used,
    }


@router.post("/reason/socratic")
async def reason_socratic(request: Request):
    from ..thinking import (
        build_socratic_prompt,
        parse_socratic_response,
        build_socratic_answer_prompt,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    topic = (body.get("topic") or body.get("task") or "").strip()
    if not topic:
        return _api_error("topic is required", "validation_error", 422)

    depth = max(1, min(int(body.get("depth", 3)), 6))

    try:
        safe_topic = check_user_task(topic, policy_profile=_config.get("safety_profile", "standard"))
        tree_resp, tree_provider = call_llm_with_fallback(
            [{"role": "user", "content": build_socratic_prompt(safe_topic, depth=depth)}],
            safe_topic,
        )
        question_tree = parse_socratic_response(tree_resp.get("content") or str(tree_resp))
        answer_resp, answer_provider = call_llm_with_fallback(
            [{"role": "user", "content": build_socratic_answer_prompt(safe_topic, question_tree)}],
            safe_topic,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    answer_text = answer_resp.get("content") or str(answer_resp)
    return {
        "topic": safe_topic,
        "depth": depth,
        "question_tree": question_tree,
        "answer": answer_text,
        "providers": {"question_tree": tree_provider, "answer": answer_provider},
    }


@router.post("/reason/verify")
async def reason_verify(request: Request):
    from ..thinking import build_verification_prompt, parse_verification_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    claim = (body.get("claim") or "").strip()
    steps = body.get("steps") or []
    domain = str(body.get("domain", "general") or "general")
    if not claim:
        return _api_error("claim is required", "validation_error", 422)
    if not isinstance(steps, list):
        return _api_error("steps must be an array", "validation_error", 422)

    try:
        safe_claim = check_user_task(claim, policy_profile=_config.get("safety_profile", "standard"))
        resp, provider = call_llm_with_fallback(
            [{"role": "user", "content": build_verification_prompt(safe_claim, steps, domain=domain)}],
            safe_claim,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    raw_text = resp.get("content") or str(resp)
    parsed = parse_verification_response(raw_text)
    return {
        "claim": safe_claim,
        "domain": domain,
        "provider": provider,
        **parsed,
        "raw_response": raw_text,
    }


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
    try:
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
    except Exception:
        generated_answer = f"Initial draft: {task}"
        generator_provider = "offline-fallback"
        critic_provider = "offline-fallback"
        critique_data = {
            "revised": generated_answer,
            "critique": "No provider available; returned deterministic fallback.",
            "confidence": 0.5,
        }

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
    incremental = bool(data.get("incremental", False))

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
        if incremental:
            metadata = {**metadata, "incremental": True}
        count = get_rag_system().ingest(text, metadata=metadata, doc_id_prefix=prefix)
        return {"ingested_chunks": count, "status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _rag_retrieval_confidence(results: list[dict]) -> float:
    if not results:
        return 0.0
    scores = []
    for r in results:
        try:
            score = float(r.get("score", 0.0))
        except Exception:
            score = 0.0
        scores.append(max(0.0, min(1.0, score)))
    return round(sum(scores) / max(len(scores), 1), 4)


def _build_rag_citations(results: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for idx, item in enumerate(results, start=1):
        meta = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        source = meta.get("source_url") or meta.get("source") or f"document-{idx}"
        chunk_ref = meta.get("chunk_index", meta.get("section", idx - 1))
        citations.append(
            {
                "rank": idx,
                "source": source,
                "chunk_ref": chunk_ref,
                "score": float(item.get("score", 0.0) or 0.0),
                "id": item.get("id", ""),
            }
        )
    return citations


def _rag_answer_with_critic(query: str, results: list[dict]) -> dict:
    from ..rag.critic import CriticAgent

    if not results:
        return {
            "answer": "No relevant documents were found for this query.",
            "model_confidence": 0.0,
            "retrieval_confidence": 0.0,
            "calibrated_confidence": 0.0,
            "critique": None,
        }

    context = "\n\n".join(
        f"[{i + 1}] {r.get('document', '')}"
        for i, r in enumerate(results[:5])
    )

    prompt = (
        "Answer the question using only the provided retrieval context. "
        "Cite sources inline as [1], [2], etc. If uncertain, explicitly say so.\n\n"
        f"Question: {query}\n\nContext:\n{context}"
    )

    answer_text = ""
    model_conf = 0.55
    try:
        llm_resp, _provider = call_llm_with_fallback(
            [{"role": "user", "content": prompt}],
            "rag_query",
        )
        answer_text = (llm_resp.get("content") if isinstance(llm_resp, dict) else str(llm_resp) or "").strip()
    except Exception:
        answer_text = " ".join(str(r.get("document", "")).strip() for r in results[:3])[:1200]

    retrieval_conf = _rag_retrieval_confidence(results)
    critic = CriticAgent()
    critique = critic.critique(query, answer_text, results)
    model_conf = round(max(0.0, min(1.0, float(critique.overall_score))), 4)
    calibrated = round((0.45 * retrieval_conf) + (0.55 * model_conf), 4)

    return {
        "answer": answer_text,
        "model_confidence": model_conf,
        "retrieval_confidence": retrieval_conf,
        "calibrated_confidence": calibrated,
        "critique": critique.to_dict(),
    }


@router.post("/rag/query")
async def rag_query(request: Request):
    data = await request.json()
    query = (data.get("query") or "").strip()
    top_k = data.get("top_k")
    filter_metadata = data.get("filter_metadata")
    include_answer = bool(data.get("include_answer", True))

    if not query:
        return JSONResponse({"error": "query field is required"}, status_code=400)

    try:
        results = get_rag_system().query(query, top_k=top_k, filter_metadata=filter_metadata)
        payload: dict = {
            "query": query,
            "results": results,
            "citations": _build_rag_citations(results),
            "retrieval_confidence": _rag_retrieval_confidence(results),
        }
        if include_answer:
            payload.update(_rag_answer_with_critic(query, results))
        return payload
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/rag/status")
def rag_status():
    try:
        return get_rag_system().stats()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/rag/documents")
def rag_documents(limit: int = 200, q: str = ""):
    """List ingested RAG corpus documents (with optional text search)."""
    try:
        rag = get_rag_system()
        docs = rag.vector_store.get_all_documents()
        query = (q or "").strip().lower()
        if query:
            docs = [
                d for d in docs
                if query in str(d.get("document", "")).lower()
                or query in str((d.get("metadata") or {}).get("source", "")).lower()
                or query in str((d.get("metadata") or {}).get("title", "")).lower()
            ]
        safe_limit = max(1, min(int(limit), 1000))
        docs = docs[:safe_limit]
        return {
            "count": len(docs),
            "items": [
                {
                    "id": str(item.get("id", "")),
                    "preview": str(item.get("document", ""))[:240],
                    "metadata": item.get("metadata") or {},
                }
                for item in docs
            ],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/rag/documents/{doc_id}")
def rag_delete_document(doc_id: str):
    """Delete a single document from the RAG corpus by id."""
    try:
        rag = get_rag_system()
        rag.vector_store.delete([doc_id])
        rag.vector_store.persist()
        return {"ok": True, "deleted": doc_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/rag/snapshots")
async def rag_snapshot_create(request: Request):
    data = await request.json() if request else {}
    label = (data.get("label") or "").strip() or None
    try:
        return get_rag_system().create_snapshot(label=label)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/rag/snapshots/{snapshot_id}/rollback")
def rag_snapshot_rollback(snapshot_id: str):
    try:
        return get_rag_system().rollback_snapshot(snapshot_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
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


@router.post("/agent/warmup")
async def agent_warmup(request: Request):
    """Pre-load agent context for a session to reduce first-call latency.

    POST body (optional):
      { "session_id": "my-sid", "persona": "coder" }

        Returns:
            { "warmed": bool, "cached": bool, "provider": str, "mode": str }

        Optional body fields:
            {
                "mode": "off|critical|background|full",
                "providers": ["ollama","openrouter","gemini","groq"]
            }
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    sid = str(body.get("session_id") or body.get("sid") or "")
    persona = str(body.get("persona") or "")
    mode = str(body.get("mode") or "full").strip().lower()
    if mode not in {"off", "critical", "background", "full"}:
        mode = "full"

    raw_providers = body.get("providers")
    provider_order: list[str] = []
    if isinstance(raw_providers, list):
        for item in raw_providers:
            p = str(item).strip().lower()
            if p and p not in provider_order:
                provider_order.append(p)

    if mode == "off":
        return JSONResponse({"warmed": False, "cached": False, "mode": "off", "skipped": True})

    if mode == "critical" and not provider_order:
        provider_order = ["ollama", "openrouter", "gemini", "groq"]

    if mode == "background":
        async def _bg_warmup() -> None:
            await asyncio.to_thread(
                warmup_agent,
                sid=sid,
                persona=persona,
                provider_order=provider_order or None,
                task="warmup_full",
            )

        asyncio.create_task(_bg_warmup())
        return JSONResponse({
            "warmed": False,
            "cached": False,
            "mode": "background",
            "scheduled": True,
            "providers": provider_order,
        })

    result = warmup_agent(
        sid=sid,
        persona=persona,
        provider_order=provider_order if mode == "critical" else None,
        task="warmup_critical" if mode == "critical" else "warmup_full",
    )
    result["mode"] = mode
    if provider_order:
        result["providers"] = provider_order
    return JSONResponse(result)


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
            form_fields = []
            try:
                fields = reader.get_fields() or {}
                form_fields = sorted(str(k) for k in fields.keys())
            except Exception:
                form_fields = []

            table_rows_total = 0
            for i, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                lines = [ln for ln in text.splitlines() if ln.strip()]
                table_rows = []
                for ln in lines:
                    if "  " in ln:
                        cols = [c.strip() for c in ln.split("  ") if c.strip()]
                        if len(cols) >= 2:
                            table_rows.append(" | ".join(cols))
                table_rows_total += len(table_rows)

                if table_rows:
                    text += "\n\n[Extracted Table]\n" + "\n".join(table_rows[:60])

                if text:
                    segments.append({
                        "text": text,
                        "metadata": {
                            **base_meta,
                            "page": i + 1,
                            "total_pages": total,
                            "table_rows": len(table_rows),
                            "form_fields": form_fields,
                        },
                    })
            if not segments:
                # OCR fallback for scanned PDFs if optional dependencies are available.
                try:
                    from pdf2image import convert_from_path
                    from io import BytesIO
                    from ..vision import ocr_image_bytes

                    images = convert_from_path(full, first_page=1, last_page=min(total, 5), dpi=200)
                    ocr_segments = []
                    for idx, image in enumerate(images):
                        buf = BytesIO()
                        image.save(buf, format="PNG")
                        ocr_text = (ocr_image_bytes(buf.getvalue(), mime_type="image/png") or "").strip()
                        if ocr_text:
                            ocr_segments.append({
                                "text": ocr_text,
                                "metadata": {
                                    **base_meta,
                                    "page": idx + 1,
                                    "total_pages": total,
                                    "ocr_used": True,
                                    "form_fields": form_fields,
                                },
                            })
                    if ocr_segments:
                        return ocr_segments
                except Exception:
                    pass

                return [{"text": "❌ No extractable text found (may be a scanned PDF)", "metadata": {**base_meta, "form_fields": form_fields}}]

            for seg in segments:
                seg["metadata"]["table_rows_total"] = table_rows_total
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
        extraction_meta = {
            "ocr_used": any(bool(s.get("metadata", {}).get("ocr_used")) for s in valid),
            "table_rows_total": sum(int(s.get("metadata", {}).get("table_rows", 0) or 0) for s in valid),
            "form_fields": sorted(
                {
                    field
                    for s in valid
                    for field in (s.get("metadata", {}).get("form_fields") or [])
                }
            ),
        }
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
            "extraction": extraction_meta,
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
        db_save_autonomy_trace(trace_id, autonomy_traces[trace_id])
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
    checkpoint_events: List[Dict[str, Any]] = [{"type": "autonomy_start", "goal": goal, "trace_id": trace_id}]
    _save_autonomy_checkpoint(trace_id, 0, goal, checkpoint_events)
    try:
        orchestrator = Orchestrator(_orchestrator_llm, max_parallel=2)
        result = orchestrator.execute(goal, {"strategy": strategy, "max_subtasks": max_subtasks})
        result["trace_id"] = trace_id
        try:
            from ..agent_lineage import record_lineage_edge

            previous_subtask_id = ""
            for idx, subtask in enumerate(result.get("subtasks", []), 1):
                subtask_id = str(subtask.get("id") or f"{trace_id}:subtask:{idx}")
                record_lineage_edge(
                    parent_task_id=trace_id,
                    child_task_id=subtask_id,
                    relation="spawned_by",
                    source="autonomy_execute",
                    metadata={
                        "goal": goal,
                        "strategy": strategy,
                        "subtask_name": str(subtask.get("name") or ""),
                    },
                )
                if previous_subtask_id:
                    record_lineage_edge(
                        parent_task_id=previous_subtask_id,
                        child_task_id=subtask_id,
                        relation="next",
                        source="autonomy_execute",
                        metadata={"goal": goal},
                    )
                previous_subtask_id = subtask_id
        except Exception:
            pass
        for idx, subtask in enumerate(result.get("subtasks", []), 1):
            checkpoint_events.append({"type": "subtask_done", "trace_id": trace_id, "subtask": subtask})
            _save_autonomy_checkpoint(trace_id, idx, goal, checkpoint_events)
        checkpoint_events.append(
            {
                "type": "autonomy_done",
                "trace_id": trace_id,
                "result": result.get("result", ""),
                "plan_summary": result.get("plan_summary", ""),
                "execution_time": result.get("execution_time", 0),
            }
        )
        _save_autonomy_checkpoint(trace_id, len(checkpoint_events), goal, checkpoint_events)
        autonomy_traces[trace_id] = {"type": "execution", "goal": goal, "status": "done", **result}
        db_save_autonomy_trace(trace_id, autonomy_traces[trace_id])
        return result
    except Exception as e:
        checkpoint_events.append({"type": "error", "trace_id": trace_id, "error": str(e)})
        _save_autonomy_checkpoint(trace_id, len(checkpoint_events), goal, checkpoint_events)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/autonomy/trace/{trace_id}")
def autonomy_trace(trace_id: str):
    """Retrieve a stored plan or execution trace by its ID."""
    trace = autonomy_traces.get(trace_id) or db_load_autonomy_trace(trace_id)
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
    history = sessions.get(sid, [])
    if history:
        try:
            summary = summarize_history(history, call_llm_with_fallback)
            if summary:
                add_memory(
                    summary,
                    tags=[sid, "session_close"],
                    persona=get_active_persona_name(),
                    session_id=sid,
                    source="session_close",
                )
        except Exception:
            pass
    sessions.pop(sid, None)
    db_delete_shared_memory(f"session_history:{sid}")
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
def _auto_title(history: list) -> str:
    for msg in history:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        head = content.split("\n", 1)[0].strip()
        return (head[:77] + "...") if len(head) > 80 else head
    return "New Chat"


def _extract_markdown_messages(markdown_text: str) -> list[dict]:
    messages: list[dict] = []
    lines = (markdown_text or "").splitlines()
    current_role: str | None = None
    current_content: list[str] = []

    def _flush():
        nonlocal current_role, current_content
        if current_role is None:
            return
        text = "\n".join(current_content).strip()
        if text:
            messages.append({"role": current_role, "content": text})
        current_role = None
        current_content = []

    for line in lines:
        token = line.strip().upper()
        if token in {"## USER", "**YOU:**"}:
            _flush()
            current_role = "user"
            continue
        if token in {"## ASSISTANT", "**ASSISTANT:**"}:
            _flush()
            current_role = "assistant"
            continue
        if current_role is not None:
            current_content.append(line)

    _flush()
    return messages


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
    cid     = data.get("chat_id") or str(uuid.uuid4())
    # Explicit title always wins (rename case); otherwise auto-generate
    title   = data.get("title") or (chats[cid]["title"] if cid in chats else None) or _auto_title(history)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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


@router.post("/chats/bulk-delete")
async def bulk_delete_chats(request: Request):
    data = await request.json()
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return _api_error("ids must be a non-empty array", "validation_error", 422)

    deleted = 0
    failed = []
    for cid in ids[:100]:
        key = str(cid)
        try:
            chats.pop(key, None)
            db_delete_chat(key)
            deleted += 1
        except Exception as exc:
            failed.append({"id": key, "reason": str(exc)})

    return {"deleted": deleted, "failed": failed, "total_attempted": len(ids[:100])}


@router.post("/chats/import")
async def import_chat_markdown(request: Request):
    data = await request.json()
    content = str(data.get("content") or "").strip()
    if not content:
        return _api_error("content is required", "validation_error", 422)

    messages = _extract_markdown_messages(content)
    if not messages:
        return _api_error("no chat messages found in markdown", "validation_error", 422)

    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    title = str(data.get("title") or _auto_title(messages)).strip()[:80] or "Imported Chat"

    chats[cid] = {
        "id": cid,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": messages,
    }
    db_save_chat(cid, title, now, now, messages)
    return {"chat_id": cid, "title": title, "message_count": len(messages)}

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
    result = []
    for cid in chat_ids:
        chat = chats.get(cid) or db_load_chat(cid)
        if chat:
            result.append(chat)
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


@router.post("/projects/{pid}/memory")
async def set_project_memory(pid: str, request: Request):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return _api_error("summary is required", "validation_error", 422)
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    merged_tags = ["project", pid] + [str(t) for t in tags]
    add_memory(summary, tags=merged_tags)
    return {"project_id": pid, "memory_stored": True, "tags": merged_tags}


@router.get("/projects/{pid}/memory")
def get_project_memory(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    raw = get_memory_context(max_entries=100)
    entries = []
    for entry in raw if isinstance(raw, list) else []:
        tags = entry.get("tags", []) if isinstance(entry, dict) else []
        if pid in tags:
            entries.append(entry)
    return {"project_id": pid, "memory_entries": entries, "count": len(entries)}


@router.post("/projects/{pid}/tool-restrictions")
async def set_project_tool_restrictions(pid: str, request: Request):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    mode = str(data.get("mode") or "allowlist").strip().lower()
    if mode not in {"allowlist", "denylist"}:
        return _api_error("mode must be allowlist or denylist", "validation_error", 422)
    tools = data.get("tools") if isinstance(data.get("tools"), list) else []
    payload = {"mode": mode, "tools": [str(t) for t in tools]}
    db_save_pref(f"project_tool_restrictions:{pid}", json.dumps(payload))
    return {"project_id": pid, "restrictions": payload}


@router.get("/projects/{pid}/tool-restrictions")
def get_project_tool_restrictions(pid: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    raw = db_load_pref(f"project_tool_restrictions:{pid}", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {"project_id": pid, "restrictions": parsed}
        except Exception:
            pass
    return {"project_id": pid, "restrictions": {"mode": "allowlist", "tools": []}}


def _load_project_collaborators(pid: str) -> list[dict]:
    raw = db_load_pref(f"project_collaborators:{pid}", "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_project_collaborators(pid: str, collaborators: list[dict]) -> None:
    db_save_pref(f"project_collaborators:{pid}", json.dumps(collaborators))


@router.post("/projects/{pid}/collaborators")
async def add_project_collaborator(pid: str, request: Request):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    username = str(data.get("username") or "").strip()
    role = str(data.get("role") or "viewer").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    collaborators = _load_project_collaborators(pid)
    if any(str(c.get("username", "")).strip().lower() == username.lower() for c in collaborators):
        return _api_error("collaborator already exists", "conflict", 409)

    collaborators.append({
        "username": username,
        "role": role,
        "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    _save_project_collaborators(pid, collaborators)
    return {"project_id": pid, "collaborator": username, "role": role, "status": "added"}


@router.get("/projects/{pid}/collaborators")
def list_project_collaborators(pid: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    collaborators = _load_project_collaborators(pid)
    return {"project_id": pid, "collaborators": collaborators, "count": len(collaborators)}


@router.delete("/projects/{pid}/collaborators/{collaborator}")
def remove_project_collaborator(pid: str, collaborator: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    collaborators = _load_project_collaborators(pid)
    kept = [c for c in collaborators if str(c.get("username", "")).strip().lower() != collaborator.strip().lower()]
    _save_project_collaborators(pid, kept)
    return {"project_id": pid, "collaborator": collaborator, "status": "removed"}


@router.post("/projects/{pid}/export-bundle")
def export_project_bundle(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(proj, indent=2))
        for cid in get_project_chats(pid):
            chat = chats.get(cid) or db_load_chat(cid)
            if chat:
                zf.writestr(f"chats/{cid}.json", json.dumps(chat, indent=2))
        mem_ctx = get_memory_context(max_entries=200)
        project_mem = []
        for item in mem_ctx if isinstance(mem_ctx, list) else []:
            tags = item.get("tags", []) if isinstance(item, dict) else []
            if pid in tags:
                project_mem.append(item)
        zf.writestr("memory.json", json.dumps(project_mem, indent=2))

    payload = buf.getvalue()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="project-{pid[:8]}-bundle.zip"'},
    )


# ── custom instructions ────────────────────────────────────────────────────────
@router.get("/instructions")
def get_instructions():
    return {"instructions": db_load_ci()}


def _load_instruction_history() -> list[dict]:
    raw = db_load_pref("instructions_history_v1", "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_instruction_history(entries: list[dict]):
    # Keep only recent history to avoid unbounded pref growth.
    db_save_pref("instructions_history_v1", json.dumps(entries[-200:], separators=(",", ":")))


def _append_instruction_version(previous: str, current: str, project_id: str = ""):
    if previous == current:
        return
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    history = _load_instruction_history()
    history.append(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id or None,
            "previous": previous,
            "current": current,
            "changed_at": now,
        }
    )
    _save_instruction_history(history)


@router.get("/instructions/versions")
def get_instruction_versions(limit: int = 50, project_id: str = ""):
    entries = _load_instruction_history()
    if project_id:
        entries = [e for e in entries if str(e.get("project_id") or "") == project_id]
    safe_limit = max(1, min(int(limit), 200))
    return {"versions": list(reversed(entries))[:safe_limit]}


@router.post("/instructions")
async def set_instructions(request: Request):
    data = await request.json()
    old_value = db_load_ci()
    new_value = str(data.get("instructions", ""))
    db_save_ci(new_value)
    _append_instruction_version(old_value, new_value)
    return {"saved": True}


@router.get("/instructions/projects/{pid}")
def get_project_instructions(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    return {
        "project_id": pid,
        "instructions": proj.get("instructions", ""),
    }


@router.post("/instructions/projects/{pid}")
async def set_project_instructions(pid: str, request: Request):
    data = await request.json()
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)

    old_value = str(proj.get("instructions", ""))
    new_value = str(data.get("instructions", ""))
    proj["instructions"] = new_value
    proj["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db_save_project(
        pid,
        proj.get("name", "New Project"),
        new_value,
        proj.get("color", "#7c6af7"),
        proj.get("created_at", proj["updated_at"]),
        proj["updated_at"],
    )
    _append_instruction_version(old_value, new_value, project_id=pid)
    return {"saved": True, "project_id": pid}


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
    return {"personas": db_load_custom_personas()}


@router.get("/personas/custom/export")
def export_custom_personas():
    return {
        "personas": db_load_custom_personas(),
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

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


@router.post("/personas/custom/import")
async def import_custom_personas(request: Request):
    data = await request.json()
    personas = data.get("personas", [])
    merge = bool(data.get("merge", True))

    if not isinstance(personas, list):
        return _api_error("personas must be a list", "validation_error", 422)

    normalized = []
    for item in personas:
        if not isinstance(item, dict):
            return _api_error("each persona must be an object", "validation_error", 422)
        pid = str(item.get("id") or uuid.uuid4())
        normalized.append(
            {
                "id": pid,
                "name": str(item.get("name") or "Custom"),
                "icon": str(item.get("icon") or "🤖"),
                "description": str(item.get("description") or ""),
                "prompt_prefix": str(item.get("prompt_prefix") or ""),
                "color": str(item.get("color") or "#7c6af7"),
                "temperature": float(item.get("temperature", 0.2)),
                "tier": str(item.get("tier") or "medium"),
            }
        )

    if not merge:
        for existing in db_load_custom_personas():
            existing_id = str(existing.get("id") or "")
            if existing_id:
                db_del_persona(existing_id)

    for persona in normalized:
        db_save_persona(
            persona["id"],
            persona["name"],
            persona["icon"],
            persona["description"],
            persona["prompt_prefix"],
            persona["color"],
            float(persona["temperature"]),
            persona["tier"],
        )

    return {
        "imported": len(normalized),
        "merge": merge,
        "total": len(db_load_custom_personas()),
    }


# ── usage dashboard ───────────────────────────────────────────────────────────


@router.get("/usage")
def usage_stats(days: int = 7, username: str = ""):
    from ..tools_builtin import estimate_cost

    safe_days = max(1, min(int(days), 365))
    usage_user = (username or "").strip()
    stats = get_usage_stats(safe_days)
    daily = get_usage_daily(safe_days)
    records = get_usage_records(days=safe_days, username=usage_user, limit=5000)
    per_user = get_usage_by_user(days=safe_days, limit=200)

    for row in stats.get("by_provider", []):
        row["est_cost_usd"] = round(
            estimate_cost(row.get("provider", ""), row.get("in_tok", 0), row.get("out_tok", 0)),
            6,
        )

    token_total = {
        "calls": 0,
        "in_tok": 0,
        "out_tok": 0,
        "cost_usd": 0.0,
    }
    for row in records:
        token_total["calls"] += 1
        token_total["in_tok"] += int(row.get("in_tokens") or 0)
        token_total["out_tok"] += int(row.get("out_tokens") or 0)
        token_total["cost_usd"] += float(row.get("cost_usd") or 0.0)
    token_total["total_tok"] = token_total["in_tok"] + token_total["out_tok"]
    token_total["cost_usd"] = round(token_total["cost_usd"], 6)

    # Simple trend projection: average recent daily totals * 7 days.
    avg_daily_tokens = 0.0
    avg_daily_calls = 0.0
    avg_daily_cost = 0.0
    if daily:
        avg_daily_tokens = sum((int(d.get("in_tok", 0)) + int(d.get("out_tok", 0))) for d in daily) / len(daily)
        avg_daily_calls = sum(int(d.get("calls", 0)) for d in daily) / len(daily)
        avg_daily_cost = token_total["cost_usd"] / len(daily)

    forecast = {
        "window_days": 7,
        "projected_calls": int(round(avg_daily_calls * 7)),
        "projected_tokens": int(round(avg_daily_tokens * 7)),
        "projected_cost_usd": round(avg_daily_cost * 7, 6),
    }

    webhook_cfg = {
        "enabled": db_load_pref("usage_webhook_enabled", "false") == "true",
        "url": db_load_pref("usage_webhook_url", ""),
    }

    return {
        "days": safe_days,
        "username": usage_user,
        "stats": stats,
        "daily": daily,
        "per_user": per_user,
        "totals": token_total,
        "forecast": forecast,
        "webhook": webhook_cfg,
    }


@router.get("/usage/export")
def usage_export(days: int = 7, format: str = "json", username: str = ""):
    safe_days = max(1, min(int(days), 365))
    fmt = (format or "json").strip().lower()
    records = get_usage_records(days=safe_days, username=(username or "").strip(), limit=50000)

    if fmt == "json":
        return {"days": safe_days, "count": len(records), "records": records}

    if fmt == "csv":
        import csv
        import io

        output = io.StringIO()
        fieldnames = ["ts", "provider", "model", "task_type", "username", "in_tokens", "out_tokens", "cost_usd"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    "ts": row.get("ts", ""),
                    "provider": row.get("provider", ""),
                    "model": row.get("model", ""),
                    "task_type": row.get("task_type", ""),
                    "username": row.get("username", ""),
                    "in_tokens": int(row.get("in_tokens") or 0),
                    "out_tokens": int(row.get("out_tokens") or 0),
                    "cost_usd": float(row.get("cost_usd") or 0.0),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=usage-{safe_days}d.csv"},
        )

    return _api_error("format must be json or csv", "validation_error", 422)


@router.get("/usage/webhook")
def usage_webhook_get(request: Request):
    require_admin(request)
    return {
        "enabled": db_load_pref("usage_webhook_enabled", "false") == "true",
        "url": db_load_pref("usage_webhook_url", ""),
        "has_secret": bool(db_load_pref("usage_webhook_secret", "")),
    }


@router.post("/usage/webhook")
async def usage_webhook_set(request: Request):
    require_admin(request)
    data = await request.json()
    enabled = bool(data.get("enabled", True))
    url = str(data.get("url", "") or "").strip()
    secret = str(data.get("secret", "") or "").strip()
    if enabled and not url:
        return _api_error("url is required when webhook is enabled", "validation_error", 422)
    if url and not (url.startswith("http://") or url.startswith("https://")):
        return _api_error("url must start with http:// or https://", "validation_error", 422)

    db_save_pref("usage_webhook_enabled", "true" if enabled else "false")
    db_save_pref("usage_webhook_url", url)
    if secret:
        db_save_pref("usage_webhook_secret", secret)
    return {"ok": True, "enabled": enabled, "url": url}


@router.post("/usage/webhook/push")
def usage_webhook_push(request: Request, days: int = 1):
    require_admin(request)

    enabled = db_load_pref("usage_webhook_enabled", "false") == "true"
    url = db_load_pref("usage_webhook_url", "").strip()
    secret = db_load_pref("usage_webhook_secret", "")
    if not enabled:
        return _api_error("usage webhook is disabled", "invalid_request", 400)
    if not url:
        return _api_error("usage webhook URL is not configured", "invalid_request", 400)

    payload = usage_stats(days=max(1, min(int(days), 365)), username="")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "nexus-ai-usage-webhook/1.0",
    }
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={signature}"

    try:
        from urllib import request as urllib_request

        req = urllib_request.Request(url=url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=10) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
        return {"ok": True, "status": status_code, "url": url}
    except Exception as exc:
        return _api_error(f"webhook push failed: {exc}", "upstream_error", 502)


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
        "keyboard_shortcuts": db_load_pref("keyboard_shortcuts", "default"),
        "language": db_load_pref("language", "en"),
        "verbosity": db_load_pref("verbosity", "balanced"),
        "code_theme": db_load_pref("code_theme", "default"),
        "notifications": db_load_pref("notifications", "enabled"),
    }

@router.post("/prefs")
async def set_prefs(request: Request):
    data = await request.json()
    for key in (
        "theme",
        "font_size",
        "keyboard_shortcuts",
        "language",
        "verbosity",
        "code_theme",
        "notifications",
    ):
        if key in data:
            db_save_pref(key, str(data[key]))
    return {"saved": True}


# ── agent ─────────────────────────────────────────────────────────────────────
@router.post("/agent")
async def agent_post(request: Request):
    data   = await request.json()
    task   = data.get("task","").strip()
    sid    = data.get("session_id")
    files  = data.get("files",[])
    images = data.get("images", [])  # list of {"url":…} or {"b64":…,"mime_type":…}
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
    # Vision fast-path: call LLM directly when images are provided.
    if images:
        _content: list = [{"type": "text", "text": task}]
        for _img in images:
            if not isinstance(_img, dict):
                continue
            if _img.get("url"):
                _content.append({"type": "image_url", "image_url": {"url": _img["url"]}})
            elif _img.get("b64"):
                _mime = _img.get("mime_type", "image/png")
                _content.append({"type": "image_url", "image_url": {"url": f"data:{_mime};base64,{_img['b64']}"}})
        try:
            _vresp, _vpid = call_llm_with_fallback([{"role": "user", "content": _content}], task="vision")
            _vout = _vresp.get("content", str(_vresp))
        except Exception as _exc:
            return _api_error(str(_exc), "vision_error", 500)
        return {"result": _vout, "provider": _vpid, "model": "", "session_id": sid}
    kwargs: dict = {}
    if data.get("max_tool_calls") is not None:
        kwargs["max_tool_calls"] = int(data.get("max_tool_calls"))
    if data.get("max_time_s") is not None:
        kwargs["max_time_s"] = float(data.get("max_time_s"))
    if data.get("max_tokens_out") is not None:
        kwargs["budget_tokens_out"] = int(data.get("max_tokens_out"))

    timeout_s = float(data.get("request_timeout_s") or 12.0)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: run_agent_task(task, history, files, sid=sid or "", usage_principal=principal, **kwargs),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        fallback = _builtin_chat_fallback(task)
        result = {
            "result": fallback,
            "provider": "Built-in",
            "model": "timeout-fallback",
            "history": history + [
                {"role": "user", "content": task},
                {"role": "assistant", "content": fallback},
            ],
        }
    if sid:
        sessions[sid]=result["history"]
        db_set_shared_memory(f"session_history:{sid}", result["history"])
    return {
        "result": result.get("result", ""),
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "session_id": sid,
    }


@router.post("/agent/stream")
async def agent_stream(request: Request):
    data      = await request.json()
    task      = data.get("task","").strip()
    sid       = data.get("session_id")
    files     = data.get("files",[])
    images    = data.get("images", [])  # list of {"url":…} or {"b64":…,"mime_type":…}
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
    db_save_execution_trace(trace_id, execution_traces[trace_id])

    history  = sessions.get(sid,[]) if sid else []

    # Vision fast-path: if images supplied, call LLM directly and stream one chunk.
    if images:
        _vcontent: list = [{"type": "text", "text": task}]
        for _img in images:
            if not isinstance(_img, dict): continue
            if _img.get("url"):
                _vcontent.append({"type": "image_url", "image_url": {"url": _img["url"]}})
            elif _img.get("b64"):
                _vmime = _img.get("mime_type", "image/png")
                _vcontent.append({"type": "image_url", "image_url": {"url": f"data:{_vmime};base64,{_img['b64']}"}})

        async def _vision_gen():
            try:
                _vr, _vp = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: call_llm_with_fallback([{"role": "user", "content": _vcontent}], task="vision")
                )
                _vc = _vr.get("content", str(_vr))
                _evt = json.dumps({"type": "done", "content": _vc, "provider": _vp})
                yield f"data: {_evt}\n\n"
            except Exception as _exc:
                _err = json.dumps({"type": "error", "message": str(_exc)})
                yield f"data: {_err}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_vision_gen(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        kwargs: dict = {}
        if data.get("max_tool_calls") is not None:
            kwargs["max_tool_calls"] = int(data.get("max_tool_calls"))
        if data.get("max_time_s") is not None:
            kwargs["max_time_s"] = float(data.get("max_time_s"))
        if data.get("max_tokens_out") is not None:
            kwargs["budget_tokens_out"] = int(data.get("max_tokens_out"))
        timeout_s = float(data.get("request_timeout_s") or 12.0)

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: run_agent_task(task, history, files, sid=sid or "", usage_principal=principal, **kwargs),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            fallback = _builtin_chat_fallback(task)
            result = {
                "result": fallback,
                "provider": "Built-in",
                "model": "timeout-fallback",
                "history": history + [
                    {"role": "user", "content": task},
                    {"role": "assistant", "content": fallback},
                ],
            }

        status_evt = {"type": "status", "message": "Processing request..."}
        execution_traces[trace_id].append(status_evt)

        if sid and result.get("history"):
            sessions[sid] = result["history"]
            db_set_shared_memory(f"session_history:{sid}", result["history"])

        done_evt = {
            "type": "done",
            "content": result.get("result", "") or "I could not produce a full reply for this turn. Please retry.",
            "provider": result.get("provider", "Built-in"),
            "model": result.get("model", "buffered-stream"),
        }
        execution_traces[trace_id].append(done_evt)
        db_save_execution_trace(trace_id, execution_traces[trace_id])
        body = (
            f"data: {json.dumps(status_evt)}\n\n"
            f"data: {json.dumps(done_evt, default=str)}\n\n"
            "data: [DONE]\n\n"
        )
    except Exception as exc:
        err_evt = {
            "type": "done",
            "content": "I started processing your request but could not finish this turn with a model response. Please retry your message.",
            "provider": "Built-in",
            "model": "buffered-stream-fallback",
        }
        try:
            execution_traces[trace_id].append({"type": "error", "message": str(exc)})
            execution_traces[trace_id].append(err_evt)
            db_save_execution_trace(trace_id, execution_traces[trace_id])
        except Exception:
            pass
        body = (
            f"data: {json.dumps(err_evt)}\n\n"
            "data: [DONE]\n\n"
        )

    return Response(
        content=body,
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no", "X-Trace-Id": trace_id},
    )

@router.get("/agent/trace/{trace_id}")
def get_agent_trace(trace_id: str):
    trace = execution_traces.get(trace_id) or db_load_execution_trace(trace_id)
    if trace is None:
        return _api_error("trace not found", "not_found", 404)
    return {"trace_id": trace_id, "events": trace}


@router.post("/agent/stop/{stream_id}")
def stop_stream(stream_id: str):
    evt = _active_streams.get(stream_id)
    if evt:
        evt.set()
        db_set_shared_memory(f"stream_stop:{stream_id}", {"stopped": True, "stopped_at": time.time()})
        return {"stopped":stream_id}
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

_FEEDBACK_TRACE_CONSENT_KEY = "feedback_trace_opt_in"
_FEEDBACK_TRACE_STORE_KEY = "feedback_trace_events"


def _feedback_trace_opt_in_enabled() -> bool:
    raw = db_load_pref(_FEEDBACK_TRACE_CONSENT_KEY, "false")
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _set_feedback_trace_opt_in(enabled: bool) -> None:
    db_save_pref(_FEEDBACK_TRACE_CONSENT_KEY, bool(enabled))


def _load_feedback_trace_events(limit: int = 5000) -> list[dict]:
    raw = db_load_pref(_FEEDBACK_TRACE_STORE_KEY, [])
    rows: list[dict] = []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rows = parsed
        except Exception:
            rows = []
    safe_limit = max(1, min(int(limit or 5000), 50000))
    return list(reversed(rows))[:safe_limit]


def _append_feedback_trace_event(payload: dict) -> dict:
    rows = db_load_pref(_FEEDBACK_TRACE_STORE_KEY, [])
    if isinstance(rows, str) and rows.strip():
        try:
            rows = json.loads(rows)
        except Exception:
            rows = []
    if not isinstance(rows, list):
        rows = []

    row = {
        "id": f"ftrace_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chat_id": str(payload.get("chat_id") or ""),
        "message_idx": int(payload.get("message_idx") or 0),
        "prompt": str(payload.get("prompt") or ""),
        "response": str(payload.get("response") or ""),
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "persona": str(payload.get("persona") or get_active_persona_name() or ""),
        "session_id": str(payload.get("session_id") or ""),
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
    }
    rows.append(row)
    db_save_pref(_FEEDBACK_TRACE_STORE_KEY, json.dumps(rows[-5000:]))
    return row


def _feedback_rows_to_jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + ("\n" if rows else "")


def _feedback_rows_to_alpaca(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "instruction": str(row.get("prompt") or f"Chat {row.get('chat_id')} message {row.get('message_idx')}").strip(),
                "input": "",
                "output": str(row.get("response") or row.get("reaction") or "").strip(),
                "metadata": {
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "persona": row.get("persona"),
                    "chat_id": row.get("chat_id"),
                    "message_idx": row.get("message_idx"),
                },
            }
        )
    return out


def _feedback_rows_to_sharegpt(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": str(row.get("id") or f"{row.get('chat_id')}:{row.get('message_idx')}"),
                "conversations": [
                    {"from": "human", "value": str(row.get("prompt") or "").strip()},
                    {"from": "gpt", "value": str(row.get("response") or row.get("reaction") or "").strip()},
                ],
                "meta": {
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "persona": row.get("persona"),
                    "chat_id": row.get("chat_id"),
                    "message_idx": row.get("message_idx"),
                },
            }
        )
    return out


def _derive_test_tags(prompt: str, response: str) -> list[str]:
    text = f"{prompt} {response}".lower()
    tags: list[str] = []
    if any(k in text for k in ("code", "python", "bug", "refactor", "function")):
        tags.append("coding")
    if any(k in text for k in ("reason", "logic", "why", "explain", "math")):
        tags.append("reasoning")
    if any(k in text for k in ("policy", "safe", "guardrail", "compliance")):
        tags.append("safety")
    if any(k in text for k in ("rag", "retrieve", "document", "source")):
        tags.append("retrieval")
    return tags or ["general"]


def _keywords_from_response(response: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for token in str(response or "").lower().replace("\n", " ").split(" "):
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) < 4:
            continue
        counts[clean] = counts.get(clean, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [word for word, _ in ranked[: max(1, limit)]]


def _build_auto_test_cases(rows: list[dict], max_cases: int = 100) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        response = str(row.get("response") or "").strip()
        if len(prompt) < 12 or len(response) < 12:
            continue
        key = f"{prompt[:160]}::{response[:160]}"
        if key in seen:
            continue
        seen.add(key)
        expected_keywords = _keywords_from_response(response, limit=5)
        case_id = f"atc_{uuid.uuid4().hex[:10]}"
        cases.append(
            {
                "id": case_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "prompt": prompt[:2000],
                "expected_keywords": expected_keywords,
                "tags": _derive_test_tags(prompt, response),
                "source": {
                    "trace_id": row.get("id"),
                    "chat_id": row.get("chat_id"),
                    "message_idx": row.get("message_idx"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                },
            }
        )
        if len(cases) >= max_cases:
            break
    return cases


_AUTO_TEST_CASES_KEY = "auto_generated_test_cases"


@router.get("/debug/profile-pack")
def debug_profile_pack(persona: str = "", sid: str = "", use_session_dir: bool = False):
    """Debug view for runtime-resolved profile layers and precedence."""
    effective_persona = (persona or get_active_persona_name() or "general").strip()
    base_dir = get_session_dir(sid) if (sid and use_session_dir) else None
    inspected = inspect_profile_pack(base_dir=base_dir, persona_name=effective_persona)
    return {
        "persona": effective_persona,
        "session_id": sid or None,
        "session_safety_profile": get_session_safety_profile(sid) if sid else None,
        "using_session_dir": bool(sid and use_session_dir),
        "base_dir": base_dir,
        "profile": inspected,
    }


@router.get("/feedback/consent")
def feedback_trace_consent_status():
    return {
        "trace_opt_in": _feedback_trace_opt_in_enabled(),
    }


@router.post("/feedback/consent")
async def set_feedback_trace_consent(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    enabled = bool(body.get("trace_opt_in", False))
    _set_feedback_trace_opt_in(enabled)
    return {"trace_opt_in": enabled}


@router.post("/feedback/trace")
async def save_feedback_trace(request: Request):
    """Store opt-in interaction traces for training/export pipelines."""
    if not _feedback_trace_opt_in_enabled():
        return _api_error("trace collection is disabled (opt-in required)", "consent_required", 403)

    body = await _read_json_body(request, "invalid JSON body")
    row = _append_feedback_trace_event(body)
    return {"saved": True, "trace": row}

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
def feedback_export(limit: int = 5000, format: str = "json", include_trace: bool = True):
    """Export message feedback/traces for training pipelines.

    Supported formats: json, jsonl, alpaca, sharegpt.
    """
    from ..db import load_feedback_export, get_feedback_stats
    data = load_feedback_export(limit)
    stats = get_feedback_stats()
    trace_rows = _load_feedback_trace_events(limit=limit) if include_trace else []

    fmt = (format or "json").strip().lower()
    combined_rows = list(trace_rows)
    if not combined_rows:
        # Backward-compatible fallback when only reaction-level feedback exists.
        for item in data:
            combined_rows.append(
                {
                    "id": f"feedback_{item.get('chat_id')}:{item.get('message_idx')}",
                    "chat_id": item.get("chat_id"),
                    "message_idx": item.get("message_idx"),
                    "reaction": item.get("reaction"),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "created_at": item.get("ts"),
                    "prompt": "",
                    "response": str(item.get("reaction") or ""),
                    "persona": "",
                }
            )

    if fmt == "jsonl":
        return Response(_feedback_rows_to_jsonl(combined_rows), media_type="application/x-ndjson")

    if fmt == "alpaca":
        return {
            "format": "alpaca",
            "count": len(combined_rows),
            "data": _feedback_rows_to_alpaca(combined_rows),
            "stats": stats,
            "trace_opt_in": _feedback_trace_opt_in_enabled(),
        }

    if fmt == "sharegpt":
        return {
            "format": "sharegpt",
            "count": len(combined_rows),
            "data": _feedback_rows_to_sharegpt(combined_rows),
            "stats": stats,
            "trace_opt_in": _feedback_trace_opt_in_enabled(),
        }

    if fmt != "json":
        return _api_error("format must be one of: json, jsonl, alpaca, sharegpt", "validation_error", 422)

    return {
        "format": "json",
        "stats":  stats,
        "count":  len(data),
        "data":   data,
        "trace_opt_in": _feedback_trace_opt_in_enabled(),
        "trace_count": len(trace_rows),
        "trace_data": trace_rows,
    }


@router.get("/feedback/stats")
def feedback_stats():
    """Return aggregate thumbs-up / thumbs-down counts."""
    from ..db import get_feedback_stats
    stats = get_feedback_stats()
    trace_rows = _load_feedback_trace_events(limit=5000)
    stats["trace_opt_in"] = _feedback_trace_opt_in_enabled()
    stats["trace_total"] = len(trace_rows)
    return stats


@router.post("/agent/test-cases/generate")
async def generate_test_cases_from_production(request: Request):
    """Generate reusable test cases from opt-in production traces/feedback."""
    body = await _read_json_body(request, "invalid JSON body")
    max_cases = max(1, min(int(body.get("max_cases") or 100), 1000))
    source_limit = max(1, min(int(body.get("source_limit") or 2000), 10000))
    include_reaction_only = bool(body.get("include_reaction_only", True))

    trace_rows = _load_feedback_trace_events(limit=source_limit)
    if not trace_rows and include_reaction_only:
        from ..db import load_feedback_export
        for item in load_feedback_export(limit=source_limit):
            trace_rows.append(
                {
                    "id": f"feedback_{item.get('chat_id')}:{item.get('message_idx')}",
                    "chat_id": item.get("chat_id"),
                    "message_idx": item.get("message_idx"),
                    "prompt": f"Message reaction context for chat {item.get('chat_id')}",
                    "response": str(item.get("reaction") or ""),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                }
            )

    cases = _build_auto_test_cases(trace_rows, max_cases=max_cases)
    db_save_pref(_AUTO_TEST_CASES_KEY, json.dumps(cases))
    return {
        "generated": len(cases),
        "source_rows": len(trace_rows),
        "stored_key": _AUTO_TEST_CASES_KEY,
        "cases": cases,
    }


@router.get("/agent/test-cases")
def list_generated_test_cases(limit: int = 200):
    raw = db_load_pref(_AUTO_TEST_CASES_KEY, "[]")
    try:
        rows = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        rows = []
    safe_limit = max(1, min(int(limit or 200), 2000))
    return {"cases": rows[:safe_limit], "total": len(rows)}


@router.post("/agent/test-cases/run")
async def run_generated_test_cases(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    limit = max(1, min(int(body.get("limit") or 20), 200))

    raw = db_load_pref(_AUTO_TEST_CASES_KEY, "[]")
    try:
        cases = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        cases = []
    cases = cases[:limit]

    if not cases:
        return {"total": 0, "passed": 0, "failed": 0, "results": []}

    results: list[dict] = []
    for case in cases:
        prompt = str(case.get("prompt") or "").strip()
        expected_keywords = [str(k).lower() for k in (case.get("expected_keywords") or []) if str(k).strip()]
        if not prompt:
            continue
        try:
            run = run_agent_task(prompt, history=[])
            answer = str(run.get("result") or "")
            answer_l = answer.lower()
            hits = [kw for kw in expected_keywords if kw in answer_l]
            pass_ratio = (len(hits) / len(expected_keywords)) if expected_keywords else 0.0
            passed = pass_ratio >= 0.4
            results.append(
                {
                    "id": case.get("id"),
                    "passed": passed,
                    "match_ratio": round(pass_ratio, 3),
                    "hits": hits,
                    "missing": [kw for kw in expected_keywords if kw not in hits],
                }
            )
        except Exception as exc:
            results.append({"id": case.get("id"), "passed": False, "error": str(exc)[:240]})

    passed = sum(1 for r in results if r.get("passed"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_pct": round((passed / max(1, len(results))) * 100.0, 2),
        "results": results,
    }


# ── Sprint F: Specialist Agent Library ───────────────────────────────────────

@router.get("/agents")
def list_specialist_agents():
    """Return the full catalogue of built-in specialist agents."""
    from ..agents.registry import list_agents
    return {"agents": list_agents(include_extended=True)}


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


@router.get("/architecture/blueprints/{name}/versions")
def list_architecture_blueprint_versions(name: str, limit: int = 100):
    from ..db import list_architecture_blueprints as db_list_architecture_blueprints

    rows = db_list_architecture_blueprints(name=name, limit=max(1, min(int(limit), 500)))
    versions = [r for r in rows if str(r.get("name") or "") == name]
    versions.sort(key=lambda r: int(r.get("version") or 0), reverse=True)
    return {
        "name": name,
        "versions": versions,
        "latest_version": versions[0].get("version") if versions else None,
        "total": len(versions),
    }


@router.post("/architecture/blueprints/{name}/activate")
async def activate_architecture_blueprint_version(name: str, request: Request):
    from ..db import load_architecture_blueprint, save_pref as _save_pref

    body = await _read_json_body(request, "invalid JSON body")
    version = int(body.get("version") or 0)
    if version <= 0:
        return _api_error("version must be a positive integer", "validation_error", 422)

    bp = load_architecture_blueprint(name=name, version=version)
    if not bp:
        return _api_error(f"architecture blueprint '{name}' version {version} not found", "not_found", 404)

    marker = {
        "name": name,
        "version": version,
        "activated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "activated_by": str(body.get("actor") or body.get("username") or "system"),
    }
    _save_pref(f"arch_bp:{name}:active", json.dumps(marker))
    return {"ok": True, "active": marker, "blueprint": bp}


@router.get("/architecture/blueprints/{name}/active")
def get_architecture_blueprint_active(name: str):
    raw = db_load_pref(f"arch_bp:{name}:active", "")
    if not raw:
        return {"name": name, "active": None}
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    return {"name": name, "active": parsed}


@router.get("/architecture/registry/{name}")
def get_architecture_registry(name: str, version: int = 0):
    from ..db import load_architecture_registry

    data = load_architecture_registry(name=name, version=version if version > 0 else None)
    if not data:
        return _api_error(f"architecture registry '{name}' not found", "not_found", 404)

    if "counts" not in data:
        snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
        nodes = snapshot.get("nodes") if isinstance(snapshot.get("nodes"), list) else []
        edges = snapshot.get("edges") if isinstance(snapshot.get("edges"), list) else []
        data = {
            **data,
            "counts": {
                "nodes": max(1, len(nodes)),
                "edges": max(1, len(edges)),
            },
        }
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
    except AllProvidersExhausted as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "type": "provider_exhausted",
                "retry_after_seconds": 20,
                "hints": [
                    "Retry shortly after provider cooldown",
                    "Configure at least one additional provider key",
                    "Lower complexity or token budget for this request",
                ],
            },
            status_code=503,
        )
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
        db_save_autonomy_trace(trace_id, autonomy_traces[trace_id])
        return result
    except Exception as exc:
        return _api_error(str(exc), "orchestration_error", 500)


@router.get("/orchestrate/hierarchical/{trace_id}")
def get_hierarchical_trace(trace_id: str):
    """Retrieve a stored hierarchical orchestration result by trace ID."""
    trace = autonomy_traces.get(trace_id) or db_load_autonomy_trace(trace_id)
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
def list_marketplace_agents(org_id: str = ""):
    """Return all available agents (built-in + imported) from the marketplace.

    Query params:
        org_id — if provided, also includes private agents scoped to this org
    """
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
    # public imported agents
    imported = load_marketplace_agents(source="imported")
    # private org-scoped agents
    org_agents: list = []
    if org_id:
        org_agents = load_marketplace_agents(org_id=org_id)
        # de-duplicate (org agents with source=imported are already in imported)
        imported_ids = {a["id"] for a in imported}
        org_agents = [a for a in org_agents if a["id"] not in imported_ids]
    all_agents = builtin + imported + org_agents
    return {"agents": all_agents, "total": len(all_agents)}


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


# NOTE: /marketplace/agents/import-url must come BEFORE /marketplace/agents/{agent_id}
@router.post("/marketplace/agents/import-url", status_code=201)
async def import_marketplace_agent_from_url(request: Request):
    """Import an agent definition from a remote URL.

    POST body:
        url      — public URL returning a JSON agent definition
        org_id   — optional org scope (makes it a private org agent)
    """
    import urllib.request
    import urllib.error

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    url    = (body.get("url")    or "").strip()
    org_id = (body.get("org_id") or "").strip()

    if not url:
        return _api_error("url is required", "validation_error", 422)
    if not url.startswith("https://"):
        return _api_error("url must use HTTPS", "validation_error", 422)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NexusAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            raw = resp.read(256 * 1024)  # 256 KB max
        agent_def = json.loads(raw)
    except urllib.error.URLError as exc:
        return _api_error(f"Failed to fetch URL: {exc}", "fetch_error", 400)
    except Exception as exc:
        return _api_error(f"Invalid agent JSON at URL: {exc}", "parse_error", 400)

    agent_id = (agent_def.get("id") or "").strip()
    name     = (agent_def.get("name") or "").strip()
    prompt   = (agent_def.get("system_prompt") or "").strip()

    if not agent_id:
        return _api_error("agent definition missing 'id'", "validation_error", 422)
    if not name:
        return _api_error("agent definition missing 'name'", "validation_error", 422)
    if not prompt:
        return _api_error("agent definition missing 'system_prompt'", "validation_error", 422)

    from ..db import save_marketplace_agent
    save_marketplace_agent(
        agent_id            = agent_id,
        name                = name,
        icon                = (agent_def.get("icon") or "🤖").strip()[:8],
        description         = str(agent_def.get("description") or "")[:512],
        system_prompt       = prompt,
        keywords            = agent_def.get("keywords") or [],
        preferred_providers = agent_def.get("preferred_providers") or [],
        temperature         = float(agent_def.get("temperature", 0.7)),
        tier                = str(agent_def.get("tier") or "standard").strip(),
        source              = "imported_url",
        org_id              = org_id,
    )
    return {"id": agent_id, "name": name, "source_url": url, "status": "imported"}


@router.get("/marketplace/agents/{agent_id}/versions")
def get_marketplace_agent_versions(agent_id: str):
    """Return version history for a marketplace agent."""
    from ..db import list_marketplace_agent_versions
    versions = list_marketplace_agent_versions(agent_id)
    return {"agent_id": agent_id, "versions": versions}


@router.get("/marketplace/agents/{agent_id}/reviews")
def get_marketplace_agent_reviews(agent_id: str):
    """Return all reviews for a marketplace agent."""
    from ..db import list_marketplace_agent_reviews
    reviews = list_marketplace_agent_reviews(agent_id)
    avg = (sum(r["rating"] for r in reviews) / len(reviews)) if reviews else None
    return {
        "agent_id":     agent_id,
        "reviews":      reviews,
        "count":        len(reviews),
        "average_rating": round(avg, 2) if avg is not None else None,
    }


@router.post("/marketplace/agents/{agent_id}/reviews", status_code=201)
async def submit_marketplace_agent_review(agent_id: str, request: Request):
    """Submit or update a review for a marketplace agent.

    POST body:
        username — reviewer identifier
        rating   — integer 1–5
        comment  — optional text comment
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    username = (body.get("username") or "").strip()
    comment  = str(body.get("comment") or "").strip()
    try:
        rating = int(body.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0

    if not username:
        return _api_error("username is required", "validation_error", 422)
    if not 1 <= rating <= 5:
        return _api_error("rating must be an integer 1–5", "validation_error", 422)

    from ..db import save_marketplace_agent_review
    review = save_marketplace_agent_review(
        agent_id=agent_id,
        username=username,
        rating=rating,
        comment=comment,
    )
    return {"agent_id": agent_id, "review": review, "status": "saved"}


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

# NOTE: /agents/bus/log and /agents/bus/dlq must be registered BEFORE
# /agents/bus/{agent_id} so FastAPI doesn't capture literal path segments.
@router.get("/agents/bus/log")
def get_bus_log(limit: int = 50, topic: str = ""):
    """Return the recent global message bus log.

    Query params:
        limit — max messages to return (default 50)
        topic — optional topic filter (empty = all topics)
    """
    from ..agent_bus import recent_log, all_agents
    msgs = recent_log(limit=limit, topic=topic if topic else None)
    return {
        "messages":      [m.to_dict() for m in msgs],
        "active_agents": all_agents(),
    }


@router.get("/agents/bus/dlq")
def get_bus_dlq(limit: int = 50):
    """Return messages in the dead-letter queue (failed/undeliverable)."""
    from ..agent_bus import get_dlq
    entries = get_dlq(limit=limit)
    return {
        "dlq":   [e.to_dict() for e in entries],
        "count": len(entries),
    }


@router.delete("/agents/bus/dlq")
def clear_bus_dlq():
    """Clear all entries from the dead-letter queue."""
    from ..agent_bus import clear_dlq
    cleared = clear_dlq()
    return {"cleared": cleared}


@router.get("/agents/bus/consume")
async def consume_agent_inbox_long_poll(
    agent_id: str,
    wait_seconds: float = 20.0,
    limit: int = 20,
    topic: str = "",
):
    """Long-poll consumer API for asynchronous bus reads."""
    from ..agent_bus import read_messages, unread_count

    aid = str(agent_id or "").strip()
    if not aid:
        return _api_error("agent_id is required", "validation_error", 422)

    timeout_s = max(0.0, min(float(wait_seconds), 60.0))
    safe_limit = max(1, min(int(limit), 200))
    start = time.monotonic()

    while True:
        msgs = read_messages(
            aid,
            limit=safe_limit,
            unread_only=True,
            mark_read=True,
            topic=topic if topic else None,
        )
        if msgs:
            return {
                "agent_id": aid,
                "messages": [m.to_dict() for m in msgs],
                "unread_count": unread_count(aid),
                "waited_seconds": round(time.monotonic() - start, 3),
                "timed_out": False,
            }

        if (time.monotonic() - start) >= timeout_s:
            return {
                "agent_id": aid,
                "messages": [],
                "unread_count": unread_count(aid),
                "waited_seconds": round(time.monotonic() - start, 3),
                "timed_out": True,
            }
        await asyncio.sleep(0.25)


@router.websocket("/agents/bus/ws/{agent_id}")
async def consume_agent_inbox_ws(websocket: WebSocket, agent_id: str):
    """WebSocket consumer API that streams unread bus messages."""
    from ..agent_bus import read_messages, unread_count

    await websocket.accept()
    topic = str(websocket.query_params.get("topic") or "").strip()
    try:
        poll_ms = int(websocket.query_params.get("poll_ms") or 300)
    except Exception:
        poll_ms = 300
    poll_s = max(0.1, min(poll_ms / 1000.0, 2.0))

    heartbeat_every = 10.0
    last_heartbeat = time.monotonic()

    try:
        while True:
            msgs = read_messages(
                agent_id,
                limit=100,
                unread_only=True,
                mark_read=True,
                topic=topic if topic else None,
            )
            for msg in msgs:
                await websocket.send_json({"type": "message", "message": msg.to_dict()})

            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_every:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "agent_id": agent_id,
                        "unread_count": unread_count(agent_id),
                        "ts": time.time(),
                    }
                )
                last_heartbeat = now

            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=poll_s)
                if incoming.strip().lower() in {"close", "disconnect", "quit"}:
                    await websocket.close()
                    break
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return


@router.get("/agents/bus/{agent_id}")
def read_agent_inbox(
    agent_id: str,
    limit: int = 20,
    unread_only: bool = False,
    topic: str = "",
):
    """Read messages in an agent's inbox.

    Query params:
        limit       — max messages to return (default 20)
        unread_only — if true, only return unread messages
        topic       — optional topic filter (empty = all topics)
    """
    from ..agent_bus import read_messages, unread_count
    msgs = read_messages(
        agent_id,
        limit=limit,
        unread_only=unread_only,
        mark_read=True,
        topic=topic if topic else None,
    )
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
        topic    — optional topic tag for subscriber filtering
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    from_id = (body.get("from_id") or "").strip()
    to_id   = (body.get("to_id")   or "").strip()
    content = (body.get("content") or "").strip()
    topic   = (body.get("topic")   or "").strip()

    if not from_id:
        return _api_error("from_id is required", "validation_error", 422)
    if not to_id:
        return _api_error("to_id is required", "validation_error", 422)
    if not content:
        return _api_error("content is required", "validation_error", 422)

    from ..agent_bus import post_message
    msg = post_message(from_id, to_id, content, topic=topic)
    return msg.to_dict()


@router.post("/agents/lineage/links", status_code=201)
async def create_agent_lineage_link(request: Request):
    body = await _read_json_body(request)
    parent_task_id = str(body.get("parent_task_id") or "").strip()
    child_task_id = str(body.get("child_task_id") or "").strip()
    relation = str(body.get("relation") or "depends_on").strip()
    source = str(body.get("source") or "api").strip()
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    if not parent_task_id or not child_task_id:
        return _api_error("parent_task_id and child_task_id are required", "validation_error", 422)
    try:
        from ..agent_lineage import record_lineage_edge

        edge = record_lineage_edge(
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            relation=relation,
            source=source,
            metadata=metadata,
        )
        return edge
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/agents/lineage/query")
def query_agent_lineage(task_id: str, direction: str = "both", limit: int = 500):
    from ..agent_lineage import query_lineage

    rows = query_lineage(task_id=task_id, direction=direction, limit=limit)
    return {
        "task_id": task_id,
        "direction": direction,
        "count": len(rows),
        "edges": rows,
    }


@router.get("/agents/lineage/graph/{root_task_id}")
def get_agent_lineage_graph(root_task_id: str, depth: int = 3, limit: int = 2000):
    from ..agent_lineage import get_lineage_graph

    return get_lineage_graph(root_task_id=root_task_id, depth=depth, limit=limit)


@router.delete("/tasks/{trace_id}")
def delete_task_trace(trace_id: str):
    deleted = _delete_trace(trace_id)
    execution_traces.pop(trace_id, None)
    if not deleted:
        return _api_error("trace not found", "not_found", 404)
    return {"deleted": trace_id, "ok": True}


@router.get("/tasks/search")
def search_task_traces(tool: str = "", event_type: str = "", error: str = "", limit: int = 100):
    safe_limit = max(1, min(int(limit), 500))
    tool_filter = (tool or "").strip().lower()
    type_filter = (event_type or "").strip().lower()
    error_filter = (error or "").strip().lower()

    traces = list_tasks(limit=safe_limit * 2).get("traces", [])
    matched: list[dict] = []
    for trace in traces:
        trace_id = str(trace.get("trace_id") or "").strip()
        if not trace_id:
            continue
        events = execution_traces.get(trace_id)
        if events is None:
            events = db_load_execution_trace(trace_id)
        if events is None:
            cp = _get_latest_checkpoint(trace_id)
            events = cp.get("events", []) if cp else []

        event_list = events if isinstance(events, list) else []
        has_tool = (not tool_filter) or any(
            tool_filter in str(evt.get("action", "")).lower() for evt in event_list if isinstance(evt, dict)
        )
        has_type = (not type_filter) or any(
            type_filter == str(evt.get("type", "")).lower() for evt in event_list if isinstance(evt, dict)
        )
        has_error = (not error_filter) or any(
            error_filter in str(evt.get("message", "")).lower() for evt in event_list if isinstance(evt, dict)
        )
        if has_tool and has_type and has_error:
            matched.append(
                {
                    "trace_id": trace_id,
                    "events": len(event_list),
                    "task": trace.get("task", ""),
                    "last_active": trace.get("last_active", trace.get("updated_at", "")),
                }
            )
            if len(matched) >= safe_limit:
                break

    return {"results": matched, "count": len(matched)}


@router.get("/tasks/{trace_id}/export")
def export_task_trace(trace_id: str):
    events = execution_traces.get(trace_id)
    if events is None:
        events = db_load_execution_trace(trace_id)
    checkpoints = _load_checkpoints(trace_id)
    if events is None and not checkpoints:
        return _api_error("trace not found", "not_found", 404)
    payload = {
        "trace_id": trace_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "events": events if isinstance(events, list) else [],
        "checkpoints": checkpoints,
    }
    return payload


@router.get("/tasks/{trace_id}/diff")
def diff_task_traces(trace_id: str, other_trace_id: str = ""):
    import difflib

    if not other_trace_id.strip():
        return _api_error("other_trace_id is required", "validation_error", 422)

    left = execution_traces.get(trace_id)
    if left is None:
        left = db_load_execution_trace(trace_id)
    right = execution_traces.get(other_trace_id)
    if right is None:
        right = db_load_execution_trace(other_trace_id)

    if left is None or right is None:
        return _api_error("one or both traces not found", "not_found", 404)

    left_lines = json.dumps(left, indent=2, sort_keys=True).splitlines()
    right_lines = json.dumps(right, indent=2, sort_keys=True).splitlines()
    diff_lines = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=f"a/{trace_id}",
            tofile=f"b/{other_trace_id}",
            lineterm="",
        )
    )
    return {
        "trace_id": trace_id,
        "other_trace_id": other_trace_id,
        "diff": "\n".join(diff_lines),
        "left_events": len(left) if isinstance(left, list) else 0,
        "right_events": len(right) if isinstance(right, list) else 0,
    }


@router.get("/tasks/anomalies")
def task_trace_anomalies(limit: int = 50):
    safe_limit = max(1, min(int(limit), 500))
    traces = list_tasks(limit=safe_limit).get("traces", [])
    anomalies: list[dict] = []

    for trace in traces:
        trace_id = str(trace.get("trace_id") or "")
        if not trace_id:
            continue
        events = execution_traces.get(trace_id)
        if events is None:
            events = db_load_execution_trace(trace_id)
        event_list = events if isinstance(events, list) else []

        error_count = sum(1 for evt in event_list if isinstance(evt, dict) and str(evt.get("type", "")).lower() == "error")
        tool_count = sum(1 for evt in event_list if isinstance(evt, dict) and str(evt.get("type", "")).lower() in {"tool", "tool_start", "tool_result"})

        reasons: list[str] = []
        if error_count > 0:
            reasons.append(f"errors:{error_count}")
        if len(event_list) > 500:
            reasons.append("high_event_volume")
        if tool_count > 200:
            reasons.append("high_tool_activity")

        if reasons:
            anomalies.append(
                {
                    "trace_id": trace_id,
                    "events": len(event_list),
                    "errors": error_count,
                    "tool_events": tool_count,
                    "reasons": reasons,
                    "last_active": trace.get("last_active", trace.get("updated_at", "")),
                }
            )

    return {"anomalies": anomalies, "count": len(anomalies)}


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


@router.get("/kg/graph")
def kg_graph_endpoint(limit: int = 500):
    return _kg_graph(limit=limit)


@router.post("/kg/merge")
async def kg_merge_endpoint(request: Request):
    data = await request.json()
    primary = (data.get("primary") or "").strip()
    duplicate = (data.get("duplicate") or "").strip()
    if not primary or not duplicate:
        return _api_error("primary and duplicate are required", "validation_error", 422)
    result = _kg_merge(primary, duplicate)
    if not result.get("merged"):
        return _api_error("merge failed", "merge_error", 400)
    return result


@router.post("/kg/import")
async def kg_import_endpoint(request: Request):
    data = await request.json()
    content = str(data.get("content", "") or "")
    if not content.strip():
        return _api_error("content is required", "validation_error", 422)
    fmt = str(data.get("format", "auto") or "auto")
    limit = int(data.get("limit", 2000) or 2000)
    return _kg_import(content, fmt=fmt, limit=limit)


@router.get("/kg/hybrid-search")
def kg_hybrid_search_endpoint(q: str = "", limit: int = 10):
    if not q.strip():
        return _api_error("q is required", "validation_error", 422)
    return _kg_hybrid_search(q.strip(), limit=limit)


# ── Execution Trace replay/resume endpoints ──────────────────────────────────

@router.get("/tasks")
def list_tasks(limit: int = 50):
    traces = _list_traces(limit=limit)
    persisted = db_list_execution_traces(limit=limit)
    seen = {t.get("trace_id") for t in traces if isinstance(t, dict)}
    for trace in persisted:
        if trace.get("trace_id") not in seen:
            traces.append(trace)
    return {"traces": traces, "count": len(traces)}


@router.get("/tasks/{trace_id}")
def get_task_trace(trace_id: str):
    # Check in-memory first (live traces), then SQLite checkpoints
    in_memory = execution_traces.get(trace_id)
    if in_memory is None:
        in_memory = db_load_execution_trace(trace_id)
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
        stored_events = db_load_execution_trace(trace_id)
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
    db_save_execution_trace(new_trace_id, execution_traces[new_trace_id])
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
                db_save_execution_trace(new_trace_id, execution_traces[new_trace_id])
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            err_event = {"type": "error", "message": str(e)}
            execution_traces[new_trace_id].append(err_event)
            db_save_execution_trace(new_trace_id, execution_traces[new_trace_id])
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
    deleted = db_delete_execution_trace(trace_id) or deleted
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
    if task.startswith("__finetune_continual__:"):
        raw = task.split(":", 1)[1].strip()
        try:
            payload = json.loads(raw)
        except Exception as exc:
            return f"continual policy parse error: {exc}"
        if not isinstance(payload, dict):
            return "continual policy payload must be an object"
        return _execute_continual_re_tune_task(payload)
    if task == "__internal_validation_program__":
        from ..validation_program import run_validation_program

        report = run_validation_program(update_baseline=False, alert_on_regression=True)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        return (
            f"validation success_rate={summary.get('success_rate', 0.0)} "
            f"tool_error_rate={summary.get('tool_error_rate', 0.0)}"
        )
    return _run_scheduled_task(task)


def startup_event() -> None:
    set_run_function(_run_scheduled_task_extended)
    restore_from_db()
    _register_quota_reset_scheduler()
    try:
        from ..benchmark import register_benchmark_schedules
        from ..validation_program import register_validation_program_schedules

        register_benchmark_schedules(_run_scheduled_task_extended)
        register_validation_program_schedules(_run_scheduled_task_extended)
    except Exception:
        pass
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
    import hashlib
    from ..db import SQLiteBackend, _backend as _b

    def _verify_sql_dump(sql_dump: str) -> bool:
        try:
            conn = _sqlite3.connect(":memory:")
            for stmt in sql_dump.split(";\n"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _replicate_offsite(sql_bytes: bytes, sha256_hex: str) -> str:
        target = os.getenv("OFFSITE_BACKUP_URL", "").strip()
        if not target:
            return "disabled"
        try:
            import urllib.request as _urlreq
            from datetime import datetime as _dt, timezone as _tz

            ts_label = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            # Append timestamp segment so each backup has a unique URL.
            # Supports both trailing-slash base URLs and pre-signed PUT URLs.
            # If target already contains a query string (pre-signed), skip append.
            if "?" not in target and not target.endswith(".sql"):
                upload_url = target.rstrip("/") + f"/nexus_backup_{ts_label}.sql"
            else:
                upload_url = target

            req = _urlreq.Request(
                upload_url,
                data=sql_bytes,
                method="PUT",
                headers={
                    "Content-Type": "application/sql",
                    "X-Backup-SHA256": sha256_hex,
                    "X-Backup-Timestamp": ts_label,
                },
            )
            with _urlreq.urlopen(req, timeout=15):
                pass

            # ── Retention sweep ───────────────────────────────────────────
            # If OFFSITE_BACKUP_RETENTION_DAYS is set AND the target is an
            # HTTP directory listing endpoint (supports DELETE), send DELETE
            # requests for backups older than the retention window.
            # This works with simple object-storage backends that support
            # listing/deleting by timestamp suffix.
            retention_days = int(os.getenv("OFFSITE_BACKUP_RETENTION_DAYS", "0"))
            if retention_days > 0 and "?" not in target:
                try:
                    import json as _json
                    cutoff_ts = _dt.now(_tz.utc).timestamp() - retention_days * 86400
                    # Fetch directory listing (expects JSON array of {name, created_at})
                    list_req = _urlreq.Request(
                        target.rstrip("/") + "/",
                        method="GET",
                        headers={"Accept": "application/json"},
                    )
                    with _urlreq.urlopen(list_req, timeout=10) as resp:
                        listing = _json.loads(resp.read())
                    for entry in listing if isinstance(listing, list) else []:
                        name = str(entry.get("name", ""))
                        created = float(entry.get("created_at", 0))
                        if name.endswith(".sql") and created < cutoff_ts:
                            del_url = target.rstrip("/") + f"/{name}"
                            del_req = _urlreq.Request(del_url, method="DELETE")
                            try:
                                with _urlreq.urlopen(del_req, timeout=10):
                                    pass
                            except Exception:
                                pass
                except Exception:
                    pass  # retention sweep is best-effort; never fail the backup itself

            return "replicated"
        except Exception:
            return "failed"

    if not isinstance(_b, SQLiteBackend):
        return _api_error("Backup only supported for SQLite backend", "not_supported", 400)
    src = _sqlite3.connect(_b.db_path)
    dst = _sqlite3.connect(":memory:")
    src.backup(dst)
    dst_buf = io.BytesIO()
    for line in dst.iterdump():
        dst_buf.write((line + "\n").encode())
    sql_bytes = dst_buf.getvalue()
    sql_text = sql_bytes.decode("utf-8", errors="ignore")
    backup_sha256 = hashlib.sha256(sql_bytes).hexdigest()
    verify_ok = _verify_sql_dump(sql_text)
    replication_status = _replicate_offsite(sql_bytes, backup_sha256)
    dst_buf.seek(0)
    src.close()
    dst.close()
    from fastapi.responses import StreamingResponse
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        dst_buf,
        media_type="application/sql",
        headers={
            "Content-Disposition": f'attachment; filename="nexus_backup_{ts}.sql"',
            "X-Backup-SHA256": backup_sha256,
            "X-Backup-Verified": "true" if verify_ok else "false",
            "X-Offsite-Replication": replication_status,
        },
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


@router.post("/backup/gist/restore")
def gist_restore_endpoint(request: Request):
    """Force restore of SQLite DB from configured GitHub Gist backup."""
    require_admin(request)
    restored = restore_from_gist()
    if restored:
        return {"ok": True, "restored": True, "message": "Database restored from gist backup"}
    return {
        "ok": False,
        "restored": False,
        "message": "No gist backup restored (missing config, missing backup, or restore failed)",
    }


@router.post("/backup/gist/push")
def gist_push_endpoint(request: Request):
    """Force immediate push of SQLite DB to configured GitHub Gist backup."""
    require_admin(request)
    gist_push_now()
    return {"ok": True, "message": "Gist backup push triggered"}


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
    try:
        from ..profiles import cleanup_stale_quota_days

        deleted = cleanup_stale_quota_days(days_to_keep=8)
        return f"quota cleanup: removed {deleted} stale daily keys"
    except Exception as e:
        return f"quota cleanup error: {e}"


def _register_quota_reset_scheduler():
    """Register weekly quota cleanup job if not already registered."""
    existing = list_jobs()
    if any(getattr(j, "name", None) == "quota-weekly-cleanup" for j in existing):
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
    from ..profiles import reset_quota_usage

    reset_quota_usage(username)
    return {"ok": True, "username": username, "reset_at": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/completions  — legacy OpenAI text completions endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/v1/")
def v1_root():
    """Version root metadata for lifecycle-aware clients."""
    return {
        "version": "v1",
        "status": "active",
        "deprecated_paths": [
            {
                "path": "/v1/completions",
                "sunset": "2026-12-31T00:00:00+00:00",
                "replacement": "/v1/chat/completions",
            }
        ],
    }

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
    """Whisper-compatible STT using shared local/provider backend helpers."""
    form = await request.form()
    file_field = form.get("file")
    language = str(form.get("language", "")) or None
    response_format = str(form.get("response_format", "json"))
    include_diarization = str(form.get("include_diarization", "false")).lower() == "true"
    include_speaker_labels = str(form.get("include_speaker_labels", "false")).lower() == "true"
    include_analysis = str(form.get("include_analysis", "false")).lower() == "true"
    voice_profile_field = form.get("voice_profile")
    voice_profile_b64 = form.get("voice_profile_base64")

    if file_field is None:
        return _v1_error("file is required", "invalid_request_error", 422)

    audio_bytes = await file_field.read()  # type: ignore[union-attr]
    mime_type = getattr(file_field, "content_type", None) or "audio/wav"

    try:
        from ..audio import AudioProviderError, analyse_audio, diarize_audio, identify_speaker, transcribe_audio

        result = transcribe_audio(audio_bytes, mime_type=mime_type, language=language, backend="auto")
    except AudioProviderError as exc:
        return _v1_error(str(exc), "model_error", 503)
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)

    if response_format == "text":
        return result.get("text", "")

    profile_bytes = None
    try:
        if voice_profile_field is not None and hasattr(voice_profile_field, "read"):
            profile_bytes = await voice_profile_field.read()  # type: ignore[union-attr]
        elif voice_profile_b64:
            profile_bytes = base64.b64decode(str(voice_profile_b64))
    except Exception:
        return _v1_error("invalid voice profile", "invalid_request_error", 422)

    payload = {
        "text": result.get("text", ""),
        "language": result.get("language", language or "en"),
        "duration": result.get("duration_seconds", 0.0),
        "segments": result.get("segments", []),
        "backend": result.get("backend", "unknown"),
    }

    diarization = None
    if include_diarization or include_speaker_labels:
        diarization = diarize_audio(audio_bytes)
        payload["diarization"] = diarization
        if diarization.get("ok"):
            payload["transcript_with_speakers"] = "\n".join(
                f"{segment.get('speaker', 'SPEAKER_01')}: {str(segment.get('text', '') or '').strip()}"
                for segment in diarization.get("segments", [])
                if str(segment.get("text", "") or "").strip()
            )

    if profile_bytes is not None or include_speaker_labels:
        payload["speaker_identification"] = identify_speaker(audio_bytes, voice_profile_bytes=profile_bytes)

    if include_analysis:
        payload["analysis"] = analyse_audio(audio_bytes, voice_profile_bytes=profile_bytes)

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/audio/speech  — TTS endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/v1/audio/speech")
async def v1_audio_speech(request: Request):
    """OpenAI-compatible TTS using shared local/provider backend helpers."""
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

    try:
        from ..audio import AudioProviderError, synthesize_speech

        audio_bytes = synthesize_speech(text, voice=voice, speed=speed, format=fmt, backend="auto")
    except AudioProviderError as exc:
        return _v1_error(str(exc), "model_error", 503)
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)

    media_map = {"mp3": "audio/mpeg", "opus": "audio/opus", "aac": "audio/aac",
                 "flac": "audio/flac", "wav": "audio/wav", "pcm": "audio/pcm"}
    filename_ext = fmt if fmt in media_map else "wav"
    return StreamingResponse(
        iter([audio_bytes]),
        media_type=media_map.get(fmt, "audio/wav"),
        headers={"Content-Disposition": f'attachment; filename="speech.{filename_ext}"'},
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


@router.get("/v1/fine-tuning/training-samples")
def v1_list_training_samples(limit: int = 100, min_quality: float = 0.0):
    safe_limit = min(max(int(limit or 100), 1), 500)
    safe_quality = max(0.0, min(float(min_quality or 0.0), 1.0))
    return {
        "object": "list",
        "data": db_list_ft_training_samples(limit=safe_limit, min_quality=safe_quality),
    }


@router.post("/v1/fine-tuning/training-samples/export")
async def v1_export_training_samples(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    min_quality = max(0.0, min(float(body.get("min_quality", 0.7) or 0.7), 1.0))
    limit = min(max(int(body.get("limit", 200) or 200), 1), 1000)
    model = str(body.get("model", "gpt-3.5-turbo") or "gpt-3.5-turbo")

    samples = db_list_ft_training_samples(limit=limit, min_quality=min_quality)
    if not samples:
        return _v1_error("no training samples matched the requested filter", "not_found_error", 404)

    _ensure_files_dir()
    file_id = f"file-{uuid.uuid4().hex[:12]}"
    data_path = os.path.join(_FILES_DIR, file_id)
    lines = []
    for sample in samples:
        lesson_text = "\n".join(f"- {lesson}" for lesson in (sample.get("lessons") or []))
        messages = [
            {"role": "system", "content": "You are a helpful assistant that improves future responses using retrospective quality signals."},
            {"role": "user", "content": str(sample.get("task") or "")},
            {"role": "assistant", "content": str(sample.get("result") or "")},
        ]
        completion = str(sample.get("result") or "")
        if lesson_text:
            completion += "\n\nRetrospective lessons:\n" + lesson_text
        lines.append(json.dumps({"messages": messages, "completion": completion}))

    with open(data_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    meta = {
        "id": file_id,
        "object": "file",
        "bytes": os.path.getsize(data_path),
        "created_at": int(time.time()),
        "filename": f"reflection-training-{model.replace('/', '-')}.jsonl",
        "purpose": "fine-tune",
        "status": "processed",
        "sample_count": len(samples),
        "min_quality": min_quality,
    }
    with open(_file_meta_path(file_id), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)

    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Fine-tuning API  — persisted compatibility lifecycle (/v1/fine-tuning/jobs)
# ─────────────────────────────────────────────────────────────────────────────

def _run_fine_tuning_job(job_id: str):
    """Background lifecycle for compatibility fine-tuning jobs.

    This keeps OpenAI-compatible job states realistic while the backend
    remains a compatibility implementation rather than a real trainer.
    """
    try:
        job = db_get_fine_tuning_job(job_id)
        if not job or job.get("status") != "queued":
            return

        db_update_fine_tuning_job(job_id, status="running")
        db_create_fine_tuning_job_event(job_id, "Job status changed to running", data={"status": "running"})
        time.sleep(0.6)

        job = db_get_fine_tuning_job(job_id)
        if not job or job.get("status") == "cancelled":
            return

        training_meta = _load_file_meta(str(job.get("training_file") or "")) or {}
        trained_tokens = max(128, int(training_meta.get("bytes", 0) // 4))
        ft_model = f"ft:{job.get('model', 'model')}:{job_id[-6:]}"
        db_update_fine_tuning_job(
            job_id,
            status="succeeded",
            fine_tuned_model=ft_model,
            trained_tokens=trained_tokens,
            finished_at=int(time.time()),
            result_files=[str(job.get("training_file") or "")],
        )
        db_create_fine_tuning_job_event(
            job_id,
            "Job completed successfully",
            data={"status": "succeeded", "fine_tuned_model": ft_model, "trained_tokens": trained_tokens},
        )
        try:
            from ..eval_pipeline import run_regression_benchmark

            suites = ["gsm8k", "arc", "safety"]
            hyperparams = job.get("hyperparameters") if isinstance(job.get("hyperparameters"), dict) else {}
            regression_provider = str(hyperparams.get("regression_provider") or "offline").strip() or "offline"
            regression = run_regression_benchmark(
                model=str(job.get("model") or "nexus-prime-base"),
                provider=regression_provider,
                suites=suites,
                threshold=0.05,
                n_samples=8,
            )
            db_create_fine_tuning_job_event(
                job_id,
                "Post-train regression benchmark completed",
                data={
                    "suites": suites,
                    "provider": regression_provider,
                    "overall_regression": bool(regression.get("overall_regression")),
                    "current_avg": regression.get("current_avg"),
                },
            )
        except Exception as exc:
            db_create_fine_tuning_job_event(
                job_id,
                "Post-train regression benchmark skipped",
                level="warning",
                data={"error": str(exc)[:300]},
            )
    except Exception as exc:
        db_update_fine_tuning_job(
            job_id,
            status="failed",
            finished_at=int(time.time()),
            error={"message": str(exc), "code": "fine_tuning_job_error"},
        )
        db_create_fine_tuning_job_event(
            job_id,
            "Job failed",
            level="error",
            data={"status": "failed", "error": str(exc)},
        )


@router.post("/v1/fine-tuning/jobs")
async def v1_create_fine_tuning_job(request: Request):
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

    init_db()
    job = FineTuningJob(
        model=payload.model,
        training_file=payload.training_file,
        validation_file=payload.validation_file,
        hyperparameters=payload.hyperparameters or {},
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(job["id"], "Job created", data={"status": "queued"})

    threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()
    return job


@router.get("/v1/fine-tuning/jobs")
def v1_list_fine_tuning_jobs(limit: int = 20, after: str = ""):
    init_db()
    safe_limit = min(max(int(limit or 20), 1), 100)
    items = db_list_fine_tuning_jobs(limit=safe_limit + 1, after=after)
    return {
        "object": "list",
        "data": items[:safe_limit],
        "has_more": len(items) > safe_limit,
    }


@router.get("/v1/fine-tuning/jobs/{job_id}")
def v1_get_fine_tuning_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)
    return job


@router.post("/v1/fine-tuning/jobs/{job_id}/cancel")
def v1_cancel_fine_tuning_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)

    if job.get("status") in {"succeeded", "failed", "cancelled"}:
        return job

    db_update_fine_tuning_job(
        job_id,
        status="cancelled",
        finished_at=int(time.time()),
        error={"message": "Cancelled by user", "code": "cancelled"},
    )
    db_create_fine_tuning_job_event(job_id, "Job cancelled", data={"status": "cancelled"})
    return db_get_fine_tuning_job(job_id)


@router.get("/v1/fine-tuning/jobs/{job_id}/events")
def v1_list_fine_tuning_job_events(job_id: str, limit: int = 100):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)

    events = db_list_fine_tuning_job_events(job_id, limit=limit)
    return {
        "object": "list",
        "data": [
            {
                "id": event.get("id"),
                "object": "fine_tuning.job.event",
                "created_at": int(event.get("created_at") or 0),
                "level": event.get("level", "info"),
                "message": event.get("message", ""),
                "data": event.get("data", {}),
            }
            for event in events
        ],
        "has_more": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 12 compatibility aliases (/finetune/jobs)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/finetune/jobs")
async def create_finetune_job(request: Request):
    """Create a persisted fine-tuning job with queued status."""
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    training_file = str(body.get("training_file") or "").strip()
    validation_file = str(body.get("validation_file") or "").strip() or None
    hyperparameters = body.get("hyperparameters") if isinstance(body.get("hyperparameters"), dict) else {}

    init_db()
    job = FineTuningJob(
        model=model,
        training_file=training_file,
        validation_file=validation_file,
        hyperparameters=hyperparameters,
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(job["id"], "Job created", data={"status": "queued"})
    threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()
    return {
        "id": job["id"],
        "status": job["status"],
        "model": job["model"],
        "training_file": job.get("training_file"),
        "validation_file": job.get("validation_file"),
        "created_at": job.get("created_at"),
        "object": "finetune.job",
    }


@router.get("/finetune/jobs")
def list_finetune_jobs(limit: int = 100, status: str = ""):
    init_db()
    safe_limit = max(1, min(int(limit), 500))
    rows = db_list_fine_tuning_jobs(limit=safe_limit)
    status_filter = (status or "").strip().lower()
    if status_filter:
        rows = [r for r in rows if str(r.get("status", "")).lower() == status_filter]
    return {
        "count": len(rows),
        "items": rows,
    }


@router.get("/finetune/jobs/{job_id}")
def get_finetune_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="finetune job not found")
    return job


@router.delete("/finetune/jobs/{job_id}")
def cancel_finetune_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="finetune job not found")

    if job.get("status") in {"queued", "running"}:
        db_update_fine_tuning_job(
            job_id,
            status="cancelled",
            finished_at=int(time.time()),
            error={"message": "Cancelled by user", "code": "cancelled"},
        )
        db_create_fine_tuning_job_event(job_id, "Job cancelled", data={"status": "cancelled"})

    return db_get_fine_tuning_job(job_id)


def _training_rows_from_feedback(include_trace: bool = True, limit: int = 5000) -> list[dict]:
    from ..db import load_feedback_export

    feedback_rows = load_feedback_export(limit=limit)
    trace_rows = _load_feedback_trace_events(limit=limit) if include_trace else []

    rows: list[dict] = []
    if trace_rows:
        for item in trace_rows:
            rows.append(
                {
                    "prompt": str(item.get("prompt") or ""),
                    "response": str(item.get("response") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                    "persona": str(item.get("persona") or ""),
                    "chat_id": str(item.get("chat_id") or ""),
                    "message_idx": int(item.get("message_idx") or 0),
                    "created_at": str(item.get("created_at") or ""),
                    "source": "trace",
                }
            )
    else:
        for item in feedback_rows:
            rows.append(
                {
                    "prompt": "",
                    "response": str(item.get("reaction") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                    "persona": "",
                    "chat_id": str(item.get("chat_id") or ""),
                    "message_idx": int(item.get("message_idx") or 0),
                    "created_at": str(item.get("ts") or ""),
                    "source": "reaction",
                }
            )
    return rows


def _dataset_checksum(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _create_finetune_job_from_rows(
    model: str,
    rows: list[dict],
    source: str,
    provenance_extra: dict | None = None,
    dataset_format: str = "jsonl",
    auto_start: bool = True,
) -> dict:
    from ..db import save_ft_dataset_version

    checksum = _dataset_checksum(rows)
    dataset_id = f"dsver-{uuid.uuid4().hex[:10]}"
    provenance = {
        "source": source,
        "row_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if isinstance(provenance_extra, dict):
        provenance.update(provenance_extra)

    dataset_version = save_ft_dataset_version(
        dataset_id=dataset_id,
        source=source,
        fmt=dataset_format,
        row_count=len(rows),
        provenance=provenance,
        checksum=checksum,
        preview_rows=rows,
    )

    training_file = f"inline://dataset/{dataset_id}"
    job = FineTuningJob(
        model=model,
        training_file=training_file,
        validation_file=None,
        hyperparameters={
            "dataset_version_id": dataset_id,
            "dataset_checksum": checksum,
            "provenance": provenance,
        },
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(
        job["id"],
        "Fine-tune created",
        data={"status": "queued", "dataset_version_id": dataset_id, "source": source},
    )
    if auto_start:
        threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()

    return {
        "job": {
            "id": job["id"],
            "status": job["status"],
            "model": job["model"],
            "training_file": training_file,
            "object": "finetune.job",
        },
        "dataset_version": dataset_version,
    }


@router.get("/finetune/adapters/active")
def get_active_finetune_adapter():
    from ..db import get_active_lora_adapter

    return {"active_adapter": get_active_lora_adapter()}


def _run_model_update_regression_gate(
    model: str,
    provider: str,
    suites: list[str] | None,
    threshold: float,
    n_samples: int,
    enforce: bool,
) -> dict:
    """Run regression benchmark for model-update actions and return gate metadata."""
    from ..eval_pipeline import run_regression_benchmark

    selected_suites = [str(s).strip() for s in (suites or ["gsm8k", "arc", "safety"]) if str(s).strip()]
    result = run_regression_benchmark(
        model=model,
        provider=provider,
        suites=selected_suites,
        threshold=float(threshold),
        n_samples=max(1, int(n_samples)),
    )
    rows = result.get("suite_results") if isinstance(result.get("suite_results"), list) else []
    avg_score = 0.0
    if rows:
        avg_score = sum(float(r.get("score") or 0.0) for r in rows) / max(1, len(rows))
    has_regression = not bool(result.get("ok", True))
    return {
        "enforced": bool(enforce),
        "allowed": (not has_regression) or (not bool(enforce)),
        "regression_count": int(result.get("regression_count") or 0),
        "has_regression": has_regression,
        "threshold": float(threshold),
        "provider": provider,
        "suites": selected_suites,
        "n_samples": max(1, int(n_samples)),
        "average_score": round(avg_score, 4),
        "benchmark": result,
    }


@router.get("/finetune/adapters")
def list_finetune_adapters(adapter_id: str = ""):
    from ..db import list_lora_adapter_versions

    rows = list_lora_adapter_versions(adapter_id=adapter_id)
    grouped = {}
    for row in rows:
        aid = str(row.get("adapter_id") or "")
        grouped.setdefault(aid, []).append(row)
    return {"adapters": grouped, "count": len(rows)}


@router.post("/finetune/adapters")
async def create_finetune_adapter_version(request: Request):
    from ..db import save_lora_adapter_version

    body = await _read_json_body(request, "invalid JSON body")
    adapter_id = str(body.get("adapter_id") or "").strip()
    version = str(body.get("version") or "").strip()
    base_model = str(body.get("base_model") or "nexus-prime-base").strip()
    checkpoint_uri = str(body.get("checkpoint_uri") or "").strip()
    if not adapter_id:
        return _api_error("adapter_id is required", "validation_error", 422)
    if not version:
        return _api_error("version is required", "validation_error", 422)
    if not checkpoint_uri:
        return _api_error("checkpoint_uri is required", "validation_error", 422)

    rec = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model=base_model,
        checkpoint_uri=checkpoint_uri,
        metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else {},
        provenance=body.get("provenance") if isinstance(body.get("provenance"), dict) else {},
        tags=body.get("tags") if isinstance(body.get("tags"), list) else [],
        status=str(body.get("status") or "ready"),
    )
    return {"adapter": rec}


@router.get("/finetune/adapters/{adapter_id}")
def get_finetune_adapter(adapter_id: str):
    from ..db import get_lora_adapter_version, list_lora_adapter_versions

    latest = get_lora_adapter_version(adapter_id=adapter_id)
    if latest is None:
        return _api_error("adapter not found", "not_found", 404)
    versions = list_lora_adapter_versions(adapter_id=adapter_id)
    return {"adapter_id": adapter_id, "latest": latest, "versions": versions}


@router.get("/finetune/adapters/{adapter_id}/versions/{version}")
def get_finetune_adapter_version(adapter_id: str, version: str):
    from ..db import get_lora_adapter_version

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)
    return {"adapter": row}


@router.get("/finetune/adapters/{adapter_id}/compare")
def compare_finetune_adapter_versions(adapter_id: str, left: str = "", right: str = ""):
    from ..db import compare_lora_adapter_versions

    if not left or not right:
        return _api_error("left and right version params are required", "validation_error", 422)
    diff = compare_lora_adapter_versions(adapter_id=adapter_id, left_version=left, right_version=right)
    if diff is None:
        return _api_error("adapter/version pair not found", "not_found", 404)
    return diff


@router.get("/finetune/adapters/{adapter_id}/proof-reports")
def list_finetune_adapter_proof_reports(adapter_id: str, version: str = "", limit: int = 20):
    from ..db import list_adapter_proof_reports

    rows = list_adapter_proof_reports(adapter_id=adapter_id, adapter_version=version, limit=limit)
    return {"proof_reports": rows, "count": len(rows)}


@router.post("/finetune/adapters/{adapter_id}/proof")
async def run_finetune_adapter_proof(adapter_id: str, request: Request):
    from ..db import get_lora_adapter_version
    from ..eval_pipeline import run_adapter_proof_report

    body = await _read_json_body(request, "invalid JSON body")
    version = str(body.get("version") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    try:
        report = run_adapter_proof_report(
            base_model=str(body.get("base_model") or row.get("base_model") or "nexus-prime-base"),
            adapter_id=adapter_id,
            adapter_version=version,
            provider=str(body.get("provider") or "offline"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            n_samples=int(body.get("n_samples") or 20),
            min_improvement=float(body.get("min_improvement") or 0.01),
            max_regressions=int(body.get("max_regressions") or 0),
            regression_threshold=float(body.get("regression_threshold") or 0.05),
        )
        return {"proof_report": report}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/finetune/adapters/{adapter_id}/promote")
async def promote_finetune_adapter(adapter_id: str, request: Request):
    from ..db import (
        get_adapter_proof_report,
        get_lora_adapter_version,
        list_adapter_proof_reports,
        update_lora_adapter_version,
    )

    body = await _read_json_body(request, "invalid JSON body")
    version = str(body.get("version") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    report_id = str(body.get("report_id") or "").strip()
    proof_report = get_adapter_proof_report(report_id) if report_id else None
    if proof_report is None:
        reports = list_adapter_proof_reports(adapter_id=adapter_id, adapter_version=version, limit=1)
        proof_report = reports[0] if reports else None
    if proof_report is None:
        return _api_error("no proof report found for adapter promotion", "proof_required", 409)
    if not bool(proof_report.get("passes", False)):
        return _api_error("adapter promotion blocked by proof gate", "proof_gate_failed", 409)

    updated = update_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        updates={
            "status": "promoted",
            "promotion_report_id": proof_report.get("report_id"),
            "promoted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    return {"promoted": True, "adapter": updated, "proof_report": proof_report}


@router.post("/finetune/adapters/{adapter_id}/hot-swap")
async def hot_swap_finetune_adapter(adapter_id: str, request: Request):
    from ..db import get_lora_adapter_version, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    if adapter_id == "multitask":
        from ..db import get_multitask_adapter_map, save_multitask_adapter_map

        task_name = str(body.get("task") or "").strip().lower()
        selected_adapter_id = str(body.get("adapter_id") or "").strip()
        selected_version = str(body.get("version") or "").strip()
        target_model = str(body.get("target_model") or "").strip()
        if not task_name or not selected_adapter_id or not selected_version:
            return _api_error("task, adapter_id and version are required", "validation_error", 422)

        selected = get_lora_adapter_version(adapter_id=selected_adapter_id, version=selected_version)
        if selected is None:
            return _api_error("adapter version not found", "not_found", 404)

        target_for_gate = target_model or str(selected.get("base_model") or "nexus-prime-base")
        gate_enabled = bool(body.get("run_regression_gate", True))
        gate_enforced = bool(body.get("enforce_regression_gate", True))
        regression_gate = None
        if gate_enabled:
            regression_gate = _run_model_update_regression_gate(
                model=target_for_gate,
                provider=str(body.get("provider") or "ollama"),
                suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
                threshold=float(body.get("threshold") or 0.05),
                n_samples=int(body.get("n_samples") or 8),
                enforce=gate_enforced,
            )
            if not bool(regression_gate.get("allowed", True)):
                return _api_error("regression gate blocked multitask adapter hot-swap", "regression_gate_failed", 409)

        current = get_multitask_adapter_map()
        mapping = current.get("mapping") if isinstance(current.get("mapping"), dict) else {}
        mapping[task_name] = {
            "adapter_id": selected_adapter_id,
            "version": selected_version,
            "target_model": target_model,
        }
        multitask = save_multitask_adapter_map(mapping)
        active = set_active_lora_adapter(
            adapter_id=selected_adapter_id,
            version=selected_version,
            target_model=target_model,
        )
        return {
            "task": task_name,
            "swapped": True,
            "active_adapter": active,
            "multitask_adapters": multitask,
            "adapter": selected,
            "regression_gate": regression_gate,
        }

    version = str(body.get("version") or "").strip()
    target_model = str(body.get("target_model") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)
    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    target_for_gate = target_model or str(row.get("base_model") or "nexus-prime-base")
    gate_enabled = bool(body.get("run_regression_gate", True))
    gate_enforced = bool(body.get("enforce_regression_gate", True))
    regression_gate = None
    if gate_enabled:
        regression_gate = _run_model_update_regression_gate(
            model=target_for_gate,
            provider=str(body.get("provider") or "ollama"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            threshold=float(body.get("threshold") or 0.05),
            n_samples=int(body.get("n_samples") or 8),
            enforce=gate_enforced,
        )
        if not bool(regression_gate.get("allowed", True)):
            return _api_error("regression gate blocked adapter hot-swap", "regression_gate_failed", 409)

    active = set_active_lora_adapter(adapter_id=adapter_id, version=version, target_model=target_model)
    return {
        "swapped": True,
        "active_adapter": active,
        "adapter": row,
        "note": "Hot-swap state recorded. Runtime model application is provider-dependent.",
        "regression_gate": regression_gate,
    }


@router.get("/finetune/datasets/versions")
def list_finetune_dataset_versions(limit: int = 100):
    from ..db import list_ft_dataset_versions

    rows = list_ft_dataset_versions(limit=limit)
    return {"dataset_versions": rows, "count": len(rows)}


@router.get("/finetune/datasets/versions/{dataset_id}")
def get_finetune_dataset_version(dataset_id: str):
    from ..db import get_ft_dataset_version

    row = get_ft_dataset_version(dataset_id)
    if row is None:
        return _api_error("dataset version not found", "not_found", 404)
    return {"dataset_version": row}


@router.post("/finetune/one-click")
async def one_click_finetune_from_feedback(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    include_trace = bool(body.get("include_trace", True))
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    limit = max(1, min(int(body.get("limit") or 5000), 20000))

    rows = _training_rows_from_feedback(include_trace=include_trace, limit=limit)
    if not rows:
        return _api_error("no feedback/trace rows available", "validation_error", 422)

    return _create_finetune_job_from_rows(
        model=model,
        rows=rows,
        source="feedback_trace",
        provenance_extra={"include_trace": include_trace},
    )


@router.post("/finetune/synthetic/generate")
async def generate_synthetic_training_data(request: Request):
    from ..db import save_synthetic_batch
    from ..simulation import SimulationEngine, export_training_dataset

    body = await _read_json_body(request, "invalid JSON body")
    topic = str(body.get("topic") or "Sovereign AI assistant capabilities").strip()
    seed = str(body.get("seed") or "").strip()
    n_samples = max(1, min(int(body.get("n_samples") or 16), 200))
    n_personas = max(2, min(int(body.get("n_personas") or 5), 8))
    n_rounds = max(1, min(int(body.get("n_rounds") or 3), 5))
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    include_vision = bool(body.get("include_vision", False))

    def _sim_llm(msgs):
        try:
            res, _ = call_llm_with_fallback(msgs, "synthetic_training_generation")
            if isinstance(res, dict):
                if res.get("action") == "respond":
                    return str(res.get("content") or "")
                return json.dumps(res)
            return str(res)
        except Exception:
            return "{\"statement\": \"Fallback synthetic statement\"}"

    rows: list[dict] = []
    try:
        engine = SimulationEngine(_sim_llm, max_personas=8, max_rounds=5)
        target_runs = max(1, min(n_samples // 4, 6))
        for idx in range(target_runs):
            sim = engine.run(
                topic=f"{topic} :: scenario {idx + 1}",
                seed=seed,
                n_personas=n_personas,
                n_rounds=n_rounds,
            )
            exported = export_training_dataset([sim.to_dict()])
            for item in exported:
                prompt = str(item.get("prompt") or "").strip()
                response = str(item.get("response") or "").strip()
                if not prompt or not response:
                    continue
                rows.append(
                    {
                        "prompt": prompt,
                        "response": response,
                        "source": "synthetic_swarm",
                        "topic": topic,
                        "modality": "vision_text" if include_vision else "text",
                    }
                )
                if len(rows) >= n_samples:
                    break
            if len(rows) >= n_samples:
                break
    except Exception:
        rows = []

    while len(rows) < n_samples:
        idx = len(rows) + 1
        rows.append(
            {
                "prompt": f"[{topic}] Generate a high-quality instruction #{idx} with grounded reasoning.",
                "response": (
                    f"Instruction #{idx} answer synthesized from multi-agent debate on {topic}. "
                    "Provide rationale, constraints, and verification steps."
                ),
                "source": "synthetic_swarm",
                "topic": topic,
                "modality": "vision_text" if include_vision else "text",
            }
        )

    for row in rows:
        db_save_ft_training_sample(
            task=str(row.get("prompt") or ""),
            result=str(row.get("response") or ""),
            quality=0.78,
            lessons=["synthetic", "agent_swarm"],
            source="synthetic_swarm",
        )

    bundle = _create_finetune_job_from_rows(
        model=model,
        rows=rows,
        source="synthetic",
        provenance_extra={
            "topic": topic,
            "seed": seed[:400],
            "n_personas": n_personas,
            "n_rounds": n_rounds,
            "include_vision": include_vision,
        },
    )
    batch_id = f"syn-{uuid.uuid4().hex[:10]}"
    batch = save_synthetic_batch(
        batch_id=batch_id,
        topic=topic,
        row_count=len(rows),
        params={
            "n_samples": n_samples,
            "n_personas": n_personas,
            "n_rounds": n_rounds,
            "include_vision": include_vision,
        },
        dataset_id=str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
    )
    return {"batch": batch, **bundle}


@router.get("/finetune/synthetic/batches")
def list_synthetic_training_batches(limit: int = 100):
    from ..db import list_synthetic_batches

    rows = list_synthetic_batches(limit=max(1, min(int(limit or 100), 500)))
    return {"batches": rows, "count": len(rows)}


@router.get("/finetune/curation/samples")
def list_curation_samples(limit: int = 100, min_quality: float = 0.0, source: str = "", approved: str = "", label: str = ""):
    from ..db import list_ft_sample_curation

    samples = db_list_ft_training_samples(limit=max(1, min(int(limit or 100), 1000)), min_quality=float(min_quality or 0.0))
    curation_map = list_ft_sample_curation()

    merged = []
    for row in samples:
        sample_id = str(row.get("id") or "")
        curation = curation_map.get(sample_id, {})
        if source and str(row.get("source") or "") != source:
            continue
        if approved.strip().lower() in {"true", "false"}:
            want = approved.strip().lower() == "true"
            if bool(curation.get("approved")) != want:
                continue
        if label and str(curation.get("label") or "").strip().lower() != label.strip().lower():
            continue
        merged.append({**row, "curation": curation})

    return {"samples": merged, "count": len(merged)}


@router.post("/finetune/curation/samples/{sample_id}/review")
async def review_curation_sample(sample_id: str, request: Request):
    from ..db import get_ft_sample_curation, upsert_ft_sample_curation

    body = await _read_json_body(request, "invalid JSON body")
    approved = body.get("approved")
    approved_val = bool(approved) if approved is not None else None
    label = str(body.get("label") or "").strip()
    notes = str(body.get("notes") or "").strip()
    reviewer = str(body.get("reviewer") or "system").strip() or "system"
    previous = get_ft_sample_curation(sample_id)
    row = upsert_ft_sample_curation(
        sample_id=sample_id,
        approved=approved_val,
        label=label,
        notes=notes,
        reviewer=reviewer,
    )
    return {"curation": row, "previous": previous}


@router.post("/finetune/curation/samples/bulk-approve")
async def bulk_approve_curation_samples(request: Request):
    from ..db import upsert_ft_sample_curation

    body = await _read_json_body(request, "invalid JSON body")
    sample_ids = body.get("sample_ids") if isinstance(body.get("sample_ids"), list) else []
    label = str(body.get("label") or "approved").strip()
    reviewer = str(body.get("reviewer") or "system").strip() or "system"
    updated = []
    for sample_id in sample_ids:
        sid = str(sample_id or "").strip()
        if not sid:
            continue
        updated.append(
            upsert_ft_sample_curation(
                sample_id=sid,
                approved=True,
                label=label,
                reviewer=reviewer,
            )
        )
    return {"updated": updated, "count": len(updated)}


@router.get("/finetune/curation/ui")
def finetune_curation_ui():
    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
        <title>Fine-tune Curation</title>
      </head>
      <body style=\"font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 24px;\">
        <h1>Training Sample Curation</h1>
        <p>Use API-backed filtering and one-click approval for Section 12 curation.</p>
        <button onclick=\"load()\">Reload Samples</button>
        <div id=\"count\" style=\"margin-top:12px;\"></div>
        <table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" style=\"margin-top:12px;width:100%;\">
          <thead><tr><th>ID</th><th>Source</th><th>Quality</th><th>Task</th><th>Approved</th><th>Label</th></tr></thead>
          <tbody id=\"rows\"></tbody>
        </table>
        <script>
          async function load() {
            const res = await fetch('/finetune/curation/samples?limit=50&min_quality=0.5');
            const data = await res.json();
            document.getElementById('count').textContent = `Loaded ${data.count || 0} samples`;
            const tbody = document.getElementById('rows');
            tbody.innerHTML = '';
            for (const s of (data.samples || [])) {
              const tr = document.createElement('tr');
              tr.innerHTML = `<td>${s.id}</td><td>${s.source || ''}</td><td>${(s.quality || 0).toFixed ? s.quality.toFixed(2) : s.quality}</td><td>${(s.task || '').slice(0,120)}</td><td>${s.curation?.approved === true}</td><td>${s.curation?.label || ''}</td>`;
              tbody.appendChild(tr);
            }
          }
          load();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/finetune/adapters/multitask")
def get_multitask_adapters():
    from ..db import get_multitask_adapter_map

    return get_multitask_adapter_map()


@router.post("/finetune/adapters/multitask")
async def set_multitask_adapters(request: Request):
    from ..db import get_lora_adapter_version, save_multitask_adapter_map

    body = await _read_json_body(request, "invalid JSON body")
    mapping = body.get("mapping") if isinstance(body.get("mapping"), dict) else {}
    normalized = {}
    for task_name, row in mapping.items():
        if not isinstance(row, dict):
            continue
        adapter_id = str(row.get("adapter_id") or "").strip()
        version = str(row.get("version") or "").strip()
        if not adapter_id or not version:
            continue
        if get_lora_adapter_version(adapter_id=adapter_id, version=version) is None:
            continue
        normalized[str(task_name).strip().lower()] = {
            "adapter_id": adapter_id,
            "version": version,
            "target_model": str(row.get("target_model") or "").strip(),
        }
    saved = save_multitask_adapter_map(normalized)
    return {"multitask_adapters": saved}


@router.post("/finetune/adapters/multitask/hot-swap")
async def hot_swap_multitask_adapter(request: Request):
    from ..db import get_lora_adapter_version, get_multitask_adapter_map, save_multitask_adapter_map, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    task_name = str(body.get("task") or "").strip().lower()
    adapter_id = str(body.get("adapter_id") or "").strip()
    version = str(body.get("version") or "").strip()
    target_model = str(body.get("target_model") or "").strip()
    if not task_name or not adapter_id or not version:
        return _api_error("task, adapter_id and version are required", "validation_error", 422)
    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    current = get_multitask_adapter_map()
    mapping = current.get("mapping") if isinstance(current.get("mapping"), dict) else {}
    mapping[task_name] = {
        "adapter_id": adapter_id,
        "version": version,
        "target_model": target_model,
    }
    saved = save_multitask_adapter_map(mapping)
    active = set_active_lora_adapter(adapter_id=adapter_id, version=version, target_model=target_model)
    return {"task": task_name, "active_adapter": active, "multitask_adapters": saved, "adapter": row}


@router.post("/finetune/multimodal/jobs")
async def create_multimodal_finetune_job(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    if not rows:
        return _api_error("rows is required and must be a non-empty list", "validation_error", 422)

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        response = str(row.get("response") or "").strip()
        image_url = str(row.get("image_url") or "").strip()
        image_b64 = str(row.get("image_b64") or "").strip()
        if not prompt or not response:
            continue
        if not image_url and not image_b64:
            continue
        normalized.append(
            {
                "prompt": prompt,
                "response": response,
                "image_url": image_url,
                "image_b64": bool(image_b64),
                "source": "multimodal_vision",
                "modality": "vision_text",
            }
        )

    if not normalized:
        return _api_error("no valid multimodal rows (requires prompt, response, image_url/image_b64)", "validation_error", 422)

    return _create_finetune_job_from_rows(
        model=model,
        rows=normalized,
        source="multimodal_vision",
        provenance_extra={"multimodal": True, "modality": "vision_text"},
    )


def _run_distill_job(job_id: str):
    from ..db import (
        append_distill_job_event,
        get_distill_job,
        save_lora_adapter_version,
        update_distill_job,
    )

    job = get_distill_job(job_id)
    if not job or str(job.get("status") or "") != "queued":
        return

    append_distill_job_event(job_id, "Distillation job started")
    update_distill_job(job_id, status="running")
    teacher = str(job.get("teacher_model") or "")
    student = str(job.get("student_model") or "nexus-prime-base")
    provider = str(job.get("provider") or "auto")
    cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
    prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), list) else []
    if not prompts:
        prompts = [
            "Explain how adapter hot-swap works in a sovereign deployment.",
            "Design a retry-safe continual fine-tune policy.",
            "Summarize RLHF vs DPO tradeoffs for local models.",
            "Provide robust guardrails for tool execution in an agent loop.",
        ]

    rows: list[dict] = []
    for prompt in prompts[:50]:
        p = str(prompt or "").strip()
        if not p:
            continue
        teacher_answer = ""
        try:
            teacher_messages = [{"role": "user", "content": p}]
            answer, _used_provider = call_llm_with_fallback(teacher_messages, "distillation", provider)
            if isinstance(answer, dict):
                teacher_answer = str(answer.get("content") or answer.get("result") or "").strip()
            else:
                teacher_answer = str(answer or "").strip()
        except Exception:
            teacher_answer = ""
        if not teacher_answer:
            teacher_answer = f"Teacher synthesis for: {p}"
        rows.append({"prompt": p, "response": teacher_answer, "source": "distillation", "teacher_model": teacher})

    if not rows:
        update_distill_job(job_id, status="failed", error={"message": "no distillation rows generated"})
        append_distill_job_event(job_id, "No rows generated", level="error")
        return

    bundle = _create_finetune_job_from_rows(
        model=student,
        rows=rows,
        source="distillation",
        provenance_extra={"teacher_model": teacher, "provider": provider, "distill_job_id": job_id},
    )
    ft_job_id = str(bundle.get("job", {}).get("id") or "")
    append_distill_job_event(job_id, "Fine-tune child job created", data={"fine_tune_job_id": ft_job_id})

    timeout_s = max(30, min(int(cfg.get("timeout_seconds") or 600), 3600))
    started = time.time()
    while time.time() - started <= timeout_s:
        current = get_distill_job(job_id)
        if not current or str(current.get("status") or "") == "cancelled":
            append_distill_job_event(job_id, "Distillation cancelled")
            return
        ft_job = db_get_fine_tuning_job(ft_job_id)
        if ft_job and str(ft_job.get("status") or "") in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.4)

    ft_job = db_get_fine_tuning_job(ft_job_id)
    status = str(ft_job.get("status") or "") if isinstance(ft_job, dict) else "failed"
    if status != "succeeded":
        update_distill_job(job_id, status="failed", error={"message": f"child fine-tune ended with {status}"})
        append_distill_job_event(job_id, "Child fine-tune failed", level="error", data={"status": status})
        return

    adapter_id = f"distill-{student.replace('/', '-') }"
    version = f"v{int(time.time())}"
    adapter = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model=student,
        checkpoint_uri=f"inline://adapters/{adapter_id}/{version}",
        metrics={"trained_tokens": int(ft_job.get("trained_tokens") or 0)},
        provenance={
            "distill_job_id": job_id,
            "teacher_model": teacher,
            "dataset_version_id": str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
        },
        tags=["distillation", "student"],
        status="ready",
    )
    result = {
        "fine_tune_job_id": ft_job_id,
        "dataset_version": bundle.get("dataset_version", {}),
        "adapter": adapter,
    }
    update_distill_job(job_id, status="succeeded", result=result, error=None)
    append_distill_job_event(job_id, "Distillation completed", data=result)


@router.post("/finetune/distill/jobs")
async def create_distillation_job(request: Request):
    from ..db import create_distill_job

    body = await _read_json_body(request, "invalid JSON body")
    teacher_model = str(body.get("teacher_model") or "").strip()
    student_model = str(body.get("student_model") or "nexus-prime-base").strip() or "nexus-prime-base"
    provider = str(body.get("provider") or "auto").strip() or "auto"
    if not teacher_model:
        return _api_error("teacher_model is required", "validation_error", 422)
    job = create_distill_job(
        teacher_model=teacher_model,
        student_model=student_model,
        provider=provider,
        config=body.get("config") if isinstance(body.get("config"), dict) else {},
    )
    threading.Thread(target=_run_distill_job, args=(job["id"],), daemon=True).start()
    return {"job": job}


@router.get("/finetune/distill/jobs")
def list_distillation_jobs(limit: int = 100):
    from ..db import list_distill_jobs

    rows = list_distill_jobs(limit=max(1, min(int(limit or 100), 500)))
    return {"jobs": rows, "count": len(rows)}


@router.get("/finetune/distill/jobs/{job_id}")
def get_distillation_job(job_id: str):
    from ..db import get_distill_job

    row = get_distill_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    return {"job": row}


@router.post("/finetune/distill/jobs/{job_id}/cancel")
def cancel_distillation_job(job_id: str):
    from ..db import get_distill_job, update_distill_job

    row = get_distill_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    if str(row.get("status") or "") not in {"succeeded", "failed", "cancelled"}:
        row = update_distill_job(job_id, status="cancelled", error={"message": "Cancelled by user"}) or row
    return {"job": row}


def _nexus_prime_alpha_wire_key() -> str:
    return "finetune.persona.nexus_prime_alpha.v1"


@router.get("/finetune/personas/nexus-prime-alpha/wire")
def get_nexus_prime_alpha_wiring():
    raw = db_load_pref(_nexus_prime_alpha_wire_key(), "{}")
    try:
        row = json.loads(raw)
        if not isinstance(row, dict):
            row = {}
    except Exception:
        row = {}
    return {"wiring": row}


@router.post("/finetune/personas/nexus-prime-alpha/wire")
async def wire_nexus_prime_alpha_persona(request: Request):
    from ..db import get_lora_adapter_version, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-alpha").strip() or "nexus-prime-alpha"
    adapter_id = str(body.get("adapter_id") or "").strip()
    adapter_version = str(body.get("adapter_version") or "").strip()
    provider_order = body.get("provider_order") if isinstance(body.get("provider_order"), list) else ["ollama", "llm7", "groq"]

    gate_enabled = bool(body.get("run_regression_gate", True))
    gate_enforced = bool(body.get("enforce_regression_gate", True))
    regression_gate = None
    if gate_enabled:
        regression_gate = _run_model_update_regression_gate(
            model=model,
            provider=str(body.get("provider") or "ollama"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            threshold=float(body.get("threshold") or 0.05),
            n_samples=int(body.get("n_samples") or 8),
            enforce=gate_enforced,
        )
        if not bool(regression_gate.get("allowed", True)):
            return _api_error("regression gate blocked nexus-prime-alpha wiring", "regression_gate_failed", 409)

    set_persona("nexus_prime_alpha")
    update_config(persona="nexus_prime_alpha", model=model)
    set_provider_persona_override("nexus_prime_alpha", [str(p).strip() for p in provider_order if str(p).strip()])

    active_adapter = {}
    if adapter_id and adapter_version:
        row = get_lora_adapter_version(adapter_id=adapter_id, version=adapter_version)
        if row is None:
            return _api_error("adapter not found", "not_found", 404)
        active_adapter = set_active_lora_adapter(adapter_id=adapter_id, version=adapter_version, target_model=model)

    wiring = {
        "persona": "nexus_prime_alpha",
        "model": model,
        "provider_order": provider_order,
        "active_adapter": active_adapter,
        "regression_gate": regression_gate,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    db_save_pref(_nexus_prime_alpha_wire_key(), json.dumps(wiring))
    return {"wired": True, "wiring": wiring}


@router.get("/models/{model_id}/card")
def get_model_card(model_id: str, markdown: bool = True):
    from ..eval_pipeline import generate_model_card, list_eval_jobs

    jobs = list_eval_jobs()
    card_md = generate_model_card(model=model_id, eval_results=jobs)
    if markdown:
        return {"model": model_id, "model_card": card_md, "format": "markdown"}

    rows = []
    for j in jobs:
        if str(j.model) != model_id:
            continue
        rows.append(
            {
                "task_id": j.task_id,
                "suite": j.suite,
                "score": j.score,
                "status": j.status,
                "regression": j.regression,
                "adapter_id": j.adapter_id,
            }
        )
    return {"model": model_id, "format": "json", "evaluations": rows}


@router.get("/models/{model_id}/transparency")
def get_model_transparency_report(model_id: str):
    from ..db import list_adapter_proof_reports, list_ft_dataset_versions, list_lora_adapter_versions
    from ..eval_pipeline import list_eval_jobs

    card = get_model_card(model_id=model_id, markdown=True)
    eval_rows = [
        {
            "task_id": j.task_id,
            "suite": j.suite,
            "score": j.score,
            "regression": j.regression,
            "created_at": j.created_at,
        }
        for j in list_eval_jobs()
        if str(j.model) == model_id
    ]
    datasets = [
        d
        for d in list_ft_dataset_versions(limit=500)
        if model_id in json.dumps(d.get("provenance") or {})
        or str(d.get("source") or "") in {"feedback_trace", "synthetic"}
    ]
    adapters = [a for a in list_lora_adapter_versions() if str(a.get("base_model") or "") == model_id]
    proof_reports = []
    for adapter in adapters[:100]:
        proof_reports.extend(
            list_adapter_proof_reports(
                adapter_id=str(adapter.get("adapter_id") or ""),
                adapter_version=str(adapter.get("version") or ""),
                limit=5,
            )
        )

    return {
        "model": model_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_card": card.get("model_card", ""),
        "evaluation_summary": {
            "count": len(eval_rows),
            "rows": eval_rows[:100],
        },
        "training_data_provenance": {
            "dataset_versions": datasets[:100],
            "count": len(datasets),
        },
        "adapter_lineage": {
            "versions": adapters[:100],
            "count": len(adapters),
        },
        "adapter_proof_reports": {
            "reports": proof_reports[:100],
            "count": len(proof_reports),
        },
        "limitations": [
            "Transparency report is derived from local registries and may omit external trainer state.",
            "Adapter application at runtime depends on provider backend support.",
        ],
    }


def _run_rlhf_dpo_job(job_id: str):
    from ..db import (
        append_rlhf_dpo_job_event,
        get_ft_dataset_version,
        get_rlhf_dpo_job,
        save_lora_adapter_version,
        update_rlhf_dpo_job,
    )
    from ..eval_pipeline import score_response
    from ..rlhf_dpo import (
        create_dpo_job as _create_native_dpo_job,
        create_rlhf_job as _create_native_rlhf_job,
        run_dpo_training as _run_native_dpo_training,
        run_rlhf_training as _run_native_rlhf_training,
    )

    def _build_preference_pair(row: dict) -> dict | None:
        prompt = str(row.get("prompt") or row.get("instruction") or "").strip()
        if not prompt:
            return None
        chosen = str(row.get("chosen") or row.get("response") or row.get("output") or "").strip()
        if not chosen:
            return None
        rejected = str(row.get("rejected") or "").strip()
        synthetic_negative = False
        if not rejected:
            synthetic_negative = True
            words = chosen.split()
            if len(words) > 6:
                rejected = " ".join(words[: max(3, len(words) // 3)])
            else:
                rejected = "Insufficient or incomplete answer."
        return {
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "synthetic_negative": synthetic_negative,
        }

    def _score_preference_pairs(pairs: list[dict]) -> dict:
        scored_rows: list[dict] = []
        chosen_total = 0.0
        rejected_total = 0.0
        margin_total = 0.0
        synthetic_negative_count = 0
        for idx, pair in enumerate(pairs, start=1):
            prompt = str(pair.get("prompt") or "")
            chosen = str(pair.get("chosen") or "")
            rejected = str(pair.get("rejected") or "")
            synthetic_negative = bool(pair.get("synthetic_negative"))
            if synthetic_negative:
                synthetic_negative_count += 1
            chosen_score = float(score_response(prompt, chosen, reference=chosen).get("score") or 0.0)
            rejected_score = float(score_response(prompt, rejected, reference=chosen).get("score") or 0.0)
            margin = round(chosen_score - rejected_score, 6)
            chosen_total += chosen_score
            rejected_total += rejected_score
            margin_total += margin
            scored_rows.append(
                {
                    "pair_id": idx,
                    "prompt": prompt,
                    "chosen_score": round(chosen_score, 6),
                    "rejected_score": round(rejected_score, 6),
                    "margin": margin,
                    "synthetic_negative": synthetic_negative,
                    "passed": margin > 0,
                }
            )

        pair_count = len(scored_rows)
        return {
            "pair_count": pair_count,
            "synthetic_negative_count": synthetic_negative_count,
            "chosen_avg": round(chosen_total / max(1, pair_count), 6),
            "rejected_avg": round(rejected_total / max(1, pair_count), 6),
            "preference_alignment_score": round(margin_total / max(1, pair_count), 6),
            "rows": scored_rows,
        }

    job = get_rlhf_dpo_job(job_id)
    if not job:
        return
    if str(job.get("status") or "") != "queued":
        return

    append_rlhf_dpo_job_event(job_id, "RLHF/DPO job started")
    update_rlhf_dpo_job(job_id, status="running", error=None)

    latest = get_rlhf_dpo_job(job_id)
    if not latest:
        return
    if str(latest.get("status") or "") == "cancelled":
        append_rlhf_dpo_job_event(job_id, "RLHF/DPO job cancelled before execution")
        return

    method = str(latest.get("method") or "dpo")
    base_model = str(latest.get("base_model") or "nexus-prime-base")
    dataset_version_id = str(latest.get("dataset_version_id") or "")
    config = latest.get("config") if isinstance(latest.get("config"), dict) else {}
    training_backend = str(config.get("training_backend") or "orchestration").strip().lower()
    if training_backend not in {"orchestration", "native"}:
        training_backend = "orchestration"
    telemetry_gates = {
        "min_pair_count": max(1, int(config.get("gate_min_pair_count") or 8)),
        "min_alignment_score": float(config.get("gate_min_alignment_score") or 0.02),
        "max_synthetic_negative_ratio": float(config.get("gate_max_synthetic_negative_ratio") or 0.75),
    }
    dataset = get_ft_dataset_version(dataset_version_id)
    if dataset is None:
        update_rlhf_dpo_job(job_id, status="failed", error={"message": "dataset_version_id not found"})
        append_rlhf_dpo_job_event(job_id, "Dataset not found", level="error", data={"dataset_version_id": dataset_version_id})
        return

    preview_rows = dataset.get("preview_rows") if isinstance(dataset.get("preview_rows"), list) else []
    preference_pairs = []
    for row in preview_rows[:200]:
        if isinstance(row, dict):
            pair = _build_preference_pair(row)
            if pair is not None:
                preference_pairs.append(pair)
    if not preference_pairs:
        update_rlhf_dpo_job(job_id, status="failed", error={"message": "dataset_version_id contains no usable preference rows"})
        append_rlhf_dpo_job_event(job_id, "No usable preference rows found", level="error", data={"dataset_version_id": dataset_version_id})
        return

    preference_metrics = _score_preference_pairs(preference_pairs)
    synthetic_ratio = float(preference_metrics["synthetic_negative_count"]) / max(1, float(preference_metrics["pair_count"]))
    gate_fail_reasons: list[str] = []
    if int(preference_metrics["pair_count"]) < int(telemetry_gates["min_pair_count"]):
        gate_fail_reasons.append(
            f"pair_count={preference_metrics['pair_count']} < min_pair_count={telemetry_gates['min_pair_count']}"
        )
    if float(preference_metrics["preference_alignment_score"]) < float(telemetry_gates["min_alignment_score"]):
        gate_fail_reasons.append(
            "preference_alignment_score="
            f"{preference_metrics['preference_alignment_score']} < min_alignment_score={telemetry_gates['min_alignment_score']}"
        )
    if synthetic_ratio > float(telemetry_gates["max_synthetic_negative_ratio"]):
        gate_fail_reasons.append(
            f"synthetic_negative_ratio={round(synthetic_ratio, 6)} > "
            f"max_synthetic_negative_ratio={telemetry_gates['max_synthetic_negative_ratio']}"
        )

    append_rlhf_dpo_job_event(
        job_id,
        "RLHF/DPO telemetry gates evaluated",
        data={
            "training_backend": training_backend,
            "telemetry_gates": telemetry_gates,
            "pair_count": preference_metrics["pair_count"],
            "preference_alignment_score": preference_metrics["preference_alignment_score"],
            "synthetic_negative_ratio": round(synthetic_ratio, 6),
            "gate_fail_reasons": gate_fail_reasons,
        },
    )

    if gate_fail_reasons:
        update_rlhf_dpo_job(
            job_id,
            status="failed",
            error={"message": "telemetry gates failed", "reasons": gate_fail_reasons},
            result={
                "training_backend": training_backend,
                "telemetry_gates": telemetry_gates,
                "pair_count": preference_metrics["pair_count"],
                "preference_alignment_score": preference_metrics["preference_alignment_score"],
                "synthetic_negative_ratio": round(synthetic_ratio, 6),
            },
        )
        append_rlhf_dpo_job_event(job_id, "RLHF/DPO telemetry gates failed", level="error", data={"reasons": gate_fail_reasons})
        return

    native_training_result: dict | None = None

    if training_backend == "native":
        import tempfile as _tempfile

        tmp_ds = os.path.join(_tempfile.gettempdir(), f"nexus_rlhf_dpo_{job_id}.jsonl")
        with open(tmp_ds, "w", encoding="utf-8") as f:
            for pair in preference_pairs:
                f.write(
                    json.dumps(
                        {
                            "prompt": pair["prompt"],
                            "chosen": pair["chosen"],
                            "rejected": pair["rejected"],
                            "margin": max(0.0, float(preference_metrics["preference_alignment_score"])),
                            "source": "rlhf_dpo_experiment",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        append_rlhf_dpo_job_event(
            job_id,
            "Native RLHF/DPO backend selected",
            data={"dataset_path": str(tmp_ds), "method": method},
        )

        if method == "dpo":
            native_job = _create_native_dpo_job(
                base_model=base_model,
                dataset_path=str(tmp_ds),
                adapter_name=f"{base_model.replace('/', '-')}-dpo-native",
                config=config,
            )
            _run_native_dpo_training(native_job)
            if native_job.status != "completed":
                update_rlhf_dpo_job(
                    job_id,
                    status="failed",
                    error={"message": f"native DPO backend failed: {native_job.error or native_job.status}"},
                )
                append_rlhf_dpo_job_event(job_id, "Native DPO backend failed", level="error", data={"job_id": native_job.job_id, "error": native_job.error})
                return
            native_training_result = {
                "native_job_id": native_job.job_id,
                "native_backend": "dpo",
                "adapter_path": native_job.adapter_path,
                "metrics": native_job.metrics,
            }
        else:
            native_job = _create_native_rlhf_job(
                base_model=base_model,
                dataset_path=str(tmp_ds),
                adapter_name=f"{base_model.replace('/', '-')}-rlhf-native",
                config=config,
            )
            _run_native_rlhf_training(native_job)
            if native_job.status != "completed":
                update_rlhf_dpo_job(
                    job_id,
                    status="failed",
                    error={"message": f"native RLHF backend failed: {native_job.error or native_job.status}"},
                )
                append_rlhf_dpo_job_event(job_id, "Native RLHF backend failed", level="error", data={"job_id": native_job.job_id, "error": native_job.error})
                return
            native_training_result = {
                "native_job_id": native_job.job_id,
                "native_backend": "rlhf",
                "adapter_path": native_job.adapter_path,
                "metrics": native_job.metrics,
                "rounds_completed": native_job.rounds_completed,
            }

    if training_backend == "orchestration":

        child = _create_finetune_job_from_rows(
        model=base_model,
        rows=[
            {
                "prompt": pair["prompt"],
                "response": pair["chosen"],
                "source": "rlhf_dpo",
                "preference_rejected": pair["rejected"],
                "synthetic_negative": pair["synthetic_negative"],
            }
            for pair in preference_pairs
        ],
        source="rlhf_dpo",
        provenance_extra={
            "method": method,
            "dataset_version_id": dataset_version_id,
            "rlhf_dpo_job_id": job_id,
            "config": latest.get("config") if isinstance(latest.get("config"), dict) else {},
            "pair_count": preference_metrics["pair_count"],
            "synthetic_negative_count": preference_metrics["synthetic_negative_count"],
        },
    )
        fine_tune_job_id = str(child.get("job", {}).get("id") or "")
        append_rlhf_dpo_job_event(job_id, "Fine-tune child job created", data={"fine_tune_job_id": fine_tune_job_id})

        timeout_seconds = 900
        started_at = time.time()
        while time.time() - started_at <= timeout_seconds:
            current = get_rlhf_dpo_job(job_id)
            if not current or str(current.get("status") or "") == "cancelled":
                append_rlhf_dpo_job_event(job_id, "RLHF/DPO job cancelled")
                return
            ft_job = db_get_fine_tuning_job(fine_tune_job_id)
            if ft_job and str(ft_job.get("status") or "") in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.4)

        ft_job = db_get_fine_tuning_job(fine_tune_job_id)
        if not ft_job:
            update_rlhf_dpo_job(job_id, status="failed", error={"message": "fine-tune child job missing"})
            append_rlhf_dpo_job_event(job_id, "Child fine-tune job missing", level="error")
            return
        ft_status = str(ft_job.get("status") or "")
        if ft_status != "succeeded":
            update_rlhf_dpo_job(
                job_id,
                status="failed",
                error={"message": f"fine-tune child job ended with status={ft_status}"},
                result={"fine_tune_job_id": fine_tune_job_id, "dataset_version_id": dataset_version_id},
            )
            append_rlhf_dpo_job_event(job_id, "Child fine-tune failed", level="error", data={"status": ft_status})
            return
    else:
        fine_tune_job_id = ""
        ft_job = {"trained_tokens": 0}

    adapter_id = f"{base_model.replace('/', '-')}-{method}"
    adapter_version = f"v{int(time.time())}"
    adapter = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=adapter_version,
        base_model=base_model,
        checkpoint_uri=f"inline://adapters/{adapter_id}/{adapter_version}",
        metrics={
            "preference_alignment_score": float(preference_metrics["preference_alignment_score"]),
            "preference_pair_count": int(preference_metrics["pair_count"]),
            "chosen_avg": float(preference_metrics["chosen_avg"]),
            "rejected_avg": float(preference_metrics["rejected_avg"]),
            "trained_tokens": int(ft_job.get("trained_tokens") or 0),
        },
        provenance={
            "method": method,
            "dataset_version_id": dataset_version_id,
            "rlhf_dpo_job_id": job_id,
            "fine_tune_job_id": fine_tune_job_id,
        },
        tags=["rlhf", method],
        status="ready",
    )
    result = {
        "preference_alignment_score": float(preference_metrics["preference_alignment_score"]),
        "pair_count": int(preference_metrics["pair_count"]),
        "chosen_avg": float(preference_metrics["chosen_avg"]),
        "rejected_avg": float(preference_metrics["rejected_avg"]),
        "synthetic_negative_count": int(preference_metrics["synthetic_negative_count"]),
        "preference_rows": preference_metrics["rows"][:25],
        "method": method,
        "training_backend": training_backend,
        "telemetry_gates": telemetry_gates,
        "synthetic_negative_ratio": round(synthetic_ratio, 6),
        "fine_tune_job_id": fine_tune_job_id,
        "dataset_version_id": dataset_version_id,
        "adapter": adapter,
    }
    if native_training_result is not None:
        result["native_training"] = native_training_result
    update_rlhf_dpo_job(
        job_id,
        status="succeeded",
        result=result,
        error=None,
    )
    append_rlhf_dpo_job_event(job_id, "RLHF/DPO job completed", data=result)


@router.post("/finetune/experiments/rlhf-dpo/jobs")
async def create_rlhf_dpo_experiment_job(request: Request):
    from ..db import create_rlhf_dpo_job, get_ft_dataset_version

    body = await _read_json_body(request, "invalid JSON body")
    method = str(body.get("method") or "dpo").strip().lower()
    if method not in {"rlhf", "dpo"}:
        return _api_error("method must be 'rlhf' or 'dpo'", "validation_error", 422)

    base_model = str(body.get("base_model") or "nexus-prime-base").strip()
    dataset_version_id = str(body.get("dataset_version_id") or "").strip()
    if not dataset_version_id:
        return _api_error("dataset_version_id is required", "validation_error", 422)
    if get_ft_dataset_version(dataset_version_id) is None:
        return _api_error("dataset_version_id not found", "not_found", 404)

    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    backend = str(config.get("training_backend") or "orchestration").strip().lower()
    if backend not in {"orchestration", "native"}:
        return _api_error("config.training_backend must be 'orchestration' or 'native'", "validation_error", 422)

    job = create_rlhf_dpo_job(
        method=method,
        base_model=base_model,
        dataset_version_id=dataset_version_id,
        config=config,
    )
    threading.Thread(target=_run_rlhf_dpo_job, args=(job["id"],), daemon=True).start()
    return {"job": job}


@router.get("/finetune/experiments/rlhf-dpo/jobs")
def list_rlhf_dpo_experiment_jobs(limit: int = 100):
    from ..db import list_rlhf_dpo_jobs

    rows = list_rlhf_dpo_jobs(limit=limit)
    return {"jobs": rows, "count": len(rows)}


@router.get("/finetune/experiments/rlhf-dpo/jobs/{job_id}")
def get_rlhf_dpo_experiment_job(job_id: str):
    from ..db import get_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    return {"job": row}


@router.get("/finetune/experiments/rlhf-dpo/jobs/{job_id}/events")
def list_rlhf_dpo_experiment_job_events(job_id: str, limit: int = 200):
    from ..db import get_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    events = row.get("events") if isinstance(row.get("events"), list) else []
    return {"job_id": job_id, "events": events[-max(1, int(limit)):], "count": len(events)}


@router.post("/finetune/experiments/rlhf-dpo/jobs/{job_id}/cancel")
def cancel_rlhf_dpo_experiment_job(job_id: str):
    from ..db import get_rlhf_dpo_job, update_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    if str(row.get("status") or "") not in {"succeeded", "failed", "cancelled"}:
        row = update_rlhf_dpo_job(job_id, status="cancelled", error={"message": "Cancelled by user"}) or row
    return {"job": row}


def _continual_policies_key() -> str:
    return "finetune.continual.policies.v1"


def _update_continual_policy(policy_id: str, updates: dict) -> dict | None:
    rows = _load_continual_policies()
    updated = None
    for idx, row in enumerate(rows):
        if str(row.get("id") or "") != str(policy_id):
            continue
        merged = dict(row)
        merged.update(dict(updates or {}))
        merged["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows[idx] = merged
        updated = merged
        break
    if updated is not None:
        _save_continual_policies(rows)
    return updated


def _execute_continual_re_tune_task(payload: dict) -> str:
    from ..eval_pipeline import run_eval_suite

    policy_id = str(payload.get("policy_id") or "").strip()
    model = str(payload.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    threshold = float(payload.get("threshold") or 0.05)
    suites = payload.get("suites") if isinstance(payload.get("suites"), list) else ["code", "autonomy", "rag"]
    n_samples = max(2, min(int(payload.get("n_samples") or 8), 64))
    provider = str(payload.get("provider") or "ollama")
    include_trace = bool(payload.get("include_trace", True))

    batch = run_eval_suite(model=model, provider=provider, suites=suites, n_samples=n_samples)
    avg_score = float(batch.get("average_score") or 0.0)
    has_regression = bool(batch.get("has_regression"))

    current_policy = None
    if policy_id:
        for row in _load_continual_policies():
            if str(row.get("id") or "") == policy_id:
                current_policy = row
                break
    prev_score = float(current_policy.get("last_average_score") or 0.0) if current_policy else 0.0
    delta = avg_score - prev_score

    updates = {
        "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_average_score": round(avg_score, 6),
        "last_delta": round(delta, 6),
        "run_count": int((current_policy or {}).get("run_count") or 0) + 1,
        "last_eval": {
            "suites": suites,
            "average_score": round(avg_score, 6),
            "has_regression": has_regression,
        },
    }
    if policy_id:
        _update_continual_policy(policy_id, updates)

    should_retune = (delta >= threshold) and (not has_regression)
    if not should_retune:
        return f"continual policy checked: avg={avg_score:.3f}, delta={delta:.3f}, threshold={threshold:.3f}, retune=no"

    rows = _training_rows_from_feedback(include_trace=include_trace, limit=5000)
    if not rows:
        return f"continual policy checked: avg={avg_score:.3f}, delta={delta:.3f}, retune_skipped=no_rows"

    try:
        bundle = _create_finetune_job_from_rows(
            model=model,
            rows=rows,
            source="continual_feedback_trace",
            provenance_extra={
                "policy_id": policy_id,
                "trigger_average_score": avg_score,
                "trigger_delta": delta,
                "include_trace": include_trace,
            },
        )
    except Exception as exc:
        err = str(exc)
        lowered = err.lower()
        transient_markers = ("cuda", "gpu", "out of memory", "nvidia", "resource", "capacity")
        if any(m in lowered for m in transient_markers):
            if policy_id:
                _update_continual_policy(
                    policy_id,
                    {
                        "last_trigger_error": err[:500],
                        "last_trigger_status": "deferred_capacity",
                    },
                )
            return (
                f"continual policy deferred: avg={avg_score:.3f}, delta={delta:.3f}, "
                f"reason={err[:160]}"
            )
        raise
    if policy_id:
        _update_continual_policy(
            policy_id,
            {
                "last_triggered_finetune_job_id": str(bundle.get("job", {}).get("id") or ""),
                "last_triggered_dataset_id": str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
                "retune_count": int((current_policy or {}).get("retune_count") or 0) + 1,
                "last_trigger_status": "triggered",
            },
        )
    return (
        f"continual policy triggered: avg={avg_score:.3f}, delta={delta:.3f}, "
        f"fine_tune_job_id={bundle.get('job', {}).get('id', '')}"
    )


def _load_continual_policies() -> list[dict]:
    raw = db_load_pref(_continual_policies_key(), "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_continual_policies(rows: list[dict]) -> None:
    db_save_pref(_continual_policies_key(), json.dumps(rows[-5000:]))


@router.post("/finetune/continual/schedule")
async def schedule_continual_finetune(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    schedule = str(body.get("schedule") or "0 3 * * 0").strip()
    threshold = float(body.get("threshold") or 0.05)
    suites = body.get("suites") if isinstance(body.get("suites"), list) else ["code", "autonomy", "rag"]
    n_samples = max(2, min(int(body.get("n_samples") or 8), 64))
    provider = str(body.get("provider") or "ollama").strip() or "ollama"
    include_trace = bool(body.get("include_trace", True))

    policy_id = str(uuid.uuid4())[:8]

    task_payload = {
        "op": "continual_re_tune",
        "policy_id": policy_id,
        "model": model,
        "threshold": threshold,
        "suites": suites,
        "n_samples": n_samples,
        "provider": provider,
        "include_trace": include_trace,
        "mode": "benchmark_then_one_click",
    }
    task = f"__finetune_continual__:{json.dumps(task_payload, separators=(',', ':'))}"
    try:
        job = schedule_job(
            name=f"continual-retune:{model}",
            task=task,
            schedule=schedule,
            max_retries=int(body.get("max_retries", 1)),
            retry_backoff_secs=int(body.get("retry_backoff_secs", 300)),
        )
    except Exception as exc:
        return _api_error(str(exc), "validation_error", 422)

    row = {
        "id": policy_id,
        "scheduler_job_id": job.id,
        "name": job.name,
        "model": model,
        "schedule": schedule,
        "threshold": threshold,
        "suites": suites,
        "n_samples": n_samples,
        "provider": provider,
        "include_trace": include_trace,
        "run_count": 0,
        "retune_count": 0,
        "last_average_score": 0.0,
        "last_delta": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scaffold": False,
    }
    policies = _load_continual_policies()
    policies = [p for p in policies if str(p.get("id") or "") != policy_id]
    policies.append(row)
    _save_continual_policies(policies)
    return {"policy": row, "scheduler_job": job_to_dict(job)}


@router.get("/finetune/continual/schedule")
def list_continual_finetune_schedules():
    return {
        "policies": _load_continual_policies(),
        "scheduler_jobs": [
            job_to_dict(j)
            for j in list_jobs()
            if str(getattr(j, "name", "")).startswith("continual-retune:")
        ],
    }


@router.delete("/finetune/continual/schedule/{policy_id}")
def delete_continual_finetune_schedule(policy_id: str):
    rows = _load_continual_policies()
    target = None
    for row in rows:
        if str(row.get("id") or "") == policy_id:
            target = row
            break
    kept = [r for r in rows if str(r.get("id") or "") != policy_id]
    _save_continual_policies(kept)
    scheduler_job_id = str((target or {}).get("scheduler_job_id") or policy_id)
    cancelled = cancel_job(scheduler_job_id)
    return {"deleted": policy_id, "scheduler_job_id": scheduler_job_id, "scheduler_cancelled": bool(cancelled)}


@router.post("/finetune/continual/schedule/{policy_id}/run-now")
def run_continual_finetune_schedule_now(policy_id: str):
    rows = _load_continual_policies()
    target = None
    for row in rows:
        if str(row.get("id") or "") == policy_id:
            target = row
            break
    if target is None:
        return _api_error("policy not found", "not_found", 404)
    payload = {
        "op": "continual_re_tune",
        "policy_id": policy_id,
        "model": target.get("model"),
        "threshold": target.get("threshold"),
        "suites": target.get("suites"),
        "n_samples": target.get("n_samples"),
        "provider": target.get("provider"),
        "include_trace": target.get("include_trace", True),
    }
    summary = _execute_continual_re_tune_task(payload)
    return {"policy_id": policy_id, "summary": summary}



# ─────────────────────────────────────────────────────────────────────────────
# Audio ingestion  — podcast / meeting transcript pipeline
# ─────────────────────────────────────────────────────────────────────────────
# POST /audio/ingest-transcript
#   Body: { "source": "<url or path>", "source_type": "youtube|audio_file|meeting_url", "metadata": {} }
#   Returns: ingestion result from audio.ingest_transcript
@router.post("/audio/ingest-transcript")
async def audio_ingest_transcript(request: Request):
    data        = await request.json()
    source      = data.get("source", "").strip()
    source_type = data.get("source_type", "audio_file")
    metadata    = data.get("metadata", {})
    if not source:
        return _api_error("source is required", "validation_error", 422)
    if source_type not in ("youtube", "audio_file", "meeting_url"):
        return _api_error("source_type must be youtube, audio_file, or meeting_url", "validation_error", 422)
    try:
        from ..audio import ingest_transcript
        result = ingest_transcript(source, source_type, metadata=metadata)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        return _api_error(str(exc), "ingest_error", 500)

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
    from ..benchmark import run_ollama_benchmark
    try:
        body = await request.json()
    except Exception:
        return _api_error("invalid JSON body", "validation_error", 400)
    result = run_ollama_benchmark(
        models=body.get("models") or None,
        prompt=str(body.get("prompt", "Say hello in one sentence.")),
        runs=int(body.get("runs", 3)),
        ollama_base=_ollama_base(),
    )
    if "error" in result and "models" not in result:
        return _api_error(result["error"], "validation_error", 422)
    return result


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


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — Agent Loop / Reflection / Autonomy SSE / Task Queue
# ═══════════════════════════════════════════════════════════════════════════════

# ── Agent reflection ──────────────────────────────────────────────────────────

@router.post("/agent/reflect")
async def agent_reflect(request: Request):
    """Run a reflection/retrospective loop on a completed task."""
    body = await request.json()
    task        = str(body.get("task", ""))
    result      = str(body.get("result", ""))
    tool_trace  = body.get("tool_trace", [])

    if not task:
        return _api_error("'task' is required", "invalid_request_error", 400)

    from ..thinking import build_reflection_prompt, parse_reflection_response
    prompt = build_reflection_prompt(task, result, tool_trace or [])
    try:
        raw_resp, provider = call_llm_with_fallback([{"role": "user", "content": prompt}], task)
    except Exception as exc:
        return _api_error(f"LLM call failed: {exc}", "model_error", 502)

    raw_text = raw_resp.get("content") or str(raw_resp)
    parsed = parse_reflection_response(raw_text)
    sample_id = db_save_ft_training_sample(
        task=task,
        result=result,
        quality=float(parsed.get("quality_score", 0.7) or 0.7),
        lessons=list(parsed.get("lessons", []) or []),
        source="reflection",
    )
    return {
        "task":         task,
        "reflection":   parsed,
        "provider": provider,
        "fine_tuning_sample_id": sample_id,
        "raw_response": raw_text,
    }


# ── Autonomy SSE streaming ─────────────────────────────────────────────────────

@router.post("/autonomy/execute/stream")
async def autonomy_execute_stream(request: Request):
    """Stream autonomy execution events via SSE."""
    body = await request.json()
    goal         = str(body.get("goal", "")).strip()
    strategy     = str(body.get("strategy", "parallel"))
    max_subtasks = int(body.get("max_subtasks", 6))
    sid          = str(body.get("sid", ""))
    trace_id     = secrets.token_hex(8)

    if not goal:
        return _api_error("'goal' is required", "invalid_request_error", 400)

    import queue as _queue
    event_queue: "_queue.Queue[dict | None]" = _queue.Queue()
    checkpoint_events: List[Dict[str, Any]] = []

    def _run_autonomy():
        try:
            orchestrator = Orchestrator(llm=_orchestrator_llm)
            start_evt = {"type": "autonomy_start", "goal": goal, "trace_id": trace_id}
            checkpoint_events.append(start_evt)
            _save_autonomy_checkpoint(trace_id, 0, goal, checkpoint_events)
            event_queue.put(start_evt)
            result = orchestrator.execute(goal, context={"strategy": strategy, "max_subtasks": max_subtasks, "sid": sid})
            result["trace_id"] = trace_id
            for idx, subtask in enumerate(result.get("subtasks", []), 1):
                evt = {"type": "subtask_done", "trace_id": trace_id, "subtask": subtask}
                checkpoint_events.append(evt)
                _save_autonomy_checkpoint(trace_id, idx, goal, checkpoint_events)
                event_queue.put(evt)
            done_evt = {
                "type": "autonomy_done",
                "trace_id": trace_id,
                "result": result.get("result", ""),
                "plan_summary": result.get("plan_summary", ""),
                "execution_time": result.get("execution_time", 0),
            }
            checkpoint_events.append(done_evt)
            _save_autonomy_checkpoint(trace_id, len(checkpoint_events), goal, checkpoint_events)
            autonomy_traces[trace_id] = {"type": "execution_stream", "goal": goal, "status": "done", **result}
            db_save_autonomy_trace(trace_id, autonomy_traces[trace_id])
            event_queue.put(done_evt)
        except Exception as exc:
            err_evt = {"type": "error", "trace_id": trace_id, "error": str(exc)}
            checkpoint_events.append(err_evt)
            _save_autonomy_checkpoint(trace_id, len(checkpoint_events), goal, checkpoint_events)
            event_queue.put(err_evt)
        finally:
            event_queue.put(None)  # sentinel

    threading.Thread(target=_run_autonomy, daemon=True).start()

    async def _gen():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, event_queue.get)
            if event is None:
                yield "data: [DONE]\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Trace-Id": trace_id},
    )


# ── Task queue routes ─────────────────────────────────────────────────────────

@router.post("/tasks/queue")
async def task_queue_submit(request: Request):
    """Submit a task to the priority queue."""
    from ..task_queue import submit_task, start_worker
    body          = await request.json()
    description   = str(body.get("description", "")).strip()
    priority      = int(body.get("priority", 5))
    deps          = body.get("deps", [])
    metadata      = body.get("metadata", {})
    schedule_cron = str(body.get("schedule_cron", ""))
    dedupe        = bool(body.get("dedupe", True))

    if not description:
        return _api_error("'description' is required", "invalid_request_error", 400)

    start_worker()
    task_id = submit_task(
        description=description,
        priority=priority,
        deps=list(deps) if isinstance(deps, list) else [],
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
        schedule_cron=schedule_cron,
        dedupe=dedupe,
    )
    return {"task_id": task_id, "status": "pending", "dedupe": dedupe}


@router.delete("/tasks/queue/{task_id}")
async def task_queue_cancel(task_id: str):
    """Cancel a pending or running task."""
    from ..task_queue import cancel_task
    cancelled = cancel_task(task_id)
    if not cancelled:
        return _api_error(f"Task '{task_id}' not found or already terminal", "not_found_error", 404)
    return {"task_id": task_id, "cancelled": True}


@router.get("/tasks/queue")
async def task_queue_list(request: Request):
    """List tasks (optionally filtered by status)."""
    from ..task_queue import list_tasks
    status = request.query_params.get("status", "")
    limit  = int(request.query_params.get("limit", 50))
    return {"tasks": list_tasks(status=status, limit=limit)}


@router.get("/tasks/queue/dag")
async def task_queue_dag():
    """Return current DAG state (blocked/ready/running/done)."""
    from ..task_queue import get_dag_status
    return get_dag_status()


@router.get("/tasks/queue/{task_id}")
async def task_queue_get(task_id: str):
    """Get a single task by ID."""
    from ..task_queue import get_task
    task = get_task(task_id)
    if task is None:
        return _api_error(f"Task '{task_id}' not found", "not_found_error", 404)
    return task


# ── Task queue shared memory ──────────────────────────────────────────────────

@router.get("/tasks/memory")
async def task_memory_list():
    """List all cross-task shared memory entries."""
    from ..task_queue import list_shared_memory
    return {"memory": list_shared_memory()}


@router.get("/tasks/memory/{key}")
async def task_memory_get(key: str):
    """Get a single shared memory entry."""
    from ..task_queue import get_shared_memory
    value = get_shared_memory(key)
    if value is None:
        return _api_error(f"Key '{key}' not found", "not_found_error", 404)
    return {"key": key, "value": value}


@router.put("/tasks/memory/{key}")
async def task_memory_set(key: str, request: Request):
    """Set a shared memory entry."""
    from ..task_queue import set_shared_memory
    body  = await request.json()
    value = body.get("value")
    set_shared_memory(key, value)
    return {"key": key, "value": value}


@router.delete("/tasks/memory/{key}")
async def task_memory_delete(key: str):
    """Delete a shared memory entry."""
    from ..task_queue import delete_shared_memory
    deleted = delete_shared_memory(key)
    if not deleted:
        return _api_error(f"Key '{key}' not found", "not_found_error", 404)
    return {"key": key, "deleted": True}


# ── Task worker control ───────────────────────────────────────────────────────

@router.get("/tasks/worker/status")
async def task_worker_status():
    """Return task worker status (running, queue depth, active tasks)."""
    from ..task_queue import worker_status
    return worker_status()


@router.post("/tasks/worker/start")
async def task_worker_start():
    """Start the background task worker."""
    from ..task_queue import start_worker
    start_worker()
    return {"started": True}


@router.post("/tasks/worker/stop")
async def task_worker_stop():
    """Stop the background task worker."""
    from ..task_queue import stop_worker
    stop_worker()
    return {"stopped": True}


# ── Simulation scenario library & comparison ─────────────────────────────────

@router.get("/simulation/scenarios")
async def simulation_scenarios():
    """List pre-built simulation scenario templates."""
    from ..simulation import SCENARIO_LIBRARY
    return {
        "scenarios": [
            {"id": k, "topic": v["topic"], "n_personas": v.get("n_personas", 5),
             "n_rounds": v.get("n_rounds", 3)}
            for k, v in SCENARIO_LIBRARY.items()
        ]
    }


@router.post("/simulation/compare")
async def simulation_compare(request: Request):
    """A/B diff two simulation results."""
    from ..simulation import compare_simulations
    body  = await request.json()
    sim_a = body.get("sim_a")
    sim_b = body.get("sim_b")
    if not sim_a or not sim_b:
        return _api_error("Both 'sim_a' and 'sim_b' are required", "invalid_request_error", 400)
    return compare_simulations(sim_a, sim_b)


@router.post("/simulation/export-training")
async def simulation_export_training(request: Request):
    """Export simulation results as a fine-tuning training dataset."""
    from ..simulation import export_training_dataset
    body    = await request.json()
    results = body.get("results", [])
    if not isinstance(results, list) or not results:
        return _api_error("'results' must be a non-empty array", "invalid_request_error", 400)
    dataset = export_training_dataset(results)
    return {"count": len(dataset), "dataset": dataset}



# =============================================================================
# Section 1 additions — Health probes, metrics, feature flags,
# MFA, org management, audit log, circuit breaker admin, cache admin
# =============================================================================

import time as _time


# ─────────────────────────────────────────────────────────────────────────────
# Enhanced health endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health/live")
def health_live():
    """Kubernetes liveness probe — always 200 while the process is alive."""
    return {"status": "alive", "ts": _time.time()}


@router.get("/health/ready")
def health_ready():
    """Kubernetes readiness probe — 200 when DB is reachable."""
    try:
        from ..db import _sql_fetchall
        _sql_fetchall("SELECT 1")
        return {"status": "ready", "ts": _time.time()}
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "error": str(exc)}, status_code=503)


@router.get("/health/deep")
def health_deep():
    """Deep health check — database, Redis, vector store, and provider connectivity."""
    import urllib.request
    results: dict = {"ts": _time.time()}

    # DB check
    try:
        from ..db import _sql_fetchall
        _sql_fetchall("SELECT 1")
        results["db"] = "ok"
    except Exception as exc:
        results["db"] = f"error: {exc}"

    # Redis check
    try:
        from ..redis_state import redis_health
        results["redis"] = redis_health()
    except Exception as exc:
        results["redis"] = f"error: {exc}"

    # Vector store (ChromaDB) check
    try:
        import chromadb
        from ..memory import _get_chroma_client
        client = _get_chroma_client()
        client.heartbeat()
        results["vector_store"] = "ok"
    except Exception as exc:
        try:
            # Fallback: try instantiating the RAG vector store directly
            from ..rag.rag_system import get_rag_system
            rag = get_rag_system()
            vs = getattr(rag, "vector_store", None)
            if vs is not None:
                results["vector_store"] = "ok"
            else:
                results["vector_store"] = "unavailable"
        except Exception as exc2:
            results["vector_store"] = f"error: {exc2}"

    # Provider reachability check (attempt a lightweight HTTP probe on the active provider)
    try:
        from ..agent import PROVIDERS, _has_key, _provider_api_key
        reachable: dict = {}
        probe_providers = {
            "ollama": ("http", str(__import__("os").getenv("OLLAMA_BASE_URL", "http://localhost:11434")) + "/api/tags"),
            "groq": ("https", "https://api.groq.com/openai/v1/models"),
            "openai": ("https", "https://api.openai.com/v1/models"),
            "gemini": ("https", "https://generativelanguage.googleapis.com/v1beta/models"),
        }
        for pid, (scheme, url) in probe_providers.items():
            cfg = PROVIDERS.get(pid)
            if not cfg or not _has_key(cfg):
                continue
            try:
                api_key = _provider_api_key(cfg)
                req = urllib.request.Request(url, method="GET")
                if api_key and pid != "ollama":
                    req.add_header("Authorization", f"Bearer {api_key}")
                req.add_header("User-Agent", "NexusAI-HealthProbe/1.0")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    reachable[pid] = "ok" if resp.status < 500 else f"http_{resp.status}"
            except Exception as e:
                reachable[pid] = f"error: {type(e).__name__}"
        results["providers"] = reachable if reachable else {"note": "no configured providers probed"}
    except Exception as exc:
        results["providers"] = f"error: {exc}"

    overall = "healthy" if results.get("db") == "ok" else "degraded"
    results["status"] = overall
    status_code = 200 if overall == "healthy" else 503
    return JSONResponse(results, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Prometheus metrics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/metrics")
def prometheus_metrics(request: Request):
    """Expose Prometheus metrics text."""
    try:
        from ..observability import get_prometheus_metrics_text
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            get_prometheus_metrics_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


# ─────────────────────────────────────────────────────────────────────────────
# API changelog
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/changelog")
def api_changelog():
    """Return API version changelog."""
    return {
        "versions": [
            {
                "version": "1.0.0",
                "date": "2025-01",
                "changes": ["Initial OpenAI-compatible API layer"],
            },
            {
                "version": "1.1.0",
                "date": "2025-06",
                "changes": [
                    "Added /health/live, /health/ready, /health/deep probes",
                    "Added /metrics Prometheus endpoint",
                    "Added MFA routes",
                    "Added org management routes",
                    "Added feature flag admin routes",
                    "Added circuit breaker admin routes",
                    "Added audit log routes",
                ],
            },
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# MFA routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/auth/mfa/setup")
async def mfa_setup(request: Request):
    """Generate a TOTP secret and return the provisioning URI."""
    username = require_auth(request)
    try:
        import pyotp  # type: ignore
        import qrcode  # type: ignore
        import base64, io
    except ImportError:
        return JSONResponse({"error": "MFA dependencies not installed"}, status_code=501)

    from ..db import save_mfa_secret, get_mfa_secret
    secret = pyotp.random_base32()
    save_mfa_secret(username, secret)
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="Nexus AI")

    # Generate QR code as base64 PNG
    try:
        qr = qrcode.make(uri)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        qr_b64 = ""

    return {"secret": secret, "uri": uri, "qr_png_base64": qr_b64}


@router.post("/auth/mfa/enroll")
async def mfa_enroll_alias(request: Request):
    """Alias for MFA enrollment endpoint (compat with feature contract)."""
    return await mfa_setup(request)


@router.post("/auth/mfa/verify")
async def mfa_verify(request: Request):
    """Verify TOTP code and enable MFA if correct."""
    username = require_auth(request)
    try:
        import pyotp  # type: ignore
    except ImportError:
        return JSONResponse({"error": "MFA dependencies not installed"}, status_code=501)

    body = await request.json()
    code = str(body.get("code", "")).strip()
    if not code:
        return _api_error("'code' is required", "invalid_request_error", 400)

    from ..db import get_mfa_secret, enable_mfa, save_mfa_recovery_codes
    import hashlib, secrets as _sec
    record = get_mfa_secret(username)
    if not record:
        return _api_error("MFA not set up", "invalid_request_error", 400)

    totp = pyotp.TOTP(record["secret"])
    if not totp.verify(code, valid_window=1):
        return _api_error("Invalid code", "invalid_mfa_code", 400)

    enable_mfa(username)

    # Generate recovery codes
    codes = [_sec.token_hex(8).upper() for _ in range(8)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    save_mfa_recovery_codes(username, hashes)

    return {"mfa_enabled": True, "recovery_codes": codes}


@router.delete("/auth/mfa")
async def mfa_disable(request: Request):
    """Disable MFA for the authenticated user."""
    username = require_auth(request)
    from ..db import disable_mfa
    disable_mfa(username)
    return {"mfa_enabled": False}


@router.post("/auth/mfa/disable")
async def mfa_disable_alias(request: Request):
    """Alias for MFA disable endpoint (compat with feature contract)."""
    return await mfa_disable(request)


@router.get("/auth/mfa/status")
async def mfa_status(request: Request):
    """Return MFA status for the authenticated user."""
    username = require_auth(request)
    from ..db import get_mfa_secret
    record = get_mfa_secret(username)
    return {
        "username": username,
        "mfa_enabled": bool(record and record.get("enabled")),
    }


@router.get("/auth/trusted-devices")
async def trusted_devices_list(request: Request):
    """List trusted devices for the authenticated user."""
    username = require_auth(request)
    from ..db import list_trusted_devices

    return {"devices": list_trusted_devices(username)}


@router.post("/auth/trusted-devices")
async def trusted_devices_add(request: Request):
    """Add current request device as trusted for authenticated user."""
    username = require_auth(request)
    from ..db import save_trusted_device

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    label = str((body or {}).get("label") or request.headers.get("User-Agent", ""))[:120]
    save_trusted_device(username, _device_hash(request), label=label)
    return {"trusted": True, "device_hash": _device_hash(request)}


@router.delete("/auth/trusted-devices/{device_hash}")
async def trusted_devices_remove(device_hash: str, request: Request):
    """Remove a trusted device hash for authenticated user."""
    username = require_auth(request)
    from ..db import remove_trusted_device

    remove_trusted_device(username, device_hash)
    return {"removed": True, "device_hash": device_hash}


@router.post("/admin/users/{username}/unlock-login")
async def admin_unlock_login(username: str, request: Request):
    """Admin endpoint to clear login lockout state for a user."""
    require_admin(request)
    from ..db import clear_login_attempts

    clear_login_attempts(username)
    return {"username": username, "unlocked": True}


@router.post("/auth/mfa/recovery-codes")
async def mfa_recovery_codes(request: Request):
    """Regenerate one-time MFA recovery codes for an authenticated user."""
    username = require_auth(request)
    from ..db import get_mfa_secret, save_mfa_recovery_codes
    import hashlib
    import secrets as _sec

    record = get_mfa_secret(username)
    if not record or not record.get("enabled"):
        return _api_error("MFA must be enabled first", "invalid_request_error", 400)

    codes = [_sec.token_hex(8).upper() for _ in range(8)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    save_mfa_recovery_codes(username, hashes)
    return {"recovery_codes": codes}


# ─────────────────────────────────────────────────────────────────────────────
# Organisation routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orgs")
async def create_org(request: Request):
    """Create a new organisation."""
    username = require_auth(request)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return _api_error("'name' is required", "invalid_request_error", 400)
    from ..orgs import create_org as _create_org
    try:
        org = _create_org(name, username, plan=body.get("plan", "free"))
        return org
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)


@router.get("/orgs")
async def list_orgs(request: Request):
    """List organisations the current user belongs to."""
    username = require_auth(request)
    from ..orgs import get_user_orgs
    return {"orgs": get_user_orgs(username)}


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, request: Request):
    """Get a single organisation."""
    username = require_auth(request)
    from ..orgs import get_org as _get_org, require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    org = _get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    return org


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, request: Request):
    """Update an organisation."""
    username = require_auth(request)
    from ..orgs import update_org as _update_org, require_org_membership
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    org = _update_org(org_id, **body)
    return org or JSONResponse({"error": "org not found"}, status_code=404)


@router.delete("/orgs/{org_id}")
async def delete_org(org_id: str, request: Request):
    """Delete an organisation (admin only)."""
    username = require_auth(request)
    from ..orgs import delete_org as _delete_org, require_org_membership, get_org
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username and _get_token_role(request) != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    _delete_org(org_id)
    return {"deleted": True}


@router.get("/orgs/{org_id}/members")
async def list_org_members(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, list_members
    try:
        require_org_membership(org_id, username)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    return {"members": list_members(org_id)}


@router.post("/orgs/{org_id}/members")
async def add_org_member(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, add_member
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    username = str(body.get("username", "")).strip()
    role = str(body.get("role", "member"))
    if not username:
        return _api_error("'username' is required", "invalid_request_error", 400)
    try:
        member = add_member(org_id, username, role=role)
        return member
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)


@router.delete("/orgs/{org_id}/members/{username}")
async def remove_org_member(org_id: str, username: str, request: Request):
    requester = require_auth(request)
    from ..orgs import require_org_membership, remove_member
    try:
        require_org_membership(org_id, requester, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    remove_member(org_id, username)
    return {"removed": True}


@router.get("/orgs/{org_id}/usage")
async def org_usage_dashboard(org_id: str, request: Request):
    """Org-level usage with member quota breakdown and aggregate rollups."""
    username = require_auth(request)
    from ..orgs import require_org_membership, list_members, get_org_quota
    from ..profiles import get_quota_state

    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)

    members = list_members(org_id)
    member_usage = []
    total_tokens_used = 0
    total_requests_used = 0
    total_token_limit = 0
    total_request_limit = 0
    for m in members:
        member_username = str(m.get("username", ""))
        quota = get_quota_state(member_username)
        total_tokens_used += int(quota.get("tokens_used_today", 0) or 0)
        total_requests_used += int(quota.get("requests_used_today", 0) or 0)
        total_token_limit += int(quota.get("tokens_limit_day", 0) or 0)
        total_request_limit += int(quota.get("requests_limit_day", 0) or 0)
        member_usage.append(
            {
                "username": member_username,
                "role": m.get("role", "member"),
                "tokens_used_today": int(quota.get("tokens_used_today", 0) or 0),
                "tokens_limit_day": int(quota.get("tokens_limit_day", 0) or 0),
                "requests_used_today": int(quota.get("requests_used_today", 0) or 0),
                "requests_limit_day": int(quota.get("requests_limit_day", 0) or 0),
                "reset_at": quota.get("reset_at"),
            }
        )

    return {
        "org_id": org_id,
        "org_quota": get_org_quota(org_id),
        "usage": {
            "tokens_used_today": total_tokens_used,
            "tokens_limit_day": total_token_limit,
            "requests_used_today": total_requests_used,
            "requests_limit_day": total_request_limit,
        },
        "members": member_usage,
        "member_count": len(member_usage),
    }


@router.post("/orgs/{org_id}/invites")
async def create_org_invite(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, create_invite
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    invite = create_invite(
        org_id,
        invited_by=username,
        email=body.get("email", ""),
        role=body.get("role", "member"),
    )
    return invite


@router.post("/orgs/invites/accept")
async def accept_org_invite(request: Request):
    username = require_auth(request)
    from ..orgs import accept_invite
    body = await request.json()
    token = str(body.get("token", "")).strip()
    if not token:
        return _api_error("'token' is required", "invalid_request_error", 400)
    try:
        result = accept_invite(token, username)
        return result
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)


# ─────────────────────────────────────────────────────────────────────────────
# Feature flag admin routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/flags")
async def list_feature_flags(request: Request):
    require_admin(request)
    from ..feature_flags import list_flags
    return {"flags": list_flags()}


@router.get("/admin/flags/{flag_name}")
async def get_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..feature_flags import list_flags
    from ..db import load_feature_flag
    flag = load_feature_flag(flag_name)
    if not flag:
        return JSONResponse({"error": "flag not found"}, status_code=404)
    return flag


@router.post("/admin/flags/{flag_name}")
async def set_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..feature_flags import set_flag
    body = await request.json()
    flag = set_flag(
        flag_name,
        enabled=bool(body.get("enabled", False)),
        description=body.get("description", ""),
        rollout_percentage=int(body.get("rollout_percentage", 0)),
        user_overrides=body.get("user_overrides"),
        org_overrides=body.get("org_overrides"),
        value=body.get("value"),
    )
    return flag


@router.delete("/admin/flags/{flag_name}")
async def delete_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..feature_flags import delete_flag
    deleted = delete_flag(flag_name)
    return {"deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# Audit log (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/audit-log")
async def admin_audit_log(request: Request):
    require_admin(request)
    from ..db import list_audit_log
    params = dict(request.query_params)
    limit = int(params.get("limit", 100))
    actor = params.get("actor", "")
    action = params.get("action", "")
    return {"entries": list_audit_log(limit=limit, actor=actor, action=action)}


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker admin routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/circuit-breakers")
async def list_circuit_breakers(request: Request):
    require_admin(request)
    try:
        from ..circuit_breaker import all_circuit_status
        return {"circuit_breakers": all_circuit_status()}
    except ImportError:
        return {"circuit_breakers": []}


@router.post("/admin/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(name: str, request: Request):
    require_admin(request)
    try:
        from ..circuit_breaker import reset_circuit
        reset = reset_circuit(name)
        return {"name": name, "reset": reset}
    except ImportError:
        return JSONResponse({"error": "circuit_breaker module not available"}, status_code=503)


# ─────────────────────────────────────────────────────────────────────────────
# Cache admin routes
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/admin/cache/{cache_key}")
async def invalidate_cache_key(cache_key: str, request: Request):
    require_admin(request)
    try:
        from ..redis_state import cache_invalidate
        cache_invalidate(cache_key)
        return {"invalidated": cache_key}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@router.post("/admin/cache/flush")
async def flush_cache(request: Request):
    require_admin(request)
    body = await request.json()
    prefix = body.get("prefix", "")
    try:
        from ..redis_state import flush_prefix, flush_all
        if prefix:
            n = flush_prefix(prefix)
            return {"flushed": n, "prefix": prefix}
        else:
            flush_all()
            return {"flushed": "all"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


# ─────────────────────────────────────────────────────────────────────────────
# GDPR / data deletion
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/privacy/data-deletion-request")
async def privacy_data_deletion_request(request: Request):
    """Handle GDPR/CCPA right-to-erasure requests.

    Supports immediate execution against existing cascade delete primitives.
    Body:
      {
        "regulation": "gdpr|ccpa|both",
        "subject_type": "user|org",
        "subject_id": "<username|org_id>",
        "confirm": true,
        "reason": "optional"
      }
    """
    actor = require_auth(request)
    body = await _read_json_body(request)

    regulation = str(body.get("regulation", "gdpr")).strip().lower()
    if regulation not in {"gdpr", "ccpa", "both"}:
        return _api_error("regulation must be one of: gdpr, ccpa, both", "validation_error", 422)

    subject_type = str(body.get("subject_type", "user")).strip().lower()
    if subject_type not in {"user", "org"}:
        return _api_error("subject_type must be one of: user, org", "validation_error", 422)

    subject_id = str(body.get("subject_id") or actor).strip()
    if not subject_id:
        return _api_error("subject_id is required", "validation_error", 422)

    if not bool(body.get("confirm", False)):
        return _api_error("confirm=true is required to execute data deletion", "validation_error", 422)

    reason = str(body.get("reason", "")).strip()[:500]
    request_id = f"delreq_{uuid.uuid4().hex[:12]}"

    try:
        deleted: dict
        if subject_type == "user":
            if subject_id != actor:
                require_admin(request)
            from ..db import delete_user_data as _delete_user_data
            deleted = _delete_user_data(subject_id)
            resource = f"user:{subject_id}"
        else:
            from ..orgs import get_org
            from ..db import delete_org_data as _delete_org_data
            org = get_org(subject_id)
            if not org:
                return _api_error("org not found", "not_found", 404)
            if org.get("owner") != actor:
                require_admin(request)
            deleted = _delete_org_data(subject_id)
            resource = f"org:{subject_id}"

        try:
            write_audit_log(
                actor=actor,
                action="privacy_data_deletion_request",
                resource=resource,
                metadata={
                    "request_id": request_id,
                    "regulation": regulation,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "reason": reason,
                    "deleted": deleted,
                },
            )
        except Exception:
            pass

        return {
            "request_id": request_id,
            "status": "completed",
            "regulation": regulation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "requested_by": actor,
            "deleted": deleted,
        }
    except HTTPException:
        raise
    except Exception as exc:
        return _api_error(f"failed to process data deletion request: {exc}", "server_error", 500)

@router.delete("/admin/users/{username}/data")
async def delete_user_data(username: str, request: Request):
    """
    GDPR right-to-erasure endpoint (admin only).
    Cascades across: DB tables, ChromaDB memory, memory JSON store, RAG corpus,
    and all Redis session / token / refresh keys for the user.
    """
    require_admin(request)
    from ..db import delete_user_data as _delete_user_data
    result = _delete_user_data(username)

    # ── Purge Redis session keys for this user ─────────────────────────────
    try:
        _r = _get_redis()
        if _r is not None:
            # Keys created by _redis_track_session / _redis_save_refresh
            pattern_sessions = f"nexus:sessions:{username}"
            pattern_refresh = f"nexus:refresh:{username}:*"
            # Remove session set
            _r.delete(pattern_sessions)
            # Remove all refresh tokens for the user
            refresh_keys = _r.keys(pattern_refresh)
            if refresh_keys:
                _r.delete(*refresh_keys)
            result["redis_sessions"] = 1
    except Exception:
        pass

    try:
        actor = require_auth(request)
        write_audit_log(
            actor=actor if isinstance(actor, str) else str(actor.get("username", "admin")),
            action="gdpr_delete",
            resource=f"user:{username}",
            metadata=result,
        )
    except Exception:
        pass
    return {"username": username, "deleted": result}


def _get_current_user(request: Request) -> str:
    """Extract username from request auth, returns '' on failure."""
    try:
        user = require_auth(request)
        return user.get("username", "")
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Org GDPR export + cascading delete
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/orgs/{org_id}/export")
async def export_org_data(org_id: str, request: Request):
    """
    Export all org data as a portable JSON bundle (GDPR data portability).
    Only org owners or admins may call this.
    """
    username = require_auth(request)
    from ..db import get_org, export_org_data as _export_org_data
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)  # raises if not admin
    bundle = _export_org_data(org_id)
    write_audit_log(
        actor=username,
        action="org_data_export",
        resource=f"org:{org_id}",
        metadata={"record_count": sum(len(v) if isinstance(v, list) else 1 for v in bundle.values())},
    )
    return JSONResponse(bundle)


@router.delete("/orgs/{org_id}/data")
async def delete_org_data(org_id: str, request: Request):
    """
    Cascading GDPR erasure of all org data.
    Only org owners or admins may call this.
    """
    username = require_auth(request)
    from ..db import get_org, delete_org_data as _delete_org_data
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    result = _delete_org_data(org_id)
    write_audit_log(
        actor=username,
        action="org_data_delete",
        resource=f"org:{org_id}",
        metadata=result,
    )
    return {"org_id": org_id, "deleted": result}


# ─────────────────────────────────────────────────────────────────────────────
# Org-scoped API keys
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orgs/{org_id}/api-keys")
async def create_org_api_key_route(org_id: str, request: Request):
    """Create a new org-scoped API key. Caller must be org owner or admin."""
    username = require_auth(request)
    from ..db import get_org, create_org_api_key, list_org_api_keys
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)

    body = await _read_json_body(request)
    name = str(body.get("name") or "").strip()
    scopes = body.get("scopes") or []
    if not name:
        return _api_error("'name' is required", "invalid_request_error", 400)
    if not isinstance(scopes, list):
        return _api_error("'scopes' must be an array", "invalid_request_error", 400)

    raw_key = "nxk_org_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    key_id = secrets.token_hex(16)
    now = time.time()

    create_org_api_key(
        key_id=key_id,
        org_id=org_id,
        created_by=username,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        scopes=json.dumps(scopes),
        created_at=now,
    )
    write_audit_log(actor=username, action="org_api_key_create", resource=f"org:{org_id}/key:{key_id}", metadata={"name": name})
    return {"id": key_id, "key": raw_key, "prefix": key_prefix, "name": name, "scopes": scopes, "created_at": now}


@router.get("/orgs/{org_id}/api-keys")
async def list_org_api_keys_route(org_id: str, request: Request):
    """List org API keys (never returns hashes)."""
    username = require_auth(request)
    from ..db import get_org, list_org_api_keys
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    keys = list_org_api_keys(org_id)
    return {"keys": keys}


@router.delete("/orgs/{org_id}/api-keys/{key_id}")
async def revoke_org_api_key_route(org_id: str, key_id: str, request: Request):
    """Revoke an org API key."""
    username = require_auth(request)
    from ..db import get_org, revoke_org_api_key
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    revoke_org_api_key(key_id=key_id, org_id=org_id)
    write_audit_log(actor=username, action="org_api_key_revoke", resource=f"org:{org_id}/key:{key_id}", metadata={})
    return {"id": key_id, "revoked": True}


# ─────────────────────────────────────────────────────────────────────────────
# WebAuthn / Passkey routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/auth/webauthn/register")
async def webauthn_register_begin(request: Request):
    """Begin WebAuthn registration ceremony — returns PublicKeyCredentialCreationOptions."""
    username = require_auth(request)
    try:
        from webauthn import generate_registration_options
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria, UserVerificationRequirement
        import json as _json

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        rp_name = os.getenv("WEBAUTHN_RP_NAME", "Nexus AI")
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_name=username,
            user_display_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        import base64 as _b64
        challenge_b64 = _b64.urlsafe_b64encode(options.challenge).rstrip(b"=").decode()
        # Persist challenge in Redis with 5-minute TTL
        try:
            from ..redis_state import get_redis
            get_redis().set(f"nexus:webauthn_challenge:{username}", challenge_b64, ex=300)
        except Exception:
            pass

        from webauthn.helpers.cose import COSEAlgorithmIdentifier
        return JSONResponse({
            "rp": {"id": rp_id, "name": rp_name},
            "user": {"name": username, "displayName": username, "id": username},
            "challenge": challenge_b64,
            "timeout": 60000,
            "attestation": "none",
        })
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)


@router.post("/auth/webauthn/register/complete")
async def webauthn_register_complete(request: Request):
    """Complete WebAuthn registration — stores credential."""
    username = require_auth(request)
    try:
        from webauthn import verify_registration_response
        from webauthn.helpers.structs import RegistrationCredential
        import base64 as _b64

        body = await _read_json_body(request)
        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        expected_origin = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

        # Fetch challenge from Redis
        expected_challenge = b""
        try:
            from ..redis_state import get_redis
            raw = get_redis().get(f"nexus:webauthn_challenge:{username}")
            if raw:
                expected_challenge = _b64.urlsafe_b64decode(raw + "==")
        except Exception:
            pass

        if not expected_challenge:
            return _api_error("registration challenge expired or not found", "invalid_request_error", 400)

        credential = RegistrationCredential.parse_raw(json.dumps(body))
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin,
            require_user_verification=False,
        )
        device_name = str(body.get("deviceName") or request.headers.get("User-Agent", "")[:80])
        from ..db import save_webauthn_credential
        save_webauthn_credential(
            credential_id=verification.credential_id.hex(),
            username=username,
            public_key=_b64.b64encode(verification.credential_public_key).decode(),
            sign_count=int(verification.sign_count),
            device_name=device_name,
        )
        write_audit_log(actor=username, action="webauthn_credential_registered", resource="auth/webauthn", metadata={"device": device_name[:40]})
        return {"registered": True}
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)
    except Exception as exc:
        return _api_error(f"WebAuthn verification failed: {exc}", "invalid_request_error", 400)


@router.post("/auth/webauthn/authenticate")
async def webauthn_authenticate_begin(request: Request):
    """Begin WebAuthn authentication — returns PublicKeyCredentialRequestOptions."""
    try:
        from webauthn import generate_authentication_options
        from webauthn.helpers.structs import UserVerificationRequirement
        import base64 as _b64

        body = await _read_json_body(request)
        username = str(body.get("username") or "").strip()
        if not username:
            return _api_error("'username' is required", "invalid_request_error", 400)

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        from ..db import list_webauthn_credentials
        stored_creds = list_webauthn_credentials(username)
        if not stored_creds:
            return _api_error("no passkeys registered for this user", "invalid_request_error", 404)

        options = generate_authentication_options(
            rp_id=rp_id,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        challenge_b64 = _b64.urlsafe_b64encode(options.challenge).rstrip(b"=").decode()
        try:
            from ..redis_state import get_redis
            get_redis().set(f"nexus:webauthn_auth_challenge:{username}", challenge_b64, ex=300)
        except Exception:
            pass
        return JSONResponse({
            "challenge": challenge_b64,
            "timeout": 60000,
            "rpId": rp_id,
            "allowCredentials": [{"id": c["credential_id"], "type": "public-key"} for c in stored_creds],
            "userVerification": "preferred",
        })
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)


@router.post("/auth/webauthn/authenticate/complete")
async def webauthn_authenticate_complete(request: Request):
    """Complete WebAuthn authentication — issues JWT on success."""
    try:
        from webauthn import verify_authentication_response
        from webauthn.helpers.structs import AuthenticationCredential
        import base64 as _b64

        body = await _read_json_body(request)
        username = str(body.get("username") or "").strip()
        if not username:
            return _api_error("'username' is required", "invalid_request_error", 400)

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        expected_origin = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

        expected_challenge = b""
        try:
            from ..redis_state import get_redis
            raw = get_redis().get(f"nexus:webauthn_auth_challenge:{username}")
            if raw:
                expected_challenge = _b64.urlsafe_b64decode(raw + "==")
        except Exception:
            pass

        if not expected_challenge:
            return _api_error("authentication challenge expired or not found", "invalid_request_error", 400)

        from ..db import get_webauthn_credential, update_webauthn_sign_count
        credential_id = str(body.get("id") or "").replace("-", "").lower()
        stored_cred = get_webauthn_credential(credential_id)
        if not stored_cred or stored_cred.get("username") != username:
            return _api_error("credential not found", "unauthorized", 401)

        credential = AuthenticationCredential.parse_raw(json.dumps(body))
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin,
            credential_public_key=_b64.b64decode(stored_cred["public_key"]),
            credential_current_sign_count=int(stored_cred.get("sign_count", 0)),
            require_user_verification=False,
        )
        update_webauthn_sign_count(credential_id, int(verification.new_sign_count))
        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        _register_user_session(username, token, refresh_token, request)
        write_audit_log(actor=username, action="webauthn_login", resource="auth/webauthn", metadata={"credential_id": credential_id[:16]})
        return {"token": token, "refresh_token": refresh_token, "username": username}
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)
    except Exception as exc:
        return _api_error(f"WebAuthn authentication failed: {exc}", "unauthorized", 401)


# ─────────────────────────────────────────────────────────────────────────────
# SAML 2.0 enterprise SSO routes
# ─────────────────────────────────────────────────────────────────────────────

def _get_saml_client(provider: str):
    """Build a pysaml2 Saml2Client for the given provider slug."""
    from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
    from saml2.client import Saml2Client
    from saml2.config import Config as Saml2Config

    idp_metadata_url = os.getenv(f"SAML_{provider.upper()}_IDP_METADATA_URL", "")
    sp_entity_id = os.getenv(f"SAML_{provider.upper()}_SP_ENTITY_ID", f"nexus-ai-{provider}")
    acs_url = os.getenv(f"SAML_{provider.upper()}_ACS_URL", f"https://localhost/auth/saml/{provider}/acs")

    if not idp_metadata_url:
        raise ValueError(f"SAML provider '{provider}' not configured (missing IDP_METADATA_URL)")

    settings = {
        "entityid": sp_entity_id,
        "service": {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [
                        (acs_url, BINDING_HTTP_POST),
                    ],
                },
                "allow_unsolicited": True,
                "authn_requests_signed": False,
                "want_assertions_signed": True,
            }
        },
        "metadata": {"remote": [{"url": idp_metadata_url}]},
    }
    cfg = Saml2Config()
    cfg.load(settings)
    return Saml2Client(config=cfg)


@router.get("/auth/saml/{provider}/login")
async def saml_login(provider: str, request: Request):
    """Initiate SAML 2.0 authentication — redirects to IdP."""
    try:
        from saml2 import BINDING_HTTP_REDIRECT
        client = _get_saml_client(provider)
        relay_state = secrets.token_hex(16)
        session_id, info = client.prepare_for_authenticate(relay_state=relay_state)
        from ..db import save_saml_session_v2
        save_saml_session_v2(
            session_id=session_id,
            provider=provider,
            relay_state=relay_state,
            expires_at=time.time() + 600,
        )
        redirect_url = dict(info["headers"]).get("Location", "")
        if not redirect_url:
            return JSONResponse({"error": "failed to generate SAML redirect"}, status_code=500)
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=redirect_url, status_code=302)
    except ImportError:
        return JSONResponse({"error": "SAML support not installed (pysaml2)"}, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": f"SAML init failed: {exc}"}, status_code=500)


@router.post("/auth/saml/{provider}/acs")
async def saml_acs(provider: str, request: Request):
    """SAML Assertion Consumer Service — processes SAMLResponse, issues JWT."""
    try:
        from saml2 import BINDING_HTTP_POST
        client = _get_saml_client(provider)
        form = await request.form()
        saml_response_raw = str(form.get("SAMLResponse", ""))
        relay_state = str(form.get("RelayState", ""))
        if not saml_response_raw:
            return JSONResponse({"error": "missing SAMLResponse"}, status_code=400)

        authn_response = client.parse_authn_request_response(
            saml_response_raw,
            BINDING_HTTP_POST,
        )
        if not authn_response:
            return JSONResponse({"error": "invalid SAML response"}, status_code=401)

        nameid = str(authn_response.get_subject() or "")
        ava = authn_response.ava or {}
        # Map NameID / attribute to username
        email = str(ava.get("email", [nameid])[0] if ava.get("email") else nameid)
        username = email.split("@")[0] if "@" in email else email
        if not username:
            return JSONResponse({"error": "could not determine username from SAML response"}, status_code=401)

        # Ensure user exists locally (auto-provision SAML users)
        from ..db import get_user, save_user
        if not get_user(username):
            auto_pw_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            save_user(username, auto_pw_hash, role="user", source="saml")

        # Link SAML session
        session_id = str(authn_response.in_response_to or relay_state)
        from ..db import complete_saml_session
        complete_saml_session(session_id=session_id, username=username, nameid=nameid)

        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        # Return tokens as JSON; the frontend should handle the redirect
        write_audit_log(actor=username, action="saml_login", resource=f"auth/saml/{provider}", metadata={"nameid": nameid[:40]})
        return {"token": token, "refresh_token": refresh_token, "username": username}
    except ImportError:
        return JSONResponse({"error": "SAML support not installed (pysaml2)"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": f"SAML ACS failed: {exc}"}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# Per-org data isolation endpoints
# Provide org-scoped views over chats, usage, memory, and RAG corpus.
# Callers must be an org member with at least viewer role.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/orgs/{org_id}/chats")
async def org_chats(org_id: str, limit: int = 200, request: Request = None):
    """Return all chats belonging to members of this org (scoped to org_id)."""
    username = require_auth(request)
    from ..db import get_org_chats as _get_org_chats
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    chats = _get_org_chats(org_id, limit=max(1, min(int(limit), 1000)))
    return {"org_id": org_id, "chats": chats, "count": len(chats)}


@router.get("/orgs/{org_id}/chats/history")
async def org_chats_history(org_id: str, days: int = 30, request: Request = None):
    """Return org-scoped usage timeline (alias for usage, chat-focused view)."""
    username = require_auth(request)
    from ..db import get_org_usage as _get_org_usage
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    rows = _get_org_usage(org_id, days=max(1, min(int(days), 90)))
    return {"org_id": org_id, "days": days, "rows": rows, "count": len(rows)}


@router.get("/orgs/{org_id}/memory")
async def org_memory(org_id: str, limit: int = 100, request: Request = None):
    """Return memory entries tagged to this org (per-org isolation)."""
    username = require_auth(request)
    from ..db import get_org_memory_entries as _get_org_memory
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    entries = _get_org_memory(org_id, limit=max(1, min(int(limit), 500)))
    return {"org_id": org_id, "entries": entries, "count": len(entries)}


@router.get("/orgs/{org_id}/rag/documents")
async def org_rag_documents(org_id: str, request: Request = None):
    """Return all RAG corpus documents tagged with this org_id."""
    username = require_auth(request)
    from ..db import get_org_rag_documents as _get_org_rag
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    docs = _get_org_rag(org_id)
    return {"org_id": org_id, "documents": docs, "count": len(docs)}


@router.post("/orgs/{org_id}/rag/ingest")
async def org_rag_ingest(org_id: str, request: Request):
    """Ingest a document into the RAG corpus tagged with this org_id."""
    username = require_auth(request)
    from ..db import ingest_rag_for_org as _ingest_org_rag
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="editor")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await _read_json_body(request)
    text = str(body.get("text") or "").strip()
    source = str(body.get("source") or "")
    metadata = body.get("metadata") or {}
    if not text:
        return _api_error("'text' is required", "invalid_request_error", 400)
    if not isinstance(metadata, dict):
        return _api_error("'metadata' must be an object", "invalid_request_error", 400)
    ok = _ingest_org_rag(text, org_id=org_id, source=source, metadata=metadata)
    if not ok:
        return JSONResponse({"error": "RAG ingest failed or RAG not configured"}, status_code=503)
    write_audit_log(actor=username, action="org_rag_ingest", resource=f"org:{org_id}")
    return {"status": "ingested", "org_id": org_id, "source": source}


# ── Swarm health and control ──────────────────────────────────────────────────

# Module-level swarm pause flag
_swarm_paused: bool = False


@router.get("/swarm/health")
def swarm_health():
    """Return a health summary of all known agents in the swarm.

    Uses the activity log to classify each agent as idle, busy, or errored
    based on recent events.
    """
    from ..agent_bus import all_agents, get_bus
    bus = get_bus()

    # Derive agent states from the last N activity events
    recent = activity_log[-200:]
    agent_state: dict[str, str] = {}
    for event in reversed(recent):
        agent_id = str(event.get("agent") or event.get("agent_id") or "")
        if not agent_id or agent_id in agent_state:
            continue
        event_type = str(event.get("type") or "").lower()
        if "error" in event_type or "fail" in event_type:
            agent_state[agent_id] = "errored"
        elif "start" in event_type or "run" in event_type:
            agent_state[agent_id] = "busy"
        else:
            agent_state[agent_id] = "idle"

    # Also include agents with messages in bus inbox
    for aid in all_agents():
        if aid not in agent_state:
            unread = bus.unread_count(aid)
            agent_state[aid] = "busy" if unread > 0 else "idle"

    counts: dict[str, int] = {"idle": 0, "busy": 0, "errored": 0, "unknown": 0}
    for state in agent_state.values():
        counts[state if state in counts else "unknown"] += 1

    return {
        "paused":  _swarm_paused,
        "agents":  [{"id": aid, "state": state} for aid, state in agent_state.items()],
        "summary": counts,
        "total":   len(agent_state),
    }


@router.post("/swarm/pause")
def swarm_pause():
    """Pause the swarm — signals agents to stop accepting new tasks."""
    global _swarm_paused
    _swarm_paused = True
    return {"paused": True, "message": "Swarm paused. Existing tasks will complete."}


@router.post("/swarm/resume")
def swarm_resume():
    """Resume the swarm after a pause."""
    global _swarm_paused
    _swarm_paused = False
    return {"paused": False, "message": "Swarm resumed."}


# ── Blueprint execution, export, and import ───────────────────────────────────

@router.post("/architecture/blueprints/{name}/execute")
async def execute_architecture_blueprint(name: str, request: Request):
    """Execute a blueprint — spawn the specialist agents it defines.

    Publishes a task message on the agent bus for each agent role in the
    blueprint's agent_layer.  Returns a list of dispatched task message IDs.

    POST body (optional):
        task     — override task description sent to each agent
        version  — specific blueprint version to execute (default: latest)
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    version = int(body.get("version", 0)) or None
    task    = str(body.get("task") or "Execute blueprint workflow").strip()

    from ..db import load_architecture_blueprint
    blueprint = load_architecture_blueprint(name, version=version)
    if not blueprint:
        return _api_error(f"Blueprint '{name}' not found", "not_found", 404)

    if _swarm_paused:
        return _api_error("Swarm is paused — resume before executing blueprints", "swarm_paused", 409)

    from ..agent_bus import post_message
    snapshot  = blueprint.get("snapshot", {})
    agent_ids = [a.get("id") for a in snapshot.get("agent_layer", []) if a.get("id")]

    if not agent_ids:
        return _api_error("Blueprint has no agents to execute", "empty_blueprint", 422)

    dispatched = []
    for agent_id in agent_ids:
        msg = post_message(
            from_id = "blueprint_executor",
            to_id   = agent_id,
            content = task,
            topic   = f"blueprint:{name}",
        )
        dispatched.append({"agent_id": agent_id, "msg_id": msg.msg_id})

    return {
        "blueprint":  name,
        "version":    blueprint.get("version"),
        "task":       task,
        "dispatched": dispatched,
        "count":      len(dispatched),
    }


@router.get("/architecture/blueprints/{name}/export")
def export_architecture_blueprint(name: str, version: int = 0):
    """Export a blueprint as a portable JSON file (downloadable).

    Query params:
        version — specific version to export (0 = latest)
    """
    from ..db import load_architecture_blueprint
    blueprint = load_architecture_blueprint(name, version=version if version > 0 else None)
    if not blueprint:
        return _api_error(f"Blueprint '{name}' not found", "not_found", 404)

    payload   = json.dumps(blueprint, indent=2).encode()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filename  = f"blueprint_{safe_name}_v{blueprint.get('version', 1)}.json"
    return Response(
        content    = payload,
        media_type = "application/json",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# NOTE: /architecture/blueprints/import must be registered before
# /architecture/blueprints/{name} to avoid {name} capturing "import".
# (FastAPI registers routes in order, so this is handled in app.py include_router.)
@router.post("/architecture/blueprints/import", status_code=201)
async def import_architecture_blueprint(request: Request):
    """Import a previously exported blueprint JSON.

    POST body: the full blueprint JSON object (as exported by GET …/export).
    Optional override keys:
        name  — rename the blueprint on import
        notes — override notes field
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    # Accept either the full export envelope or a raw snapshot
    if "snapshot" in body:
        name     = str(body.get("name") or "imported").strip() or "imported"
        notes    = str(body.get("notes") or "").strip()
        snapshot = body["snapshot"]
    else:
        # Treat the whole body as the snapshot
        name     = str(body.get("name") or "imported").strip() or "imported"
        notes    = ""
        snapshot = body

    if not isinstance(snapshot, dict):
        return _api_error("'snapshot' must be a JSON object", "validation_error", 422)

    from ..db import save_architecture_blueprint
    created = save_architecture_blueprint(name=name, snapshot=snapshot, notes=notes)
    return {"blueprint": created, "status": "imported"}


# ── Swarm health and control ──────────────────────────────────────────────────

# Module-level swarm pause flag
_swarm_paused: bool = False


@router.get("/swarm/health")
def swarm_health():
    """Return a health summary of all known agents in the swarm.

    Uses the activity log to classify each agent as idle, busy, or errored
    based on recent events.
    """
    from ..agent_bus import all_agents, get_bus
    bus = get_bus()

    # Derive agent states from the last N activity events
    recent = activity_log[-200:]
    agent_state: dict[str, str] = {}
    for event in reversed(recent):
        agent_id = str(event.get("agent") or event.get("agent_id") or "")
        if not agent_id or agent_id in agent_state:
            continue
        event_type = str(event.get("type") or "").lower()
        if "error" in event_type or "fail" in event_type:
            agent_state[agent_id] = "errored"
        elif "start" in event_type or "run" in event_type:
            agent_state[agent_id] = "busy"
        else:
            agent_state[agent_id] = "idle"

    # Also include agents with messages in bus inbox
    for aid in all_agents():
        if aid not in agent_state:
            unread = bus.unread_count(aid)
            agent_state[aid] = "busy" if unread > 0 else "idle"

    counts: dict[str, int] = {"idle": 0, "busy": 0, "errored": 0, "unknown": 0}
    for state in agent_state.values():
        counts[state if state in counts else "unknown"] += 1

    return {
        "paused":  _swarm_paused,
        "agents":  [{"id": aid, "state": state} for aid, state in agent_state.items()],
        "summary": counts,
        "total":   len(agent_state),
    }


@router.post("/swarm/pause")
def swarm_pause():
    """Pause the swarm — signals agents to stop accepting new tasks."""
    global _swarm_paused
    _swarm_paused = True
    return {"paused": True, "message": "Swarm paused. Existing tasks will complete."}


@router.post("/swarm/resume")
def swarm_resume():
    """Resume the swarm after a pause."""
    global _swarm_paused
    _swarm_paused = False
    return {"paused": False, "message": "Swarm resumed."}


# ── Blueprint execution, export, and import ───────────────────────────────────

@router.post("/architecture/blueprints/{name}/execute")
async def execute_architecture_blueprint(name: str, request: Request):
    """Execute a blueprint — spawn the specialist agents it defines.

    Publishes a task message on the agent bus for each agent role in the
    blueprint's agent_layer.  Returns a list of dispatched task message IDs.

    POST body (optional):
        task     — override task description sent to each agent
        version  — specific blueprint version to execute (default: latest)
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    version = int(body.get("version", 0)) or None
    task    = str(body.get("task") or "Execute blueprint workflow").strip()

    from ..db import load_architecture_blueprint
    blueprint = load_architecture_blueprint(name, version=version)
    if not blueprint:
        return _api_error(f"Blueprint '{name}' not found", "not_found", 404)

    if _swarm_paused:
        return _api_error("Swarm is paused — resume before executing blueprints", "swarm_paused", 409)

    from ..agent_bus import post_message
    snapshot  = blueprint.get("snapshot", {})
    agent_ids = [a.get("id") for a in snapshot.get("agent_layer", []) if a.get("id")]

    if not agent_ids:
        return _api_error("Blueprint has no agents to execute", "empty_blueprint", 422)

    dispatched = []
    for agent_id in agent_ids:
        msg = post_message(
            from_id = "blueprint_executor",
            to_id   = agent_id,
            content = task,
            topic   = f"blueprint:{name}",
        )
        dispatched.append({"agent_id": agent_id, "msg_id": msg.msg_id})

    return {
        "blueprint":  name,
        "version":    blueprint.get("version"),
        "task":       task,
        "dispatched": dispatched,
        "count":      len(dispatched),
    }


@router.get("/architecture/blueprints/{name}/export")
def export_architecture_blueprint(name: str, version: int = 0):
    """Export a blueprint as a portable JSON file (downloadable).

    Query params:
        version — specific version to export (0 = latest)
    """
    from ..db import load_architecture_blueprint
    blueprint = load_architecture_blueprint(name, version=version if version > 0 else None)
    if not blueprint:
        return _api_error(f"Blueprint '{name}' not found", "not_found", 404)

    payload   = json.dumps(blueprint, indent=2).encode()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filename  = f"blueprint_{safe_name}_v{blueprint.get('version', 1)}.json"
    return Response(
        content    = payload,
        media_type = "application/json",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# NOTE: /architecture/blueprints/import must be registered before
# /architecture/blueprints/{name} to avoid {name} capturing "import".
# (FastAPI registers routes in order, so this is handled in app.py include_router.)
@router.post("/architecture/blueprints/import", status_code=201)
async def import_architecture_blueprint(request: Request):
    """Import a previously exported blueprint JSON.

    POST body: the full blueprint JSON object (as exported by GET …/export).
    Optional override keys:
        name  — rename the blueprint on import
        notes — override notes field
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    # Accept either the full export envelope or a raw snapshot
    if "snapshot" in body:
        name     = str(body.get("name") or "imported").strip() or "imported"
        notes    = str(body.get("notes") or "").strip()
        snapshot = body["snapshot"]
    else:
        # Treat the whole body as the snapshot
        name     = str(body.get("name") or "imported").strip() or "imported"
        notes    = ""
        snapshot = body

    if not isinstance(snapshot, dict):
        return _api_error("'snapshot' must be a JSON object", "validation_error", 422)

    from ..db import save_architecture_blueprint
    created = save_architecture_blueprint(name=name, snapshot=snapshot, notes=notes)
    return {"blueprint": created, "status": "imported"}




# ═══════════════════════════════════════════════════════════════════════════════
#  NEW ROUTES — Sections 17-25 feature implementations
# ═══════════════════════════════════════════════════════════════════════════════

# ── S3/R2 Backup (Section 17.2) ───────────────────────────────────────────────

@router.post("/backup/s3/configure")
async def api_backup_s3_configure(request: Request):
    from ..object_storage import configure_s3
    body = await request.json()
    result = configure_s3(body)
    if not result["ok"]:
        return _api_error(result.get("error", "S3 config failed"), status_code=400)
    return result


@router.post("/backup/s3/push")
async def api_backup_s3_push():
    from ..object_storage import push_db_to_s3
    result = push_db_to_s3()
    if not result["ok"]:
        return _api_error(result.get("error", "S3 push failed"), status_code=500)
    return result


@router.post("/backup/s3/restore")
async def api_backup_s3_restore(request: Request):
    from ..object_storage import restore_db_from_s3
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    result = restore_db_from_s3(key=body.get("key"))
    if not result["ok"]:
        return _api_error(result.get("error", "S3 restore failed"), status_code=500)
    return result


@router.get("/backup/s3/backups")
async def api_backup_s3_list(limit: int = 20):
    from ..object_storage import list_s3_backups
    return {"backups": list_s3_backups(limit=limit)}


# ── Notion / Obsidian Export (Section 17.3) ───────────────────────────────────

@router.post("/export/notion/{conversation_id}")
async def api_export_notion(conversation_id: str, request: Request):
    from ..object_storage import export_chat_to_notion
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    chat = body.get("chat") or db_load_chat(conversation_id) or {}
    result = export_chat_to_notion(chat)
    if not result.get("ok"):
        return _api_error(result.get("error", "Notion export failed"), status_code=500)
    return result


@router.post("/export/obsidian/{conversation_id}")
async def api_export_obsidian(conversation_id: str, request: Request):
    from ..object_storage import export_chat_to_obsidian
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    chat = body.get("chat") or db_load_chat(conversation_id) or {}
    result = export_chat_to_obsidian(chat)
    if not result.get("ok"):
        return _api_error(result.get("error", "Obsidian export failed"), status_code=500)
    return result


@router.post("/export/obsidian/workspace")
async def api_export_obsidian_workspace(request: Request):
    from ..object_storage import export_workspace_to_obsidian
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    chats = body.get("chats") or db_load_chats()
    result = export_workspace_to_obsidian(chats)
    return result


# ── Nexus Hub — multi-instance management (Section 18.1) ─────────────────────

@router.post("/hub/instances")
async def api_hub_register(request: Request):
    from ..nexus_hub import register_instance
    body = await request.json()
    result = register_instance(**body)
    return result


@router.get("/hub/instances")
async def api_hub_list(include_offline: bool = True):
    from ..nexus_hub import list_instances
    return {"instances": list_instances(include_offline=include_offline)}


@router.get("/hub/instances/{instance_id}")
async def api_hub_get(instance_id: str):
    from ..nexus_hub import get_instance
    inst = get_instance(instance_id)
    if not inst:
        return _api_error("Instance not found", status_code=404)
    return inst


@router.delete("/hub/instances/{instance_id}")
async def api_hub_deregister(instance_id: str):
    from ..nexus_hub import deregister_instance
    ok = deregister_instance(instance_id)
    return {"ok": ok}


@router.post("/hub/instances/{instance_id}/ping")
async def api_hub_ping(instance_id: str):
    from ..nexus_hub import ping_instance
    return await ping_instance(instance_id)


@router.post("/hub/instances/{instance_id}/passthrough")
async def api_hub_passthrough(instance_id: str, request: Request):
    from ..nexus_hub import passthrough_request
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    method  = body.get("method", "GET")
    path    = body.get("path", "/v1/health")
    payload = body.get("body")
    headers = body.get("headers", {})
    result  = await passthrough_request(instance_id, method, path, payload, headers)
    if not result.get("ok"):
        return _api_error(result.get("error", "Passthrough failed"), status_code=502)
    return result


# ── Nexus Systems passthrough (Section 25.3) ──────────────────────────────────

@router.post("/nexus/passthrough")
async def api_nexus_systems_passthrough(request: Request):
    from ..nexus_hub import nexus_systems_passthrough
    body = await request.json()
    method   = body.get("method", "GET")
    endpoint = body.get("endpoint", "/")
    payload  = body.get("body")
    result   = await nexus_systems_passthrough(method, endpoint, payload)
    if not result.get("ok"):
        return _api_error(result.get("error", "Nexus Systems passthrough failed"), status_code=502)
    return result


# ── Federated learning (Section 18.3) ─────────────────────────────────────────

@router.post("/federated/round")
async def api_federated_round(request: Request):
    from ..federated import compute_and_submit_update
    body = await request.json()
    samples = body.get("samples", [])
    try:
        global_round = int(body.get("global_round", 0))
    except Exception:
        return _api_error("global_round must be an integer", "validation_error", 422)

    result = compute_and_submit_update(samples, global_round)
    payload = result.to_dict()
    status = str(payload.get("status") or "")
    if status == "disabled":
        return JSONResponse(payload, status_code=503)
    if status == "failed":
        return JSONResponse(payload, status_code=400)
    return payload


@router.get("/federated/status")
async def api_federated_status():
    from ..federated import get_federation_status
    return get_federation_status()


@router.get("/federated/rounds")
async def api_federated_rounds(limit: int = 20):
    from ..federated import list_rounds
    return {"rounds": list_rounds(limit=limit)}


# ── Drift detection (Sections 19.3, 20.2) ────────────────────────────────────

@router.get("/admin/drift")
async def api_drift_summary():
    from ..drift_detector import get_drift_summary
    return get_drift_summary()


@router.get("/admin/drift/events")
async def api_drift_events(plane: str = "all", severity: str = "all", limit: int = 50):
    from ..drift_detector import list_drift_events
    return {"events": list_drift_events(plane=plane, severity=severity, limit=limit)}


@router.post("/admin/drift/baseline/quality")
async def api_drift_baseline_quality(request: Request):
    from ..drift_detector import set_quality_baseline
    body = await request.json()
    set_quality_baseline(body)
    return {"ok": True, "message": "Quality baseline updated"}


@router.post("/admin/drift/baseline/safety")
async def api_drift_baseline_safety(request: Request):
    from ..drift_detector import update_safety_baseline
    body = await request.json()
    update_safety_baseline(body)
    return {"ok": True, "message": "Safety baseline updated"}


@router.post("/admin/drift/check/architecture")
async def api_drift_check_arch():
    from ..drift_detector import check_architecture_drift
    result = check_architecture_drift()
    return result


@router.get("/admin/drift/weekly")
async def api_drift_weekly_results():
    from ..drift_detector import get_weekly_results
    return {"results": get_weekly_results()}


@router.post("/admin/drift/weekly/run")
async def api_drift_weekly_run():
    from ..drift_detector import run_weekly_quality_benchmark
    result = run_weekly_quality_benchmark()
    return result


# ── MoE routing + reasoning modes (Section 20.1) ─────────────────────────────

@router.post("/routing/moe")
async def api_moe_route(request: Request):
    from ..moe_router import route_to_expert
    body = await request.json()
    prompt     = str(body.get("prompt", ""))
    persona    = body.get("persona", "nexus")
    complexity = int(body.get("complexity", 5))
    return route_to_expert(prompt, persona=persona, complexity=complexity)


@router.post("/agent/hypothesis")
async def api_hypothesis(request: Request):
    from ..moe_router import build_hypothesis_prompt
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    question = str(body.get("question", ""))
    context  = str(body.get("context", ""))
    prompt   = build_hypothesis_prompt(question, context)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="hypothesis"
    )
    return {"reasoning": resp.get("content", ""), "provider": provider}


@router.post("/agent/socratic")
async def api_socratic(request: Request):
    from ..moe_router import build_socratic_prompt
    from ..agent import call_llm_with_fallback
    body  = await request.json()
    topic = str(body.get("topic", ""))
    depth = int(body.get("depth", 3))
    prompt = build_socratic_prompt(topic, depth=depth)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="socratic"
    )
    return {"reasoning": resp.get("content", ""), "provider": provider}


@router.post("/agent/verify")
async def api_formal_proof(request: Request):
    from ..moe_router import build_formal_proof_prompt
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    statement  = str(body.get("statement", ""))
    proof_type = str(body.get("proof_type", "direct"))
    prompt     = build_formal_proof_prompt(statement, proof_type=proof_type)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="formal_proof"
    )
    return {"proof": resp.get("content", ""), "provider": provider}


@router.get("/reasoning/sessions")
async def api_reasoning_sessions(limit: int = 50):
    from ..moe_router import list_reasoning_sessions
    return {"sessions": list_reasoning_sessions(limit=limit)}


# ── Team policies + RBAC + compliance (Sections 21.1, 21.2) ──────────────────

@router.post("/admin/team-policies")
async def api_create_policy(request: Request):
    from ..team_policies import create_policy
    body    = await request.json()
    team_id = str(body.pop("team_id", "default"))
    name    = str(body.pop("name", "Unnamed Policy"))
    result  = create_policy(team_id, name, **body)
    return result


@router.get("/admin/team-policies")
async def api_list_policies(team_id: str = "default"):
    from ..team_policies import list_policies
    return {"policies": list_policies(team_id=team_id)}


@router.get("/admin/team-policies/{policy_id}")
async def api_get_policy(policy_id: str):
    from ..team_policies import get_policy
    p = get_policy(policy_id)
    if not p:
        return _api_error("Policy not found", status_code=404)
    return p


@router.put("/admin/team-policies/{policy_id}")
async def api_update_policy(policy_id: str, request: Request):
    from ..team_policies import update_policy
    body   = await request.json()
    result = update_policy(policy_id, updates=body)
    if not result:
        return _api_error("Policy not found", status_code=404)
    return result


@router.delete("/admin/team-policies/{policy_id}")
async def api_delete_policy(policy_id: str):
    from ..team_policies import delete_policy
    ok = delete_policy(policy_id)
    return {"ok": ok}


@router.post("/admin/team-policies/evaluate")
async def api_evaluate_policy(request: Request):
    from ..team_policies import evaluate_policy
    body = await request.json()
    team_id = str(body.get("team_id", "default"))
    tool_action = str(body.get("tool_action", ""))
    username = str(body.get("user") or body.get("username") or "")
    role = str(body.get("role", "user"))
    context = body.get("context", {}) or {}
    model = str(body.get("model") or context.get("model") or "").strip() or None
    region = str(body.get("region") or context.get("region") or "").strip() or None
    return evaluate_policy(
        team_id=team_id,
        tool_action=tool_action,
        model=model,
        region=region,
        username=username,
        role=role,
        context=context,
    )


@router.get("/admin/roles")
async def api_list_roles():
    from ..team_policies import ROLE_HIERARCHY
    return {"roles": list(ROLE_HIERARCHY.keys())}


@router.post("/admin/roles/check")
async def api_check_role(request: Request):
    from ..team_policies import role_can
    body          = await request.json()
    actor_role    = str(body.get("actor_role", "user"))
    required_role = str(body.get("required_role", "admin"))
    return {"can": role_can(actor_role, required_role)}


@router.get("/admin/compliance")
async def api_get_compliance():
    from ..team_policies import get_compliance_config
    return get_compliance_config()


@router.put("/admin/compliance")
async def api_update_compliance(request: Request):
    from ..team_policies import update_compliance_config
    body = await request.json()
    try:
        return update_compliance_config(body)
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/admin/compliance/connectors/{connector}")
async def api_get_compliance_connector(connector: str):
    from ..team_policies import get_managed_connector_config
    try:
        return get_managed_connector_config(connector)
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.put("/admin/compliance/connectors/{connector}")
async def api_update_compliance_connector(connector: str, request: Request):
    from ..team_policies import update_managed_connector_config
    body = await request.json()
    try:
        return update_managed_connector_config(
            connector=connector,
            enabled=body.get("enabled") if "enabled" in body else None,
            providers=body.get("providers") if isinstance(body.get("providers"), list) else None,
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/admin/compliance/connectors/{connector}/test")
async def api_test_compliance_connector(connector: str, request: Request):
    from ..team_policies import test_managed_connector
    body = await request.json()
    return test_managed_connector(
        connector=connector,
        provider=str(body.get("provider", "")),
        region=str(body.get("region", "")),
    )


@router.get("/admin/deployment-profile")
async def api_get_deployment_profile():
    """Return the active deployment profile and its key settings."""
    from ..deployment_profiles import get_profile_summary
    return get_profile_summary()


@router.get("/admin/deployment-profiles")
async def api_list_deployment_profiles():
    """List all built-in deployment profiles."""
    from ..deployment_profiles import list_profiles
    return {"profiles": list_profiles()}


@router.post("/admin/quota/departments")
async def api_set_dept_quota(request: Request):
    from ..team_policies import set_department_quota
    body = await request.json()
    dept = str(body.get("department", ""))
    return set_department_quota(
        department=dept,
        daily_tokens=int(body.get("daily_tokens", 100000)),
        monthly_cost_usd=float(body.get("monthly_cost_usd", 500.0)),
        max_users=int(body.get("max_users", 50)),
    )


@router.get("/admin/quota/departments")
async def api_list_dept_quotas():
    from ..team_policies import list_department_quotas
    return {"quotas": list_department_quotas()}


@router.get("/admin/quota/departments/{department}")
async def api_get_dept_quota(department: str):
    from ..team_policies import get_department_quota
    q = get_department_quota(department)
    if not q:
        return _api_error("Department not found", status_code=404)
    return q


@router.get("/admin/policy-violations")
async def api_list_violations(team_id: str | None = None, limit: int = 100):
    from ..team_policies import list_violations, list_policy_alerts
    return {
        "violations": list_violations(team_id=team_id, limit=limit),
        "alerts": list_policy_alerts(team_id=team_id, status="open", limit=limit),
    }


@router.post("/admin/approval-workflows")
async def api_create_workflow(request: Request):
    from ..team_policies import create_approval_workflow
    body      = await request.json()
    action    = str(body.get("action", ""))
    requestor = str(body.get("requestor", ""))
    tiers     = body.get("custom_tiers")
    return create_approval_workflow(action, requestor, custom_tiers=tiers)


@router.get("/admin/approval-workflows")
async def api_list_workflows(status: str | None = None, limit: int = 50):
    from ..team_policies import list_workflows
    return {"workflows": list_workflows(status=status, limit=limit)}


@router.post("/admin/approval-workflows/{workflow_id}/advance")
async def api_advance_workflow(workflow_id: str, request: Request):
    from ..team_policies import advance_workflow
    body = await request.json()
    approver = str(body.get("approver", ""))
    approver_role = str(body.get("approver_role", "admin"))
    decision = str(body.get("decision", "approve"))
    comment = str(body.get("comment", ""))
    result = advance_workflow(workflow_id, approver, approver_role, decision, reason=comment)
    if result.get("error") == "workflow not found":
        return _api_error("Workflow not found", status_code=404)
    if not result.get("ok"):
        return _api_error(result.get("error", "Workflow advance failed"), status_code=400)
    return result


@router.get("/admin/audit-log/export")
async def api_audit_export(fmt: str = "json", limit: int = 500):
    from ..db import verify_safety_audit_entries
    from ..team_policies import build_audit_export
    entries = db_load_safety_audit_entries(limit=limit)
    content_bytes, content_type = build_audit_export(entries, fmt=fmt)
    integrity = verify_safety_audit_entries(limit=limit)
    if fmt == "csv":
        from fastapi.responses import Response
        return Response(
            content=content_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": "attachment; filename=audit.csv",
                "X-Audit-Integrity": "ok" if integrity.get("ok") else "failed",
            },
        )
    return {
        "entries": entries,
        "export": content_bytes.decode("utf-8"),
        "format": fmt,
        "content_type": content_type,
        "integrity": integrity,
    }


# ── Browser automation (Section 23.1) ─────────────────────────────────────────

@router.post("/browser/sessions")
async def api_browser_create(request: Request):
    from ..browser_agent import create_session
    body = await request.json()
    result = create_session(
        start_url=str(body.get("start_url", "https://example.com")),
        hitl_checkpoints=body.get("hitl_checkpoints", []),
    )
    return result


@router.get("/browser/sessions")
async def api_browser_list():
    from ..browser_agent import list_sessions
    return {"sessions": list_sessions()}


@router.get("/browser/sessions/{session_id}")
async def api_browser_get(session_id: str):
    from ..browser_agent import get_session
    s = get_session(session_id)
    if not s:
        return _api_error("Session not found", status_code=404)
    return s


@router.post("/browser/sessions/{session_id}/step")
async def api_browser_step(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body   = await request.json()
    action = str(body.get("action", "navigate"))
    params = body.get("params", {})
    result = await execute_step(session_id, action, params)
    if not result.get("ok"):
        return _api_error(result.get("error", "Step failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/confirm")
async def api_browser_confirm(session_id: str, request: Request):
    from ..browser_agent import confirm_pending_step
    body = await request.json()
    approve = bool(body.get("approve", False))
    actor = str(body.get("actor") or body.get("username") or "")
    result = await confirm_pending_step(session_id=session_id, approve=approve, actor=actor)
    if not result.get("ok"):
        return _api_error(result.get("error", "confirmation failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/pause")
async def api_browser_pause(session_id: str, request: Request):
    from ..browser_agent import pause_session
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = str(body.get("reason") or "manual_pause")
    result = pause_session(session_id=session_id, reason=reason)
    if not result.get("ok"):
        return _api_error(result.get("error", "pause failed"), status_code=404)
    return result


@router.post("/browser/sessions/{session_id}/resume")
async def api_browser_resume(session_id: str, request: Request):
    from ..browser_agent import resume_session
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    replay_navigation = bool(body.get("replay_navigation", False))
    result = resume_session(session_id=session_id, replay_navigation=replay_navigation)
    if not result.get("ok"):
        return _api_error(result.get("error", "resume failed"), status_code=404)
    return result


@router.get("/browser/sessions/{session_id}/history")
async def api_browser_history(session_id: str):
    from ..browser_agent import get_navigation_history
    history = get_navigation_history(session_id)
    return {"history": history}


@router.post("/browser/sessions/{session_id}/visual-elements")
async def api_browser_visual_elements(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    params = {
        "url": body.get("url"),
        "max_elements": body.get("max_elements", 40),
    }
    result = await execute_step(session_id=session_id, action="detect_elements", params=params)
    if not result.get("ok"):
        return _api_error(result.get("error", "visual element detection failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/form-plan")
async def api_browser_form_plan(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body = await request.json()
    result = await execute_step(
        session_id=session_id,
        action="queue_form_fill",
        params={
            "fields": body.get("fields") if isinstance(body.get("fields"), dict) else {},
            "submit_selector": body.get("submit_selector"),
            "form_selector": body.get("form_selector"),
        },
    )
    if not result.get("ok"):
        return _api_error(result.get("error", "form plan creation failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/form-plan/{plan_id}/execute")
async def api_browser_execute_form_plan(session_id: str, plan_id: str):
    from ..browser_agent import execute_step
    result = await execute_step(
        session_id=session_id,
        action="execute_form_plan",
        params={"plan_id": plan_id},
    )
    if not result.get("ok"):
        return _api_error(result.get("error", "form plan execution failed"), status_code=400)
    return result


# ── SLO dashboard (Section 24.1) ──────────────────────────────────────────────

@router.get("/slo/dashboard")
async def api_slo_dashboard():
    from ..slo import get_slo_dashboard
    return get_slo_dashboard()


@router.post("/slo/latency")
async def api_slo_record_latency(request: Request):
    from ..slo import record_latency
    body     = await request.json()
    endpoint = str(body.get("endpoint", "unknown"))
    latency  = float(body.get("latency_ms", 0))
    success  = bool(body.get("success", True))
    record_latency(endpoint, latency, success)
    return {"ok": True}


@router.get("/slo/hotspots")
async def api_slo_hotspots(threshold_ms: float = 2000.0):
    from ..slo import detect_latency_hotspots
    return {"hotspots": detect_latency_hotspots(threshold_ms=threshold_ms)}


@router.get("/slo/hardware-hint")
async def api_slo_hardware_hint():
    from ..slo import get_hardware_routing_hint
    return get_hardware_routing_hint()


# ── Team budgets + cost attribution (Sections 24.2, 24.3) ────────────────────

@router.post("/billing/teams/{team_id}/budget")
async def api_set_team_budget(team_id: str, request: Request):
    from ..slo import set_team_budget
    body = await request.json()
    return set_team_budget(
        team_id=team_id,
        monthly_limit_usd=float(body.get("monthly_limit_usd", 100.0)),
        daily_limit_usd=float(body.get("daily_limit_usd", 0.0)),
        alert_threshold_pct=float(body.get("alert_threshold_pct", body.get("alert_at_pct", 80.0))),
    )


@router.get("/billing/teams/{team_id}/budget")
async def api_get_team_budget(team_id: str):
    from ..slo import get_team_budget
    b = get_team_budget(team_id)
    if not b:
        return _api_error("Team budget not found", status_code=404)
    return b


@router.get("/billing/teams")
async def api_list_team_budgets():
    from ..slo import list_team_budgets
    return {"budgets": list_team_budgets()}


@router.get("/billing/alerts")
async def api_list_budget_alerts():
    from ..slo import list_budget_alerts
    return {"alerts": list_budget_alerts()}


@router.post("/billing/attribution")
async def api_record_attribution(request: Request):
    from ..slo import record_attribution
    body = await request.json()
    record_attribution(
        team_id=str(body.get("team_id", "")),
        department=str(body.get("department", "")),
        user=str(body.get("user", "")),
        cost_usd=float(body.get("cost_usd", 0.0)),
        tokens=int(body.get("tokens", 0)),
        model=str(body.get("model", "")),
        endpoint=str(body.get("endpoint", "")),
    )
    return {"ok": True}


@router.get("/billing/attribution/report")
async def api_attribution_report(team_id: str | None = None,
                                   department: str | None = None):
    from ..slo import get_attribution_report
    return get_attribution_report(team_id=team_id, department=department)


@router.put("/billing/teams/{team_id}/capacity")
async def api_set_reserved_capacity(team_id: str, request: Request):
    from ..slo import set_reserved_capacity
    body = await request.json()
    return set_reserved_capacity(
        team_id=team_id,
        reserved_rps=float(body.get("reserved_rps", 0.0)),
        max_concurrency=int(body.get("max_concurrency", 0)),
        guarantee_tier=str(body.get("guarantee_tier", "standard")),
        expires_at=str(body.get("expires_at", "")),
    )


@router.get("/billing/teams/{team_id}/capacity")
async def api_get_reserved_capacity(team_id: str):
    from ..slo import get_reserved_capacity
    row = get_reserved_capacity(team_id)
    if not row:
        return _api_error("Reserved capacity not found", status_code=404)
    return row


@router.get("/billing/capacity")
async def api_list_reserved_capacity():
    from ..slo import list_reserved_capacity
    return {"capacity": list_reserved_capacity()}


@router.post("/billing/teams/{team_id}/capacity/check")
async def api_check_rate_guarantee(team_id: str, request: Request):
    from ..slo import check_rate_guarantee
    body = await request.json()
    return check_rate_guarantee(
        team_id=team_id,
        requested_rps=float(body.get("requested_rps", 0.0)),
        requested_concurrency=int(body.get("requested_concurrency", 0)),
    )


@router.put("/billing/teams/{team_id}/spot")
async def api_set_spot_policy(team_id: str, request: Request):
    from ..slo import set_spot_policy
    body = await request.json()
    return set_spot_policy(
        team_id=team_id,
        enabled=bool(body.get("enabled", False)),
        max_discount_pct=float(body.get("max_discount_pct", 50.0)),
        fallback_on_preempt=bool(body.get("fallback_on_preempt", True)),
        max_preemptions_per_hour=int(body.get("max_preemptions_per_hour", 2)),
    )


@router.get("/billing/teams/{team_id}/spot")
async def api_get_spot_policy(team_id: str):
    from ..slo import get_spot_policy
    row = get_spot_policy(team_id)
    if not row:
        return _api_error("Spot policy not found", status_code=404)
    return row


@router.post("/billing/teams/{team_id}/spot/events")
async def api_record_spot_event(team_id: str, request: Request):
    from ..slo import record_spot_event
    body = await request.json()
    return record_spot_event(
        team_id=team_id,
        event_type=str(body.get("event_type", "preempted")),
        details=body.get("details") if isinstance(body.get("details"), dict) else {},
    )


# ── Custom tool registry (Section 25.1) ───────────────────────────────────────

@router.post("/tools/registry")
async def api_tools_register(request: Request):
    from ..marketplace_registry import register_tool
    body = await request.json()
    result = register_tool(**body)
    return result


@router.get("/tools/registry")
async def api_tools_list(category: str | None = None):
    from ..marketplace_registry import list_tools
    return {"tools": list_tools(tag=category)}


@router.get("/tools/registry/{tool_id}")
async def api_tools_get(tool_id: str):
    from ..marketplace_registry import get_tool
    t = get_tool(tool_id)
    if not t:
        return _api_error("Tool not found", status_code=404)
    return t


@router.post("/tools/registry/{tool_id}/invoke")
async def api_tools_invoke(tool_id: str, request: Request):
    from ..marketplace_registry import invoke_custom_tool
    body   = await request.json()
    params = body.get("params", {})
    result = await invoke_custom_tool(tool_id, params)
    if not result.get("ok"):
        return _api_error(result.get("error", "Tool invocation failed"), status_code=400)
    return result


@router.delete("/tools/registry/{tool_id}")
async def api_tools_delete(tool_id: str):
    from ..marketplace_registry import deactivate_tool
    ok = deactivate_tool(tool_id)
    return {"ok": ok}


# ── Marketplace connectors (Section 25.2) ─────────────────────────────────────

@router.get("/marketplace/connectors")
async def api_connectors_list(installed_only: bool = False):
    from ..marketplace_registry import list_connectors
    return {"connectors": list_connectors(installed_only=installed_only)}


@router.get("/marketplace/connectors/{connector_id}")
async def api_connectors_get(connector_id: str):
    from ..marketplace_registry import get_connector
    c = get_connector(connector_id)
    if not c:
        return _api_error("Connector not found", status_code=404)
    return c


@router.post("/marketplace/connectors/{connector_id}/install")
async def api_connectors_install(connector_id: str, request: Request):
    from ..marketplace_registry import install_connector
    body   = await request.json()
    config = body.get("config", {})
    result = install_connector(connector_id, config=config)
    if not result.get("ok"):
        return _api_error(result.get("error", "Install failed"), status_code=400)
    return result


@router.delete("/marketplace/connectors/{connector_id}/install")
async def api_connectors_uninstall(connector_id: str):
    from ..marketplace_registry import uninstall_connector
    result = uninstall_connector(connector_id)
    return result


# ── Agent templates (Section 25.2) ───────────────────────────────────────────

@router.post("/marketplace/templates")
async def api_templates_publish(request: Request):
    from ..marketplace_registry import publish_template
    body   = await request.json()
    result = publish_template(**body)
    return result


@router.get("/marketplace/templates")
async def api_templates_list(category: str | None = None, tags: str | None = None):
    from ..marketplace_registry import list_templates
    tags_list = tags.split(",") if tags else None
    return {"templates": list_templates(tag=category)}


@router.get("/marketplace/templates/{template_id}")
async def api_templates_get(template_id: str):
    from ..marketplace_registry import get_template
    t = get_template(template_id)
    if not t:
        return _api_error("Template not found", status_code=404)
    return t


@router.post("/marketplace/templates/{template_id}/deploy")
async def api_templates_deploy(template_id: str, request: Request):
    from ..marketplace_registry import deploy_template
    body      = await request.json()
    overrides = body.get("overrides", {})
    result    = deploy_template(template_id)
    if not result.get("ok"):
        return _api_error(result.get("error", "Deploy failed"), status_code=400)
    return result


# ── Community personas (Section 25.2) ────────────────────────────────────────

@router.post("/marketplace/personas")
async def api_community_persona_publish(request: Request):
    from ..marketplace_registry import publish_persona
    body   = await request.json()
    result = publish_persona(**body)
    return result


@router.get("/marketplace/personas")
async def api_community_personas_list(tags: str | None = None):
    from ..marketplace_registry import list_community_personas
    tags_list = tags.split(",") if tags else None
    return {"personas": list_community_personas(tag=tags_list[0] if tags_list else None)}


@router.get("/marketplace/personas/{persona_id}")
async def api_community_persona_get(persona_id: str):
    from ..marketplace_registry import get_community_persona
    p = get_community_persona(persona_id)
    if not p:
        return _api_error("Persona not found", status_code=404)
    return p


# ── Provider plugins (Section 25.2) ──────────────────────────────────────────

@router.post("/providers/plugins")
async def api_providers_plugin_register(request: Request):
    from ..marketplace_registry import register_provider_plugin
    body   = await request.json()
    result = register_provider_plugin(**body)
    return result


@router.get("/providers/plugins")
async def api_providers_plugins_list(active_only: bool = False):
    from ..marketplace_registry import list_provider_plugins
    return {"plugins": list_provider_plugins(active_only=active_only)}


@router.post("/providers/plugins/{plugin_id}/activate")
async def api_providers_plugin_activate(plugin_id: str, request: Request):
    from ..marketplace_registry import activate_provider_plugin
    body   = await request.json()
    active = bool(body.get("active", True))
    if not active:
        from ..marketplace_registry import list_provider_plugins
        # deactivation not yet implemented, return current state
        return {"ok": False, "note": "Deactivation not yet implemented"}
    result = activate_provider_plugin(plugin_id)
    if not result:
        return _api_error("Plugin not found", status_code=404)
    return result


# ── Vision extras — chart extraction + document understanding (Section 22) ────

@router.post("/vision/extract-charts")
async def api_vision_extract_charts(request: Request):
    from ..vision import extract_charts_and_tables
    import base64
    body      = await request.json()
    image_b64 = str(body.get("image_base64", ""))
    mime_type = str(body.get("mime_type", "image/png"))
    if not image_b64:
        return _api_error("image_base64 required", status_code=422)
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return _api_error("Invalid base64 image", status_code=422)
    return extract_charts_and_tables(image_bytes, mime_type=mime_type)


@router.post("/documents/understand")
async def api_documents_understand(request: Request):
    from ..vision import understand_pdf, understand_office_doc
    import base64
    body      = await request.json()
    file_b64  = str(body.get("file_base64", ""))
    filename  = str(body.get("filename", "document.pdf"))
    mime_type = str(body.get("mime_type", "application/pdf"))
    if not file_b64:
        return _api_error("file_base64 required", status_code=422)
    try:
        file_bytes = base64.b64decode(file_b64)
    except Exception:
        return _api_error("Invalid base64 file", status_code=422)
    if "pdf" in mime_type or filename.lower().endswith(".pdf"):
        return understand_pdf(file_bytes)
    return understand_office_doc(file_bytes, filename=filename)


@router.post("/documents/diff")
async def api_documents_diff(request: Request):
    from ..vision import diff_documents
    body     = await request.json()
    text_a   = str(body.get("text_a", ""))
    text_b   = str(body.get("text_b", ""))
    ctx      = int(body.get("context_lines", 3))
    return diff_documents(text_a, text_b, context_lines=ctx)


# ── Audio extras — analysis + diarization + streaming (Section 22) ────────────

@router.post("/audio/analyse")
async def api_audio_analyse(request: Request):
    from ..audio import AudioProviderError, analyse_audio
    import base64
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    analyses = body.get("analyses")
    profile_b64 = body.get("voice_profile_base64")
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    try:
        return analyse_audio(audio_bytes, analyses=analyses, voice_profile_bytes=profile_bytes)
    except AudioProviderError as exc:
        return _api_error(str(exc), status_code=503)
    except ValueError as exc:
        return _api_error(str(exc), status_code=422)


@router.post("/audio/diarize")
async def api_audio_diarize(request: Request):
    from ..audio import diarize_audio
    import base64
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    num_speakers = body.get("num_speakers")
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return diarize_audio(audio_bytes, num_speakers=num_speakers)


@router.post("/audio/identify-speaker")
async def api_audio_identify_speaker(request: Request):
    from ..audio import identify_speaker
    import base64
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    profile_b64 = body.get("voice_profile_base64")
    known_profiles = body.get("known_profiles") if isinstance(body.get("known_profiles"), list) else None
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return identify_speaker(audio_bytes, voice_profile_bytes=profile_bytes, known_profiles=known_profiles)


@router.post("/audio/stream-chunk")
async def api_audio_stream_chunk(request: Request):
    from ..audio import stream_transcribe_chunk
    import base64
    body = await request.json()
    chunk_b64 = str(body.get("audio_chunk_base64", ""))
    session_state = body.get("session_state")
    session_id = str(body.get("session_id", ""))
    language = str(body.get("language", "")) or None
    finalize = bool(body.get("finalize", False))
    diarize = bool(body.get("diarize", False))
    identify_speaker_enabled = bool(body.get("identify_speaker", False))
    profile_b64 = body.get("voice_profile_base64")
    speaker_name = str(body.get("speaker_name", ""))
    if not chunk_b64:
        return _api_error("audio_chunk_base64 required", status_code=422)
    try:
        chunk_bytes = base64.b64decode(chunk_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return stream_transcribe_chunk(
        chunk_bytes,
        session_state=session_state,
        session_id=session_id,
        language=language,
        finalize=finalize,
        diarize=diarize,
        identify_speaker_enabled=identify_speaker_enabled,
        voice_profile_bytes=profile_bytes,
        speaker_name=speaker_name,
    )


@router.websocket("/audio/live/ws")
async def api_audio_live_ws(websocket: WebSocket):
    """Realtime voice-agent socket.

    Client messages (JSON):
    - {"type":"chunk","audio_chunk_base64":"...","session_id":"..."}
    - {"type":"finalize","audio_chunk_base64":"...optional...","prompt":"...optional..."}
    """
    from ..audio import stream_transcribe_chunk
    await websocket.accept()
    session_id = ""
    session_state = {}
    last_chunk_bytes = b""

    try:
        while True:
            payload = await websocket.receive_json()
            msg_type = str(payload.get("type") or "chunk").strip().lower()
            session_id = str(payload.get("session_id") or session_id or "")
            language = str(payload.get("language") or "") or None
            diarize = bool(payload.get("diarize", False))
            identify_speaker = bool(payload.get("identify_speaker", False))
            prompt = str(payload.get("prompt") or "").strip()

            chunk_b64 = str(payload.get("audio_chunk_base64") or "")
            chunk_bytes = b""
            if chunk_b64:
                try:
                    chunk_bytes = base64.b64decode(chunk_b64)
                    last_chunk_bytes = chunk_bytes
                except Exception:
                    await websocket.send_json({"type": "error", "error": "invalid base64 chunk"})
                    continue

            if msg_type == "chunk":
                if not chunk_bytes:
                    await websocket.send_json({"type": "error", "error": "audio_chunk_base64 required"})
                    continue
                result = stream_transcribe_chunk(
                    chunk_bytes,
                    session_state=session_state,
                    session_id=session_id,
                    language=language,
                    finalize=False,
                    diarize=diarize,
                    identify_speaker_enabled=identify_speaker,
                )
                session_state = dict(result.get("session_state") or session_state)
                session_id = str(result.get("session_id") or session_id)
                await websocket.send_json({"type": "partial", **result})
                continue

            if msg_type == "finalize":
                final_chunk = chunk_bytes or last_chunk_bytes
                if not final_chunk:
                    await websocket.send_json({"type": "error", "error": "no audio available to finalize"})
                    continue
                result = stream_transcribe_chunk(
                    final_chunk,
                    session_state=session_state,
                    session_id=session_id,
                    language=language,
                    finalize=True,
                    diarize=diarize,
                    identify_speaker_enabled=identify_speaker,
                )
                session_state = dict(result.get("session_state") or session_state)
                session_id = str(result.get("session_id") or session_id)
                await websocket.send_json({"type": "final", **result})

                final_text = str(result.get("final_transcript") or result.get("partial") or "").strip()
                if final_text:
                    agent_task = prompt or final_text
                    agent_out = run_agent_task(agent_task, history=[], files=[], sid=session_id)
                    await websocket.send_json({
                        "type": "agent_response",
                        "session_id": session_id,
                        "task": agent_task,
                        "agent": agent_out,
                    })
                continue

            await websocket.send_json({"type": "error", "error": f"unsupported message type: {msg_type}"})
    except WebSocketDisconnect:
        return


# ── Video extras — transcription + chapters + editing (Section 22) ───────────

@router.post("/video/transcribe")
async def api_video_transcribe(request: Request):
    from ..generation import video_to_text
    import base64
    body           = await request.json()
    video_b64      = str(body.get("video_base64", ""))
    frame_interval = float(body.get("frame_interval_s", 5.0))
    max_frames     = int(body.get("max_frames", 20))
    if not video_b64:
        return _api_error("video_base64 required", status_code=422)
    video_bytes = base64.b64decode(video_b64)
    return video_to_text(video_bytes, frame_interval_s=frame_interval, max_frames=max_frames)


@router.post("/video/chapters")
async def api_video_chapters(request: Request):
    from ..generation import detect_video_chapters_from_transcript
    import base64
    body      = await request.json()
    video_b64 = body.get("video_base64")
    video_url = body.get("video_url")
    if video_b64:
        video_bytes = base64.b64decode(video_b64)
        chapters    = detect_video_chapters_from_transcript(video_bytes)
    elif video_url:
        from ..generation import detect_video_chapters
        chapters = detect_video_chapters(video_url)
    else:
        return _api_error("video_base64 or video_url required", status_code=422)
    return {"chapters": chapters}


@router.post("/video/edit")
async def api_video_edit(request: Request):
    from ..generation import edit_video
    import base64
    body        = await request.json()
    video_b64   = str(body.get("video_base64", ""))
    operations  = body.get("operations", [])
    if not video_b64:
        return _api_error("video_base64 required", status_code=422)
    video_bytes = base64.b64decode(video_b64)
    result      = edit_video(video_bytes, operations)
    if result.get("output_bytes"):
        output_b64         = base64.b64encode(result["output_bytes"]).decode()
        result["output_bytes"] = None
        result["output_base64"] = output_b64
    return result


# ── WebSocket collab room (Section 22 / collab upgrade) ───────────────────────

@router.websocket("/collab/rooms/{room_id}/ws")
async def api_collab_ws(room_id: str, websocket: WebSocket):
    from ..collab import ws_manager, get_room, create_room
    # Ensure room exists
    if not get_room(room_id):
        create_room(owner="ws-join", name=f"Room {room_id}")
    await ws_manager.connect(room_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Broadcast to all others in room
            await ws_manager.broadcast(room_id, {
                "type":    "message",
                "room_id": room_id,
                "data":    data,
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(room_id, websocket)
    except Exception:
        ws_manager.disconnect(room_id, websocket)


# ── SIEM integration config (Section 21) ──────────────────────────────────────

@router.get("/admin/siem/config")
async def api_siem_get():
    from ..db import load_pref as _lp
    config = _lp("siem_config") or {}
    return {"config": config}


@router.post("/admin/siem/config")
async def api_siem_set(request: Request):
    from ..db import save_pref as _sp
    body = await request.json()
    # Validate required fields
    endpoint = str(body.get("endpoint", "")).strip()
    if not endpoint:
        return _api_error("endpoint required", status_code=422)
    config = {
        "endpoint":   endpoint,
        "format":     str(body.get("format", "json")),
        "auth_token": str(body.get("auth_token", "")),
        "enabled":    bool(body.get("enabled", True)),
        "events":     list(body.get("events", ["safety_violation", "auth_failure"])),
    }
    _sp("siem_config", config)
    return {"ok": True, "config": config}


@router.post("/admin/siem/test")
async def api_siem_test():
    from ..db import load_pref as _lp
    import httpx
    config = _lp("siem_config") or {}
    endpoint = config.get("endpoint", "")
    if not endpoint:
        return _api_error("No SIEM endpoint configured", status_code=400)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                endpoint,
                json={"type": "test", "source": "nexus-ai", "message": "SIEM integration test"},
                headers={"Authorization": f"Bearer {config.get('auth_token', '')}"},
            )
            return {"ok": True, "status_code": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Developer tooling — code review + bug fix + migration (Section 18) ────────

_BUG_FIX_CHECKPOINTS_KEY = "agent_bug_fix_checkpoints_v1"


def _load_bug_fix_checkpoints() -> list[dict[str, Any]]:
    raw = db_load_pref(_BUG_FIX_CHECKPOINTS_KEY, "[]")
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else []
            if isinstance(parsed, list):
                return [row for row in parsed if isinstance(row, dict)]
        except Exception:
            return []
    return []


def _save_bug_fix_checkpoints(rows: list[dict[str, Any]]) -> None:
    db_save_pref(_BUG_FIX_CHECKPOINTS_KEY, json.dumps(rows[-1000:], separators=(",", ":")))

@router.post("/agent/code-review")
async def api_code_review(request: Request):
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    code     = str(body.get("code", ""))
    language = str(body.get("language", "python"))
    focus    = str(body.get("focus", "security, bugs, style"))
    if not code:
        return _api_error("code required", status_code=422)
    prompt = (
        f"Review this {language} code for: {focus}.\n\n"
        f"```{language}\n{code}\n```\n\n"
        "Return JSON: {\"issues\": [{\"line\": int|null, \"severity\": \"error|warning|info\", "
        "\"message\": str, \"suggestion\": str}], \"summary\": str, \"score\": 0-10}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="code_review"
    )
    import json, re
    text = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m    = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


@router.post("/agent/bug-fix")
async def api_bug_fix(request: Request):
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    code       = str(body.get("code", ""))
    error_msg  = str(body.get("error", ""))
    language   = str(body.get("language", "python"))
    test_command = str(body.get("test_command", "")).strip()
    if not code:
        return _api_error("code required", status_code=422)

    checkpoint_id = "bf_" + secrets.token_hex(6)
    checkpoints = _load_bug_fix_checkpoints()
    checkpoint = {
        "checkpoint_id": checkpoint_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "language": language,
        "error": error_msg,
        "original_code": code,
        "test_command": test_command,
        "status": "created",
    }
    checkpoints.append(checkpoint)
    _save_bug_fix_checkpoints(checkpoints)

    prompt = (
        f"Fix this {language} code.\nError: {error_msg}\n\n"
        f"```{language}\n{code}\n```\n\n"
        "Return JSON: {\"fixed_code\": str, \"explanation\": str, \"changes\": [str], "
        "\"confidence\": 0.0-1.0, \"risk\": \"low|medium|high\"}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="bug_fix"
    )
    import json, re
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    if not isinstance(result, dict):
        result = {"raw": text}

    fixed_code = str(result.get("fixed_code") or "").strip()
    checkpoint["status"] = "fixed" if fixed_code else "review_required"
    checkpoint["provider"] = provider
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint["fixed_code"] = fixed_code
    checkpoint["confidence"] = result.get("confidence")
    checkpoint["risk"] = result.get("risk")
    _save_bug_fix_checkpoints(checkpoints)

    result["provider"] = provider
    result["checkpoint_id"] = checkpoint_id
    result["rollback_available"] = True
    return result


@router.get("/agent/bug-fix/checkpoints")
async def api_bug_fix_checkpoints(limit: int = 50):
    rows = _load_bug_fix_checkpoints()
    rows = sorted(rows, key=lambda item: str(item.get("created_at", "")), reverse=True)
    capped = rows[: max(1, min(int(limit), 200))]
    return {"checkpoints": capped, "total": len(rows)}


@router.get("/agent/bug-fix/checkpoints/{checkpoint_id}")
async def api_bug_fix_checkpoint_get(checkpoint_id: str):
    rows = _load_bug_fix_checkpoints()
    for row in rows:
        if str(row.get("checkpoint_id") or "") == checkpoint_id:
            return row
    return _api_error("Checkpoint not found", status_code=404)


@router.post("/agent/bug-fix/checkpoints/{checkpoint_id}/rollback")
async def api_bug_fix_checkpoint_rollback(checkpoint_id: str):
    rows = _load_bug_fix_checkpoints()
    for row in rows:
        if str(row.get("checkpoint_id") or "") != checkpoint_id:
            continue
        row["status"] = "rolled_back"
        row["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        _save_bug_fix_checkpoints(rows)
        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "language": row.get("language", "python"),
            "restored_code": row.get("original_code", ""),
            "error": row.get("error", ""),
        }
    return _api_error("Checkpoint not found", status_code=404)


@router.post("/agent/self-correct")
async def api_agent_self_correct(request: Request):
    from ..agent import call_llm_with_fallback
    from ..thinking import build_critique_prompt, parse_critique_response

    body = await request.json()
    question = str(body.get("question", "") or body.get("task", "")).strip()
    answer = str(body.get("answer", "") or body.get("content", "")).strip()
    try:
        confidence = float(body.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    threshold = float(body.get("threshold", 0.75) or 0.75)

    if not answer:
        return _api_error("answer is required", status_code=422)
    if confidence >= threshold:
        return {
            "corrected": False,
            "reason": "confidence_above_threshold",
            "threshold": threshold,
            "confidence": confidence,
            "answer": answer,
        }

    critique_prompt = build_critique_prompt(answer, question or "Provide a better version of this answer")
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": critique_prompt}],
        task="self_correction",
    )
    raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    parsed = parse_critique_response(raw)
    revised = str(parsed.get("revised") or "").strip() or answer
    critique = str(parsed.get("critique") or "").strip()
    revised_confidence = float(parsed.get("confidence", confidence) or confidence)

    db_save_self_review(
        review_id="self_correct_" + secrets.token_hex(6),
        traces_analyzed=0,
        insights=[{"type": "self_correction", "critique": critique}],
        suggestions=[revised],
        provider=provider,
    )

    return {
        "corrected": revised != answer,
        "provider": provider,
        "original_confidence": confidence,
        "threshold": threshold,
        "revised_confidence": revised_confidence,
        "critique": critique,
        "answer": revised,
    }


@router.post("/agent/code-loop")
async def api_agent_code_loop(request: Request):
    from ..agent import run_repo_edit_verify_loop

    body = await request.json()
    task = str(body.get("task") or body.get("prompt") or "").strip()
    if not task:
        return _api_error("task is required", status_code=422)

    sid = str(body.get("sid") or body.get("session_id") or "").strip()
    verify_command = str(body.get("verify_command") or "").strip()
    try:
        max_loops = int(body.get("max_loops", 3) or 3)
    except Exception:
        max_loops = 3

    history = body.get("history") if isinstance(body.get("history"), list) else []
    files = body.get("files") if isinstance(body.get("files"), list) else []
    usage_principal = str(body.get("usage_principal") or "").strip()

    return run_repo_edit_verify_loop(
        task=task,
        history=history,
        files=files,
        sid=sid,
        verify_command=verify_command,
        max_loops=max(1, min(max_loops, 8)),
        usage_principal=usage_principal,
    )


@router.post("/agent/migrate")
async def api_migrate_code(request: Request):
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    code       = str(body.get("code", ""))
    from_lang  = str(body.get("from_language", "python2"))
    to_lang    = str(body.get("to_language", "python3"))
    if not code:
        return _api_error("code required", status_code=422)
    prompt = (
        f"Migrate this code from {from_lang} to {to_lang}.\n\n"
        f"```\n{code}\n```\n\n"
        "Return JSON: {\"migrated_code\": str, \"changes\": [str], \"warnings\": [str]}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="code_migration"
    )
    import json, re
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


@router.post("/agent/diagnose-logs")
async def api_diagnose_logs(request: Request):
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    logs     = str(body.get("logs", ""))
    service  = str(body.get("service", ""))
    if not logs:
        return _api_error("logs required", status_code=422)
    prompt = (
        f"Diagnose these {service} logs and identify root causes.\n\n"
        f"```\n{logs[:8000]}\n```\n\n"
        "Return JSON: {\"issues\": [{\"severity\": str, \"message\": str, \"fix\": str}], "
        "\"root_cause\": str, \"next_steps\": [str]}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="log_diagnosis"
    )
    import json, re
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


@router.post("/benchmark/safety")
async def api_benchmark_safety(request: Request):
    from ..benchmark import run_safety_benchmark
    body = await request.json()
    return run_safety_benchmark(test_cases=body.get("test_cases") or None)


@router.get("/benchmark/safety/results")
async def api_benchmark_safety_results():
    from ..benchmark import load_safety_benchmark_results, evaluate_safety_release_gate
    results = load_safety_benchmark_results(limit=500)
    return {"results": results, "release_gate": evaluate_safety_release_gate(results)}


@router.get("/benchmark/safety/gate")
async def api_benchmark_safety_gate():
    from ..benchmark import load_safety_gate_config, load_safety_benchmark_results, evaluate_safety_release_gate
    cfg = load_safety_gate_config()
    return {"config": cfg, "status": evaluate_safety_release_gate(load_safety_benchmark_results(limit=500), cfg)}


@router.post("/benchmark/safety/gate")
async def api_benchmark_safety_gate_config(request: Request):
    from ..benchmark import update_safety_gate_config
    body = await _read_json_body(request, "invalid JSON body")
    return update_safety_gate_config(body)


# ── Benchmark regression (Section 19.3) ──────────────────────────────────────

@router.get("/benchmark/regression")
async def api_benchmark_regression():
    from ..benchmark import get_regression_report
    return get_regression_report()


@router.post("/benchmark/regression/baseline")
async def api_benchmark_regression_baseline(request: Request):
    from ..benchmark import set_regression_baseline
    body = await request.json()
    return set_regression_baseline(body)


# ── Concurrent task management extras (Section 23) ───────────────────────────

@router.post("/tasks/queue/{task_id}/cancel")
async def api_task_cancel(task_id: str):
    from ..task_queue import cancel_task, get_task_runtime_status
    ok = cancel_task(task_id)
    if not ok:
        return _api_error("Task not found or already terminal", status_code=404)
    return {
        "ok": True,
        "task_id": task_id,
        "status": get_task_runtime_status(task_id),
    }


@router.get("/tasks/queue/{task_id}/status")
async def api_task_status(task_id: str):
    from ..task_queue import get_task_runtime_status
    status = get_task_runtime_status(task_id)
    if status is None:
        return _api_error("Task not found", status_code=404)
    return status


@router.post("/tasks/sessions")
@router.post("/tasks/queue/sessions")
@router.post("/task-sessions")
async def api_task_session_create(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = str(body.get("session_id") or f"ts_{secrets.token_hex(6)}")
    label = str(body.get("label") or "")
    created_by = str(body.get("created_by") or "")
    return {
        "session_id": session_id,
        "label": label,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/tasks/sessions")
@router.get("/tasks/queue/sessions")
@router.get("/task-sessions")
async def api_task_sessions(limit: int = 200):
    from ..task_queue import list_task_sessions
    return {"sessions": list_task_sessions(limit=max(1, min(int(limit), 1000)))}


@router.get("/tasks/sessions/{session_id}")
@router.get("/tasks/queue/sessions/{session_id}")
@router.get("/task-sessions/{session_id}")
async def api_task_session_detail(session_id: str, status: str = "", limit: int = 200):
    from ..task_queue import get_session_tasks
    tasks = get_session_tasks(session_id=session_id, status=status, limit=max(1, min(int(limit), 1000)))
    if not tasks:
        return _api_error("Task session not found", status_code=404)
    return {"session_id": session_id, "tasks": tasks, "total": len(tasks)}


@router.post("/tasks/sessions/{session_id}/cancel")
@router.post("/tasks/queue/sessions/{session_id}/cancel")
@router.post("/task-sessions/{session_id}/cancel")
async def api_task_session_cancel(session_id: str, request: Request):
    from ..task_queue import cancel_session_tasks
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    include_running = bool(body.get("include_running", True))
    result = cancel_session_tasks(session_id=session_id, include_running=include_running)
    if result.get("cancelled", 0) == 0:
        return _api_error("No cancellable tasks found for session", status_code=404)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Section 26 gap-fill routes
# ═══════════════════════════════════════════════════════════════════════════════

# ── 26.1 Security: field encryption, IP filter ───────────────────────────────

@router.get("/admin/security/ip-filter")
async def api_ip_filter_status(request: Request):
    _require_admin(request)
    try:
        from ..security.ip_filter import get_filter_status
        return get_filter_status()
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/security/ip-filter/allowlist")
async def api_ip_allowlist_add(request: Request):
    _require_admin(request)
    body = await request.json()
    cidr = str(body.get("cidr", "")).strip()
    if not cidr:
        return _api_error("cidr is required", status_code=400)
    try:
        from ..security.ip_filter import add_to_allowlist
        ok = add_to_allowlist(cidr)
        return {"added": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.delete("/admin/security/ip-filter/allowlist/{cidr:path}")
async def api_ip_allowlist_remove(request: Request, cidr: str):
    _require_admin(request)
    try:
        from ..security.ip_filter import remove_from_allowlist
        ok = remove_from_allowlist(cidr)
        return {"removed": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/security/ip-filter/blocklist")
async def api_ip_blocklist_add(request: Request):
    _require_admin(request)
    body = await request.json()
    cidr = str(body.get("cidr", "")).strip()
    if not cidr:
        return _api_error("cidr is required", status_code=400)
    try:
        from ..security.ip_filter import add_to_blocklist
        ok = add_to_blocklist(cidr)
        return {"added": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/security/check-ip")
async def api_check_ip(request: Request):
    _require_admin(request)
    body = await request.json()
    ip = str(body.get("ip", "")).strip()
    if not ip:
        return _api_error("ip is required", status_code=400)
    try:
        from ..security.ip_filter import is_ip_allowed
        allowed, reason = is_ip_allowed(ip)
        return {"ip": ip, "allowed": allowed, "reason": reason}
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.3 Safety: hallucination detection, watermarking, copyright, bias ──────

@router.post("/safety/hallucination/check")
async def api_hallucination_check(request: Request):
    body = await request.json()
    response_text = str(body.get("response", ""))
    context = str(body.get("context", ""))
    if not response_text:
        return _api_error("response is required", status_code=400)
    try:
        from ..safety.hallucination import check_grounding
        result = check_grounding(response_text, context)
        return {
            "grounded": result.grounded, "score": result.score, "method": result.method,
            "ungrounded_sentences": result.ungrounded_sentences,
            "evidence_sentences": result.evidence_sentences, "details": result.details,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/safety/watermark/embed")
async def api_watermark_embed(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    session_id = str(body.get("session_id", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.watermark import watermark_text
        marked = watermark_text(text, session_id=session_id)
        return {"watermarked_text": marked, "session_id": session_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/safety/watermark/detect")
async def api_watermark_detect(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    session_id = str(body.get("session_id", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.watermark import detect_watermark, verify_watermark
        detection = detect_watermark(text)
        if session_id:
            verification = verify_watermark(text, session_id)
            detection["verification"] = verification
        return detection
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/safety/copyright/check")
async def api_copyright_check(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.copyright import check_copyright
        result = check_copyright(text)
        return {
            "flagged": result.flagged, "matches": result.matches,
            "notice_detected": result.notice_detected,
            "notice_patterns": result.notice_patterns,
            "highest_similarity": result.highest_similarity,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/safety/copyright/register")
async def api_copyright_register(request: Request):
    _require_admin(request)
    body = await request.json()
    work_id = str(body.get("work_id", "")).strip()
    title = str(body.get("title", "")).strip()
    text = str(body.get("text", "")).strip()
    if not all([work_id, title, text]):
        return _api_error("work_id, title, and text are required", status_code=400)
    try:
        from ..safety.copyright import register_protected_work
        register_protected_work(work_id, title, text, metadata=body.get("metadata", {}))
        return {"registered": True, "work_id": work_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/safety/copyright/works")
async def api_copyright_works(request: Request):
    _require_admin(request)
    try:
        from ..safety.copyright import list_protected_works
        return {"works": list_protected_works()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/safety/bias/evaluate")
async def api_bias_evaluate(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.bias_eval import evaluate_bias
        report = evaluate_bias(text)
        return {
            "flagged": report.flagged, "bias_score": report.bias_score,
            "summary": report.summary,
            "stereotype_matches": report.stereotype_matches,
            "gender_disparity": report.gender_disparity,
            "race_sentiment_scores": report.race_sentiment_scores,
            "religion_sentiment_scores": report.religion_sentiment_scores,
            "text_snippet": report.text_snippet,
        }
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.4 Evaluation: A/B testing, human eval ─────────────────────────────────

@router.get("/evals/experiments")
async def api_list_experiments(request: Request):
    try:
        from ..evals.ab_testing import list_experiments
        return {"experiments": list_experiments()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/evals/experiments")
async def api_create_experiment(request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    variants = body.get("variants", [])
    if not name or not variants:
        return _api_error("name and variants are required", status_code=400)
    try:
        from ..evals.ab_testing import create_experiment
        exp = create_experiment(
            name=name, variants=variants,
            metric=str(body.get("metric", "quality_score")),
            description=str(body.get("description", "")),
        )
        return {"experiment_id": exp.experiment_id, "name": exp.name, "status": exp.status}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/evals/experiments/{experiment_id}/start")
async def api_start_experiment(request: Request, experiment_id: str):
    try:
        from ..evals.ab_testing import start_experiment
        ok = start_experiment(experiment_id)
        return {"started": ok, "experiment_id": experiment_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/evals/experiments/{experiment_id}/pause")
async def api_pause_experiment(request: Request, experiment_id: str):
    try:
        from ..evals.ab_testing import pause_experiment
        ok = pause_experiment(experiment_id)
        return {"paused": ok, "experiment_id": experiment_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/evals/experiments/{experiment_id}/analysis")
async def api_analyze_experiment(request: Request, experiment_id: str):
    try:
        from ..evals.ab_testing import analyze_experiment
        return analyze_experiment(experiment_id)
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/human-eval/tasks")
async def api_human_eval_tasks(request: Request, limit: int = 20):
    _require_admin(request)
    try:
        from ..evals.human_eval_pipeline import get_pending_tasks
        return {"tasks": get_pending_tasks(limit=min(int(limit), 100))}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/human-eval/tasks/{task_id}/rate")
async def api_human_eval_rate(request: Request, task_id: str):
    _require_admin(request)
    body = await request.json()
    rating = body.get("rating")
    rater_id = str(body.get("rater_id", "admin"))
    notes = str(body.get("notes", ""))
    if rating is None:
        return _api_error("rating is required", status_code=400)
    try:
        from ..evals.human_eval_pipeline import submit_rating
        ok = submit_rating(task_id, rating, rater_id, notes)
        return {"submitted": ok, "task_id": task_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/human-eval/stats")
async def api_human_eval_stats(request: Request):
    _require_admin(request)
    try:
        from ..evals.human_eval_pipeline import get_eval_stats
        return get_eval_stats()
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.6 Operational Excellence: retention, cost anomaly, alerting ───────────

@router.get("/admin/retention/policies")
async def api_retention_policies(request: Request):
    _require_admin(request)
    try:
        from ..retention import list_policies
        return {"policies": list_policies()}
    except Exception as exc:
        return _api_error(str(exc))


@router.put("/admin/retention/policies/{data_type}")
async def api_retention_set_policy(request: Request, data_type: str):
    _require_admin(request)
    body = await request.json()
    days = int(body.get("retention_days", 0))
    if days <= 0:
        return _api_error("retention_days must be > 0", status_code=400)
    try:
        from ..retention import set_policy
        set_policy(data_type, days)
        return {"set": True, "data_type": data_type, "retention_days": days}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/retention/purge")
async def api_retention_purge(request: Request):
    _require_admin(request)
    try:
        from ..retention import run_purge_cycle
        results = run_purge_cycle()
        return {"purged": results}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/retention/history")
async def api_retention_history(request: Request, limit: int = 10):
    _require_admin(request)
    try:
        from ..retention import get_purge_history
        return {"history": get_purge_history(limit=min(int(limit), 100))}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/cost-anomaly/history")
async def api_cost_anomaly_history(request: Request, team: str = "", limit: int = 50):
    _require_admin(request)
    try:
        from ..cost_anomaly import get_anomaly_history
        return {"anomalies": get_anomaly_history(team=team or None, limit=min(int(limit), 500))}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/cost-anomaly/check")
async def api_cost_anomaly_check(request: Request):
    _require_admin(request)
    try:
        from ..cost_anomaly import check_all_teams
        return {"anomalies": check_all_teams()}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/capacity/planning")
async def api_capacity_planning_report(request: Request, days: int = 30, horizon_days: int = 14):
    _require_admin(request)
    safe_days = max(7, min(int(days), 365))
    safe_horizon = max(1, min(int(horizon_days), 90))
    try:
        series = get_usage_daily(days=safe_days)
        if not series:
            return {
                "days": safe_days,
                "horizon_days": safe_horizon,
                "history_points": 0,
                "daily_avg_calls": 0,
                "daily_avg_tokens": 0,
                "projected_calls": 0,
                "projected_tokens": 0,
                "recommendation": "insufficient_data",
            }

        total_calls = sum(int(row.get("calls") or 0) for row in series)
        total_tokens = sum(int(row.get("in_tok") or 0) + int(row.get("out_tok") or 0) for row in series)
        day_count = max(1, len(series))
        avg_calls = total_calls / day_count
        avg_tokens = total_tokens / day_count

        projected_calls = int(round(avg_calls * safe_horizon))
        projected_tokens = int(round(avg_tokens * safe_horizon))

        peak_calls = max(int(row.get("calls") or 0) for row in series)
        peak_tokens = max(int(row.get("in_tok") or 0) + int(row.get("out_tok") or 0) for row in series)
        recommended_daily_capacity = int(round(max(avg_calls * 1.3, peak_calls * 1.1)))

        return {
            "days": safe_days,
            "horizon_days": safe_horizon,
            "history_points": day_count,
            "daily_avg_calls": round(avg_calls, 2),
            "daily_avg_tokens": round(avg_tokens, 2),
            "daily_peak_calls": peak_calls,
            "daily_peak_tokens": peak_tokens,
            "projected_calls": projected_calls,
            "projected_tokens": projected_tokens,
            "recommended_daily_capacity": recommended_daily_capacity,
            "recommendation": "scale_up" if peak_calls > avg_calls * 1.2 else "steady",
            "series": series,
        }
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.5 Developer Ecosystem: webhook delivery ────────────────────────────────

@router.get("/admin/webhooks/delivery/stats")
async def api_webhook_delivery_stats(request: Request):
    _require_admin(request)
    try:
        from ..webhooks_delivery import get_webhook_stats
        return get_webhook_stats()
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/webhooks/delivery/dlq")
async def api_webhook_dlq(request: Request):
    _require_admin(request)
    try:
        from ..webhooks_delivery import list_dlq
        return {"dlq": list_dlq()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/webhooks/delivery/{delivery_id}/retry")
async def api_webhook_retry(request: Request, delivery_id: str):
    _require_admin(request)
    try:
        from ..webhooks_delivery import retry_dlq_delivery
        ok = retry_dlq_delivery(delivery_id)
        return {"retried": ok, "delivery_id": delivery_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/webhooks/outbound")
async def api_enqueue_webhook(request: Request):
    body = await request.json()
    url = str(body.get("url", "")).strip()
    event_type = str(body.get("event_type", "generic")).strip()
    payload = body.get("payload", {})
    if not url:
        return _api_error("url is required", status_code=400)
    try:
        from ..webhooks_delivery import enqueue_webhook
        delivery = enqueue_webhook(url=url, event_type=event_type, payload=payload)
        return {"delivery_id": delivery.delivery_id, "status": delivery.status, "url": url}
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.7 Agent Capabilities: persistent state, tool policies, structured output

@router.post("/agents/state")
async def api_create_agent_state(request: Request):
    body = await request.json()
    objective = str(body.get("objective", "")).strip()
    if not objective:
        return _api_error("objective is required", status_code=400)
    user = body.get("username", "") or ""
    try:
        from ..agent_state import create_agent_state
        state = create_agent_state(
            objective=objective,
            session_id=str(body.get("session_id", "")),
            username=user,
            persona_id=str(body.get("persona_id", "")),
            metadata=body.get("metadata", {}),
        )
        return {"agent_id": state.agent_id, "objective": state.objective, "status": state.status}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/agents/state/{agent_id}")
async def api_get_agent_state(request: Request, agent_id: str):
    try:
        from ..agent_state import get_agent_state, get_plan_summary
        state = get_agent_state(agent_id)
        if not state:
            return _api_error("Agent state not found", status_code=404)
        summary = get_plan_summary(state)
        return {
            "agent_id": state.agent_id, "status": state.status,
            "objective": state.objective, "plan_summary": summary,
            "step_count": state.step_count, "updated_at": state.updated_at,
            "working_memory": state.working_memory,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/agents/active")
async def api_list_active_agents(request: Request, username: str = ""):
    try:
        from ..agent_state import list_active_agents
        return {"agents": list_active_agents(username=username or None)}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/admin/tool-policies")
async def api_list_tool_policies(request: Request):
    _require_admin(request)
    try:
        from ..agent_tool_policy import list_policies
        return {"policies": list_policies()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/tool-policies")
async def api_set_tool_policy(request: Request):
    _require_admin(request)
    body = await request.json()
    persona_id = str(body.get("persona_id", "")).strip()
    if not persona_id:
        return _api_error("persona_id is required", status_code=400)
    try:
        from ..agent_tool_policy import ToolPolicy, set_policy
        policy = ToolPolicy(
            persona_id=persona_id,
            mode=str(body.get("mode", "unrestricted")),
            allowed_tools=body.get("allowed_tools", []),
            denied_tools=body.get("denied_tools", []),
            max_calls_per_session=int(body.get("max_calls_per_session", 0)),
            require_approval_for=body.get("require_approval_for", []),
            description=str(body.get("description", "")),
        )
        set_policy(policy)
        return {"set": True, "persona_id": persona_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/structured-output/generate")
async def api_structured_generate(request: Request):
    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    schema = body.get("schema", {})
    if not prompt or not schema:
        return _api_error("prompt and schema are required", status_code=400)
    try:
        from ..structured_output import generate_structured
        result = generate_structured(
            prompt=prompt, schema=schema,
            model_name=str(body.get("model", "")),
            max_tokens=int(body.get("max_tokens", 2048)),
            temperature=float(body.get("temperature", 0.1)),
        )
        return result
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/structured-output/validate")
async def api_structured_validate(request: Request):
    body = await request.json()
    output = str(body.get("output", ""))
    schema = body.get("schema", {})
    if not output or not schema:
        return _api_error("output and schema are required", status_code=400)
    try:
        from ..structured_output import validate_output
        return validate_output(output, schema)
    except Exception as exc:
        return _api_error(str(exc))


# ── 26.8 Data & Knowledge: citation, incremental index ───────────────────────

@router.post("/rag/cite")
async def api_rag_cite(request: Request):
    body = await request.json()
    response_text = str(body.get("response", "")).strip()
    chunks = body.get("chunks", [])
    if not response_text:
        return _api_error("response is required", status_code=400)
    try:
        from ..rag.citation import attribute_response
        result = attribute_response(
            response=response_text, chunks=chunks,
            method=str(body.get("method", "auto")),
            min_confidence=float(body.get("min_confidence", 0.1)),
        )
        return {
            "inline_text": result.inline_text,
            "footnotes": result.footnotes,
            "sources": result.sources,
            "method": result.method,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/rag/index/{collection}/stats")
async def api_rag_index_stats(request: Request, collection: str):
    try:
        from ..rag.incremental_index import get_index_stats
        return get_index_stats(collection)
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/rag/index/{collection}/invalidate/{doc_id}")
async def api_rag_invalidate_doc(request: Request, collection: str, doc_id: str):
    _require_admin(request)
    try:
        from ..rag.incremental_index import invalidate_document
        ok = invalidate_document(doc_id, collection)
        return {"invalidated": ok, "doc_id": doc_id, "collection": collection}
    except Exception as exc:
        return _api_error(str(exc))


# ── Memory forgetting ─────────────────────────────────────────────────────────

@router.get("/admin/memory/health")
async def api_memory_health(request: Request):
    _require_admin(request)
    try:
        from ..memory.forgetting import get_memory_health_report
        return get_memory_health_report()
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/admin/memory/consolidate")
async def api_memory_consolidate(request: Request):
    _require_admin(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = bool(body.get("dry_run", False))
    try:
        from ..memory.forgetting import run_consolidation
        return run_consolidation(dry_run=dry_run)
    except Exception as exc:
        return _api_error(str(exc))


# ── Dataset-backed benchmark runners ─────────────────────────────────────────

@router.post("/benchmark/dataset/run")
async def api_benchmark_dataset_run(request: Request):
    """Run a publishable dataset benchmark (gsm8k, truthfulqa, humaneval, mmlu, hellaswag)."""
    body = await request.json()
    dataset = str(body.get("dataset", "gsm8k")).strip()
    provider = str(body.get("provider", "")).strip()
    model = str(body.get("model", "")).strip()
    max_samples = min(int(body.get("max_samples", 10)), 50)
    try:
        from ..benchmark import run_dataset_benchmark
        return run_dataset_benchmark(dataset=dataset, provider=provider, model=model, max_samples=max_samples)
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/benchmark/dataset/suite")
async def api_benchmark_dataset_suite(request: Request):
    """Run a full suite of dataset benchmarks and return aggregated results."""
    body = await request.json()
    datasets = body.get("datasets") or None
    provider = str(body.get("provider", "")).strip()
    model = str(body.get("model", "")).strip()
    max_samples = min(int(body.get("max_samples_per_dataset", 10)), 50)
    try:
        from ..benchmark import run_dataset_suite_benchmark
        return run_dataset_suite_benchmark(datasets=datasets, provider=provider, model=model, max_samples_per_dataset=max_samples)
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/benchmark/dataset/history")
async def api_benchmark_dataset_history(request: Request):
    """Return persisted dataset benchmark history."""
    dataset = str(request.query_params.get("dataset", "")).strip()
    limit = min(int(request.query_params.get("limit", 50)), 500)
    try:
        from ..benchmark import get_dataset_benchmark_history
        return get_dataset_benchmark_history(dataset=dataset, limit=limit)
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/benchmark/dataset/datasets")
async def api_benchmark_dataset_list(request: Request):
    """List available dataset benchmark runners."""
    from ..evals.dataset_runners import DATASET_RUNNERS
    return {
        "datasets": list(DATASET_RUNNERS.keys()),
        "hf_enabled": __import__("os").getenv("BENCHMARK_USE_HF_DATASETS", "false").lower() == "true",
        "note": "Set BENCHMARK_USE_HF_DATASETS=true to load live samples from HuggingFace",
    }


# ── Benchmark artifact export ─────────────────────────────────────────────────

@router.get("/benchmark/export/{run_id}")
async def api_benchmark_export(request: Request, run_id: str):
    """Export a benchmark run as publishable artifacts (JSONL, CSV, HTML, leaderboard JSON)."""
    formats_raw = str(request.query_params.get("formats", "")).strip()
    formats = [f.strip() for f in formats_raw.split(",") if f.strip()] or None
    try:
        from ..benchmark import export_benchmark_run
        result = export_benchmark_run(run_id=run_id, formats=formats)
        if "error" in result:
            return _api_error(result["error"], status_code=404)
        return result
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/benchmark/export/suite")
async def api_benchmark_export_suite(request: Request):
    """Export a complete benchmark suite as publishable artifacts."""
    body = await request.json()
    suite_data = body.get("suite_data", {})
    full_results = body.get("full_results", [])
    formats_raw = str(body.get("formats", "")).strip()
    formats = [f.strip() for f in formats_raw.split(",") if f.strip()] or None
    if not suite_data or not full_results:
        return _api_error("suite_data and full_results are required", status_code=400)
    try:
        from ..benchmark import export_dataset_suite_artifacts
        return export_dataset_suite_artifacts(suite_data=suite_data, full_results=full_results, formats=formats)
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/benchmark/export/{run_id}/html")
async def api_benchmark_export_html(request: Request, run_id: str):
    """Return the HTML benchmark report directly (text/html content type)."""
    from fastapi.responses import HTMLResponse
    try:
        from ..benchmark import export_benchmark_run
        result = export_benchmark_run(run_id=run_id, formats=["html"])
        if "error" in result:
            return HTMLResponse(f"<h1>Not found</h1><p>{result['error']}</p>", status_code=404)
        return HTMLResponse(content=result.get("html", "<p>No HTML output.</p>"))
    except Exception as exc:
        return HTMLResponse(f"<h1>Error</h1><p>{exc}</p>", status_code=500)
