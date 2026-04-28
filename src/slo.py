"""SLO (Service Level Objective) tracking and budget management for Nexus AI.

Tracks:
- p50/p95/p99 latency per endpoint and provider
- Error rates and availability
- Per-team budget allocation, usage, and over-budget alerts
- Hardware-aware routing hints
- Cost attribution and chargeback

All metrics are in-memory with time-bucket aggregation.
For persistent SLO storage, export to Prometheus/Datadog via observability.py.
"""
from __future__ import annotations

import logging
import math
import os
import statistics
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Latency buckets ───────────────────────────────────────────────────────────

# Keep last N latency samples per endpoint
_LATENCY_WINDOW = int(os.getenv("SLO_LATENCY_WINDOW", "1000"))
_latency_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=_LATENCY_WINDOW))
_error_counts:    dict[str, int]   = defaultdict(int)
_request_counts:  dict[str, int]   = defaultdict(int)
_baseline_latency: dict[str, dict[str, float]] = {}  # endpoint -> {p50, p95, p99}


def record_latency(endpoint: str, latency_ms: float, success: bool = True) -> None:
    """Record a single request latency sample."""
    _latency_samples[endpoint].append(latency_ms)
    _request_counts[endpoint] += 1
    if not success:
        _error_counts[endpoint] += 1


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * pct / 100.0
    lo  = int(idx)
    hi  = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[lo]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def get_latency_stats(endpoint: str) -> dict:
    samples = list(_latency_samples[endpoint])
    total   = _request_counts[endpoint]
    errors  = _error_counts[endpoint]
    if not samples:
        return {"endpoint": endpoint, "samples": 0, "p50": 0, "p95": 0, "p99": 0,
                "mean": 0, "error_rate": 0, "availability": 1.0}
    return {
        "endpoint":     endpoint,
        "samples":      len(samples),
        "p50":          round(_percentile(samples, 50), 1),
        "p95":          round(_percentile(samples, 95), 1),
        "p99":          round(_percentile(samples, 99), 1),
        "mean":         round(statistics.mean(samples), 1),
        "min":          round(min(samples), 1),
        "max":          round(max(samples), 1),
        "total_requests": total,
        "error_rate":   round(errors / total, 4) if total else 0,
        "availability": round(1 - errors / total, 4) if total else 1.0,
    }


def get_all_latency_stats() -> list[dict]:
    return [get_latency_stats(ep) for ep in sorted(_latency_samples.keys())]


def set_latency_baseline(endpoint: str, p50: float, p95: float, p99: float) -> None:
    _baseline_latency[endpoint] = {"p50": p50, "p95": p95, "p99": p99}


def detect_latency_hotspots(threshold_ms: float = 2000.0) -> list[dict]:
    """Return endpoints where p95 exceeds the threshold."""
    hotspots = []
    for endpoint in _latency_samples:
        stats   = get_latency_stats(endpoint)
        p95     = stats["p95"]
        baseline = _baseline_latency.get(endpoint, {})
        if p95 > threshold_ms:
            hotspots.append({
                "endpoint":   endpoint,
                "p95_ms":     p95,
                "threshold":  threshold_ms,
                "baseline_p95": baseline.get("p95"),
                "severity":   "critical" if p95 > threshold_ms * 2 else "warning",
            })
    return sorted(hotspots, key=lambda x: x["p95_ms"], reverse=True)


# ── SLO objectives ────────────────────────────────────────────────────────────

@dataclass
class SLODefinition:
    slo_id: str
    name: str
    endpoint: str
    p95_budget_ms: float = 2000.0
    p99_budget_ms: float = 5000.0
    availability_target: float = 0.999
    error_budget_pct: float = 0.1    # % of requests allowed to fail

    def to_dict(self) -> dict:
        return {
            "slo_id":               self.slo_id,
            "name":                 self.name,
            "endpoint":             self.endpoint,
            "p95_budget_ms":        self.p95_budget_ms,
            "p99_budget_ms":        self.p99_budget_ms,
            "availability_target":  self.availability_target,
            "error_budget_pct":     self.error_budget_pct,
        }


