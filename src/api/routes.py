import os, uuid, json, asyncio, threading, time, hmac, secrets, hashlib
import jwt as _jwt
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError
from ..app import app
from ..agent import (run_agent_task, stream_agent_task, get_providers_list, get_config, update_config, call_llm_with_fallback, get_session_dir, set_session_token, _session_state, get_system_resources, _config, PERSONAS, activity_log, _MAX_ACTIVITY, get_session_safety_profile, set_session_safety_profile, safety_log, _push_safety_event)
from ..approvals import list_tool_approvals, decide_tool_approval
from ..scheduler import (
    schedule_job,
    list_jobs,
    cancel_job,
    job_to_dict,
    set_run_function,
)
from ..gist_backup import restore_from_gist
from ..db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats, load_chat as db_load_chat, delete_chat as db_delete_chat, save_share as db_save_share, load_share as db_load_share, init_projects_table, save_project as db_save_project, load_projects as db_load_projects, delete_project as db_delete_project, assign_chat_to_project, get_project_chats, save_custom_instructions as db_save_ci, load_custom_instructions as db_load_ci, update_memory_entry as db_update_memory, delete_memory_entry as db_delete_memory, pin_chat as db_pin_chat, get_pinned_chats, search_chats as db_search_chats, get_usage_stats, get_usage_daily, init_usage_table, save_custom_persona as db_save_persona, load_custom_personas as db_load_custom_personas, delete_custom_persona as db_del_persona, load_pref as db_load_pref, save_pref as db_save_pref)
from ..personas import list_personas, set_persona, get_active_persona_name, get_persona
from ..memory import (add_memory, get_memory_context, summarize_history, get_semantic_memory, add_semantic_memory, delete_all as delete_all_memory, get_all as get_all_memory)
from ..autonomy import Orchestrator, PlanningSystem, classify_subtask
from ..safety import GuardrailViolation, check_user_task, scrub_pii
from ..safety_pipeline import SAFETY_POLICY_PROFILES, get_safety_policy, screen_input
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


def _apply_response_format_hint(task: str, response_format: str) -> str:
    if not response_format:
        return task
    response_format = response_format.strip().lower()
    if response_format == "json":
        return task + (
            "\n\nRespond with strict JSON only. "
            "The response must be valid JSON and contain no extra prose or markdown."
        )
    return task


def _run_scheduled_task(task: str) -> str:
    """Execute a scheduled background task and return short result text."""
    sid = f"sched_{uuid.uuid4().hex[:8]}"
    result = run_agent_task(task, history=[], sid=sid)
    return str(result.get("result", ""))[:1200]


def _validate_json_output(text: str):
    try:
        return json.loads(text)
    except Exception as exc:
        raise ValueError(str(exc))


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
    payload = {"sub": username, "exp": int(_t()) + JWT_EXPIRE_H * 3600}
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def _orchestrator_llm(prompt: str, task: str = "") -> str:
    result, _pid = call_llm_with_fallback([{"role":"user","content":prompt}], task)
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)


def _read_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload.get("sub")
    except Exception:
        return None

def require_auth(request: Request) -> str:
    from fastapi import HTTPException
    username = _read_token(request)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized — valid Bearer token required")
    return username

# ── auth endpoints ────────────────────────────────────────────────────────────
@app.post("/auth/register")
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
        return {"token": token, "username": username}
    return JSONResponse({"error": "registration failed"}, status_code=500)

@app.post("/auth/login")
def auth_login(username: str = "", password: str = ""):
    from ..db import get_user
    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)
    user = get_user(username)
    if not user or not _verify_pw(password, user["password"]):
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    token = _make_token(username)
    return {"token": token, "username": username}

@app.get("/auth/me")
def auth_me(request: Request):
    username = _read_token(request)
    if not username:
        return JSONResponse({"username": None}, status_code=401)
    return {"username": username}

@app.get("/")
def home(): return FileResponse("static/index.html")


