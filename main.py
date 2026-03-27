import os
import uuid
import json
import asyncio
import threading
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from agent import (run_agent_task, stream_agent_task, get_providers_list,
                   get_config, update_config, call_llm_with_fallback)
from memory import (add_memory, get_memory_context, summarize_history,
                    delete_all as delete_all_memory, get_all as get_all_memory)

app = FastAPI(title="Claude Alt")
app.mount("/static", StaticFiles(directory="static"), name="static")

sessions: dict[str, list] = {}
chats:    dict[str, dict] = {}
shares:   dict[str, dict] = {}   # share_id → {title, messages, created_at}

# ── helpers ───────────────────────────────────────────────────────────────────
def _auto_title(history: list) -> str:
    for m in history:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            t = m["content"]
            if not t.startswith("Tool result:") and not t.startswith("Continue"):
                return t.strip()[:60]
    return "Chat " + datetime.utcnow().strftime("%b %d")


# ── static ────────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return FileResponse("static/index.html")

@app.get("/health")
def health():
    return {"status": "healthy", "provider": get_config()["provider"]}

@app.get("/providers")
def providers():
    return {"providers": get_providers_list()}


# ── settings ──────────────────────────────────────────────────────────────────
@app.get("/settings")
def get_settings():
    return get_config()

@app.post("/settings")
async def post_settings(request: Request):
    data = await request.json()
    return update_config(
        provider    = data.get("provider"),
        model       = data.get("model"),
        temperature = data.get("temperature"),
    )


# ── memory ────────────────────────────────────────────────────────────────────
@app.get("/memory")
def list_memory():
    return {"memories": get_all_memory()}

@app.delete("/memory")
def clear_memory():
    delete_all_memory()
    return {"cleared": True}


# ── sessions ──────────────────────────────────────────────────────────────────
@app.post("/session")
def new_session():
    sid = str(uuid.uuid4())
    # Seed session with memory context
    memory_ctx = get_memory_context()
    if memory_ctx:
        sessions[sid] = [{"role": "user",      "content": memory_ctx},
                         {"role": "assistant", "content": "Understood, I have context from our previous sessions."}]
    else:
        sessions[sid] = []
    return {"session_id": sid, "has_memory": bool(memory_ctx)}

@app.delete("/session/{sid}")
def clear_session(sid: str):
    sessions.pop(sid, None)
    return {"cleared": sid}


# ── chat history ──────────────────────────────────────────────────────────────
@app.get("/chats")
def list_chats():
    listed = sorted(chats.values(), key=lambda c: c["updated_at"], reverse=True)
    return {"chats": [{"id": c["id"], "title": c["title"],
                       "created_at": c["created_at"], "updated_at": c["updated_at"],
                       "message_count": len(c["messages"])} for c in listed]}

@app.post("/chats")
async def save_chat(request: Request):
    data    = await request.json()
    sid     = data.get("session_id")
    history = sessions.get(sid, []) if sid else data.get("messages", [])
    title   = data.get("title") or _auto_title(history)
    now     = datetime.utcnow().isoformat()
    cid     = data.get("chat_id") or str(uuid.uuid4())
    chats[cid] = {
        "id":         cid,
        "title":      title[:80],
        "created_at": chats[cid]["created_at"] if cid in chats else now,
        "updated_at": now,
        "messages":   history,
    }
    # Async: summarize and store in memory
    def _bg_summarize():
        summary = summarize_history(history, call_llm_with_fallback)
        if summary:
            add_memory(summary)
    threading.Thread(target=_bg_summarize, daemon=True).start()
    return {"chat_id": cid, "title": chats[cid]["title"]}

@app.get("/chats/{cid}")
def load_chat(cid: str):
    chat = chats.get(cid)
    if not chat:
        return {"error": "Chat not found"}
    return chat

@app.delete("/chats/{cid}")
def delete_chat(cid: str):
    chats.pop(cid, None)
    return {"deleted": cid}


# ── export ────────────────────────────────────────────────────────────────────
@app.get("/chats/{cid}/export")
def export_chat(cid: str):
    chat = chats.get(cid)
    if not chat:
        return {"error": "Chat not found"}
    lines = [f"# {chat['title']}", f"*Exported from Claude Alt — {chat['updated_at'][:10]}*", ""]
    for m in chat["messages"]:
        role = m.get("role", "")
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        if content.startswith("Tool result:") or content.startswith("Continue") or content.startswith("[MEMORY"):
            continue
        if role == "user":
            lines += [f"**You:** {content}", ""]
        elif role == "assistant" and not content.startswith("{"):
            lines += [f"**Assistant:** {content}", ""]
    md = "\n".join(lines)
    return StreamingResponse(
        iter([md]),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="chat-{cid[:8]}.md"'}
    )