_slos: dict[str, SLODefinition] = {
    "agent":   SLODefinition("agent",   "Agent endpoint",    "/agent",          p95_budget_ms=5000),
    "chat":    SLODefinition("chat",    "Chat completions",  "/v1/chat/completions", p95_budget_ms=3000),
    "health":  SLODefinition("health",  "Health check",      "/health/live",    p95_budget_ms=200),
}


def get_slo_status(slo_id: str) -> dict:
    slo   = _slos.get(slo_id)
    if not slo:
        return {"ok": False, "error": "SLO not found"}
    stats = get_latency_stats(slo.endpoint)
    p95   = stats["p95"]
    p99   = stats["p99"]
    avail = stats["availability"]
    p95_ok = p95 <= slo.p95_budget_ms or stats["samples"] == 0
    p99_ok = p99 <= slo.p99_budget_ms or stats["samples"] == 0
    avail_ok = avail >= slo.availability_target or stats["samples"] == 0
    return {
        **slo.to_dict(),
        "current_p95_ms":     p95,
        "current_p99_ms":     p99,
        "current_availability": avail,
        "p95_ok":             p95_ok,
        "p99_ok":             p99_ok,
        "availability_ok":    avail_ok,
        "overall_status":     "green" if (p95_ok and p99_ok and avail_ok) else
                              "red" if not avail_ok else "yellow",
        "error_budget_remaining": max(0.0, slo.availability_target - (1 - avail)),
    }