# ── Webhook trigger ─────────────────────────────────────────────────────────────
# POST /webhook/trigger  { "task": "fix the login bug", "repo": "owner/repo" }
# Runs the agent asynchronously and streams back SSE or returns a run_id for polling.
# Optional header: X-Webhook-Secret: <secret>  (validated against WEBHOOK_SECRET env var)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

@app.post("/webhook/trigger")
async def webhook_trigger(request: Request):
    from fastapi import HTTPException
    secret = request.headers.get("x-webhook-secret", "")
    if WEBHOOK_SECRET and not hmac.compare_digest(secret, WEBHOOK_SECRET):
        return JSONResponse({"error": "invalid webhook secret"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    task = body.get("task", "")
    if not task:
        return JSONResponse({"error": "task field is required"}, status_code=400)
    try:
        task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    repo = body.get("repo", "")
    # Spin off agent in background thread, return a run_id
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

@app.get("/webhook/status/{run_id}")
async def webhook_status(run_id: str):
    result = run_results.get(run_id)
    if not result:
        return JSONResponse({"error": "run_id not found"}, status_code=404)
    return result

@app.get("/health")
def health(): return {"status":"healthy","provider":get_config()["provider"]}

@app.get("/api/system/resources")
def system_resources():
    return get_system_resources()

@app.get("/providers")
def providers(): return {"providers":get_providers_list()}


# ── Swarm View ────────────────────────────────────────────────────────────────

@app.get("/swarm/activity")
def swarm_activity(limit: int = 50):
    """Return the most recent swarm activity events (capped at _MAX_ACTIVITY)."""
    limit = max(1, min(limit, _MAX_ACTIVITY))
    return {"events": activity_log[-limit:], "total": len(activity_log)}


@app.post("/safety/check")
async def safety_check(request: Request):
    data = await request.json()
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


@app.post("/safety/pii-scan")
async def pii_scan(request: Request):
    data = await request.json()
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


@app.post("/safety/prompt-injection")
async def prompt_injection_scan(request: Request):
    data = await request.json()
    text = (data.get("text") or "")
    if not text.strip():
        return _api_error("text is required", "validation_error", 422)

    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard") or "standard")
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
    }

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

@app.get("/scheduler/jobs")
def scheduler_jobs():
    jobs = [job_to_dict(j) for j in list_jobs()]
    return {"jobs": jobs, "total": len(jobs)}


@app.post("/scheduler/jobs")
async def scheduler_create_job(request: Request):
    body = await request.json()
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


@app.post("/scheduler/jobs/{job_id}/cancel")
def scheduler_cancel_job(job_id: str):
    if cancel_job(job_id):
        return {"ok": True, "job_id": job_id}
    return _api_error("job not found", "not_found", 404)


# ── OpenAI-compatible API (v1) ────────────────────────────────────────────────
# Allows Nexusclaw, Nexus Computer, and any OpenAI-compatible client to use
# Nexus AI as a drop-in API engine.  Set base_url to http://<host>:<port>/v1.
#
# Endpoints:
#   GET  /v1/models                  – list available models
#   POST /v1/chat/completions        – synchronous or streaming chat

@app.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": [
            {"id": "nexus-ai", "object": "model", "created": 0, "owned_by": "nexus-systems"},
            {"id": "nexus-ai/auto", "object": "model", "created": 0, "owned_by": "nexus-systems"},
        ] + [
            {"id": f"nexus-ai/{p}", "object": "model", "created": 0, "owned_by": "nexus-systems"}
            for p in get_providers_list()
        ],
    }

@app.get("/v1/models/capabilities")
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
                "capabilities": ["chat", "streaming", "tool_calls", "embeddings"],
            }
            for provider in providers
        ],
    }

