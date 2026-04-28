from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(RuntimeError):
    pass


@dataclass
class _CircuitBreaker:
    name: str
    failure_threshold: int = 3
    recovery_timeout_s: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_at: float = 0.0

    def status(self) -> dict[str, Any]:
        now = time.time()
        reopen_in = 0.0
        if self.state == CircuitState.OPEN:
            reopen_in = max(0.0, self.recovery_timeout_s - (now - self.last_failure_at))
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": int(self.failure_count),
            "failure_threshold": int(self.failure_threshold),
            "last_failure_at": float(self.last_failure_at),
            "recovery_timeout_s": float(self.recovery_timeout_s),
            "reopen_in_s": round(reopen_in, 3),
        }

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_at >= self.recovery_timeout_s:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen(self.name)
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.failure_count += 1
            self.last_failure_at = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            raise
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        return result


_BREAKERS: dict[str, _CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> _CircuitBreaker:
    breaker = _BREAKERS.get(name)
    if breaker is None:
        breaker = _CircuitBreaker(name=name)
        _BREAKERS[name] = breaker
    return breaker