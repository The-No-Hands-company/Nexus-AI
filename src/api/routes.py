import os, uuid, json, asyncio, threading, time, hmac, secrets, hashlib
import jwt as _jwt
from datetime import datetime
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError
from ..app import app
from ..agent import (run_agent_task, stream_agent_task, get_providers_list, get_config, update_config, call_llm_with_fallback, get_session_dir, set_session_token, _session_state, get_system_resources, _config, PERSONAS)
from ..gist_backup import restore_from_gist
from ..db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats, load_chat as db_load_chat, delete_chat as db_delete_chat, save_share as db_save_share, load_share as db_load_share, init_projects_table, save_project as db_save_project, load_projects as db_load_projects, delete_project as db_delete_project, assign_chat_to_project, get_project_chats, save_custom_instructions as db_save_ci, load_custom_instructions as db_load_ci, update_memory_entry as db_update_memory, delete_memory_entry as db_delete_memory, pin_chat as db_pin_chat, get_pinned_chats, search_chats as db_search_chats, get_usage_stats, get_usage_daily, init_usage_table, save_custom_persona as db_save_persona, load_custom_personas as db_load_custom_personas, delete_custom_persona as db_del_persona, load_pref as db_load_pref, save_pref as db_save_pref)
from ..personas import list_personas, set_persona, get_active_persona_name, get_persona
from ..memory import (add_memory, get_memory_context, summarize_history, get_semantic_memory, add_semantic_memory, delete_all as delete_all_memory, get_all as get_all_memory)
from ..autonomy import Orchestrator, PlanningSystem, classify_subtask
from ..safety import GuardrailViolation, check_user_task
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
        task = check_user_task(task)
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


@app.post("/safety/check")
async def safety_check(request: Request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return _api_error("text is required", "validation_error", 422)
    allow_destructive = bool(data.get("allow_destructive", False))
    from ..safety import check_text_against_guardrail
    decision = check_text_against_guardrail(text, allow_destructive=allow_destructive)
    return {
        "allowed": decision.allowed,
        "issues": [
            {
                "code": issue.code,
                "reason": issue.reason,
                "detail": issue.detail,
                "severity": issue.severity,
                "pattern": issue.pattern,
            }
            for issue in decision.issues
        ],
        "masked_text": decision.masked_text,
    }


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
    return update_config(provider=data.get("provider"),
                         model=data.get("model"),
                         temperature=data.get("temperature"),
                         persona=data.get("persona"))

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


# ── RAG endpoints ─────────────────────────────────────────────────────────────
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
    now     = datetime.utcnow().isoformat()
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
    share_data = {"title":chat["title"],"messages":chat["messages"],
                   "created_at":datetime.utcnow().isoformat()}
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
    now  = datetime.utcnow().isoformat()
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
        "last_session": datetime.utcnow().isoformat(),
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
        task = check_user_task(task)
    except GuardrailViolation as exc:
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
        task = check_user_task(task)
    except GuardrailViolation as exc:
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
            for event in stream_agent_task(task, history, files, stop_evt, sid=sid or ""):
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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_register_with_nexus_cloud())
    asyncio.create_task(_heartbeat_loop())


