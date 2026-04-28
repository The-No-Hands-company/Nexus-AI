"""Drift detection and quality monitoring for Nexus AI.

Three detection planes:
1. Output quality drift — rolling baseline vs recent benchmark scores
2. Architecture drift — compares live code symbols against ARCHITECTURE.md contracts
3. Safety drift — monitors safety trigger rates and flag distribution
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARCHITECTURE_DOC = os.getenv(
    "ARCHITECTURE_MD_PATH",
    str(Path(__file__).parent.parent / "docs" / "ARCHITECTURE.md"),
)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class DriftEvent:
    event_id: str
    plane: str           # quality | architecture | safety
    severity: str        # info | warning | critical
    message: str
    detail: dict
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "event_id":    self.event_id,
            "plane":       self.plane,
            "severity":    self.severity,
            "message":     self.message,
            "detail":      self.detail,
            "detected_at": self.detected_at,
        }


_events: list[DriftEvent]          = []
_quality_baseline: dict[str, float] = {}   # metric_name -> baseline value
_safety_baseline:  dict[str, float] = {}
import uuid as _uuid


def _new_id() -> str:
    return str(_uuid.uuid4())[:12]


def _record(plane: str, severity: str, message: str, detail: dict) -> DriftEvent:
    evt = DriftEvent(event_id=_new_id(), plane=plane, severity=severity,
                     message=message, detail=detail)
    _events.append(evt)
    if len(_events) > 500:
        _events.pop(0)
    logger.info("Drift[%s/%s]: %s", plane, severity, message)
    return evt


# ── Quality drift ─────────────────────────────────────────────────────────────

def set_quality_baseline(metrics: dict[str, float]) -> None:
    """Record current benchmark scores as the quality baseline."""
    global _quality_baseline
    _quality_baseline = dict(metrics)
    logger.info("Quality baseline set: %s", _quality_baseline)


def check_quality_drift(current_metrics: dict[str, float],
                        threshold_pct: float = 10.0) -> list[DriftEvent]:
    """Compare current scores to baseline and emit events for regressions."""
    events = []
    for metric, baseline_val in _quality_baseline.items():
        current_val = current_metrics.get(metric)
        if current_val is None:
            continue
        if baseline_val == 0:
            continue
        delta_pct = ((current_val - baseline_val) / abs(baseline_val)) * 100.0
        if delta_pct < -threshold_pct:
            severity = "critical" if delta_pct < -(threshold_pct * 2) else "warning"
            events.append(_record(
                "quality", severity,
                f"Quality regression on '{metric}': {baseline_val:.3f} → {current_val:.3f} ({delta_pct:+.1f}%)",
                {"metric": metric, "baseline": baseline_val, "current": current_val, "delta_pct": delta_pct},
            ))
    return events


# ── Architecture drift ────────────────────────────────────────────────────────

_ARCH_CONTRACT_PATTERNS = [
    # module name → expected to exist in src/
    (r"src/agent\.py",           "agent.py"),
    (r"src/safety_pipeline\.py", "safety_pipeline.py"),
    (r"src/tools_builtin\.py",   "tools_builtin.py"),
    (r"src/personas\.py",        "personas.py"),
    (r"src/memory\.py",          "memory.py"),
    (r"src/autonomy\.py",        "autonomy.py"),
    (r"src/model_router\.py",    "model_router.py"),
]


def check_architecture_drift() -> list[DriftEvent]:
    """Compare live source files against contracts declared in ARCHITECTURE.md."""
    src_dir = Path(__file__).parent
    events  = []

    # 1. Check that contractually required modules exist
    for _pattern, filename in _ARCH_CONTRACT_PATTERNS:
        if not (src_dir / filename).exists():
            events.append(_record(
                "architecture", "critical",
                f"Required module missing: src/{filename}",
                {"filename": filename, "contract": "ARCHITECTURE.md"},
            ))

    # 2. Parse ARCHITECTURE.md for endpoint contracts and verify they exist in routes.py
    arch_path   = Path(ARCHITECTURE_DOC)
    routes_path = src_dir / "api" / "routes.py"

    if arch_path.exists() and routes_path.exists():
        arch_text   = arch_path.read_text(errors="ignore")
        routes_text = routes_path.read_text(errors="ignore")

        # Find all backtick-enclosed route patterns like `POST /agent`
        route_refs = re.findall(r"`(?:GET|POST|PUT|DELETE|PATCH)\s+(/[^`\s]+)`", arch_text)
        for route in set(route_refs):
            path_only = route.split(" ")[-1].rstrip("/")
            # Strip path params: /foo/{bar} → /foo/
            normalized = re.sub(r"\{[^}]+\}", "{id}", path_only)
            if normalized not in routes_text:
                # Soft warning — docs may reference future routes
                events.append(_record(
                    "architecture", "info",
                    f"Route referenced in ARCHITECTURE.md not found in routes.py: {route}",
                    {"route": route, "normalized": normalized},
                ))

    return events


# ── Safety drift ──────────────────────────────────────────────────────────────

def update_safety_baseline(metrics: dict[str, float]) -> None:
    global _safety_baseline
    _safety_baseline = dict(metrics)


def check_safety_drift(current_metrics: dict[str, float],
                       threshold_pct: float = 20.0) -> list[DriftEvent]:
    """Detect unusual spikes or drops in safety trigger rates."""
    events = []
    for metric, baseline_val in _safety_baseline.items():
        current_val = current_metrics.get(metric)
        if current_val is None or baseline_val == 0:
            continue
        delta_pct = ((current_val - baseline_val) / abs(baseline_val)) * 100.0
        if abs(delta_pct) > threshold_pct:
            severity = "critical" if abs(delta_pct) > threshold_pct * 2 else "warning"
            direction = "spike" if delta_pct > 0 else "drop"
            events.append(_record(
                "safety", severity,
                f"Safety metric '{metric}' {direction}: {baseline_val:.3f} → {current_val:.3f} ({delta_pct:+.1f}%)",
                {"metric": metric, "baseline": baseline_val, "current": current_val,
                 "delta_pct": delta_pct, "direction": direction},
            ))
    return events


# ── Weekly regression schedule ────────────────────────────────────────────────

_last_weekly_run: float = 0.0
_weekly_results: list[dict] = []


def run_weekly_quality_benchmark(benchmark_fn: Any | None = None) -> dict:
    """Run the quality regression benchmark and compare against baseline.

    Args:
        benchmark_fn: optional callable() → dict[metric_name, float]
    """
    global _last_weekly_run
    _last_weekly_run = time.time()

    if benchmark_fn:
        try:
            current_metrics = benchmark_fn()
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "ran_at": datetime.now(timezone.utc).isoformat()}
            _weekly_results.append(result)
            return result
    else:
        # Synthetic placeholder — in production wire to eval_pipeline
        current_metrics = {
            "code_pass_rate":     0.0,
            "rag_recall":         0.0,
            "safety_block_rate":  0.0,
        }

    drift_events = check_quality_drift(current_metrics)
    ran_at = datetime.now(timezone.utc).isoformat()
    result = {
        "ok":             True,
        "ran_at":         ran_at,
        "current_metrics": current_metrics,
        "baseline":        _quality_baseline,
        "drift_events":    [e.to_dict() for e in drift_events],
        "regressions":     len([e for e in drift_events if e.severity in ("warning", "critical")]),
    }
    _weekly_results.append(result)
    if len(_weekly_results) > 52:  # keep ~1 year
        _weekly_results.pop(0)
    logger.info("Weekly benchmark complete: %d regressions detected", result["regressions"])
    return result


# ── Query ─────────────────────────────────────────────────────────────────────

def list_drift_events(plane: str | None = None, severity: str | None = None,
                      limit: int = 100) -> list[dict]:
    filtered = _events
    if plane and str(plane).lower() not in {"", "all", "*"}:
        filtered = [e for e in filtered if e.plane == plane]
    if severity and str(severity).lower() not in {"", "all", "*"}:
        filtered = [e for e in filtered if e.severity == severity]
    return [e.to_dict() for e in reversed(filtered[-limit:])]


def get_drift_summary() -> dict:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in _events:
        counts[e.plane][e.severity] += 1
    return {
        "total_events":      len(_events),
        "by_plane":          {p: dict(s) for p, s in counts.items()},
        "quality_baseline":  _quality_baseline,
        "safety_baseline":   _safety_baseline,
        "last_weekly_run":   datetime.fromtimestamp(_last_weekly_run, tz=timezone.utc).isoformat()
                             if _last_weekly_run else None,
        "weekly_results_count": len(_weekly_results),
    }


def get_weekly_results(limit: int = 12) -> list[dict]:
    return list(reversed(_weekly_results[-limit:]))


# ── Capability-cluster regression ────────────────────────────────────────────

_CLUSTER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coding": ("code", "coding", "python", "refactor", "lint"),
    "reasoning": ("reason", "logic", "math", "analysis", "consensus"),
    "retrieval": ("rag", "retrieve", "search", "embedding", "vector"),
    "safety": ("safety", "guardrail", "policy", "compliance", "redteam"),
    "multimodal": ("vision", "audio", "video", "image", "ocr", "speech"),
}


def capability_cluster_for_task(task_type: str) -> str:
    """Map a benchmark task/probe label to a stable capability cluster."""
    label = str(task_type or "").strip().lower()
    if not label:
        return "general"
    for cluster, keywords in _CLUSTER_KEYWORDS.items():
        if any(k in label for k in keywords):
            return cluster
    return "general"


def detect_capability_cluster_regressions(
    benchmark_rows: list[dict],
    min_samples: int = 3,
    degradation_threshold_pct: float = 15.0,
) -> list[dict]:
    """Detect regressions by capability cluster using recent-vs-prior windows.

    Expects rows in newest-first order (as returned by db.load_benchmark_results).
    Uses latency increase and response-length collapse as simple regression signals.
    """
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for row in benchmark_rows:
        task_label = str(row.get("task_type") or row.get("probe") or "")
        cluster = capability_cluster_for_task(task_label)
        by_cluster[cluster].append(row)

    regressions: list[dict] = []
    for cluster, rows in by_cluster.items():
        if len(rows) < max(2 * min_samples, 4):
            continue

        half = max(min_samples, len(rows) // 2)
        recent_rows = rows[:half]
        prior_rows = rows[half:half * 2]
        if len(prior_rows) < min_samples:
            continue

        def _avg(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        recent_latency = _avg([float(r.get("latency_ms") or 0.0) for r in recent_rows if float(r.get("latency_ms") or 0.0) > 0])
        prior_latency = _avg([float(r.get("latency_ms") or 0.0) for r in prior_rows if float(r.get("latency_ms") or 0.0) > 0])
        recent_len = _avg([float(r.get("response_len") or 0.0) for r in recent_rows])
        prior_len = _avg([float(r.get("response_len") or 0.0) for r in prior_rows])

        latency_delta_pct = 0.0
        if prior_latency > 0:
            latency_delta_pct = ((recent_latency - prior_latency) / prior_latency) * 100.0

        response_delta_pct = 0.0
        if prior_len > 0:
            response_delta_pct = ((recent_len - prior_len) / prior_len) * 100.0

        degraded_latency = prior_latency > 0 and latency_delta_pct > degradation_threshold_pct
        degraded_response = prior_len > 0 and response_delta_pct < -degradation_threshold_pct
        if not (degraded_latency or degraded_response):
            continue

        severity = "critical" if (latency_delta_pct > degradation_threshold_pct * 2 or response_delta_pct < -(degradation_threshold_pct * 2)) else "warning"
        detail = {
            "cluster": cluster,
            "sample_count": len(rows),
            "recent_latency_ms": round(recent_latency, 3),
            "prior_latency_ms": round(prior_latency, 3),
            "latency_delta_pct": round(latency_delta_pct, 3),
            "recent_response_len": round(recent_len, 3),
            "prior_response_len": round(prior_len, 3),
            "response_delta_pct": round(response_delta_pct, 3),
        }
        regressions.append(
            {
                "cluster": cluster,
                "severity": severity,
                "detail": detail,
                "event": _record(
                    "quality",
                    severity,
                    f"Capability-cluster regression detected: {cluster}",
                    detail,
                ).to_dict(),
            }
        )

    return regressions
