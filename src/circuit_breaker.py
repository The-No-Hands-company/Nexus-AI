"""Circuit breaker implementation for Nexus AI.

Provides per-dependency circuit breakers that prevent cascading failures when
an external dependency (LLM provider, database, Redis, etc.) is unhealthy.

States:
  CLOSED   — normal operation; failures are counted
  OPEN     — all calls are rejected immediately
  HALF_OPEN — a single probe call is allowed to test recovery

Environment variables:
    CB_FAILURE_THRESHOLD  — failures before opening (default: 5)
    CB_RECOVERY_TIMEOUT   — seconds in OPEN before trying HALF_OPEN (default: 30)
    CB_SUCCESS_THRESHOLD  — successes in HALF_OPEN before closing (default: 2)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from enum import Enum
from typing import Callable, Any

logger = logging.getLogger("nexus.circuit_breaker")

_DEFAULT_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
_DEFAULT_RECOVERY_TIMEOUT = float(os.getenv("CB_RECOVERY_TIMEOUT", "30"))
_DEFAULT_SUCCESS_THRESHOLD = int(os.getenv("CB_SUCCESS_THRESHOLD", "2"))


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted on an open circuit."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit '{name}' is OPEN. Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """Thread-safe circuit breaker for a single dependency."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = _DEFAULT_RECOVERY_TIMEOUT,
        success_threshold: int = _DEFAULT_SUCCESS_THRESHOLD,
        expected_exceptions: tuple = (Exception,),
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._expected = expected_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_state()

    def _get_state(self) -> CircuitState:
        """Internal state resolution with automatic OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("circuit_half_open name=%s", self.name)
        return self._state

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute a callable through the circuit breaker.

        Raises CircuitBreakerOpen if the circuit is OPEN.
        """
        with self._lock:
            state = self._get_state()
            if state == CircuitState.OPEN:
                retry_after = max(
                    0.0,
                    self._recovery_timeout - (time.time() - self._last_failure_time),
                )
                raise CircuitBreakerOpen(self.name, retry_after)

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except self._expected as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("circuit_closed name=%s", self.name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("circuit_open_from_half_open name=%s", self.name)
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self._failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_open name=%s failures=%s",
                    self.name,
                    self._failure_count,
                )

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
        logger.info("circuit_reset name=%s", self.name)

    def status(self) -> dict:
        with self._lock:
            state = self._get_state()
            retry_after = 0.0
            if state == CircuitState.OPEN:
                retry_after = max(
                    0.0,
                    self._recovery_timeout - (time.time() - self._last_failure_time),
                )
            return {
                "name": self.name,
                "state": state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "retry_after_seconds": round(retry_after, 1),
            }


# ── Registry of all circuit breakers ─────────────────────────────────────────

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: float = _DEFAULT_RECOVERY_TIMEOUT,
    success_threshold: int = _DEFAULT_SUCCESS_THRESHOLD,
    expected_exceptions: tuple = (Exception,),
) -> CircuitBreaker:
    """Return (or create) a named circuit breaker."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                success_threshold=success_threshold,
                expected_exceptions=expected_exceptions,
            )
        return _registry[name]


def all_circuit_status() -> list[dict]:
    """Return status of all registered circuit breakers."""
    with _registry_lock:
        return [cb.status() for cb in _registry.values()]


def reset_circuit(name: str) -> bool:
    """Manually reset a named circuit breaker. Returns False if not found."""
    with _registry_lock:
        cb = _registry.get(name)
    if cb:
        cb.reset()
        return True
    return False


# ── Convenience decorator ─────────────────────────────────────────────────────

def circuit_protected(
    name: str,
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout: float = _DEFAULT_RECOVERY_TIMEOUT,
    fallback: Any = None,
):
    """Decorator: wrap a function with a named circuit breaker.

    If the circuit is open, returns ``fallback`` instead of raising.
    """
    def decorator(fn: Callable) -> Callable:
        cb = get_circuit_breaker(name, failure_threshold, recovery_timeout)

        def wrapper(*args, **kwargs):
            try:
                return cb.call(fn, *args, **kwargs)
            except CircuitBreakerOpen:
                logger.warning("circuit_fallback name=%s fn=%s", name, fn.__name__)
                return fallback

        wrapper.__wrapped__ = fn  # type: ignore
        return wrapper

    return decorator
