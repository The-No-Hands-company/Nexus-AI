"""
src/webhooks_delivery.py — Outbound webhook delivery with retry and dead-letter queue

Provides at-least-once delivery guarantees for outbound webhook events:
  - Exponential backoff retry (max 5 attempts by default)
  - Dead-letter queue (DLQ) for permanently failed deliveries
  - HMAC-SHA256 signature on all outbound requests
  - Delivery receipt logging to DB
  - Background delivery worker with configurable concurrency

This replaces the fire-and-forget 10-second POST in the existing webhook route.

Environment variables:
    WEBHOOK_MAX_ATTEMPTS       — max delivery attempts (default: 5)
    WEBHOOK_INITIAL_BACKOFF_S  — initial retry delay in seconds (default: 30)
    WEBHOOK_MAX_BACKOFF_S      — max retry delay cap (default: 3600)
    WEBHOOK_TIMEOUT_S          — per-attempt HTTP timeout (default: 30)
    WEBHOOK_SIGNING_SECRET     — HMAC key for outbound signatures (default: WEBHOOK_SECRET env)
    WEBHOOK_WORKER_CONCURRENCY — parallel delivery threads (default: 4)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nexus.webhooks_delivery")

_MAX_ATTEMPTS = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "5"))
_INITIAL_BACKOFF = float(os.getenv("WEBHOOK_INITIAL_BACKOFF_S", "30"))
_MAX_BACKOFF = float(os.getenv("WEBHOOK_MAX_BACKOFF_S", "3600"))
_TIMEOUT = float(os.getenv("WEBHOOK_TIMEOUT_S", "30"))
_SIGNING_SECRET = os.getenv("WEBHOOK_SIGNING_SECRET", os.getenv("WEBHOOK_SECRET", "")).encode()
_CONCURRENCY = int(os.getenv("WEBHOOK_WORKER_CONCURRENCY", "4"))


# ── Delivery task model ───────────────────────────────────────────────────────

@dataclass
class WebhookDelivery:
    delivery_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    url: str = ""
    event_type: str = ""
    payload: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    attempt: int = 0
    max_attempts: int = _MAX_ATTEMPTS
    next_attempt_at: float = field(default_factory=time.time)
    status: str = "pending"           # pending | delivered | dlq | cancelled
    last_error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    delivered_at: str | None = None


# ── Delivery queue ────────────────────────────────────────────────────────────

_delivery_queue: queue.PriorityQueue = queue.PriorityQueue()
_workers: list[threading.Thread] = []
_worker_stop = threading.Event()


# ── Signature computation ─────────────────────────────────────────────────────

def _compute_signature(payload_bytes: bytes, timestamp: int) -> str:
    """Compute HMAC-SHA256 signature for outbound payload (Stripe-style)."""
    signing_input = f"v0:{timestamp}:".encode() + payload_bytes
    return "v0=" + hmac.new(_SIGNING_SECRET, signing_input, hashlib.sha256).hexdigest()


# ── HTTP delivery ─────────────────────────────────────────────────────────────

def _deliver_once(delivery: WebhookDelivery) -> tuple[bool, str]:
    """Attempt a single HTTP POST delivery. Returns (success, error_message)."""
    payload_bytes = json.dumps(delivery.payload, ensure_ascii=False).encode("utf-8")
    ts = int(time.time())

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Nexus-AI-Webhooks/1.0",
        "X-Nexus-Event": delivery.event_type,
        "X-Nexus-Delivery": delivery.delivery_id,
        "X-Nexus-Timestamp": str(ts),
        **delivery.headers,
    }
    if _SIGNING_SECRET:
        headers["X-Nexus-Signature"] = _compute_signature(payload_bytes, ts)

    req = urllib.request.Request(
        delivery.url, data=payload_bytes, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            status_code = resp.status
            if 200 <= status_code < 300:
                return True, ""
            return False, f"HTTP {status_code}"
    except Exception as exc:
        return False, str(exc)


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter."""
    delay = min(_MAX_BACKOFF, _INITIAL_BACKOFF * (2 ** (attempt - 1)))
    jitter = delay * 0.1 * (0.5 - __import__('random').random())
    return delay + jitter


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_delivery(delivery: WebhookDelivery) -> None:
    try:
        from src.db import load_pref, save_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        deliveries[delivery.delivery_id] = {
            "delivery_id": delivery.delivery_id, "url": delivery.url,
            "event_type": delivery.event_type, "payload": delivery.payload,
            "attempt": delivery.attempt, "max_attempts": delivery.max_attempts,
            "next_attempt_at": delivery.next_attempt_at, "status": delivery.status,
            "last_error": delivery.last_error, "created_at": delivery.created_at,
            "delivered_at": delivery.delivered_at,
        }
        # Keep last 10000 deliveries
        if len(deliveries) > 10000:
            oldest = sorted(deliveries.keys(),
                            key=lambda k: deliveries[k].get("created_at", ""))
            for k in oldest[:1000]:
                deliveries.pop(k, None)
        save_pref("webhook:deliveries", deliveries)
    except Exception:
        pass


