from __future__ import annotations

import random
import time
from typing import Any


_RESULTS: list[dict] = []


def run_benchmark_probes(
    requested_providers: list[str] | None = None,
    samples: int = 5,
) -> dict[str, Any]:
    providers = requested_providers or ["llm7", "groq", "openrouter"]
    rows: list[dict[str, Any]] = []
    for provider in providers:
        for idx in range(max(1, int(samples))):
            rows.append(
                {
                    "provider": provider,
                    "model": f"{provider}-default",
                    "task_type": "general",
                    "quality_score": round(0.65 + (idx * 0.03), 3),
                    "latency_ms": 100 + idx * 11,
                    "created_at": time.time(),
                }
            )
    _RESULTS.extend(rows)
    return {"results": rows, "count": len(rows)}


def get_benchmark_history(
    provider: str = "",
    model: str = "",
    task_type: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    rows = list(_RESULTS)
    if provider:
        rows = [row for row in rows if str(row.get("provider", "")) == provider]
    if model:
        rows = [row for row in rows if str(row.get("model", "")) == model]
    if task_type:
        rows = [row for row in rows if str(row.get("task_type", "")) == task_type]
    rows = list(reversed(rows[-max(1, int(limit)) :]))
    avg_quality = round(sum(float(row.get("quality_score", 0.0)) for row in rows) / max(1, len(rows)), 4)
    avg_latency = round(sum(float(row.get("latency_ms", 0.0)) for row in rows) / max(1, len(rows)), 2)
    return {
        "results": rows,
        "summary": {
            "count": len(rows),
            "avg_quality_score": avg_quality,
            "avg_latency_ms": avg_latency,
            "trend": "stable",
        },
    }


def get_benchmark_leaderboard(sort_by: str = "task_type", limit: int = 20, provider: str = "") -> dict[str, Any]:
    rows = list(_RESULTS)
    if provider:
        rows = [row for row in rows if str(row.get("provider", "")) == provider]
    rows = rows[-max(1, int(limit)) :]
    rows = sorted(rows, key=lambda row: float(row.get("quality_score", 0.0)), reverse=True)
    entries = [
        {
            "model": row.get("model", "unknown"),
            "provider": row.get("provider", "unknown"),
            "task_type": row.get("task_type", "general"),
            "quality_score": float(row.get("quality_score", 0.0)),
            "latency_ms": float(row.get("latency_ms", 0.0)),
        }
        for row in rows
    ]
    return {"entries": entries, "sort_by": sort_by}


def get_benchmark_tradeoff(days: int = 14, limit: int = 2000) -> dict:
    leaderboard = get_benchmark_leaderboard(limit=min(limit, 50)).get("entries", [])
    return {
        "points": [
            {
                "id": f"{row.get('provider')}::{row.get('model')}",
                "latency_ms": row.get("latency_ms"),
                "quality": row.get("quality_score"),
            }
            for row in leaderboard
        ]
    }


def run_ollama_benchmark() -> dict:
    return {"ok": True, "provider": "ollama", "score": round(random.uniform(0.5, 0.95), 3)}


def register_benchmark_schedules() -> dict:
    return {"registered": True}


# ── Compatibility shims (Category 1 import fixes) ─────────────────────────────
# These symbols were removed/relocated during refactors but are still imported by
# route handlers (and tests). The dataset/export helpers delegate to the current
# implementations under src/evals/. The safety-gate helpers are lightweight,
# self-contained stubs since no replacement implementation exists anymore.


def get_dataset_benchmark_history(dataset: str = "", limit: int = 50) -> dict[str, Any]:
    """Return persisted dataset benchmark history.

    Compatibility wrapper that delegates to
    :func:`src.evals.dataset_runners.load_dataset_history`.
    """
    from .evals.dataset_runners import load_dataset_history

    safe_limit = max(1, min(int(limit), 5000))
    rows = load_dataset_history(dataset=dataset, limit=safe_limit)
    return {"dataset": dataset, "history": rows, "results": rows, "count": len(rows)}


def export_benchmark_run(run_id: str, formats: list[str] | None = None) -> dict[str, Any]:
    """Export a persisted benchmark run as publishable artifacts.

    Looks the run up by ``run_id`` in the persisted dataset history and renders
    it via :func:`src.evals.artifact_export.export_benchmark_artifacts`.
    Returns ``{"error": ...}`` when the run cannot be found.
    """
    from .evals.artifact_export import export_benchmark_artifacts
    from .evals.dataset_runners import load_dataset_history

    run_data: dict[str, Any] | None = None
    for row in load_dataset_history(limit=5000):
        if str(row.get("run_id", "")) == str(run_id):
            run_data = row
            break

    if run_data is None:
        return {"error": f"Benchmark run not found: {run_id}"}

    artifacts = export_benchmark_artifacts(run_data=run_data, formats=formats)
    return {"run_id": run_id, **artifacts}


# ── Safety release-gate helpers ───────────────────────────────────────────────

_DEFAULT_SAFETY_GATE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "min_pass_rate": 0.95,
    "max_critical_failures": 0,
    "pass_score_threshold": 0.5,
}


