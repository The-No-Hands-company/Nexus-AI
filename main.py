import os
import uuid
import asyncio
import threading
import json
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent_task, stream_agent_task, get_providers_list, PROVIDER

app = FastAPI(title="Claude Alt")
app.mount("/static", StaticFiles(directory="static"), name="static")

sessions: dict[str, list] = {}


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "healthy", "provider": PROVIDER}


@app.get("/providers")
def providers():
    return {"providers": get_providers_list()}


@app.post("/session")
def new_session():
    sid = str(uuid.uuid4())
    sessions[sid] = []
    return {"session_id": sid}


@app.delete("/session/{sid}")
def clear_session(sid: str):
    sessions.pop(sid, None)
    return {"cleared": sid}


# ── non-streaming endpoint (kept for compatibility) ───────────────────────────
@app.post("/agent")
async def agent_post(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    files = data.get("files", [])
    if not task:
        return {"error": "task is required"}
    history = sessions.get(sid, []) if sid else []
    result  = run_agent_task(task, history, files)
    if sid:
        sessions[sid] = result["history"]
    return {"result": result["result"], "provider": result["provider"],
            "model": result["model"], "session_id": sid}


# ── streaming SSE endpoint ────────────────────────────────────────────────────
@app.post("/agent/stream")
async def agent_stream(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    files = data.get("files", [])
    if not task:
        return {"error": "task is required"}

    history = sessions.get(sid, []) if sid else []
    loop    = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run_in_thread():
        try:
            for event in stream_agent_task(task, history, files):
                # Update session history on done
                if event["type"] == "done" and sid:
                    sessions[sid] = event.get("history", history)
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            # Strip history from SSE payload (too large, stored server-side)
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
