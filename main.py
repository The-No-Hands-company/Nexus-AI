import os, uuid, json, asyncio, threading, time
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from agent import (run_agent_task, stream_agent_task, get_providers_list,
                   get_config, update_config, call_llm_with_fallback,
                   get_session_dir, set_session_token, _session_state,
                   _config, PERSONAS)
from gist_backup import restore_from_gist
from db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats,
               load_chat as db_load_chat, delete_chat as db_delete_chat,
               save_share as db_save_share, load_share as db_load_share,
               init_projects_table, save_project as db_save_project,
               load_projects as db_load_projects, delete_project as db_delete_project,
               assign_chat_to_project, get_project_chats,
               save_custom_instructions as db_save_ci, load_custom_instructions as db_load_ci,
               update_memory_entry as db_update_memory, delete_memory_entry as db_delete_memory,
               pin_chat as db_pin_chat, get_pinned_chats, search_chats as db_search_chats,
               get_usage_stats, get_usage_daily, init_usage_table,
               save_custom_persona as db_save_persona, load_custom_personas as db_load_personas,
               delete_custom_persona as db_del_persona)
from personas import list_personas, set_persona, get_active_persona_name, get_persona
from memory import (add_memory, get_memory_context, summarize_history,
                    delete_all as delete_all_memory, get_all as get_all_memory)

app = FastAPI(title="Claude Alt")
app.mount("/static", StaticFiles(directory="static"), name="static")

sessions: dict[str, list] = {}
_active_streams: dict[str, threading.Event] = {}

# ── init DB and seed in-memory caches ─────────────────────────────────────────
restore_from_gist()   # pull from Gist before opening DB
init_db()
init_projects_table()
try:
    init_usage_table()
except Exception:
    pass


# Seed chats from DB
chats: dict[str, dict] = {}
for _row in db_load_chats():
    _row["messages"] = __import__("json").loads(_row["messages"]) if isinstance(_row["messages"], str) else _row["messages"]
    chats[_row["id"]] = _row

# Shares are kept in-memory only (read-only links, OK to lose on restart)
shares: dict[str, dict] = {}
_active_streams: dict[str, threading.Event] = {}


def _auto_title(history):
    for m in history:
        if m.get("role")=="user" and isinstance(m.get("content"),str):
            t = m["content"]
            if not any(t.startswith(p) for p in ["Tool result:","Continue","[MEMORY","[GITHUB"]):
                return t.strip()[:60]
    return "Chat "+datetime.utcnow().strftime("%b %d")


# ── static ────────────────────────────────────────────────────────────────────
@app.get("/")
def home(): return FileResponse("static/index.html")

@app.get("/health")
def health(): return {"status":"healthy","provider":get_config()["provider"]}

@app.get("/providers")
def providers(): return {"providers":get_providers_list()}


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


# ── sessions ──────────────────────────────────────────────────────────────────
@app.post("/session")
def new_session():
    sid = str(uuid.uuid4())
    memory_ctx = get_memory_context()
    if memory_ctx:
        sessions[sid] = [{"role":"user","content":memory_ctx},
                         {"role":"assistant","content":"Understood, I have context from previous sessions."}]
    else:
        sessions[sid] = []
    # ensure session workdir exists
    get_session_dir(sid)
    return {"session_id":sid,"has_memory":bool(memory_ctx)}

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
    lines = [f"# {chat['title']}",f"*Exported from Claude Alt — {chat['updated_at'][:10]}*",""]
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
    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{chat['title']} — Claude Alt</title>
<style>body{{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 20px;background:#09090e;color:#e2e8f0}}
h1{{font-size:1.3rem}}p.sub{{color:#64748b;font-size:.8rem;margin-bottom:30px}}
.u,.a{{padding:12px 16px;border-radius:12px;margin:10px 0}}
.u{{background:#7c6af7;color:#fff;margin-left:60px}}.a{{background:#111118;border:1px solid #1f1f2e;margin-right:60px}}
strong{{font-size:.75rem;opacity:.7;display:block;margin-bottom:4px}}p{{margin:0;line-height:1.6;white-space:pre-wrap}}
.brand{{text-align:center;margin-top:40px;font-size:.75rem;color:#64748b}}</style></head>
<body><h1>{chat['title']}</h1><p class="sub">Shared from Claude Alt · {chat['created_at'][:10]}</p>
{msgs_html}<div class="brand">Made with <a href="/" style="color:#7c6af7">Claude Alt</a></div></body></html>"""
    return HTMLResponse(html)


# ── projects ──────────────────────────────────────────────────────────────────
projects: dict[str, dict] = {r["id"]: r for r in db_load_projects()}

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
_session_requests: dict[str, list] = {}   # {sid: [timestamps]}
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
        from tools_builtin import estimate_cost, PROVIDER_COSTS
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
    from agent import PROVIDERS, _has_key, _is_rate_limited, _cooldowns

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
_reactions: dict[str, dict] = {}   # {reaction_id: {chat_id, msg_idx, reaction}}

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
_session_requests: dict[str, list] = {}   # {sid: [timestamps]}
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
        from tools_builtin import estimate_cost, PROVIDER_COSTS
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
    from agent import PROVIDERS, _has_key, _is_rate_limited, _cooldowns

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
_reactions: dict[str, dict] = {}   # {reaction_id: {chat_id, msg_idx, reaction}}

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
    if not task: return {"error":"task is required"}
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
    if not task: return {"error":"task is required"}

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
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait,{"type":"error","message":str(e)})
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
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.post("/agent/stop/{stream_id}")
def stop_stream(stream_id: str):
    evt = _active_streams.get(stream_id)
    if evt: evt.set(); return {"stopped":stream_id}
    return {"not_found":stream_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT",8000))
    uvicorn.run("main:app",host="0.0.0.0",port=port,log_level="info")