def get_slo_dashboard() -> dict:
    return {
        "slos":      [get_slo_status(sid) for sid in _slos],
        "hotspots":  detect_latency_hotspots(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Hardware-aware routing ────────────────────────────────────────────────────

def get_hardware_routing_hint() -> dict:
    """Return recommended routing (GPU vs CPU) based on observed latencies."""
    try:
        import psutil  # type: ignore
        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        ram_available_gb = ram.available / (1024 ** 3)
    except ImportError:
        cpu_pct = 0.0
        ram_available_gb = 0.0

    gpu_available = False
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            gpu_available = True
            gpu_util = float(r.stdout.strip().split("\n")[0] or "0")
        else:
            gpu_util = 0.0
    except Exception:
        gpu_util = 0.0

    if gpu_available and gpu_util < 80:
        preferred = "gpu"
        reason    = f"GPU available and utilization is {gpu_util:.0f}%"
    elif cpu_pct < 70 and ram_available_gb > 4:
        preferred = "cpu"
        reason    = f"CPU at {cpu_pct:.0f}%, {ram_available_gb:.1f}GB RAM free"
    else:
        preferred = "cloud_offload"
        reason    = f"Local resources constrained (CPU {cpu_pct:.0f}%, RAM {ram_available_gb:.1f}GB)"

    return {
        "preferred_backend": preferred,
        "reason":            reason,
        "cpu_utilization":   cpu_pct,
        "ram_available_gb":  round(ram_available_gb, 2),
        "gpu_available":     gpu_available,
        "gpu_utilization":   gpu_util if gpu_available else None,
    }


# ── Per-team budget — DB-persisted ───────────────────────────────────────────
# All budget state is stored in the DB via src/db.py db_* helpers so it
# survives container restarts. In-memory dicts are gone.


def set_team_budget(team_id: str, monthly_limit_usd: float,
                    daily_limit_usd: float = 0.0,
                    alert_threshold_pct: float = 80.0) -> dict:
    from .db import db_set_team_budget
    db_set_team_budget(team_id, monthly_limit_usd, daily_limit_usd, alert_threshold_pct)
    return get_team_budget(team_id)


def record_team_spending(team_id: str, cost_usd: float, endpoint: str = "",
                         model: str = "") -> dict:
    from .db import db_add_team_spending, db_get_team_budget, db_add_budget_alert
    spending = db_add_team_spending(team_id, cost_usd)
    budget   = db_get_team_budget(team_id)
    if budget:
        threshold     = budget["alert_threshold_pct"] / 100.0
        monthly_limit = budget.get("monthly_limit_usd", 0)
        if monthly_limit > 0:
            utilization = spending.get("month_usd", 0.0) / monthly_limit
            if utilization >= threshold:
                db_add_budget_alert(team_id, "monthly_budget_threshold", utilization, threshold)
                logger.warning("Budget alert: team %s at %.1f%% of monthly limit", team_id, utilization * 100)
    return {"team_id": team_id, "spending": spending}


def get_team_budget(team_id: str) -> dict:
    from .db import db_get_team_budget, db_get_team_spending
    budget   = db_get_team_budget(team_id) or {}
    spending = db_get_team_spending(team_id)
    if budget:
        monthly_limit = budget.get("monthly_limit_usd", 0)
        month_used    = spending.get("month_usd", 0.0)
        remaining     = max(0.0, monthly_limit - month_used)
        utilization   = month_used / monthly_limit if monthly_limit > 0 else 0.0
    else:
        remaining   = None
        utilization = None
    return {
        **budget,
        "spending":                spending,
        "monthly_remaining_usd":   remaining,
        "monthly_utilization_pct": round((utilization or 0.0) * 100, 1),
    }


def list_team_budgets() -> list[dict]:
    from .db import db_list_team_budgets
    return [get_team_budget(b["team_id"]) for b in db_list_team_budgets()]


def list_budget_alerts(team_id: str | None = None, limit: int = 100) -> list[dict]:
    from .db import db_list_budget_alerts
    return db_list_budget_alerts(team_id=team_id, limit=limit)


# ── Cost attribution / chargeback — DB-persisted ─────────────────────────────


def record_attribution(team_id: str, department: str, user: str,
                        cost_usd: float, tokens: int,
                        model: str = "", endpoint: str = "") -> dict:
    from .db import db_record_attribution
    return db_record_attribution(team_id, department, user, cost_usd, tokens, model, endpoint)


def get_attribution_report(team_id: str | None = None, department: str | None = None,
                            limit: int = 500) -> dict:
    from .db import db_get_attribution_report
    items = db_get_attribution_report(team_id=team_id, department=department, limit=limit)

    total_cost   = sum(r.get("cost_usd", 0.0) for r in items)
    total_tokens = sum(r.get("tokens", 0)   for r in items)

    by_department: dict[str, dict] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0, "requests": 0})
    by_model:      dict[str, dict] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0, "requests": 0})
    by_user:       dict[str, dict] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0, "requests": 0})

    for r in items:
        for agg, key in [(by_department, r.get("department", "")),
                         (by_model, r.get("model", "")),
                         (by_user, r.get("user", ""))]:
            agg[key]["cost_usd"] += r.get("cost_usd", 0.0)
            agg[key]["tokens"]   += r.get("tokens", 0)
            agg[key]["requests"] += 1

    return {
        "total_cost_usd":   round(total_cost, 4),
        "total_tokens":     total_tokens,
        "record_count":     len(items),
        "by_department":    dict(by_department),
        "by_model":         dict(by_model),
        "by_user":          dict(by_user),
        "records":          items,
    }


# ── Reserved Capacity + Spot/Preemptible Controls — DB-persisted ─────────────


