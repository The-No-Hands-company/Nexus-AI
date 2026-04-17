import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, init_projects_table, init_usage_table, init_users_table
from .auth import MULTI_USER
from .gist_backup import restore_from_gist
from .safety_middleware import SafetyPipelineMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Restore from Gist (Cloud sync)
    try:
        restore_from_gist()
    except Exception as e:
        print(f"Startup: Gist restore failed: {e}")

    # 2. Initialize Database Tables
    init_db()
    init_projects_table()
    init_usage_table()
    init_users_table()

    # 3. Trigger route-specific startup (e.g., scheduler)
    from .api import routes as api_routes
    if hasattr(api_routes, "startup_event"):
        api_routes.startup_event()
    
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="Nexus AI",
        description="The sovereign, agentic OS for the No-Hands Company.",
        version="1.0.0",
        lifespan=lifespan
    )

    # Middlewares
    app.add_middleware(SafetyPipelineMiddleware)
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Iframe embedding for Nexus Cloud
    @app.middleware("http")
    async def allow_iframe_embedding(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "ALLOWALL"
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response

    # Static Files
    static_path = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    # Load Routes
    from .api.routes import router as api_router
    app.include_router(api_router)

    return app

app = create_app()
