import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Import your agent
from agent import run_agent_task

app = FastAPI()

# Serve static files (your frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.post("/agent")
async def agent_post(request: Request):
    data = await request.json()
    task = data.get("task")
    result = run_agent_task(task)
    return {"result": result}


@app.get("/agent")
def agent_get(task: str):
    result = run_agent_task(task)
    return {"result": result}


# ====================== IMPORTANT FOR RAILWAY ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",           # or just app if you prefer
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )
