"""Observability module for Nexus AI.

Provides:
  - Structured JSON application logging via structlog (falls back to stdlib)
  - X-Request-ID / X-Correlation-ID middleware
  - Prometheus metrics (counter, histogram)
  - OpenTelemetry tracer setup (OTLP export when OTLP_ENDPOINT is set)
  - Admin audit log writer

Environment variables:
    LOG_LEVEL        — log level (default: INFO)
    LOG_FORMAT       — "json" (default) or "text"
    OTLP_ENDPOINT    — OpenTelemetry collector endpoint (optional)
    PROMETHEUS_PORT  — if set, expose a separate Prometheus HTTP server on this port
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
import threading
from logging.handlers import RotatingFileHandler
from urllib import request as _urlrequest
from contextvars import ContextVar
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# ── Context variables ─────────────────────────────────────────────────────────

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

# ── Structured logging setup ──────────────────────────────────────────────────

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()

_structlog_available = False
try:
    import structlog  # type: ignore
    _structlog_available = True
except ImportError:
    pass


def _setup_structlog() -> None:
    if not _structlog_available:
        return

    import structlog  # type: ignore

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
    ]

    if _LOG_FORMAT == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, _LOG_LEVEL, logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


_setup_structlog()

# ── Public logger factory ─────────────────────────────────────────────────────


def get_logger(name: str = "nexus"):
    """Return a structured logger. Falls back to stdlib logging if structlog is not installed."""
    if _structlog_available:
        import structlog  # type: ignore
        return structlog.get_logger(name)
    return logging.getLogger(name)


logger = get_logger("nexus.observability")

# ── Basic stdlib logging setup (always configure) ─────────────────────────────

def setup_logging() -> None:
    """Configure root logging to emit structured JSON or human-readable lines."""
    numeric_level = getattr(logging, _LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)

    if _LOG_FORMAT == "json":
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    formatter = logging.Formatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%S")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        max_bytes = int(os.getenv("LOG_MAX_BYTES", "10485760"))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
        file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    forward_url = os.getenv("LOG_FORWARD_URL", "").strip()
    if forward_url:
        root.addHandler(_HttpForwardHandler(forward_url))


class _HttpForwardHandler(logging.Handler):
    """Best-effort async-ish HTTP forwarding handler for external log sinks."""

    def __init__(self, endpoint: str) -> None:
        super().__init__()
        self._endpoint = endpoint
        self._timeout = float(os.getenv("LOG_FORWARD_TIMEOUT", "1.5"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "ts": int(time.time()),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            data = json.dumps(payload).encode("utf-8")
            req = _urlrequest.Request(
                self._endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            _urlrequest.urlopen(req, timeout=self._timeout).read(0)
        except Exception:
            # Never allow logging sink failures to break request flow.
            pass


# ── Prometheus metrics ────────────────────────────────────────────────────────

_prometheus_available = False
try:
    import prometheus_client as prom  # type: ignore
    _prometheus_available = True
except ImportError:
    pass


class _NoopCounter:
    def labels(self, **_): return self
    def inc(self, *_, **__): pass


class _NoopHistogram:
    def labels(self, **_): return self
    def observe(self, *_, **__): pass
    def time(self):
        import contextlib
        return contextlib.nullcontext()


class _NoopGauge:
    def labels(self, **_):
        return self

    def set(self, *_, **__):
        pass


if _prometheus_available:
    import prometheus_client as prom  # type: ignore

    HTTP_REQUESTS_TOTAL = prom.Counter(
        "nexus_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    HTTP_REQUEST_DURATION = prom.Histogram(
        "nexus_http_request_duration_seconds",
        "HTTP request duration",
        ["method", "path"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    LLM_CALLS_TOTAL = prom.Counter(
        "nexus_llm_calls_total",
        "Total LLM provider calls",
        ["provider", "status"],
    )
    LLM_LATENCY = prom.Histogram(
        "nexus_llm_latency_seconds",
        "LLM call latency",
        ["provider"],
        buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0],
    )
    SAFETY_BLOCKS_TOTAL = prom.Counter(
        "nexus_safety_blocks_total",
        "Total guardrail blocks",
        ["profile", "reason"],
    )
    ACTIVE_STREAMS = prom.Gauge(
        "nexus_active_streams",
        "Currently active SSE streams",
    )
    TASK_QUEUE_DEPTH = prom.Gauge(
        "nexus_task_queue_depth",
        "Current background task queue depth",
    )
    CACHE_HITS = prom.Counter(
        "nexus_cache_hits_total",
        "Cache hit/miss events",
        ["result"],
    )
else:
    HTTP_REQUESTS_TOTAL = _NoopCounter()
    HTTP_REQUEST_DURATION = _NoopHistogram()
    LLM_CALLS_TOTAL = _NoopCounter()
    LLM_LATENCY = _NoopHistogram()
    SAFETY_BLOCKS_TOTAL = _NoopCounter()
    ACTIVE_STREAMS = _NoopGauge()
    TASK_QUEUE_DEPTH = _NoopGauge()
    CACHE_HITS = _NoopCounter()


def set_active_streams_gauge(count: int) -> None:
    """Update active SSE stream gauge with best-effort safety."""
    try:
        ACTIVE_STREAMS.set(max(0, int(count)))
    except Exception:
        pass


def set_task_queue_depth_gauge(depth: int) -> None:
    """Update queue depth gauge with best-effort safety."""
    try:
        TASK_QUEUE_DEPTH.set(max(0, int(depth)))
    except Exception:
        pass


def refresh_runtime_gauges() -> None:
    """Refresh runtime gauges from live in-memory state.

    This keeps /metrics representative even when no requests are currently flowing.
    """
    try:
        from .task_queue import worker_status

        status = worker_status()
        set_task_queue_depth_gauge(int(status.get("queue_depth", 0)))
    except Exception:
        pass

    try:
        from .api.state import _active_streams

        set_active_streams_gauge(len(_active_streams))
    except Exception:
        pass


def get_prometheus_metrics_text() -> str:
    """Return Prometheus metrics in text exposition format."""
    if not _prometheus_available:
        return "# prometheus_client not installed\n"
    from io import BytesIO
    import prometheus_client  # type: ignore
    output = BytesIO()
    prometheus_client.exposition.write_to_textfile  # type: ignore
    return prometheus_client.exposition.generate_latest(  # type: ignore
        prometheus_client.REGISTRY
    ).decode("utf-8")


# ── OpenTelemetry tracing ─────────────────────────────────────────────────────

_otel_available = False
_tracer = None

try:
    from opentelemetry import trace  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
    _otel_available = True
except ImportError:
    pass


def _setup_otel() -> None:
    global _tracer
    if not _otel_available:
        return
    otlp_endpoint = os.getenv("OTLP_ENDPOINT", "")
    from opentelemetry import trace  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.resources import Resource  # type: ignore
    resource = Resource.create({"service.name": "nexus-ai"})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry OTLP configured: %s", otlp_endpoint)
        except Exception as exc:
            logger.warning("OTLP exporter setup failed: %s", exc)

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("nexus-ai")


_setup_otel()


def get_tracer():
    """Return the OpenTelemetry tracer or a no-op proxy."""
    if _otel_available and _tracer:
        return _tracer

    class _NoopTracer:
        def start_as_current_span(self, name, **__):
            import contextlib
            return contextlib.nullcontext()

    return _NoopTracer()


# ── X-Request-ID / X-Correlation-ID middleware ───────────────────────────────

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inject X-Request-ID and X-Correlation-ID into every request/response.

    - Uses the incoming X-Request-ID header if present; generates one otherwise.
    - X-Correlation-ID is propagated from the upstream caller if set.
    - Both values are stored in async context variables and echoed in the response.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = request.headers.get(self._header) or str(uuid.uuid4())
        corr_id = request.headers.get("X-Correlation-ID", req_id)
        actor = request.client.host if request.client else "unknown"
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            actor = f"bearer:{auth[7:19]}"
        elif request.headers.get("X-API-Key", ""):
            actor = f"api_key:{request.headers.get('X-API-Key', '')[:12]}"
        audit_body = os.getenv("AUDIT_BODY_LOG", "false").lower() == "true"
        req_body = ""
        if audit_body:
            try:
                raw = (await request.body())[:4096]
                req_body = _redact_sensitive(raw.decode("utf-8", errors="ignore"))
            except Exception:
                req_body = ""

        token_rid = request_id_ctx.set(req_id)
        token_cid = correlation_id_ctx.set(corr_id)

        start = time.time()
        try:
            try:
                from .secrets_manager import secret_access_context
                from .observability import get_tracer as _get_tracer  # local import for cycle safety

                tracer = _get_tracer()
                with secret_access_context(actor=actor, request_id=req_id):
                    with tracer.start_as_current_span("http.request") as span:
                        if hasattr(span, "set_attribute"):
                            span.set_attribute("http.method", request.method)
                            span.set_attribute("http.path", request.url.path)
                            span.set_attribute("request.id", req_id)
                            span.set_attribute("correlation.id", corr_id)
                        response = await call_next(request)
            except Exception:
                response = await call_next(request)
        finally:
            request_id_ctx.reset(token_rid)
            correlation_id_ctx.reset(token_cid)

        latency_ms = round((time.time() - start) * 1000, 2)
        response.headers[self._header] = req_id
        response.headers["X-Correlation-ID"] = corr_id
        response.headers["X-Response-Time-Ms"] = str(latency_ms)

        # Record Prometheus metrics
        path = request.url.path
        # Normalise dynamic path segments to avoid high-cardinality label explosion
        path_label = _normalise_path(path)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path_label, status=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, path=path_label).observe(
            (time.time() - start)
        )

        if audit_body:
            resp_body = ""
            try:
                raw_resp = getattr(response, "body", b"") or b""
                if isinstance(raw_resp, bytes):
                    raw_resp = raw_resp[:4096]
                    resp_body = _redact_sensitive(raw_resp.decode("utf-8", errors="ignore"))
            except Exception:
                resp_body = ""
            logger.info(
                "http_audit",
                method=request.method,
                path=path,
                status=response.status_code,
                request_id=req_id,
                request_body=req_body,
                response_body=resp_body,
            )

        return response


def _redact_sensitive(text: str) -> str:
    import re

    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted_email]", text)
    text = re.sub(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b", "[redacted_ssn]", text)
    text = re.sub(r"\b(?:\d[ -]*?){13,19}\b", "[redacted_card]", text)
    return text


def _normalise_path(path: str) -> str:
    """Replace UUID / numeric segments with a placeholder to reduce cardinality."""
    import re
    path = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}", path)
    path = re.sub(r"/\d+", "/{n}", path)
    return path


def get_current_request_id() -> str:
    return request_id_ctx.get()


def get_current_correlation_id() -> str:
    return correlation_id_ctx.get()


# ── Backpressure / rate limiting middleware ───────────────────────────────────

_REQUEST_PROTECTION_EXEMPT_PREFIXES = (
    "/static/",
)

_REQUEST_PROTECTION_EXEMPT_PATHS = {
    "/",
    "/health",
    "/health/live",
    "/health/ready",
    "/health/deep",
    "/metrics",
    "/manifest.json",
    "/sw.js",
    "/favicon.ico",
}


def _is_request_protection_exempt(path: str) -> bool:
    return path in _REQUEST_PROTECTION_EXEMPT_PATHS or any(
        path.startswith(prefix) for prefix in _REQUEST_PROTECTION_EXEMPT_PREFIXES
    )

class BackpressureMiddleware(BaseHTTPMiddleware):
    """Reject requests with 503 when the active request count exceeds a threshold.

    This is process-local and intended for single-worker or low-concurrency use.
    For multi-worker deployments, use the Redis-backed rate limiter instead.
    """

    def __init__(self, app: ASGIApp, max_concurrent: int = 100) -> None:
        super().__init__(app)
        self._max = int(os.getenv("MAX_CONCURRENT_REQUESTS", str(max_concurrent)))
        self._max_queue_depth = int(os.getenv("MAX_WORKER_QUEUE_DEPTH", "200"))
        self._active = 0
        self._lock = __import__("threading").Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if _is_request_protection_exempt(path):
            return await call_next(request)

        with self._lock:
            queue_depth = 0
            try:
                from .task_queue import worker_status

                queue_depth = int(worker_status().get("queue_depth", 0))
                set_task_queue_depth_gauge(queue_depth)
            except Exception:
                queue_depth = 0

            if queue_depth >= self._max_queue_depth:
                return Response(
                    content=json.dumps({
                        "error": "Service overloaded — worker queue is saturated",
                        "type": "backpressure_queue_depth",
                        "queue_depth": queue_depth,
                        "queue_limit": self._max_queue_depth,
                    }),
                    status_code=503,
                    media_type="application/json",
                    headers={"Retry-After": "5"},
                )

            if self._active >= self._max:
                return Response(
                    content=json.dumps({
                        "error": "Service overloaded — try again shortly",
                        "type": "backpressure",
                        "active": self._active,
                        "limit": self._max,
                    }),
                    status_code=503,
                    media_type="application/json",
                    headers={"Retry-After": "5"},
                )
            self._active += 1

        try:
            return await call_next(request)
        finally:
            with self._lock:
                self._active -= 1


# ── IP rate limit middleware (token bucket) ───────────────────────────────────

class IpRateLimitMiddleware(BaseHTTPMiddleware):
    """Lightweight per-IP token-bucket rate limiter.

    Checks Redis if available; falls back to in-process dict.
    Environment variables:
        IP_RATE_LIMIT_RPM  — requests per minute per IP (default: 200)
        IP_RATE_LIMIT_MODE — "hard" (block) or "soft" (allow + log)
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._rpm = int(os.getenv("IP_RATE_LIMIT_RPM", "200"))
        self._mode = os.getenv("IP_RATE_LIMIT_MODE", "hard").lower()

    def _get_ip(self, request: Request) -> str:
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return forwarded or (request.client.host if request.client else "unknown")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if _is_request_protection_exempt(path):
            return await call_next(request)

        # Keep contract/integration tests deterministic; they use Starlette's test client host.
        if (request.client and request.client.host == "testclient") or os.getenv("PYTEST_CURRENT_TEST"):
            return await call_next(request)

        ip = self._get_ip(request)
        minute_bucket = int(time.time() // 60)

        try:
            from .redis_state import incr_rate_counter
            count = incr_rate_counter(f"ip:{ip}", str(minute_bucket), 60)
        except Exception:
            count = 0

        if count > self._rpm:
            if self._mode == "hard":
                return Response(
                    content=json.dumps({
                        "error": "IP rate limit exceeded",
                        "type": "ip_rate_limit",
                        "limit": self._rpm,
                        "retry_after": 60,
                    }),
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "Retry-After": "60",
                        "X-RateLimit-Limit": str(self._rpm),
                        "X-RateLimit-Remaining": "0",
                    },
                )
            # soft mode: log but allow through
            logger.warning("ip_rate_limit_exceeded", ip=ip, count=count, limit=self._rpm)

        return await call_next(request)