@app.post("/v1/embeddings")
async def v1_embeddings(request: Request):
    try:
        payload = V1EmbeddingsRequest(**(await request.json()))
    except ValidationError:
        return _api_error("Invalid embeddings request", "validation_error", 422)

    inputs = [payload.input] if isinstance(payload.input, str) else payload.input
    if not inputs:
        return _api_error("input is required", "validation_error", 422)

    try:
        embeddings = get_rag_system().embedding_model.embed_batch(inputs)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
    except Exception as exc:
        return _api_error(f"Failed to generate embeddings: {exc}", "model_error", 500)

    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": list(vec), "index": idx}
            for idx, vec in enumerate(embeddings)
        ],
        "model": payload.model,
    }

@app.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    try:
        payload = V1ChatCompletionsRequest(**(await request.json()))
    except ValidationError:
        return _api_error("Invalid chat completions request", "validation_error", 422)

    messages = payload.messages
    stream = payload.stream
    model = payload.model
    response_format = payload.response_format

    if not messages:
        return _api_error("messages is required", "validation_error", 422)

    # Separate system messages from conversation turns
    system_parts = [m.content for m in messages if m.role == "system"]
    turns = [m for m in messages if m.role != "system"]

    if not turns or turns[-1].role != "user":
        return _api_error("Last message must be role=user", "validation_error", 422)

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
        return _api_error(exc.reason, exc.code, 422)

    task = _apply_response_format_hint(task, response_format or "")

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
                        if response_format == "json":
                            try:
                                _validate_json_output(content)
                                delta_text = content
                            except ValueError as exc:
                                delta_text = (
                                    f"\nError: response_format=json required valid JSON but model output failed to parse: {exc}"
                                )
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
    if response_format == "json":
        try:
            validated = _validate_json_output(output)
            output = json.dumps(validated)
        except ValueError:
            return _api_error(
                "response_format=json required valid JSON but model output failed to parse",
                "invalid_response_format",
                422,
            )

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
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_nexus": {"provider": result.get("provider", ""), "model": result.get("model", "")},
    }


# ── settings ──────────────────────────────────────────────────────────────────
@app.get("/manifest.json")
def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})

@app.get("/personas")
def get_personas():
    return {"personas": list_personas(), "active": get_active_persona_name()}

@app.post("/personas/{persona_id}")
def switch_persona(persona_id: str):
    p = set_persona(persona_id)
    return {"active": persona_id, "persona": p}

@app.get("/settings")
def get_settings(): return get_config()

@app.post("/settings")
async def post_settings(request: Request):
    data = await request.json()
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


@app.get("/settings/safety")
def get_safety_settings():
    profile = _config.get("safety_profile", "standard")
    return {
        "safety_profile": profile,
        "policy": get_safety_policy(profile),
        "available_profiles": sorted(SAFETY_POLICY_PROFILES.keys()),
    }


@app.post("/settings/safety")
async def update_safety_settings(request: Request):
    data = await request.json()
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


@app.get("/safety/profiles")
def list_safety_profiles():
    return {
        "active": _config.get("safety_profile", "standard"),
        "profiles": {
            name: get_safety_policy(name)
            for name in sorted(SAFETY_POLICY_PROFILES.keys())
        },
    }


@app.get("/safety/audit")
def get_safety_audit(limit: int = 200, session_id: str = "", event_type: str = ""):
    limit = max(1, min(limit, 1000))
    session_id = (session_id or "").strip()
    event_type = (event_type or "").strip()
    filtered: list = list(safety_log)
    if session_id:
        filtered = [
            event for event in filtered
            if str(event.get("session") or "") == session_id
            or str(event.get("session_id") or "") == session_id
        ]
    if event_type:
        filtered = [event for event in filtered if event.get("type") == event_type]
    events = filtered[-limit:]
    return {
        "events": events,
        "total": len(filtered),
        "session_id": session_id or None,
        "event_type": event_type or None,
        "filtered": bool(session_id or event_type),
    }

