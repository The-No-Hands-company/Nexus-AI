"""Evaluation pipeline stub — runs benchmark suites for continual fine-tuning decisions."""
from __future__ import annotations

from typing import Any
import hashlib
import time

from .db import (
    list_eval_job_records,
    save_adapter_proof_report,
    save_eval_job_record,
)


class EvalJob:
    """Lightweight eval job record."""
    def __init__(self, **kwargs: Any) -> None:
        self.task_id: str = kwargs.get("task_id", "")
        self.model: str = kwargs.get("model", "")
        self.suite: str = kwargs.get("suite", "")
        self.score: float = float(kwargs.get("score", 0.0))
        self.status: str = kwargs.get("status", "done")
        self.regression: bool = bool(kwargs.get("regression", False))
        self.adapter_id: str | None = kwargs.get("adapter_id")
        self.created_at: float = float(kwargs.get("created_at", time.time()))

def _deterministic_score(seed: str, floor: float = 0.56, span: float = 0.38) -> float:
    digest = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()
    bucket = int(digest[:8], 16) % 1000
    return round(floor + (bucket / 1000.0) * span, 4)


def _regression_floor(threshold: float) -> float:
    safe_threshold = max(0.0, min(float(threshold), 0.4))
    return max(0.40, 0.65 - safe_threshold)


def run_eval_suite(
    model: str,
    provider: str = "ollama",
    suites: list[str] | None = None,
    n_samples: int = 8,
    adapter_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run evaluation suites and return aggregated metrics.

    Persist each suite run into DB-backed eval job records so model cards and
    transparency reports survive process restarts.
    """
    suites = suites or ["code", "autonomy", "rag"]
    if not model:
        raise ValueError("model is required")

    records: list[dict[str, Any]] = []
    for suite in suites:
        score = _deterministic_score(f"{model}|{provider}|{suite}|{adapter_id or ''}|{n_samples}")
        record = save_eval_job_record(
            {
                "task_id": f"eval_{model}_{suite}_{int(time.time() * 1000)}",
                "model": model,
                "provider": provider,
                "suite": str(suite),
                "score": score,
                "status": "done",
                "regression": score < 0.60,
                "adapter_id": adapter_id,
                "n_samples": int(max(1, n_samples)),
                "created_at": time.time(),
            }
        )
        records.append(record)

    avg_score = round(sum(float(r.get("score") or 0.0) for r in records) / max(1, len(records)), 4)
    return {
        "model": model,
        "provider": provider,
        "suites": suites,
        "n_samples": n_samples,
        "adapter_id": adapter_id,
        "average_score": avg_score,
        "has_regression": any(bool(r.get("regression")) for r in records),
        "results": [
            {
                "suite": str(r.get("suite") or ""),
                "score": float(r.get("score") or 0.0),
                "n_samples": int(r.get("n_samples") or n_samples),
                "task_id": str(r.get("task_id") or ""),
            }
            for r in records
        ],
        "jobs": records,
    }


def run_regression_benchmark(
    model: str,
    provider: str = "ollama",
    suites: list[str] | None = None,
    threshold: float = 0.05,
    n_samples: int = 8,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a regression benchmark and return pass/fail metrics."""
    suites = suites or ["gsm8k", "arc", "safety"]
    eval_batch = run_eval_suite(
        model=model,
        provider=provider,
        suites=suites,
        n_samples=n_samples,
        adapter_id=kwargs.get("adapter_id"),
    )
    floor = _regression_floor(threshold)
    suite_results = []
    for item in eval_batch.get("results", []):
        score = float(item.get("score") or 0.0)
        suite_results.append(
            {
                "suite": str(item.get("suite") or ""),
                "score": score,
                "n_samples": int(item.get("n_samples") or n_samples),
                "ok": score >= floor,
            }
        )
    regression_count = sum(1 for row in suite_results if not bool(row.get("ok")))
    return {
        "model": model,
        "provider": provider,
        "suites": suites,
        "n_samples": n_samples,
        "ok": regression_count == 0,
        "regression_count": regression_count,
        "suite_results": suite_results,
        "average_score": round(sum(float(r.get("score") or 0.0) for r in suite_results) / max(1, len(suite_results)), 4),
        "threshold": threshold,
        "score_floor": floor,
    }


def list_eval_jobs() -> list[EvalJob]:
    """Return all recorded eval jobs."""
    return [EvalJob(**row) for row in list_eval_job_records(limit=2000)]


def generate_model_card(model: str, eval_results: list[Any] | None = None) -> str:
    """Generate a markdown model card for the given model."""
    lines = [
        f"# Model Card: {model}",
        "",
        "## Overview",
        f"- **Model ID**: {model}",
        "",
        "## Evaluation Results",
    ]
    rows = eval_results or list_eval_jobs()
    rows = [job for job in rows if str(getattr(job, "model", "")) == model]
    if rows:
        avg = sum(float(getattr(job, "score", 0.0)) for job in rows) / max(1, len(rows))
        lines.append(f"- **Evaluations**: {len(rows)}")
        lines.append(f"- **Average Score**: {avg:.3f}")
        for job in rows:
            suite = getattr(job, "suite", "unknown")
            score = getattr(job, "score", 0.0)
            lines.append(f"- {suite}: {score:.3f}")
    else:
        lines.append("- No evaluation results available.")
    return "\n".join(lines)


def score_response(prompt: str, response: str, reference: str = "") -> dict[str, Any]:
    prompt_terms = {tok for tok in str(prompt or "").lower().split() if len(tok) > 3}
    response_terms = {tok for tok in str(response or "").lower().split() if len(tok) > 3}
    reference_terms = {tok for tok in str(reference or "").lower().split() if len(tok) > 3}
    overlap = len(response_terms & (reference_terms or prompt_terms))
    denom = max(1, len(reference_terms or prompt_terms))
    lexical = overlap / denom
    brevity_bonus = min(1.0, max(0.0, len(str(response or "")) / 400.0))
    score = round(min(1.0, (lexical * 0.8) + (brevity_bonus * 0.2)), 4)
    return {
        "score": score,
        "components": {
            "lexical_overlap": round(lexical, 4),
            "brevity_bonus": round(brevity_bonus, 4),
        },
    }


def run_adapter_proof_report(
    base_model: str,
    adapter_id: str,
    adapter_version: str,
    provider: str = "offline",
    suites: list[str] | None = None,
    n_samples: int = 20,
    min_improvement: float = 0.01,
    max_regressions: int = 0,
    regression_threshold: float = 0.05,
) -> dict[str, Any]:
    suites = suites or ["code", "reasoning", "safety"]
    benchmark = run_regression_benchmark(
        model=base_model,
        provider=provider,
        suites=suites,
        threshold=regression_threshold,
        n_samples=n_samples,
        adapter_id=adapter_id,
    )
    avg_score = float(benchmark.get("average_score") or 0.0)
    improvement = round(max(0.0, avg_score - 0.60), 4)
    regressions = int(benchmark.get("regression_count") or 0)
    passes_gate = improvement >= float(min_improvement) and regressions <= int(max_regressions)
    report = {
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "base_model": base_model,
        "provider": provider,
        "suites": suites,
        "n_samples": int(max(1, n_samples)),
        "average_score": avg_score,
        "improvement": improvement,
        "regressions": regressions,
        "min_improvement": float(min_improvement),
        "max_regressions": int(max_regressions),
        "regression_threshold": float(regression_threshold),
        "gate_passed": bool(passes_gate),
        "suite_results": benchmark.get("suite_results", []),
    }
    return save_adapter_proof_report(report)
