from __future__ import annotations

"""Federated inference and training-round helpers with graceful fallback hooks."""

from dataclasses import dataclass
import json
import os
import time
from typing import Any
from urllib import request as _urlrequest

from .config.feature_flags import ENABLE_FEDERATED_LLM
from .db import load_pref, save_pref
from .feature_flags import is_enabled


_ROUNDS_KEY = "federated.rounds.v1"
_HOOKS_KEY = "federated.fallback_hooks.v1"


@dataclass
class FederatedRoundResult:
    status: str
    global_round: int
    samples_seen: int
    submitted: bool
    message: str = ""
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "global_round": int(self.global_round),
            "samples_seen": int(self.samples_seen),
            "submitted": bool(self.submitted),
            "message": self.message,
            "latency_ms": int(self.latency_ms),
        }


def _load_json(key: str, default: Any) -> Any:
    raw = load_pref(key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _save_json(key: str, value: Any) -> None:
    save_pref(key, json.dumps(value, separators=(",", ":")))


def _append_fallback_hook(reason: str, detail: str = "") -> None:
    hooks = _load_json(_HOOKS_KEY, [])
    if not isinstance(hooks, list):
        hooks = []
    hooks.append({
        "ts": time.time(),
        "reason": str(reason or "fallback"),
        "detail": str(detail or "")[:300],
    })
    _save_json(_HOOKS_KEY, hooks[-500:])


def _append_round(record: dict[str, Any]) -> None:
    rounds = _load_json(_ROUNDS_KEY, [])
    if not isinstance(rounds, list):
        rounds = []
    rounds.append(record)
    _save_json(_ROUNDS_KEY, rounds[-1000:])


def list_rounds(limit: int = 20) -> list[dict[str, Any]]:
    rows = _load_json(_ROUNDS_KEY, [])
    if not isinstance(rows, list):
        return []
    safe_limit = max(1, min(int(limit or 20), 1000))
    return list(reversed(rows[-safe_limit:]))


def get_federation_status() -> dict[str, Any]:
    rounds = _load_json(_ROUNDS_KEY, [])
    hooks = _load_json(_HOOKS_KEY, [])
    rounds = rounds if isinstance(rounds, list) else []
    hooks = hooks if isinstance(hooks, list) else []
    latest_round = rounds[-1] if rounds else None
    return {
        "enabled": is_enabled(ENABLE_FEDERATED_LLM, default=False),
        "total_rounds": len(rounds),
        "latest_round": latest_round,
        "fallback_hooks": hooks[-20:],
        "fallback_hook_summary": get_fallback_hook_summary(limit=200),
        "federated_inference_url": os.getenv("FEDERATED_INFERENCE_URL", "").strip(),
    }


def list_fallback_hooks(limit: int = 100, since_ts: float = 0.0) -> list[dict[str, Any]]:
    hooks = _load_json(_HOOKS_KEY, [])
    if not isinstance(hooks, list):
        hooks = []
    filtered = hooks
    if since_ts > 0:
        filtered = [h for h in hooks if float(h.get("ts") or 0.0) >= since_ts]
    safe_limit = max(1, min(int(limit or 100), 2000))
    return list(reversed(filtered[-safe_limit:]))


def get_fallback_hook_summary(limit: int = 200, since_ts: float = 0.0) -> dict[str, Any]:
    hooks = list_fallback_hooks(limit=limit, since_ts=since_ts)
    reason_counts: dict[str, int] = {}
    for hook in hooks:
        reason = str(hook.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    latest = hooks[0] if hooks else None
    return {
        "count": len(hooks),
        "reason_counts": reason_counts,
        "latest": latest,
        "window_size": max(1, min(int(limit or 200), 2000)),
        "filters": {
            "since_ts": since_ts if since_ts > 0 else None,
        },
    }


def compute_and_submit_update(samples: list[Any], global_round: int) -> FederatedRoundResult:
    enabled = is_enabled(ENABLE_FEDERATED_LLM, default=False)
    if not enabled:
        _append_fallback_hook("disabled", "ENABLE_FEDERATED_LLM is off")
        return FederatedRoundResult(
            status="disabled",
            global_round=int(global_round),
            samples_seen=0,
            submitted=False,
            message="Federated LLM is disabled by feature flag.",
        )

    started = time.time()
    sample_count = len(samples) if isinstance(samples, list) else 0
    if sample_count <= 0:
        return FederatedRoundResult(
            status="failed",
            global_round=int(global_round),
            samples_seen=0,
            submitted=False,
            message="samples must be a non-empty list",
        )

    latency_ms = int((time.time() - started) * 1000)
    payload = {
        "ts": time.time(),
        "global_round": int(global_round),
        "samples_seen": int(sample_count),
        "status": "submitted",
        "latency_ms": latency_ms,
    }
    _append_round(payload)
    return FederatedRoundResult(
        status="submitted",
        global_round=int(global_round),
        samples_seen=int(sample_count),
        submitted=True,
        message="federated update accepted",
        latency_ms=latency_ms,
    )


def try_federated_inference(messages: list[dict], task: str, routing_hints: dict[str, Any] | None = None) -> dict[str, Any]:
    if not is_enabled(ENABLE_FEDERATED_LLM, default=False):
        return {"ok": False, "reason": "disabled"}

    endpoint = os.getenv("FEDERATED_INFERENCE_URL", "").strip()
    if not endpoint:
        _append_fallback_hook("missing_endpoint", "FEDERATED_INFERENCE_URL not configured")
        return {"ok": False, "reason": "missing_endpoint"}

    started = time.time()
    body = {
        "messages": messages,
        "task": task,
        "routing_hints": routing_hints or {},
    }
    req = _urlrequest.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        timeout = max(1.0, float(os.getenv("FEDERATED_INFERENCE_TIMEOUT_S", "4.0") or 4.0))
        with _urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("invalid federated response shape")
        if "action" not in parsed:
            parsed = {
                "action": "respond",
                "content": str(parsed.get("content") or parsed.get("response") or ""),
                "confidence": float(parsed.get("confidence") or 0.85),
            }
        return {
            "ok": True,
            "provider": "federated",
            "latency_ms": int((time.time() - started) * 1000),
            "response": parsed,
        }
    except Exception as exc:
        _append_fallback_hook("request_failed", str(exc))
        return {
            "ok": False,
            "reason": "request_failed",
            "detail": str(exc),
            "latency_ms": int((time.time() - started) * 1000),
        }