@app.get("/personas")
def list_personas():
    active = _config["persona"]
    return {"personas": [
        {"id": k, "label": v["label"], "emoji": v["emoji"],
         "description": v["description"], "active": k == active}
        for k, v in PERSONAS.items()
    ]}


# ── memory ────────────────────────────────────────────────────────────────────
@app.get("/memory")
def list_memory(): return {"memories": get_all_memory()}

@app.delete("/memory")
def clear_memory(): delete_all_memory(); return {"cleared":True}

@app.post("/memory/prune")
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

@app.get("/memory/semantic")
def get_semantic_mem():
    try:
        from ..memory import get_semantic_memory
        return {"memories": get_semantic_memory("", 5)}
    except Exception as e:
        return {"memories": [], "note": str(e)}

@app.post("/memory/semantic")
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

@app.post("/benchmark/run")
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


@app.get("/benchmark/results")
def benchmark_results():
    """Return stored benchmark results (most recent first)."""
    from ..db import load_benchmark_results
    return {"results": load_benchmark_results()}


# ── Consensus reasoning endpoint ──────────────────────────────────────────────
@app.post("/reason/consensus")
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
        return {
            "consensus": consensus_text,
            "provider":  winning_pid,
            "ensemble":  meta.get("ensemble", False),
            "unanimous": meta.get("unanimous"),
            "polled":    meta.get("polled", []),
        }
    except Exception as exc:
        return _api_error(str(exc), "consensus_error", 500)


# ── RAG endpoints ─────────────────────────────────────────────────────────
@app.post("/rag/ingest")
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


@app.post("/rag/query")
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


@app.get("/rag/status")
def rag_status():
    try:
        return get_rag_system().stats()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/autonomy/plan")
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


@app.post("/autonomy/execute")
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


