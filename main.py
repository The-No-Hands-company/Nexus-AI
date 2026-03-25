import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent_task

app = FastAPI(title="Claude Alt - Self-hosted Code Agent")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/agent")
async def agent_post(request: Request):
    data = await request.json()
    task = data.get("task", "")
    result = run_agent_task(task)
    return result


@app.get("/agent")
def agent_get(task: str):
    result = run_agent_task(task)
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