def _load_pending_deliveries() -> list[WebhookDelivery]:
    """Load pending and retry-due deliveries from DB on startup."""
    try:
        from src.db import load_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        now = time.time()
        pending = []
        for d in deliveries.values():
            if d.get("status") == "pending" and d.get("next_attempt_at", 0) <= now:
                pending.append(WebhookDelivery(
                    delivery_id=d["delivery_id"], url=d["url"],
                    event_type=d.get("event_type", ""), payload=d.get("payload", {}),
                    attempt=d.get("attempt", 0), max_attempts=d.get("max_attempts", _MAX_ATTEMPTS),
                    next_attempt_at=d.get("next_attempt_at", now),
                    status=d.get("status", "pending"), last_error=d.get("last_error", ""),
                    created_at=d.get("created_at", ""), delivered_at=d.get("delivered_at"),
                ))
        return pending
    except Exception:
        return []


# ── Worker loop ───────────────────────────────────────────────────────────────

def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            # Priority queue: (next_attempt_at, delivery)
            priority, delivery = _delivery_queue.get(timeout=5)
        except queue.Empty:
            continue

        now = time.time()
        if delivery.next_attempt_at > now:
            # Not ready yet — put back
            _delivery_queue.put((delivery.next_attempt_at, delivery))
            time.sleep(min(2.0, delivery.next_attempt_at - now))
            continue

        delivery.attempt += 1
        success, error = _deliver_once(delivery)

        if success:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(timezone.utc).isoformat()
            logger.info("Webhook delivered: %s → %s (attempt %d)",
                        delivery.event_type, delivery.url, delivery.attempt)
        else:
            delivery.last_error = error
            logger.warning("Webhook delivery failed: %s (attempt %d/%d): %s",
                           delivery.delivery_id, delivery.attempt, delivery.max_attempts, error)
            if delivery.attempt >= delivery.max_attempts:
                delivery.status = "dlq"
                logger.error("Webhook moved to DLQ: %s → %s", delivery.event_type, delivery.url)
            else:
                delivery.next_attempt_at = time.time() + _backoff(delivery.attempt)
                _delivery_queue.put((delivery.next_attempt_at, delivery))

        _save_delivery(delivery)
        _delivery_queue.task_done()


# ── Public API ────────────────────────────────────────────────────────────────

def enqueue_webhook(
    url: str,
    event_type: str,
    payload: dict,
    headers: dict | None = None,
    max_attempts: int | None = None,
) -> WebhookDelivery:
    """Enqueue an outbound webhook delivery with guaranteed retry.

    Returns the WebhookDelivery object for tracking.
    """
    delivery = WebhookDelivery(
        url=url, event_type=event_type, payload=payload,
        headers=headers or {},
        max_attempts=max_attempts if max_attempts is not None else _MAX_ATTEMPTS,
    )
    _save_delivery(delivery)
    _delivery_queue.put((delivery.next_attempt_at, delivery))
    return delivery


def start_webhook_worker() -> None:
    """Start the background webhook delivery workers."""
    global _workers
    _worker_stop.clear()
    # Hydrate pending deliveries from DB
    for pending in _load_pending_deliveries():
        _delivery_queue.put((pending.next_attempt_at, pending))

    for i in range(_CONCURRENCY):
        t = threading.Thread(target=_worker_loop, daemon=True, name=f"webhook-worker-{i}")
        t.start()
        _workers.append(t)
    logger.info("Webhook delivery workers started (concurrency=%d)", _CONCURRENCY)


def stop_webhook_worker() -> None:
    _worker_stop.set()


def get_delivery_status(delivery_id: str) -> dict | None:
    try:
        from src.db import load_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        return deliveries.get(delivery_id)
    except Exception:
        return None


def list_dlq() -> list[dict]:
    """Return all deliveries in the dead-letter queue."""
    try:
        from src.db import load_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        return [d for d in deliveries.values() if d.get("status") == "dlq"]
    except Exception:
        return []


def retry_dlq_delivery(delivery_id: str) -> bool:
    """Move a DLQ delivery back to pending for retry."""
    try:
        from src.db import load_pref, save_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        d = deliveries.get(delivery_id)
        if not d or d.get("status") != "dlq":
            return False
        d["status"] = "pending"
        d["attempt"] = 0
        d["next_attempt_at"] = time.time()
        deliveries[delivery_id] = d
        save_pref("webhook:deliveries", deliveries)
        delivery = WebhookDelivery(
            delivery_id=d["delivery_id"], url=d["url"], event_type=d.get("event_type", ""),
            payload=d.get("payload", {}), attempt=0, max_attempts=d.get("max_attempts", _MAX_ATTEMPTS),
            next_attempt_at=time.time(), status="pending",
        )
        _delivery_queue.put((delivery.next_attempt_at, delivery))
        return True
    except Exception:
        return False


def get_webhook_stats() -> dict:
    try:
        from src.db import load_pref  # type: ignore
        deliveries = load_pref("webhook:deliveries") or {}
        statuses = [d.get("status") for d in deliveries.values()]
        return {
            "total": len(statuses),
            "delivered": statuses.count("delivered"),
            "pending": statuses.count("pending"),
            "dlq": statuses.count("dlq"),
            "cancelled": statuses.count("cancelled"),
            "queue_depth": _delivery_queue.qsize(),
        }
    except Exception:
        return {}
