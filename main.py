from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent_task

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.post("/agent")
async def agent(request: Request):
    data = await request.json()
    task = data.get("task")

    result = run_agent_task(task)

    return {"result": result}


@app.get("/agent")
def agent_get(task: str):
    result = run_agent_task(task)
    return {"result": result}
