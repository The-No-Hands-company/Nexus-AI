"""
src/alerting.py — Incident alerting integration (PagerDuty, OpsGenie, generic webhook)

Sends alerts to on-call systems when SLO thresholds are breached, error rates spike,
or safety events are triggered. Includes rate limiting to prevent alert storms.

Supported providers (tried in priority order if ALERTING_PROVIDER="auto"):
  1. PagerDuty Events API v2 (PAGERDUTY_INTEGRATION_KEY)
  2. OpsGenie Alerts API (OPSGENIE_API_KEY)
  3. Generic outbound webhook (ALERTING_WEBHOOK_URL)
  4. Structured log (always active as fallback)

Environment variables:
    ALERTING_PROVIDER         — "pagerduty" | "opsgenie" | "webhook" | "auto" | "log"
    PAGERDUTY_INTEGRATION_KEY — PagerDuty Events v2 integration key (routing key)
    OPSGENIE_API_KEY          — OpsGenie REST API key
    ALERTING_WEBHOOK_URL      — Generic webhook URL for alert payloads
    ALERT_RATE_LIMIT_SECONDS  — Minimum seconds between identical alerts (default: 300)
    ALERT_ENVIRONMENT         — Environment label e.g. "production" (default: env var APP_ENV)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.alerting")

_PROVIDER = os.getenv("ALERTING_PROVIDER", "auto").strip().lower()
_PD_KEY = os.getenv("PAGERDUTY_INTEGRATION_KEY", "").strip()
_OG_KEY = os.getenv("OPSGENIE_API_KEY", "").strip()
_WEBHOOK_URL = os.getenv("ALERTING_WEBHOOK_URL", "").strip()
_RATE_LIMIT_S = int(os.getenv("ALERT_RATE_LIMIT_SECONDS", "300"))
_ENVIRONMENT = os.getenv("ALERT_ENVIRONMENT", os.getenv("APP_ENV", "production")).strip()

# ── Rate limiting (in-process deduplication) ──────────────────────────────────

_alert_history: dict[str, float] = {}  # dedup_key -> last_sent_ts
_alert_lock = threading.Lock()


def _dedup_key(title: str, severity: str) -> str:
    return hashlib.md5(f"{title}:{severity}".encode()).hexdigest()[:16]


def _is_rate_limited(dedup_key: str) -> bool:
    with _alert_lock:
        last = _alert_history.get(dedup_key, 0.0)
        if time.time() - last < _RATE_LIMIT_S:
            return True
        _alert_history[dedup_key] = time.time()
        return False


# ── Alert dataclass ───────────────────────────────────────────────────────────

@dataclass
class Alert:
    title: str
    severity: str                           # "critical" | "error" | "warning" | "info"
    summary: str = ""
    source: str = "nexus-ai"
    component: str = ""
    group: str = ""
    details: dict = field(default_factory=dict)
    dedup_key: str = ""

    def __post_init__(self):
        if not self.dedup_key:
            self.dedup_key = _dedup_key(self.title, self.severity)


# ── PagerDuty provider ────────────────────────────────────────────────────────

def _send_pagerduty(alert: Alert) -> bool:
    if not _PD_KEY:
        return False
    severity_map = {"critical": "critical", "error": "error", "warning": "warning", "info": "info"}
    payload = {
        "routing_key": _PD_KEY,
        "event_action": "trigger",
        "dedup_key": alert.dedup_key,
        "payload": {
            "summary": alert.title,
            "severity": severity_map.get(alert.severity, "error"),
            "source": alert.source,
            "component": alert.component or "nexus-ai",
            "group": alert.group or _ENVIRONMENT,
            "custom_details": {
                "summary": alert.summary,
                "environment": _ENVIRONMENT,
                **alert.details,
            },
        },
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://events.pagerduty.com/v2/enqueue",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        logger.info("PagerDuty alert sent: %s (status=%s)", alert.dedup_key, resp.get("status"))
        return True
    except Exception as exc:
        logger.error("PagerDuty send failed: %s", exc)
        return False


# ── OpsGenie provider ─────────────────────────────────────────────────────────

def _send_opsgenie(alert: Alert) -> bool:
    if not _OG_KEY:
        return False
    priority_map = {"critical": "P1", "error": "P2", "warning": "P3", "info": "P5"}
    payload = {
        "message": alert.title,
        "alias": alert.dedup_key,
        "description": alert.summary,
        "priority": priority_map.get(alert.severity, "P2"),
        "source": alert.source,
        "tags": [_ENVIRONMENT, alert.severity],
        "details": {**alert.details, "component": alert.component},
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://api.opsgenie.com/v2/alerts",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"GenieKey {_OG_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        logger.info("OpsGenie alert sent: %s", resp.get("requestId"))
        return True
    except Exception as exc:
        logger.error("OpsGenie send failed: %s", exc)
        return False


# ── Generic webhook provider ──────────────────────────────────────────────────

def _send_webhook(alert: Alert) -> bool:
    if not _WEBHOOK_URL:
        return False
    payload = {
        "title": alert.title,
        "severity": alert.severity,
        "summary": alert.summary,
        "source": alert.source,
        "component": alert.component,
        "environment": _ENVIRONMENT,
        "dedup_key": alert.dedup_key,
        "details": alert.details,
        "timestamp": time.time(),
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            _WEBHOOK_URL, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        logger.info("Webhook alert sent: %s", alert.dedup_key)
        return True
    except Exception as exc:
        logger.error("Webhook alert send failed: %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_alert(alert: Alert, force: bool = False) -> dict:
    """Send an alert to the configured provider.

    Returns {"sent": bool, "provider": str, "rate_limited": bool}.
    Rate-limits identical alerts to one per ALERT_RATE_LIMIT_SECONDS.
    """
    if not force and _is_rate_limited(alert.dedup_key):
        logger.debug("Alert rate-limited: %s", alert.dedup_key)
        return {"sent": False, "provider": "none", "rate_limited": True}

    provider = _PROVIDER
    sent = False
    used_provider = "log"

    if provider in ("pagerduty", "auto") and _PD_KEY:
        sent = _send_pagerduty(alert)
        if sent:
            used_provider = "pagerduty"

    if not sent and provider in ("opsgenie", "auto") and _OG_KEY:
        sent = _send_opsgenie(alert)
        if sent:
            used_provider = "opsgenie"

    if not sent and provider in ("webhook", "auto") and _WEBHOOK_URL:
        sent = _send_webhook(alert)
        if sent:
            used_provider = "webhook"

    # Always log to structured log as fallback
    log_fn = logger.critical if alert.severity == "critical" else logger.warning
    log_fn("ALERT [%s] %s — %s", alert.severity.upper(), alert.title, alert.summary)

    return {"sent": sent, "provider": used_provider, "rate_limited": False}


def alert_slo_breach(
    slo_name: str,
    metric: str,
    current: float,
    threshold: float,
    severity: str = "error",
) -> dict:
    """Convenience helper for SLO threshold breaches."""
    return send_alert(Alert(
        title=f"SLO breach: {slo_name}",
        severity=severity,
        summary=f"{metric} = {current:.3f} (threshold: {threshold:.3f})",
        component="slo",
        details={"slo_name": slo_name, "metric": metric, "current": current, "threshold": threshold},
    ))


def alert_error_rate(service: str, error_rate: float, threshold: float = 0.05) -> dict:
    """Alert when error rate exceeds threshold."""
    return send_alert(Alert(
        title=f"High error rate: {service}",
        severity="critical" if error_rate > threshold * 2 else "error",
        summary=f"Error rate {error_rate:.1%} exceeds threshold {threshold:.1%}",
        component=service,
        details={"error_rate": error_rate, "threshold": threshold},
    ))


def alert_safety_event(event_type: str, username: str, details: dict) -> dict:
    """Alert on critical safety events."""
    return send_alert(Alert(
        title=f"Safety event: {event_type}",
        severity="critical",
        summary=f"Safety event '{event_type}' for user '{username}'",
        component="safety",
        details={"username": username, **details},
    ))


def resolve_alert(dedup_key: str) -> bool:
    """Resolve/close an active PagerDuty incident."""
    if not _PD_KEY:
        return False
    payload = {
        "routing_key": _PD_KEY,
        "event_action": "resolve",
        "dedup_key": dedup_key,
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://events.pagerduty.com/v2/enqueue",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception:
        return False
