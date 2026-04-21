"""
src/cost_anomaly.py — Cost anomaly detection and alerting

Detects abnormal spending patterns using statistical methods:
  - Z-score: flags daily/hourly spend more than N std deviations above rolling mean
  - IQR: flags values outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
  - Simple threshold: hard cap in USD per day/hour/request

On detection, fires an alert via src.alerting and persists the anomaly event.

Environment variables:
    COST_ANOMALY_ZSCORE_THRESHOLD  — z-score to flag (default: 3.0)
    COST_ANOMALY_WINDOW_DAYS       — rolling window for baseline (default: 30)
    COST_ANOMALY_MIN_DATAPOINTS    — min datapoints before z-score fires (default: 7)
    COST_ANOMALY_HARD_CAP_USD_DAY  — hard daily cap per team/workspace (default: 0 = disabled)
    COST_ANOMALY_CHECK_INTERVAL_S  — seconds between anomaly checks (default: 3600)
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("nexus.cost_anomaly")

_ZSCORE_THRESHOLD = float(os.getenv("COST_ANOMALY_ZSCORE_THRESHOLD", "3.0"))
_WINDOW_DAYS = int(os.getenv("COST_ANOMALY_WINDOW_DAYS", "30"))
_MIN_DATAPOINTS = int(os.getenv("COST_ANOMALY_MIN_DATAPOINTS", "7"))
_HARD_CAP = float(os.getenv("COST_ANOMALY_HARD_CAP_USD_DAY", "0"))
_CHECK_INTERVAL = int(os.getenv("COST_ANOMALY_CHECK_INTERVAL_S", "3600"))

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ── Statistics helpers ────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _zscore(value: float, values: list[float]) -> float:
    if len(values) < _MIN_DATAPOINTS:
        return 0.0
    mu = _mean(values)
    sigma = _std(values, mu)
    if sigma == 0:
        return 0.0
    return (value - mu) / sigma


def _iqr_bounds(values: list[float]) -> tuple[float, float]:
    if len(values) < 4:
        return -float("inf"), float("inf")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1 = sorted_vals[n // 4]
    q3 = sorted_vals[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_daily_spend_history(team: str | None = None) -> dict[str, list[float]]:
    """Load daily spend history from DB for all teams or a specific team.

    Returns {team_name: [spend_day-N, ..., spend_day-1, spend_today]}.
    """
    history: dict[str, list[float]] = {}
    try:
        from src.db import load_pref  # type: ignore
        spending_data = load_pref("slo:team_spending") or {}
        if isinstance(spending_data, dict):
            for team_name, data in spending_data.items():
                if team and team_name != team:
                    continue
                if isinstance(data, dict):
                    daily = data.get("daily_history", [])
                    if isinstance(daily, list):
                        history[team_name] = [float(v) for v in daily[-_WINDOW_DAYS:]]
    except Exception as exc:
        logger.debug("load_daily_spend_history: %s", exc)
    return history


def _get_today_spend(team: str) -> float:
    try:
        from src.db import load_pref  # type: ignore
        spending_data = load_pref("slo:team_spending") or {}
        if isinstance(spending_data, dict) and team in spending_data:
            return float(spending_data[team].get("daily_total", 0.0))
    except Exception:
        pass
    return 0.0


# ── Anomaly detection ─────────────────────────────────────────────────────────

def check_team_anomaly(team: str) -> dict | None:
    """Check if today's spend for *team* is anomalous.

    Returns anomaly dict if detected, None otherwise.
    """
    history = _load_daily_spend_history(team)
    historical = history.get(team, [])
    today = _get_today_spend(team)

    anomaly = None

    # Hard cap check
    if _HARD_CAP > 0 and today > _HARD_CAP:
        anomaly = {
            "type": "hard_cap",
            "team": team,
            "today_spend": today,
            "threshold": _HARD_CAP,
            "z_score": None,
            "severity": "critical",
        }

    # Z-score check
    if anomaly is None and len(historical) >= _MIN_DATAPOINTS:
        z = _zscore(today, historical)
        if abs(z) >= _ZSCORE_THRESHOLD:
            mu = _mean(historical)
            sigma = _std(historical, mu)
            anomaly = {
                "type": "zscore",
                "team": team,
                "today_spend": today,
                "historical_mean": round(mu, 4),
                "historical_std": round(sigma, 4),
                "z_score": round(z, 2),
                "threshold": _ZSCORE_THRESHOLD,
                "severity": "critical" if z > _ZSCORE_THRESHOLD * 1.5 else "error",
            }

    # IQR check
    if anomaly is None and len(historical) >= 4:
        lo, hi = _iqr_bounds(historical)
        if today > hi:
            anomaly = {
                "type": "iqr",
                "team": team,
                "today_spend": today,
                "iqr_upper": round(hi, 4),
                "severity": "warning",
            }

    if anomaly:
        anomaly["timestamp"] = datetime.now(timezone.utc).isoformat()
        _record_anomaly(anomaly)
        _fire_anomaly_alert(anomaly)

    return anomaly


def check_all_teams() -> list[dict]:
    """Run anomaly check across all teams. Returns list of detected anomalies."""
    anomalies = []
    history = _load_daily_spend_history()
    for team in history:
        result = check_team_anomaly(team)
        if result:
            anomalies.append(result)
    return anomalies


# ── Persistence ───────────────────────────────────────────────────────────────

def _record_anomaly(anomaly: dict) -> None:
    try:
        from src.db import load_pref, save_pref  # type: ignore
        events = load_pref("cost_anomaly:events") or []
        events.append(anomaly)
        save_pref("cost_anomaly:events", events[-1000:])
    except Exception:
        pass


def get_anomaly_history(team: str | None = None, limit: int = 50) -> list[dict]:
    try:
        from src.db import load_pref  # type: ignore
        events = load_pref("cost_anomaly:events") or []
        if team:
            events = [e for e in events if e.get("team") == team]
        return list(reversed(events[-limit:]))
    except Exception:
        return []


# ── Alert integration ─────────────────────────────────────────────────────────

def _fire_anomaly_alert(anomaly: dict) -> None:
    try:
        from src.alerting import Alert, send_alert  # type: ignore
        team = anomaly["team"]
        spend = anomaly["today_spend"]
        severity = anomaly.get("severity", "error")
        atype = anomaly.get("type", "unknown")
        title = f"Cost anomaly [{atype}]: team '{team}'"
        summary = f"Today's spend ${spend:.2f}"
        if atype == "zscore":
            summary += f" (z={anomaly.get('z_score', 0):.1f}σ, mean=${anomaly.get('historical_mean', 0):.2f})"
        elif atype == "hard_cap":
            summary += f" exceeds cap ${anomaly.get('threshold', 0):.2f}"
        elif atype == "iqr":
            summary += f" exceeds IQR upper bound ${anomaly.get('iqr_upper', 0):.2f}"
        send_alert(Alert(
            title=title, severity=severity, summary=summary,
            component="cost_anomaly", details=anomaly,
        ))
    except Exception as exc:
        logger.debug("_fire_anomaly_alert: %s", exc)


# ── Background worker ─────────────────────────────────────────────────────────

def _worker_loop() -> None:
    logger.info("Cost anomaly worker started (check every %ds)", _CHECK_INTERVAL)
    while not _stop_event.is_set():
        try:
            anomalies = check_all_teams()
            if anomalies:
                logger.warning("Cost anomalies detected: %d", len(anomalies))
        except Exception as exc:
            logger.error("Cost anomaly check failed: %s", exc)
        _stop_event.wait(_CHECK_INTERVAL)


def start_cost_anomaly_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="cost-anomaly-worker")
    _worker_thread.start()


def stop_cost_anomaly_worker() -> None:
    _stop_event.set()
