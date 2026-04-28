"""
src/retention.py — Automated data retention and purge policy engine

Implements GDPR Article 5(1)(e) "storage limitation" principle:
data is kept no longer than necessary for its purpose.

Supported retention policies:
  - chat_history:     default 90 days
  - usage_records:    default 365 days
  - audit_logs:       default 2555 days (7 years, compliance minimum)
  - safety_events:    default 365 days
  - agent_state:      default 30 days
  - attribution_log:  default 180 days

Policies are configurable via DB prefs or environment variables.
The purge job runs as a background thread (start_retention_worker()).
Schedule: daily at configurable hour (RETENTION_PURGE_HOUR, default 3 AM UTC).

Environment variables:
    RETENTION_CHAT_DAYS         — chat history retention (default: 90)
    RETENTION_USAGE_DAYS        — usage records retention (default: 365)
    RETENTION_AUDIT_DAYS        — audit log retention (default: 2555)
    RETENTION_SAFETY_DAYS       — safety events retention (default: 365)
    RETENTION_AGENT_STATE_DAYS  — agent state retention (default: 30)
    RETENTION_PURGE_HOUR        — UTC hour to run purge job (default: 3)
    RETENTION_DRY_RUN           — "1" to log what would be deleted without deleting
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("nexus.retention")

_POLICIES: dict[str, int] = {
    "chat_history":    int(os.getenv("RETENTION_CHAT_DAYS", "90")),
    "usage_records":   int(os.getenv("RETENTION_USAGE_DAYS", "365")),
    "audit_logs":      int(os.getenv("RETENTION_AUDIT_DAYS", "2555")),
    "safety_events":   int(os.getenv("RETENTION_SAFETY_DAYS", "365")),
    "agent_state":     int(os.getenv("RETENTION_AGENT_STATE_DAYS", "30")),
    "attribution_log": int(os.getenv("RETENTION_ATTRIBUTION_DAYS", "180")),
}
_PURGE_HOUR = int(os.getenv("RETENTION_PURGE_HOUR", "3"))
_DRY_RUN = os.getenv("RETENTION_DRY_RUN", "0").strip() == "1"

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ── Policy management ─────────────────────────────────────────────────────────

def set_policy(data_type: str, retention_days: int) -> None:
    """Set retention policy for a data type. Persists to DB."""
    _POLICIES[data_type] = retention_days
    try:
        from src.db import save_pref  # type: ignore
        all_policies = dict(_POLICIES)
        all_policies[data_type] = retention_days
        save_pref("retention:policies", all_policies)
    except Exception:
        pass


def get_policy(data_type: str) -> int | None:
    return _POLICIES.get(data_type)


def list_policies() -> dict[str, int]:
    return dict(_POLICIES)


def _load_policies_from_db() -> None:
    try:
        from src.db import load_pref  # type: ignore
        saved = load_pref("retention:policies")
        if isinstance(saved, dict):
            _POLICIES.update(saved)
    except Exception:
        pass


# ── Purge implementations ─────────────────────────────────────────────────────

def _cutoff(days: int) -> str:
    """ISO-8601 cutoff timestamp for records older than *days* days."""
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff_dt.isoformat()


def _purge_chat_history(days: int) -> int:
    """Delete chat history records older than *days* days. Returns deleted count."""
    cutoff = _cutoff(days)
    try:
        from src.db import _backend  # type: ignore
        if hasattr(_backend, "_get_conn"):
            conn = _backend._get_conn()
            if _DRY_RUN:
                count = conn.execute(
                    "SELECT COUNT(*) FROM chats WHERE created_at < ?", (cutoff,)
                ).fetchone()[0]
                logger.info("DRY RUN: would purge %d chat records older than %s", count, cutoff)
                return count
            cursor = conn.execute("DELETE FROM chats WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount
    except Exception as exc:
        logger.error("purge_chat_history failed: %s", exc)
    return 0


def _purge_usage_records(days: int) -> int:
    cutoff = _cutoff(days)
    try:
        from src.db import _backend  # type: ignore
        if hasattr(_backend, "_get_conn"):
            conn = _backend._get_conn()
            if _DRY_RUN:
                count = conn.execute(
                    "SELECT COUNT(*) FROM usage WHERE created_at < ?", (cutoff,)
                ).fetchone()[0]
                logger.info("DRY RUN: would purge %d usage records older than %s", count, cutoff)
                return count
            cursor = conn.execute("DELETE FROM usage WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount
    except Exception as exc:
        logger.error("purge_usage_records failed: %s", exc)
    return 0


def _purge_safety_events(days: int) -> int:
    cutoff = _cutoff(days)
    try:
        from src.db import _backend  # type: ignore
        if hasattr(_backend, "_get_conn"):
            conn = _backend._get_conn()
            if _DRY_RUN:
                count = conn.execute(
                    "SELECT COUNT(*) FROM safety_audit_events WHERE created_at < ?", (cutoff,)
                ).fetchone()[0]
                logger.info("DRY RUN: would purge %d safety events older than %s", count, cutoff)
                return count
            cursor = conn.execute(
                "DELETE FROM safety_audit_events WHERE created_at < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
    except Exception as exc:
        logger.error("purge_safety_events failed: %s", exc)
    return 0


def _purge_pref_namespace(namespace: str, days: int) -> int:
    """Purge JSON-blob pref entries in a namespace where created_at < cutoff."""
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    try:
        from src.db import _backend, load_pref, save_pref  # type: ignore
        data = load_pref(namespace)
        if not isinstance(data, list):
            return 0
        before = len(data)
        after_list = []
        for entry in data:
            ts_str = entry.get("created_at") or entry.get("timestamp") or ""
            try:
                entry_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            except Exception:
                entry_ts = 0.0
            if entry_ts >= cutoff_ts:
                after_list.append(entry)
        if not _DRY_RUN:
            save_pref(namespace, after_list)
        pruned = before - len(after_list)
        if pruned:
            logger.info("%spurged %d entries from %s", "DRY RUN: would purge " if _DRY_RUN else "", pruned, namespace)
        return pruned
    except Exception as exc:
        logger.error("purge_pref_namespace(%s) failed: %s", namespace, exc)
        return 0


# ── Run single purge cycle ────────────────────────────────────────────────────

def run_purge_cycle() -> dict[str, int]:
    """Run a full retention purge cycle. Returns dict of {data_type: deleted_count}."""
    _load_policies_from_db()
    results = {}

    chat_days = _POLICIES.get("chat_history", 90)
    results["chat_history"] = _purge_chat_history(chat_days)

    usage_days = _POLICIES.get("usage_records", 365)
    results["usage_records"] = _purge_usage_records(usage_days)

    safety_days = _POLICIES.get("safety_events", 365)
    results["safety_events"] = _purge_safety_events(safety_days)

    attr_days = _POLICIES.get("attribution_log", 180)
    results["attribution_log"] = _purge_pref_namespace("slo:attribution_log", attr_days)

    budget_alert_days = _POLICIES.get("budget_alerts", 90)
    results["budget_alerts"] = _purge_pref_namespace("slo:budget_alerts", budget_alert_days)

    total = sum(results.values())
    logger.info("Retention purge complete: %d total records purged. Details: %s", total, results)

    # Record purge run in DB
    try:
        from src.db import save_pref  # type: ignore
        from src.db import load_pref
        history = load_pref("retention:purge_history") or []
        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "dry_run": _DRY_RUN,
        })
        save_pref("retention:purge_history", history[-100:])  # keep last 100 runs
    except Exception:
        pass

    return results


# ── Background worker ─────────────────────────────────────────────────────────

def _worker_loop() -> None:
    logger.info("Retention worker started (purge hour: %02d:00 UTC, dry_run=%s)", _PURGE_HOUR, _DRY_RUN)
    while not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        if now.hour == _PURGE_HOUR and now.minute < 5:
            try:
                run_purge_cycle()
            except Exception as exc:
                logger.error("Retention purge cycle failed: %s", exc)
            # Sleep past the 5-minute window to avoid running twice
            _stop_event.wait(360)
        else:
            _stop_event.wait(60)


def start_retention_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="retention-worker")
    _worker_thread.start()


def stop_retention_worker() -> None:
    _stop_event.set()


def get_purge_history(limit: int = 10) -> list[dict]:
    try:
        from src.db import load_pref  # type: ignore
        history = load_pref("retention:purge_history") or []
        return list(reversed(history[-limit:]))
    except Exception:
        return []
