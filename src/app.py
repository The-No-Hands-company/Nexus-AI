import os, uuid, json, asyncio, threading, time
import secrets, hashlib
import jwt as _jwt
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .agent import (run_agent_task, stream_agent_task, get_providers_list,
                   get_config, update_config, call_llm_with_fallback,
                   get_session_dir, set_session_token, _session_state,
                   get_system_resources,
                   _config, PERSONAS)
from .gist_backup import restore_from_gist
from .db import (init_db, save_chat as db_save_chat, load_chats as db_load_chats,
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
from .personas import list_personas, set_persona, get_active_persona_name, get_persona
from .memory import (add_memory, get_memory_context, summarize_history, get_semantic_memory, add_semantic_memory,
                    delete_all as delete_all_memory, get_all as get_all_memory)
from .autonomy import Orchestrator, PlanningSystem, classify_subtask

app = FastAPI(title="Nexus AI")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Allow Nexus Cloud portal to embed this app in an iframe.
@app.middleware("http")
async def allow_iframe_embedding(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response

JWT_SECRET   = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = int(os.getenv("JWT_EXPIRE_HOURS", "168"))

# ── init DB and seed in-memory caches ─────────────────────────────────────────
restore_from_gist()   # pull from Gist before opening DB
init_db()
init_projects_table()
try:
    init_usage_table()
    init_users_table()
except Exception:
    pass




def _auto_title(history):
    for m in history:
        if m.get("role")=="user" and isinstance(m.get("content"),str):
            t = m["content"]
            if not any(t.startswith(p) for p in ["Tool result:","Continue","[MEMORY","[GITHUB"]):
                return t.strip()[:60]
    return "Chat " + datetime.now(timezone.utc).strftime("%b %d")


# ── static ────────────────────────────────────────────────────────────────────


import src.api.routes

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT",8000))
    uvicorn.run("main:app",host="0.0.0.0",port=port,log_level="info")
