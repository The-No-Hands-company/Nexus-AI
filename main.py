import os
import uuid
import json
import asyncio
import threading
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from agent import (run_agent_task, stream_agent_task, get_providers_list,
                   get_config, update_config)

app = FastAPI(title="Claude Alt")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── session store ─────────────────────────────────────────────────────────────
sessions: dict[str, list] = {}

# ── chat history store ────────────────────────────────────────────────────────
# { chat_id: { id, title, created_at, updated_at, messages: [...] } }
chats: dict[str, dict] = {}


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    cfg = get_config()
    return {"status": "healthy", "provider": cfg["provider"]}


@app.get("/debug/env")
def debug_env():
    """Shows which provider env vars are present — values are hidden."""
    from agent import PROVIDERS
    result = {}
    for pid, cfg in PROVIDERS.items():
        key_name = cfg["env_key"]
        val = os.getenv(key_name, "")
        result[key_name] = {
            "present": bool(val),
            "length":  len(val),
            "prefix":  val[:4] + "…" if val else "(not set)",
        }
    return result
    return {"providers": get_providers_list()}


# ── settings ──────────────────────────────────────────────────────────────────
@app.get("/settings")
def get_settings():
    return get_config()


@app.post("/settings")
async def post_settings(request: Request):
    data = await request.json()
    cfg  = update_config(
        provider    = data.get("provider"),
        model       = data.get("model"),
        temperature = data.get("temperature"),
    )
    return cfg


# ── sessions ──────────────────────────────────────────────────────────────────
@app.post("/session")
def new_session():
    sid = str(uuid.uuid4())
    sessions[sid] = []
    return {"session_id": sid}


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
    title   = data.get("title", "Untitled chat")
    history = sessions.get(sid, []) if sid else data.get("messages", [])
    now     = datetime.utcnow().isoformat()
    # Check if we're updating an existing saved chat
    cid = data.get("chat_id") or str(uuid.uuid4())
    chats[cid] = {
        "id":         cid,
        "title":      title[:80],
        "created_at": chats[cid]["created_at"] if cid in chats else now,
        "updated_at": now,
        "messages":   history,
    }
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


# ── agent (non-streaming) ─────────────────────────────────────────────────────
@app.post("/agent")
async def agent_post(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    files = data.get("files", [])

    # Special: restore session history (used when loading a saved chat)
    if task == "__restore__" and "_history" in data:
        if sid:
            sessions[sid] = data["_history"]
        return {"result": "restored", "provider": "-", "model": "-"}

    if not task:
        return {"error": "task is required"}
    history = sessions.get(sid, []) if sid else []
    result  = run_agent_task(task, history, files)
    if sid:
        sessions[sid] = result["history"]
    return {"result": result["result"], "provider": result["provider"],
            "model": result["model"], "session_id": sid}


# ── agent (streaming SSE) ─────────────────────────────────────────────────────
@app.post("/agent/stream")
async def agent_stream(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    files = data.get("files", [])
    if not task:
        return {"error": "task is required"}

    history = sessions.get(sid, []) if sid else []
    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run_in_thread():
        try:
            for event in stream_agent_task(task, history, files):
                if event["type"] == "done" and sid:
                    sessions[sid] = event.get("history", history)
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait,
                                      {"type": "error", "message": str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            payload = {k: v for k, v in event.items() if k != "history"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
