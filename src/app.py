import logging
import os
import asyncio
import signal
import threading
import time
from email.utils import format_datetime
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .deployment_profiles import apply_profile
apply_profile()  # apply NEXUS_PROFILE overrides before dependent modules read env vars

from .db import init_db, init_projects_table, init_usage_table, init_users_table
from .auth import MULTI_USER  # noqa: F401  (side-effect: sets auth mode)
from .gist_backup import restore_from_gist
from .safety_middleware import SafetyPipelineMiddleware

# ── Observability setup (graceful import) ─────────────────────────────────────

try:
    from .observability import (
        setup_logging,
        RequestIdMiddleware,
        IpRateLimitMiddleware,
        PerPrincipalConcurrencyMiddleware,
        BackpressureMiddleware,
        wait_for_dependencies,
        get_logger,
    )
    setup_logging()
    _logger = get_logger("nexus.app")
    _OBS_AVAILABLE = True
except Exception:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    _logger = logging.getLogger("nexus.app")
    _OBS_AVAILABLE = False

    class _NoopMW:
        def __init__(self, *a, **kw): pass

    RequestIdMiddleware = _NoopMW  # type: ignore[misc,assignment]
    IpRateLimitMiddleware = _NoopMW  # type: ignore[misc,assignment]
    PerPrincipalConcurrencyMiddleware = _NoopMW  # type: ignore[misc,assignment]
    BackpressureMiddleware = _NoopMW  # type: ignore[misc,assignment]

    async def wait_for_dependencies(timeout: int = 10) -> dict:  # type: ignore[misc]
        return {}


# ── Shutdown signal handler ───────────────────────────────────────────────────

_SHUTDOWN_SIGNAL = False
_INFLIGHT_REQUESTS = 0
_INFLIGHT_LOCK = threading.Lock()
_DEPRECATED_ENDPOINTS = {
    "/v1/completions": "2026-12-31T00:00:00+00:00",
}


def _startup_warmup_mode() -> str:
    mode = str(os.getenv("AGENT_STARTUP_WARMUP_MODE", "full")).strip().lower()
    if mode not in {"off", "critical", "background", "full"}:
        mode = "full"
    return mode


def _startup_warmup_critical_providers() -> list[str]:
    raw = os.getenv("AGENT_STARTUP_WARMUP_CRITICAL", "ollama,openrouter,gemini,groq")
    providers: list[str] = []
    for item in raw.split(","):
        p = item.strip().lower()
        if p and p not in providers:
            providers.append(p)
    return providers


def _inflight_inc() -> None:
    global _INFLIGHT_REQUESTS
    with _INFLIGHT_LOCK:
        _INFLIGHT_REQUESTS += 1


def _inflight_dec() -> None:
    global _INFLIGHT_REQUESTS
    with _INFLIGHT_LOCK:
        _INFLIGHT_REQUESTS = max(0, _INFLIGHT_REQUESTS - 1)


def _inflight_count() -> int:
    with _INFLIGHT_LOCK:
        return _INFLIGHT_REQUESTS

