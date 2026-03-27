import os
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent_task, get_providers_list, PROVIDER

app = FastAPI(title="Claude Alt - Self-hosted Code Agent")
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


@app.post("/agent")
async def agent_post(request: Request):
    data  = await request.json()
    task  = data.get("task", "").strip()
    sid   = data.get("session_id")
    if not task:
        return {"error": "task is required"}
    history = sessions.get(sid, []) if sid else []
    result  = run_agent_task(task, history)
    if sid:
        sessions[sid] = result["history"]
    return {
        "result":   result["result"],
        "provider": result["provider"],
        "model":    result["model"],
        "session_id": sid,
    }


@app.delete("/session/{sid}")
def clear_session(sid: str):
    sessions.pop(sid, None)
    return {"cleared": sid}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