class PerPrincipalConcurrencyMiddleware(BaseHTTPMiddleware):
    """Limit concurrent in-flight requests per caller principal.

    Principal resolution order:
      1) Bearer token subject-ish fingerprint
      2) X-API-Key fingerprint
      3) source IP
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._limit = int(os.getenv("MAX_CONCURRENT_PER_PRINCIPAL", "8"))
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def _principal(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            return f"bearer:{token[:16]}"
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            return f"api_key:{api_key[:12]}"
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip and request.client:
            ip = request.client.host
        return f"ip:{ip or 'unknown'}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if _is_request_protection_exempt(path):
            return await call_next(request)

        principal = self._principal(request)
        with self._lock:
            cur = self._active.get(principal, 0)
            if cur >= self._limit:
                return Response(
                    content=json.dumps(
                        {
                            "error": "too many concurrent requests for principal",
                            "type": "principal_concurrency_limit",
                            "limit": self._limit,
                        }
                    ),
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "2"},
                )
            self._active[principal] = cur + 1

        try:
            return await call_next(request)
        finally:
            with self._lock:
                nxt = self._active.get(principal, 1) - 1
                if nxt <= 0:
                    self._active.pop(principal, None)
                else:
                    self._active[principal] = nxt


# ── Admin audit log ───────────────────────────────────────────────────────────

def write_audit_log(
    actor: str,
    action: str,
    resource: str = "",
    result: str = "ok",
    metadata: dict | None = None,
    request_id: str = "",
) -> None:
    """Persist an admin audit log entry to the database.

    This is a best-effort write; failures are logged but not re-raised.
    """
    try:
        from .db import write_audit_entry
        write_audit_entry(
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            metadata=json.dumps(metadata or {}),
            request_id=request_id or get_current_request_id(),
        )
    except Exception as exc:
        logger.warning("audit_log_write_failed", error=str(exc))


# ── Startup / health utilities ────────────────────────────────────────────────

def wait_for_dependencies(timeout: float = 30.0) -> dict[str, bool]:
    """Poll critical startup dependencies until ready or timeout.

    Returns a dict of {dependency: ok}.
    """
    results: dict[str, bool] = {}

    # Database
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            from .db import init_db
            init_db()
            results["database"] = True
            break
        except Exception:
            time.sleep(0.5)
    else:
        results["database"] = False

    # Redis (optional — skip if not configured)
    if os.getenv("REDIS_URL"):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                from .redis_state import is_redis_available
                if is_redis_available():
                    results["redis"] = True
                    break
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
        else:
            results["redis"] = False

    return results