@app.get("/autonomy/trace/{trace_id}")
def autonomy_trace(trace_id: str):
    """Retrieve a stored plan or execution trace by its ID."""
    trace = autonomy_traces.get(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace not found"}, status_code=404)
    return trace


# ── sessions ──────────────────────────────────────────────────────────────────
@app.post("/session")
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

@app.delete("/session/{sid}")
def clear_session(sid: str):
    sessions.pop(sid, None)
    _session_state.pop(sid, None)
    return {"cleared":sid}


# ── token endpoint (set from UI without pasting in chat) ─────────────────────
@app.post("/session/{sid}/token")
async def set_token(sid: str, request: Request):
    data  = await request.json()
    token = data.get("token","").strip()
    if token: set_session_token(sid, token)
    return {"set": bool(token)}


# ── per-session safety profile override ──────────────────────────────────────
@app.get("/session/{sid}/safety")
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

@app.post("/session/{sid}/safety")
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
@app.get("/chats")
def list_chats():
    pinned_ids = set(get_pinned_chats())
    def _sort(ch):
        return (ch["id"] not in pinned_ids, ch["updated_at"])
    listed = sorted(chats.values(), key=_sort, reverse=True)
    return {"chats":[{"id":c["id"],"title":c["title"],"created_at":c["created_at"],
                      "updated_at":c["updated_at"],"message_count":len(c["messages"]),
                      "pinned": c["id"] in pinned_ids} for c in listed]}

@app.post("/chats")
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

@app.get("/chats/{cid}")
def load_chat(cid: str):
    chat = chats.get(cid) or db_load_chat(cid)
    if chat and cid not in chats:
        chats[cid] = chat   # repopulate in-memory cache
    return chat if chat else {"error":"Not found"}

@app.delete("/chats/{cid}")
def delete_chat(cid: str):
    chats.pop(cid, None)
    db_delete_chat(cid)
    return {"deleted":cid}

@app.get("/chats/{cid}/export")
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

@app.post("/chats/{cid}/share")
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

@app.get("/share/{share_id}")
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

@app.get("/projects")
def list_projects():
    return {"projects": list(sorted(projects.values(), key=lambda p: p["updated_at"], reverse=True))}

@app.post("/projects")
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

@app.get("/projects/{pid}")
def get_project(pid: str):
    return projects.get(pid) or {"error":"Not found"}

@app.delete("/projects/{pid}")
def del_project(pid: str):
    projects.pop(pid, None)
    db_delete_project(pid)
    return {"deleted": pid}

@app.post("/projects/{pid}/chats/{cid}")
def link_chat_to_project(pid: str, cid: str):
    assign_chat_to_project(pid, cid)
    return {"linked": cid}

@app.get("/projects/{pid}/chats")
def project_chat_list(pid: str):
    chat_ids = get_project_chats(pid)
    result   = [chats[cid] for cid in chat_ids if cid in chats]
    return {"chats": result}

@app.get("/projects/{pid}/context")
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

@app.post("/projects/{pid}/sessions")
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

@app.post("/projects/{pid}/context")
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
@app.get("/instructions")
def get_instructions():
    return {"instructions": db_load_ci()}

@app.post("/instructions")
async def set_instructions(request: Request):
    data = await request.json()
    db_save_ci(data.get("instructions",""))
    return {"saved": True}


# ── memory CRUD ────────────────────────────────────────────────────────────────
@app.patch("/memory/{entry_id}")
async def update_memory(entry_id: int, request: Request):
    data = await request.json()
    db_update_memory(entry_id, data.get("summary",""))
    return {"updated": entry_id}

@app.delete("/memory/{entry_id}")
def delete_memory_item(entry_id: int):
    db_delete_memory(entry_id)
    return {"deleted": entry_id}


# ── usage dashboard ───────────────────────────────────────────────────────────
# Per-session rate limiting

# ── search ────────────────────────────────────────────────────────────────────
@app.get("/chats/search")
def search_chats_endpoint(q: str = ""):
    if not q.strip():
        return {"results": []}
    return {"results": db_search_chats(q)}


# ── pin ────────────────────────────────────────────────────────────────────────
@app.post("/chats/{cid}/pin")
async def pin_chat_endpoint(cid: str, request: Request):
    data   = await request.json()
    pinned = data.get("pinned", True)
    db_pin_chat(cid, pinned)
    if cid in chats:
        chats[cid]["pinned"] = pinned
    return {"pinned": pinned}


# ── custom personas ────────────────────────────────────────────────────────────
@app.get("/personas/custom")
def list_custom_personas():
    return {"personas": db_load_personas()}

@app.post("/personas/custom")
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

@app.delete("/personas/custom/{pid}")
def delete_custom_persona_endpoint(pid: str):
    db_del_persona(pid)
    return {"deleted": pid}


# ── usage dashboard ───────────────────────────────────────────────────────────
# Per-session rate limiting
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX    = int(os.getenv("SESSION_RATE_LIMIT", "30"))   # req/min per session

def _check_rate_limit(sid: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    if not sid:
        return True
    now    = time.time()
    times  = _session_requests.get(sid, [])
    recent = [t for t in times if now - t < RATE_LIMIT_WINDOW]
    if len(recent) >= RATE_LIMIT_MAX:
        return False
    recent.append(now)
    _session_requests[sid] = recent
    return True


@app.get("/usage")
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
@app.get("/providers/health")
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

@app.post("/reactions")
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

@app.get("/reactions")
def get_reactions(chat_id: str = ""):
    if chat_id:
        return {"reactions": {k:v for k,v in _reactions.items() if v.get("chat_id")==chat_id}}
    return {"reactions": _reactions}


# ── search ───────────────────────────────────────────────────────────────────
@app.get("/search")
def search_chats_endpoint(q: str = ""):
    if not q.strip():
        return {"results": []}
    return {"results": db_search_chats(q)}


# ── pins ──────────────────────────────────────────────────────────────────────
_pins: set = set(get_pinned_chats())

@app.post("/chats/{cid}/pin")
def pin_chat_endpoint(cid: str):
    _pins.add(cid)
    db_pin_chat(cid, True)
    return {"pinned": cid}

@app.delete("/chats/{cid}/pin")
def unpin_chat_endpoint(cid: str):
    _pins.discard(cid)
    db_pin_chat(cid, False)
    return {"unpinned": cid}

@app.get("/chats/pinned")
def get_pinned():
    result = [chats[cid] for cid in _pins if cid in chats]
    return {"chats": result}


# ── user preferences ──────────────────────────────────────────────────────────
@app.get("/prefs")
def get_prefs():
    return {
        "theme":     db_load_pref("theme", "dark"),
        "font_size": db_load_pref("font_size", "15"),
    }

@app.post("/prefs")
async def set_prefs(request: Request):
    data = await request.json()
    for key in ("theme", "font_size"):
        if key in data:
            db_save_pref(key, str(data[key]))
    return {"saved": True}


# ── agent ─────────────────────────────────────────────────────────────────────
@app.post("/agent")
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


@app.post("/agent/stream")
async def agent_stream(request: Request):
    data      = await request.json()
    task      = data.get("task","").strip()
    sid       = data.get("session_id")
    files     = data.get("files",[])
    stream_id = data.get("stream_id", str(uuid.uuid4()))
    trace_id  = data.get("trace_id", str(uuid.uuid4()))
    if not task:
        return _api_error("task is required", "validation_error", 422)

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

    # Rate limit check
    import time as _time
    if sid and not _check_rate_limit(sid):
        return JSONResponse({"error": f"Rate limit exceeded: max {RATE_LIMIT_MAX} requests/min per session."}, status_code=429)

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

@app.get("/agent/trace/{trace_id}")
def get_agent_trace(trace_id: str):
    trace = execution_traces.get(trace_id)
    if trace is None:
        return _api_error("trace not found", "not_found", 404)
    return {"trace_id": trace_id, "events": trace}


@app.post("/agent/stop/{stream_id}")
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

@app.get("/memory/search")
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

@app.post("/feedback/{chat_id}/{message_idx}")
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


@app.get("/feedback/export")
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


@app.get("/feedback/stats")
def feedback_stats():
    """Return aggregate thumbs-up / thumbs-down counts."""
    from ..db import get_feedback_stats
    return get_feedback_stats()


# ── Sprint F: Specialist Agent Library ───────────────────────────────────────

@app.get("/agents")
def list_specialist_agents():
    """Return the full catalogue of built-in specialist agents."""
    from ..agents import list_agents
    return {"agents": list_agents()}


@app.get("/agents/{agent_id}")
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


@app.post("/agents/{agent_id}/run")
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


@app.post("/agents/classify")
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

@app.post("/orchestrate/hierarchical")
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


@app.get("/orchestrate/hierarchical/{trace_id}")
def get_hierarchical_trace(trace_id: str):
    """Retrieve a stored hierarchical orchestration result by trace ID."""
    trace = autonomy_traces.get(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace not found"}, status_code=404)
    return trace


# ── Sprint G: Simulate Endpoint ───────────────────────────────────────────────

@app.post("/simulate")
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

@app.get("/marketplace/agents")
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


@app.post("/marketplace/agents", status_code=201)
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


@app.delete("/marketplace/agents/{agent_id}", status_code=200)
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
@app.get("/agents/bus/log")
def get_bus_log(limit: int = 50):
    """Return the recent global message bus log."""
    from ..agent_bus import recent_log, all_agents
    msgs = recent_log(limit=limit)
    return {
        "messages":      [m.to_dict() for m in msgs],
        "active_agents": all_agents(),
    }


@app.get("/agents/bus/{agent_id}")
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


@app.post("/agents/bus", status_code=201)
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


@app.delete("/tasks/{trace_id}")
def delete_task_trace(trace_id: str):
    deleted = _delete_trace(trace_id)
    execution_traces.pop(trace_id, None)
    if not deleted:
        return _api_error("trace not found", "not_found", 404)
    return {"deleted": trace_id, "ok": True}


# ── Ensemble settings endpoints ──────────────────────────────────────────────

@app.post("/kg/store")
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


@app.get("/kg/query")
def kg_query_endpoint(q: str = "", limit: int = 10):
    if not q:
        return _api_error("q is required", "validation_error", 422)
    results = _kg_query(q, limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/kg/entities")
def kg_entities_endpoint(entity_type: str = "", limit: int = 100):
    results = _kg_list(entity_type=entity_type or None, limit=limit)
    return {"entities": results, "count": len(results)}


@app.get("/kg/entities/{name}")
def kg_entity_get_endpoint(name: str):
    entity = _kg_get(name)
    if entity is None:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return entity


@app.delete("/kg/entities/{name}")
def kg_entity_delete_endpoint(name: str):
    deleted = _kg_delete(name)
    if not deleted:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return {"deleted": name, "ok": True}


# ── Execution Trace replay/resume endpoints ──────────────────────────────────

@app.get("/tasks")
def list_tasks(limit: int = 50):
    traces = _list_traces(limit=limit)
    return {"traces": traces, "count": len(traces)}


@app.get("/tasks/{trace_id}")
def get_task_trace(trace_id: str):
    # Check in-memory first (live traces), then SQLite checkpoints
    in_memory = execution_traces.get(trace_id)
    checkpoints = _load_checkpoints(trace_id)
    if in_memory is None and not checkpoints:
        return _api_error("trace not found", "not_found", 404)
    events = in_memory if in_memory is not None else []
    return {"trace_id": trace_id, "events": events, "checkpoints": len(checkpoints)}


@app.get("/tasks/{trace_id}/replay")
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


@app.post("/tasks/{trace_id}/resume")
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


@app.delete("/tasks/{trace_id}")
def delete_task_trace(trace_id: str):
    deleted = _delete_trace(trace_id)
    execution_traces.pop(trace_id, None)
    if not deleted:
        return _api_error("trace not found", "not_found", 404)
    return {"deleted": trace_id, "ok": True}


# ── Ensemble settings endpoints ──────────────────────────────────────────────

@app.get("/settings/ensemble")
def get_ensemble_settings():
    return {
        "ensemble_mode":      _config.get("ensemble_mode", True),
        "ensemble_threshold": _config.get("ensemble_threshold", 0.4),
        "ensemble_enabled":   get_ensemble_enabled(),
    }


@app.post("/settings/ensemble")
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


@app.get("/settings/hitl")
def get_hitl_settings():
    return {
        "hitl_approval_mode": _config.get("hitl_approval_mode", "off"),
    }


@app.post("/settings/hitl")
async def update_hitl_settings(request: Request):
    data = await request.json()
    mode = str(data.get("hitl_approval_mode", "off")).lower().strip()
    if mode not in ("off", "warn", "block"):
        return _api_error("hitl_approval_mode must be one of: off, warn, block", "validation_error", 422)
    update_config(hitl_approval_mode=mode)
    return {"hitl_approval_mode": _config.get("hitl_approval_mode", "off")}


@app.get("/approvals")
def get_approvals(session_id: str = ""):
    return {
        "items": list_tool_approvals(session_id),
        "total": len(list_tool_approvals(session_id)),
    }


@app.post("/approvals/{approval_id}")
async def resolve_approval(approval_id: str, request: Request):
    data = await request.json()
    approved = bool(data.get("approved", False))
    note = str(data.get("note", ""))
    resolved = decide_tool_approval(approval_id, approved=approved, note=note)
    if not resolved:
        return _api_error("approval not found", "not_found", 404)
    return resolved


def startup_event() -> None:
    set_run_function(_run_scheduled_task)
    asyncio.create_task(_register_with_nexus_cloud())
    asyncio.create_task(_heartbeat_loop())