# ── share ─────────────────────────────────────────────────────────────────────
@app.post("/chats/{cid}/share")
def share_chat(cid: str):
    chat = chats.get(cid)
    if not chat:
        return {"error": "Chat not found"}
    share_id = str(uuid.uuid4())[:8]
    shares[share_id] = {
        "title":      chat["title"],
        "messages":   chat["messages"],
        "created_at": datetime.utcnow().isoformat(),
    }
    return {"share_id": share_id, "url": f"/share/{share_id}"}

@app.get("/share/{share_id}")
def view_share(share_id: str):
    chat = shares.get(share_id)
    if not chat:
        return HTMLResponse("<h2>Share not found or expired.</h2>", status_code=404)
    # Render a simple read-only HTML view
    msgs_html = ""
    for m in chat["messages"]:
        role    = m.get("role", "")
        content = m.get("content", "")
        if not isinstance(content, str): continue
        if content.startswith("Tool result:") or content.startswith("Continue") or content.startswith("[MEMORY"): continue
        if role == "user":
            msgs_html += f'<div class="u"><strong>You</strong><p>{content}</p></div>'
        elif role == "assistant" and not content.startswith("{"):
            msgs_html += f'<div class="a"><strong>Assistant</strong><p>{content}</p></div>'
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{chat['title']} — Claude Alt</title>
<style>
body{{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 20px;background:#09090e;color:#e2e8f0}}
h1{{font-size:1.3rem;margin-bottom:4px}}p.sub{{color:#64748b;font-size:.8rem;margin-bottom:30px}}
.u,.a{{padding:12px 16px;border-radius:12px;margin:10px 0}}
.u{{background:#7c6af7;color:#fff;margin-left:60px}}.a{{background:#111118;border:1px solid #1f1f2e;margin-right:60px}}
strong{{font-size:.75rem;opacity:.7;display:block;margin-bottom:4px}}p{{margin:0;line-height:1.6;white-space:pre-wrap}}
.brand{{text-align:center;margin-top:40px;font-size:.75rem;color:#64748b}}
</style></head><body>
<h1>{chat['title']}</h1>
<p class="sub">Shared from Claude Alt · {chat['created_at'][:10]}</p>
{msgs_html}
<div class="brand">Made with <a href="/" style="color:#7c6af7">Claude Alt</a></div>
</body></html>"""
    return HTMLResponse(html)


# ── agent ─────────────────────────────────────────────────────────────────────
@app.post("/agent")
async def agent_post(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    files = data.get("files", [])
    if task == "__restore__" and "_history" in data:
        if sid: sessions[sid] = data["_history"]
        return {"result": "restored", "provider": "-", "model": "-"}
    if not task:
        return {"error": "task is required"}
    history = sessions.get(sid, []) if sid else []
    result  = run_agent_task(task, history, files)
    if sid: sessions[sid] = result["history"]
    return {"result": result["result"], "provider": result["provider"],
            "model": result["model"], "session_id": sid}


# ── streaming agent ───────────────────────────────────────────────────────────
# track active streams so we can abort them
_active_streams: dict[str, threading.Event] = {}

@app.post("/agent/stream")
async def agent_stream(request: Request):
    data      = await request.json()
    task      = data.get("task", "").strip()
    sid       = data.get("session_id")
    files     = data.get("files", [])
    stream_id = data.get("stream_id", str(uuid.uuid4()))
    if not task:
        return {"error": "task is required"}

    history   = sessions.get(sid, []) if sid else []
    loop      = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_evt  = threading.Event()
    _active_streams[stream_id] = stop_evt

    def run_in_thread():
        try:
            for event in stream_agent_task(task, history, files, stop_evt):
                if stop_evt.is_set():
                    break
                if event["type"] == "done" and sid:
                    sessions[sid] = event.get("history", history)
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait,
                                      {"type": "error", "message": str(e)})
        finally:
            _active_streams.pop(stream_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def generate():
        try:
            while True:
                event = await queue.get()
                if event is None: break
                payload = {k: v for k, v in event.items() if k != "history"}
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            stop_evt.set()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/agent/stop/{stream_id}")
def stop_stream(stream_id: str):
    evt = _active_streams.get(stream_id)
    if evt:
        evt.set()
        return {"stopped": stream_id}
    return {"not_found": stream_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
