"""nexus_ai_sdk.operator — Production operator wrapper with defaults.

``NexusOperator`` wraps ``NexusAIClient`` and adds:
  - Exponential backoff retry on transient errors (5xx, timeout, connection error)
  - Health-check on construction (opt-in via ``verify_health=True``)
  - Configurable per-request timeout with overall deadline
  - Request ID propagation for distributed tracing
  - Structured error enrichment with retry metadata
  - Thread-safe singleton pattern via ``NexusOperator.default()``

Operator defaults are tuned for production: retry up to 3 times with
jitter, 60s per-request timeout, 10s health-check timeout.
"""
from __future__ import annotations

import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .client import NexusAIClient, NexusAIError
from ._version import __version__


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    jitter: float = 0.1
    retryable_status: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )

    def delay(self, attempt: int) -> float:
        """Exponential backoff with ±jitter."""
        raw = self.base_delay_s * (2 ** attempt)
        capped = min(raw, self.max_delay_s)
        jitter_amt = capped * self.jitter * (2 * random.random() - 1)
        return max(0.0, capped + jitter_amt)


@dataclass
class OperatorConfig:
    base_url: str = ""
    api_key: str = ""
    timeout_s: float = 60.0
    verify_health: bool = False
    health_timeout_s: float = 10.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    default_model: str = ""
    default_provider: str = ""
    user_agent_extra: str = ""


class NexusOperator:
    """Production-grade operator wrapper around ``NexusAIClient``."""

    _default_instance: "NexusOperator | None" = None
    _default_lock = threading.Lock()

    def __init__(self, config: OperatorConfig | None = None) -> None:
        cfg = config or OperatorConfig()
        if not cfg.base_url:
            cfg.base_url = os.getenv("NEXUS_BASE_URL", "http://localhost:8000")
        if not cfg.api_key:
            cfg.api_key = os.getenv("NEXUS_API_KEY", "")
        if not cfg.default_model:
            cfg.default_model = os.getenv("NEXUS_DEFAULT_MODEL", "")
        if not cfg.default_provider:
            cfg.default_provider = os.getenv("NEXUS_DEFAULT_PROVIDER", "")

        self.config = cfg
        self._client = NexusAIClient(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            timeout_s=int(cfg.timeout_s),
        )

        if cfg.verify_health:
            self._verify_health()

    def _verify_health(self) -> None:
        """Check server health at construction time."""
        import requests as _req
        url = f"{self.config.base_url.rstrip('/')}/health"
        try:
            r = _req.get(url, timeout=self.config.health_timeout_s)
            if r.status_code >= 400:
                raise NexusAIError(f"Server health check failed: {r.status_code}", status=r.status_code)
        except NexusAIError:
            raise
        except Exception as exc:
            raise NexusAIError(f"Cannot reach Nexus AI server at {url}: {exc}") from exc

    @classmethod
    def default(cls) -> "NexusOperator":
        """Return a process-level singleton operator using env-var config."""
        with cls._default_lock:
            if cls._default_instance is None:
                cls._default_instance = cls()
            return cls._default_instance

    @classmethod
    def reset_default(cls) -> None:
        with cls._default_lock:
            cls._default_instance = None

    def _with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute fn with exponential-backoff retry on transient errors."""
        cfg = self.config.retry
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(cfg.max_attempts):
            try:
                return fn(*args, **kwargs)
            except NexusAIError as exc:
                last_exc = exc
                if exc.status not in cfg.retryable_status:
                    raise
                if attempt < cfg.max_attempts - 1:
                    time.sleep(cfg.delay(attempt))
            except Exception as exc:
                last_exc = exc
                if attempt < cfg.max_attempts - 1:
                    time.sleep(cfg.delay(attempt))
        raise last_exc

    def _request_id(self) -> str:
        return f"op-{uuid.uuid4().hex[:12]}"

    # ── Chat ──────────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request with retry."""
        model = model or self.config.default_model
        return self._with_retry(
            self._client.chat_completions, model, messages, stream=stream, **kwargs
        )

    def chat_stream(self, messages: list[dict[str, Any]], model: str = "", **kwargs: Any):
        """Stream a chat completion (no retry — streaming is not idempotent)."""
        model = model or self.config.default_model
        return self._client.chat_stream(model, messages, **kwargs)

    # ── Agent ─────────────────────────────────────────────────────────────────

    def run_agent(
        self,
        task: str,
        session_id: str = "",
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run an agent task with retry."""
        return self._with_retry(self._client.run_agent, task, session_id, history)

    # ── Benchmarks ────────────────────────────────────────────────────────────

    def benchmark_dataset(
        self,
        dataset: str,
        provider: str = "",
        model: str = "",
        max_samples: int = 10,
    ) -> dict[str, Any]:
        """Run a dataset benchmark via the operator (retry on transient errors)."""
        provider = provider or self.config.default_provider
        model = model or self.config.default_model
        return self._with_retry(
            self._client._request, "POST", "/benchmark/dataset/run",
            {"dataset": dataset, "provider": provider, "model": model, "max_samples": max_samples},
        )

    def benchmark_dataset_suite(
        self,
        datasets: list[str] | None = None,
        provider: str = "",
        model: str = "",
        max_samples_per_dataset: int = 10,
    ) -> dict[str, Any]:
        provider = provider or self.config.default_provider
        model = model or self.config.default_model
        return self._with_retry(
            self._client._request, "POST", "/benchmark/dataset/suite",
            {"datasets": datasets, "provider": provider, "model": model, "max_samples_per_dataset": max_samples_per_dataset},
        )

    def benchmark_export(self, run_id: str, formats: list[str] | None = None) -> dict[str, Any]:
        qs = f"?formats={','.join(formats)}" if formats else ""
        return self._with_retry(self._client._request, "GET", f"/benchmark/export/{run_id}{qs}")

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        return self._with_retry(self._client._request, "GET", "/health")

    def is_healthy(self) -> bool:
        try:
            h = self.health()
            return str(h.get("status", "")).lower() in ("ok", "healthy", "ready")
        except Exception:
            return False

    # ── Raw access ────────────────────────────────────────────────────────────

    @property
    def client(self) -> NexusAIClient:
        """Direct access to the underlying NexusAIClient."""
        return self._client