def _register_shutdown_handlers() -> None:
    def _handle(signum, frame):
        global _SHUTDOWN_SIGNAL
        _SHUTDOWN_SIGNAL = True
        _logger.info("shutdown_signal_received")
    try:
        signal.signal(signal.SIGTERM, _handle)
    except (OSError, ValueError):
        pass


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _register_shutdown_handlers()

    try:
        restore_from_gist()
    except Exception as exc:
        _logger.warning("gist_restore_failed error=%s", exc)

    init_db()
    init_projects_table()
    init_usage_table()
    init_users_table()

    try:
        health = await wait_for_dependencies(timeout=10)
        _logger.info("startup_deps_ready health=%s", health)
    except Exception as exc:
        _logger.warning("startup_deps_check_failed error=%s", exc)

    try:
        from .secrets_manager import start_secret_rotation_daemon

        start_secret_rotation_daemon()
    except Exception as exc:
        _logger.warning("secret_rotation_start_failed error=%s", exc)

    from .api import routes as api_routes
    if hasattr(api_routes, "startup_event"):
        api_routes.startup_event()

    # Warmup strategy: OFF | CRITICAL | BACKGROUND | FULL
    mode = _startup_warmup_mode()
    critical = _startup_warmup_critical_providers()
    try:
        from .agent import warmup_agent

        if mode == "off":
            _logger.info("agent_warmup_skipped mode=off")
        elif mode == "critical":
            result = warmup_agent(
                sid="runtime",
                persona="general",
                provider_order=critical,
                task="warmup_critical",
            )
            _logger.info("agent_warmup_complete mode=critical result=%s", result)
        elif mode == "background":
            async def _bg_warmup() -> None:
                try:
                    result = await asyncio.to_thread(
                        warmup_agent,
                        sid="runtime",
                        persona="general",
                        provider_order=None,
                        task="warmup_full",
                    )
                    _logger.info("agent_warmup_complete mode=background result=%s", result)
                except Exception as bg_exc:
                    _logger.warning("agent_warmup_failed mode=background error=%s", bg_exc)

            asyncio.create_task(_bg_warmup())
            _logger.info("agent_warmup_scheduled mode=background")
        else:
            result = warmup_agent(
                sid="runtime",
                persona="general",
                provider_order=None,
                task="warmup_full",
            )
            _logger.info("agent_warmup_complete mode=full result=%s", result)
    except Exception as exc:
        _logger.warning("agent_warmup_failed mode=%s error=%s", mode, exc)

    # Zero-downtime online DDL migrations (non-blocking, idempotent)
    try:
        from .online_ddl import run_pending_migrations
        migration_results = run_pending_migrations()
        _logger.info("online_ddl_complete results=%s", migration_results)
    except Exception as exc:
        _logger.warning("online_ddl_failed error=%s", exc)

    # Initialize async PostgreSQL pool (asyncpg) if DATABASE_URL is PostgreSQL
    try:
        from .db import init_async_pool
        await init_async_pool()
        _logger.info("async_pg_pool_initialized")
    except Exception as exc:
        _logger.warning("async_pg_pool_init_failed error=%s", exc)

    # Start background workers introduced in Section 26 gap-fill
    try:
        from .retention import start_retention_worker
        start_retention_worker()
        _logger.info("retention_worker_started")
    except Exception as exc:
        _logger.warning("retention_worker_start_failed error=%s", exc)

    try:
        from .cost_anomaly import start_cost_anomaly_worker
        start_cost_anomaly_worker()
        _logger.info("cost_anomaly_worker_started")
    except Exception as exc:
        _logger.warning("cost_anomaly_worker_start_failed error=%s", exc)

    try:
        from .webhooks_delivery import start_webhook_worker
        start_webhook_worker()
        _logger.info("webhook_delivery_worker_started")
    except Exception as exc:
        _logger.warning("webhook_delivery_worker_start_failed error=%s", exc)

    try:
        from .memory.forgetting import start_forgetting_worker
        start_forgetting_worker()
        _logger.info("memory_forgetting_worker_started")
    except Exception as exc:
        _logger.warning("memory_forgetting_worker_start_failed error=%s", exc)

    # Load tool policies and copyright registry from DB
    try:
        from .agent_tool_policy import _load_policies_from_db
        _load_policies_from_db()
        _logger.info("agent_tool_policies_loaded")
    except Exception as exc:
        _logger.warning("agent_tool_policies_load_failed error=%s", exc)

    try:
        from .safety.copyright import load_registry_from_db
        load_registry_from_db()
        _logger.info("copyright_registry_loaded")
    except Exception as exc:
        _logger.warning("copyright_registry_load_failed error=%s", exc)

    yield

    # Graceful shutdown: wait briefly for in-flight requests to finish.
    timeout_s = float(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT", "20"))
    deadline = time.time() + timeout_s
    while _inflight_count() > 0 and time.time() < deadline:
        time.sleep(0.1)

    # Close async pool
    try:
        from .db import close_async_pool
        await close_async_pool()
    except Exception:
        pass

    _logger.info("shutdown_complete inflight=%s", _inflight_count())


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Nexus AI",
        description="The sovereign, agentic OS for the No-Hands Company.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        accept = (request.headers.get("Accept") or "").lower()
        if "application/vnd.nexus.v2+json" in accept and not request.url.path.startswith("/v2/"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "error": "Requested API version is not available",
                    "type": "unsupported_api_version",
                    "requested": "v2",
                    "available": ["v1"],
                },
                status_code=406,
            )

        if _SHUTDOWN_SIGNAL and request.url.path not in (
            "/health",
            "/health/live",
            "/health/ready",
            "/health/deep",
            "/metrics",
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "error": "server shutting down",
                    "type": "shutdown_draining",
                },
                status_code=503,
                headers={"Retry-After": "5"},
            )

        _inflight_inc()
        try:
            response = await call_next(request)
            response.headers["X-Frame-Options"] = "ALLOWALL"
            response.headers["Content-Security-Policy"] = "frame-ancestors *"
            if request.url.path.startswith("/v1"):
                response.headers["X-API-Version"] = "v1"
            else:
                response.headers["X-API-Version"] = "legacy"
            if request.url.path in _DEPRECATED_ENDPOINTS:
                sunset_iso = _DEPRECATED_ENDPOINTS[request.url.path]
                sunset_dt = datetime.fromisoformat(sunset_iso)
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = format_datetime(sunset_dt.astimezone(timezone.utc), usegmt=True)
            return response
        finally:
            _inflight_dec()

    app.add_middleware(SafetyPipelineMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if _OBS_AVAILABLE:
        app.add_middleware(BackpressureMiddleware)  # type: ignore[arg-type]
        app.add_middleware(PerPrincipalConcurrencyMiddleware)  # type: ignore[arg-type]
        app.add_middleware(IpRateLimitMiddleware)   # type: ignore[arg-type]
        app.add_middleware(RequestIdMiddleware)     # type: ignore[arg-type]

    # Opt-in request/response body audit logging (gated by AUDIT_BODY_LOG=true)
    if os.getenv("AUDIT_BODY_LOG", "").lower() == "true":
        from starlette.middleware.base import BaseHTTPMiddleware
        import re as _re

        _PII_PATTERNS = [
            _re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),            # SSN
            _re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),  # email
            _re.compile(r'\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b'),  # phone
            _re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b'),  # credit card
            _re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),      # IPv4
        ]
        _REDACT_FIELDS = {"password", "token", "secret", "api_key", "key", "credential"}

        def _scrub_pii(text: str) -> str:
            for pat in _PII_PATTERNS:
                text = pat.sub("[REDACTED]", text)
            return text

        def _redact_body(raw: bytes) -> str:
            try:
                import json as _json
                decoded = raw.decode("utf-8", errors="replace")
                parsed = _json.loads(decoded)
                if isinstance(parsed, dict):
                    for fld in _REDACT_FIELDS:
                        if fld in parsed:
                            parsed[fld] = "[REDACTED]"
                    return _scrub_pii(_json.dumps(parsed, ensure_ascii=False)[:4096])
                return _scrub_pii(decoded[:4096])
            except Exception:
                return "[binary-or-invalid-json]"

        class AuditBodyLogMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                req_body = await request.body()
                response = await call_next(request)
                resp_body = b""
                async for chunk in response.body_iterator:
                    resp_body += chunk
                req_redacted = _redact_body(req_body)
                resp_redacted = _redact_body(resp_body)
                _logger.info(
                    "audit_body path=%s method=%s req_body=%s resp_body=%s status=%s",
                    request.url.path,
                    request.method,
                    req_redacted,
                    resp_redacted,
                    response.status_code,
                )
                from starlette.responses import Response
                return Response(
                    content=resp_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        app.add_middleware(AuditBodyLogMiddleware)

    static_path = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/status", include_in_schema=False)
    async def public_status_page():
        status_page = os.path.join(static_path, "status.html")
        if os.path.exists(status_page):
            return FileResponse(status_page, media_type="text/html")
        return JSONResponse(
            {
                "ok": True,
                "status": "operational",
                "detail": "Status page is not available; serve static/status.html to enable UI.",
            }
        )

    from .api.routes import router as api_router
    from .routes.rlhf import router as rlhf_router
    # Mount with no prefix for backwards-compat bare paths (/chat, /health, etc.)
    app.include_router(api_router)
    # Mount again under /v1 so every route is also reachable at /v1/<path>.
    # Clients that use the explicit /v1/ prefix will work; existing bare-path
    # clients continue to work unchanged.  The X-API-Version response header
    # (set by the existing APIVersionMiddleware) still signals "v1" vs "legacy".
    app.include_router(api_router, prefix="/v1")
    # RLHF router already uses /v1/rlhf prefix internally.
    app.include_router(rlhf_router)

    # SCIM 2.0 provisioning endpoints
    try:
        from .api.scim import router as scim_router
        app.include_router(scim_router)
    except Exception as exc:
        _logger.warning("scim_router_load_failed error=%s", exc)

    # IP allowlist/geo-blocking middleware (opt-in via IP_ALLOWLIST or GEO_BLOCKED_COUNTRIES)
    if os.getenv("IP_ALLOWLIST") or os.getenv("GEO_BLOCKED_COUNTRIES") or os.getenv("IP_BLOCKLIST"):
        try:
            from .security.ip_filter import IPFilterMiddleware
            app.add_middleware(IPFilterMiddleware)
            _logger.info("ip_filter_middleware_enabled")
        except Exception as exc:
            _logger.warning("ip_filter_middleware_failed error=%s", exc)

    return app


app = create_app()