def set_reserved_capacity(
    team_id: str,
    reserved_rps: float,
    max_concurrency: int,
    guarantee_tier: str = "standard",
    expires_at: str = "",
) -> dict[str, Any]:
    from .db import _load_json_pref, _save_json_pref
    now = datetime.now(timezone.utc).isoformat()
    caps = _load_json_pref("slo:reserved_capacity", {})
    caps[team_id] = {
        "team_id": team_id,
        "reserved_rps": max(0.0, float(reserved_rps or 0.0)),
        "max_concurrency": max(0, int(max_concurrency or 0)),
        "guarantee_tier": str(guarantee_tier or "standard").strip().lower(),
        "expires_at": str(expires_at or "").strip(),
        "updated_at": now,
    }
    _save_json_pref("slo:reserved_capacity", caps)
    return dict(caps[team_id])


def get_reserved_capacity(team_id: str) -> dict[str, Any] | None:
    from .db import _load_json_pref
    row = _load_json_pref("slo:reserved_capacity", {}).get(team_id)
    return dict(row) if row else None


def list_reserved_capacity() -> list[dict[str, Any]]:
    from .db import _load_json_pref
    return list(_load_json_pref("slo:reserved_capacity", {}).values())


def check_rate_guarantee(
    team_id: str,
    requested_rps: float,
    requested_concurrency: int,
) -> dict[str, Any]:
    cap = get_reserved_capacity(team_id)
    if not cap:
        return {
            "team_id": team_id,
            "ok": False,
            "reason": "no_reserved_capacity",
            "requested_rps": float(requested_rps or 0.0),
            "requested_concurrency": int(requested_concurrency or 0),
        }

    req_rps = max(0.0, float(requested_rps or 0.0))
    req_conc = max(0, int(requested_concurrency or 0))
    allowed_rps = float(cap.get("reserved_rps") or 0.0)
    allowed_conc = int(cap.get("max_concurrency") or 0)
    ok = req_rps <= allowed_rps and req_conc <= allowed_conc
    return {
        "team_id": team_id,
        "ok": ok,
        "requested_rps": req_rps,
        "requested_concurrency": req_conc,
        "allowed_rps": allowed_rps,
        "allowed_concurrency": allowed_conc,
        "guarantee_tier": cap.get("guarantee_tier", "standard"),
        "reason": "within_reserved_capacity" if ok else "reserved_capacity_exceeded",
    }


def set_spot_policy(
    team_id: str,
    enabled: bool,
    max_discount_pct: float,
    fallback_on_preempt: bool = True,
    max_preemptions_per_hour: int = 2,
) -> dict[str, Any]:
    from .db import _load_json_pref, _save_json_pref
    now = datetime.now(timezone.utc).isoformat()
    policies = _load_json_pref("slo:spot_policies", {})
    policies[team_id] = {
        "team_id": team_id,
        "enabled": bool(enabled),
        "max_discount_pct": max(0.0, min(95.0, float(max_discount_pct or 0.0))),
        "fallback_on_preempt": bool(fallback_on_preempt),
        "max_preemptions_per_hour": max(0, int(max_preemptions_per_hour or 0)),
        "updated_at": now,
    }
    _save_json_pref("slo:spot_policies", policies)
    return dict(policies[team_id])


def get_spot_policy(team_id: str) -> dict[str, Any] | None:
    from .db import _load_json_pref
    row = _load_json_pref("slo:spot_policies", {}).get(team_id)
    return dict(row) if row else None


def record_spot_event(
    team_id: str,
    event_type: str = "preempted",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .db import _load_json_pref, _save_json_pref
    policy = get_spot_policy(team_id)
    if not policy:
        return {"ok": False, "error": "spot_policy_not_found", "team_id": team_id}

    entry = {
        "id": str(uuid.uuid4())[:8],
        "ts": datetime.now(timezone.utc).isoformat(),
        "team_id": team_id,
        "event_type": str(event_type or "preempted").strip().lower(),
        "details": details or {},
        "fallback_on_preempt": bool(policy.get("fallback_on_preempt", True)),
    }
    events = _load_json_pref("slo:spot_events", [])
    events.append(entry)
    _save_json_pref("slo:spot_events", events[-10000:])
    return {"ok": True, "event": entry}