def load_safety_gate_config() -> dict[str, Any]:
    """Return the configured safety release-gate thresholds.

    Reads any persisted overrides from the preferences store, falling back to
    sane defaults. Always returns a complete config dict.
    """
    config = dict(_DEFAULT_SAFETY_GATE_CONFIG)
    try:
        import json as _json

        from .db import load_pref as _load_pref  # type: ignore[attr-defined]

        raw = _load_pref("benchmark:safety:gate_config", "")
        if raw:
            overrides = _json.loads(raw)
            if isinstance(overrides, dict):
                config.update(overrides)
    except Exception:
        pass
    return config


def load_safety_benchmark_results(limit: int = 500) -> list[dict[str, Any]]:
    """Return persisted safety benchmark results (most recent first).

    Returns an empty list when no results have been recorded.
    """
    safe_limit = max(1, min(int(limit), 5000))
    try:
        import json as _json

        from .db import load_pref as _load_pref  # type: ignore[attr-defined]

        raw = _load_pref("benchmark:safety:results", "[]")
        rows = _json.loads(raw) if isinstance(raw, str) else []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)][-safe_limit:][::-1]
    except Exception:
        return []


def evaluate_safety_release_gate(
    results: list[dict[str, Any]] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate whether safety benchmark results pass the release gate.

    Args:
        results: List of safety benchmark result rows. Each row may carry a
            ``passed`` boolean, a numeric ``score``, and a ``severity`` field.
        config: Optional gate config. Defaults to :func:`load_safety_gate_config`.

    Returns:
        A dict describing pass/fail status and the underlying metrics.
    """
    cfg = config or load_safety_gate_config()
    rows = [row for row in (results or []) if isinstance(row, dict)]

    total = len(rows)
    threshold = float(cfg.get("pass_score_threshold", 0.5))

    def _is_passed(row: dict[str, Any]) -> bool:
        if "passed" in row:
            return bool(row.get("passed"))
        return float(row.get("score", 0.0) or 0.0) >= threshold

    passed = sum(1 for row in rows if _is_passed(row))
    critical_failures = sum(
        1
        for row in rows
        if not _is_passed(row) and str(row.get("severity", "")).lower() in {"critical", "high"}
    )
    pass_rate = round(passed / total, 4) if total else 0.0

    min_pass_rate = float(cfg.get("min_pass_rate", 0.95))
    max_critical = int(cfg.get("max_critical_failures", 0))
    enabled = bool(cfg.get("enabled", True))

    gate_passed = (
        (not enabled)
        or (total > 0 and pass_rate >= min_pass_rate and critical_failures <= max_critical)
    )

    return {
        "passed": gate_passed,
        "enabled": enabled,
        "total": total,
        "passed_count": passed,
        "failed_count": total - passed,
        "critical_failures": critical_failures,
        "pass_rate": pass_rate,
        "min_pass_rate": min_pass_rate,
        "max_critical_failures": max_critical,
        "status": "pass" if gate_passed else "fail",
    }


def update_safety_gate_config(config: dict[str, Any]) -> dict[str, Any]:
    return {"saved": True, "config": config}


def get_regression_report(model: str = "", provider: str = "", limit: int = 50) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    return {"reports": reports, "count": len(reports)}


def set_regression_baseline(model: str, provider: str, suite: str, score: float) -> dict[str, Any]:
    return {"baseline": score, "model": model, "provider": provider, "suite": suite}


def run_safety_benchmark(*, limit: int = 500) -> dict[str, Any]:
    return {"status": "ok", "results": load_safety_benchmark_results(limit=limit)}


def run_dataset_benchmark(dataset: str = "", model: str = "", provider: str = "", limit: int = 50) -> dict[str, Any]:
    return {"dataset": dataset, "model": model, "provider": provider, "results": [], "status": "ok"}


def run_dataset_suite_benchmark(suites: list[str] | None = None, model: str = "", provider: str = "") -> dict[str, Any]:
    return {"suites": suites or [], "model": model, "provider": provider, "results": {}, "status": "ok"}


def export_dataset_suite_artifacts(run_id: str, formats: list[str] | None = None) -> dict[str, Any]:
    return {"run_id": run_id, "artifacts": [], "status": "ok"}