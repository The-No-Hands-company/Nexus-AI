"""
src/evals/ab_testing.py — A/B testing framework for model and prompt changes

Provides:
  - Experiment management: create, start, pause, stop experiments
  - Traffic splitting: deterministic hash-based assignment (no randomness per-request)
  - Metric collection: latency, cost, quality score, thumbs up/down
  - Statistical significance testing: chi-squared (binary outcomes), Welch's t-test (continuous)
  - Winner selection: automatic winner declaration when significance threshold met

Experiments are persisted to DB. Assignment is deterministic per (experiment_id, user_id)
so a given user always sees the same variant.

Environment variables:
    AB_SIGNIFICANCE_THRESHOLD — p-value to declare significance (default: 0.05)
    AB_MIN_SAMPLES_PER_ARM    — min samples per arm before testing (default: 30)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nexus.evals.ab_testing")

_SIGNIFICANCE_THRESHOLD = float(os.getenv("AB_SIGNIFICANCE_THRESHOLD", "0.05"))
_MIN_SAMPLES = int(os.getenv("AB_MIN_SAMPLES_PER_ARM", "30"))


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ABVariant:
    variant_id: str
    name: str                   # "control" | "treatment_A" | etc.
    model: str = ""
    prompt_template: str = ""
    parameters: dict = field(default_factory=dict)
    traffic_weight: float = 0.5  # proportion of traffic (must sum to 1.0 across variants)


@dataclass
class ABExperiment:
    experiment_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = ""
    description: str = ""
    variants: list[ABVariant] = field(default_factory=list)
    metric: str = "quality_score"    # metric to optimize
    status: str = "draft"            # draft | running | paused | completed
    winner: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class ABObservation:
    experiment_id: str
    variant_id: str
    user_id: str
    metric_value: float
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Experiment store ──────────────────────────────────────────────────────────

_experiments: dict[str, ABExperiment] = {}
_observations: dict[str, list[ABObservation]] = {}  # experiment_id -> list


def _save_experiment(exp: ABExperiment) -> None:
    _experiments[exp.experiment_id] = exp
    try:
        from src.db import load_pref, save_pref  # type: ignore
        data = load_pref("ab:experiments") or {}
        data[exp.experiment_id] = {
            "experiment_id": exp.experiment_id, "name": exp.name,
            "description": exp.description, "metric": exp.metric,
            "status": exp.status, "winner": exp.winner,
            "created_at": exp.created_at, "started_at": exp.started_at,
            "completed_at": exp.completed_at,
            "variants": [
                {"variant_id": v.variant_id, "name": v.name, "model": v.model,
                 "prompt_template": v.prompt_template, "parameters": v.parameters,
                 "traffic_weight": v.traffic_weight}
                for v in exp.variants
            ],
        }
        save_pref("ab:experiments", data)
    except Exception:
        pass


def _load_experiments_from_db() -> None:
    try:
        from src.db import load_pref  # type: ignore
        data = load_pref("ab:experiments") or {}
        for exp_id, d in data.items():
            variants = [
                ABVariant(
                    variant_id=v["variant_id"], name=v["name"], model=v.get("model", ""),
                    prompt_template=v.get("prompt_template", ""),
                    parameters=v.get("parameters", {}),
                    traffic_weight=v.get("traffic_weight", 0.5),
                )
                for v in d.get("variants", [])
            ]
            _experiments[exp_id] = ABExperiment(
                experiment_id=d["experiment_id"], name=d.get("name", ""),
                description=d.get("description", ""), metric=d.get("metric", "quality_score"),
                variants=variants, status=d.get("status", "draft"),
                winner=d.get("winner"), created_at=d.get("created_at", ""),
                started_at=d.get("started_at"), completed_at=d.get("completed_at"),
            )
    except Exception:
        pass


# ── Traffic assignment ────────────────────────────────────────────────────────

def assign_variant(experiment_id: str, user_id: str) -> ABVariant | None:
    """Deterministically assign a user to a variant.

    Uses SHA-256 hash of (experiment_id + user_id) for stable assignment.
    Returns None if the experiment is not running.
    """
    exp = _experiments.get(experiment_id)
    if not exp or exp.status != "running" or not exp.variants:
        return None

    # Hash to a float in [0, 1)
    raw = hashlib.sha256(f"{experiment_id}:{user_id}".encode()).digest()
    bucket = int.from_bytes(raw[:4], "big") / (2**32)

    # Walk the cumulative weight distribution
    cumulative = 0.0
    for variant in exp.variants:
        cumulative += variant.traffic_weight
        if bucket < cumulative:
            return variant
    return exp.variants[-1]


# ── Statistical testing ───────────────────────────────────────────────────────

def _welch_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t-test. Returns (t_statistic, p_value)."""
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0
    mean_a = sum(a) / n_a
    mean_b = sum(b) / n_b
    var_a = sum((x - mean_a) ** 2 for x in a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (n_b - 1)
    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return 0.0, 1.0
    t = (mean_a - mean_b) / se
    # Welch-Satterthwaite degrees of freedom
    df_num = (var_a / n_a + var_b / n_b) ** 2
    df_den = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = df_num / df_den if df_den else 1.0
    # Approximate p-value using scipy if available, else use normal approximation
    try:
        from scipy import stats  # type: ignore
        p = 2 * stats.t.sf(abs(t), df)
    except ImportError:
        # Normal approximation for large df
        z = abs(t)
        p = 2 * (1 - _norm_cdf(z))
    return t, float(p)


def _norm_cdf(z: float) -> float:
    """Approximation of standard normal CDF using Abramowitz & Stegun."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _chi_squared_test(success_a: int, n_a: int, success_b: int, n_b: int) -> tuple[float, float]:
    """Chi-squared test for 2x2 contingency table."""
    fail_a = n_a - success_a
    fail_b = n_b - success_b
    total = n_a + n_b
    if total == 0:
        return 0.0, 1.0
    r1 = n_a
    r2 = n_b
    c1 = success_a + success_b
    c2 = fail_a + fail_b
    expected = [[r1 * c1 / total, r1 * c2 / total], [r2 * c1 / total, r2 * c2 / total]]
    observed = [[success_a, fail_a], [success_b, fail_b]]
    chi2 = sum(
        (observed[i][j] - expected[i][j]) ** 2 / expected[i][j]
        for i in range(2) for j in range(2)
        if expected[i][j] > 0
    )
    try:
        from scipy.stats import chi2 as _chi2  # type: ignore
        p = 1 - _chi2.cdf(chi2, df=1)
    except ImportError:
        # Crude approximation
        p = math.exp(-chi2 / 2)
    return chi2, float(p)


# ── Public API ────────────────────────────────────────────────────────────────

def create_experiment(
    name: str,
    variants: list[dict],
    metric: str = "quality_score",
    description: str = "",
) -> ABExperiment:
    """Create a new A/B experiment.

    variants: list of dicts with keys: name, model, prompt_template, parameters, traffic_weight
    """
    exp = ABExperiment(
        name=name, description=description, metric=metric,
        variants=[
            ABVariant(
                variant_id=str(uuid.uuid4())[:8],
                name=v.get("name", f"variant_{i}"),
                model=v.get("model", ""),
                prompt_template=v.get("prompt_template", ""),
                parameters=v.get("parameters", {}),
                traffic_weight=v.get("traffic_weight", 1.0 / len(variants)),
            )
            for i, v in enumerate(variants)
        ],
    )
    _save_experiment(exp)
    return exp


def start_experiment(experiment_id: str) -> bool:
    exp = _experiments.get(experiment_id)
    if not exp or exp.status not in ("draft", "paused"):
        return False
    exp.status = "running"
    exp.started_at = datetime.now(timezone.utc).isoformat()
    _save_experiment(exp)
    return True


def pause_experiment(experiment_id: str) -> bool:
    exp = _experiments.get(experiment_id)
    if not exp or exp.status != "running":
        return False
    exp.status = "paused"
    _save_experiment(exp)
    return True


def record_observation(
    experiment_id: str,
    variant_id: str,
    user_id: str,
    metric_value: float,
    metadata: dict | None = None,
) -> None:
    obs = ABObservation(
        experiment_id=experiment_id, variant_id=variant_id,
        user_id=user_id, metric_value=metric_value, metadata=metadata or {},
    )
    _observations.setdefault(experiment_id, []).append(obs)
    # Persist sample (keep last 10k per experiment)
    try:
        from src.db import load_pref, save_pref  # type: ignore
        key = f"ab:obs:{experiment_id}"
        existing = load_pref(key) or []
        existing.append({
            "variant_id": variant_id, "user_id": user_id,
            "metric_value": metric_value, "metadata": metadata or {},
            "timestamp": obs.timestamp,
        })
        save_pref(key, existing[-10000:])
    except Exception:
        pass


def analyze_experiment(experiment_id: str) -> dict:
    """Run statistical analysis on an experiment. Returns analysis dict."""
    exp = _experiments.get(experiment_id)
    if not exp:
        return {"error": "experiment not found"}

    # Load observations from DB
    variant_obs: dict[str, list[float]] = {}
    try:
        from src.db import load_pref  # type: ignore
        obs_list = load_pref(f"ab:obs:{experiment_id}") or []
        for obs in obs_list:
            vid = obs.get("variant_id", "")
            variant_obs.setdefault(vid, []).append(float(obs.get("metric_value", 0)))
    except Exception:
        pass

    # Also include in-memory observations
    for obs in _observations.get(experiment_id, []):
        variant_obs.setdefault(obs.variant_id, []).append(obs.metric_value)

    stats = {}
    for variant in exp.variants:
        vals = variant_obs.get(variant.variant_id, [])
        n = len(vals)
        mean = sum(vals) / n if n else 0.0
        stats[variant.variant_id] = {
            "name": variant.name, "n": n, "mean": round(mean, 4),
            "sufficient": n >= _MIN_SAMPLES,
        }

    # Compare first two variants (control vs treatment)
    variant_ids = [v.variant_id for v in exp.variants]
    significance_result = {}
    if len(variant_ids) >= 2:
        a_vals = variant_obs.get(variant_ids[0], [])
        b_vals = variant_obs.get(variant_ids[1], [])
        if len(a_vals) >= _MIN_SAMPLES and len(b_vals) >= _MIN_SAMPLES:
            t, p = _welch_t_test(a_vals, b_vals)
            significant = p < _SIGNIFICANCE_THRESHOLD
            significance_result = {
                "t_statistic": round(t, 4),
                "p_value": round(p, 6),
                "significant": significant,
                "confidence_level": 1 - _SIGNIFICANCE_THRESHOLD,
            }
            if significant:
                # Declare winner as the variant with higher mean
                winner_id = max(stats, key=lambda k: stats[k]["mean"])
                exp.winner = winner_id
                exp.status = "completed"
                exp.completed_at = datetime.now(timezone.utc).isoformat()
                _save_experiment(exp)

    return {
        "experiment_id": experiment_id,
        "name": exp.name,
        "status": exp.status,
        "metric": exp.metric,
        "variant_stats": stats,
        "significance": significance_result,
        "winner": exp.winner,
    }


def list_experiments() -> list[dict]:
    _load_experiments_from_db()
    return [
        {"experiment_id": e.experiment_id, "name": e.name, "status": e.status,
         "metric": e.metric, "winner": e.winner, "created_at": e.created_at,
         "variant_count": len(e.variants)}
        for e in _experiments.values()
    ]


def get_experiment(experiment_id: str) -> ABExperiment | None:
    _load_experiments_from_db()
    return _experiments.get(experiment_id)
