"""Model/provider leaderboard helpers.

The leaderboard is derived from existing persisted signals:
- `usage_log` for request volume and task mix
- `benchmark_results` for latency samples
- `message_feedback` for thumbs-up/down approval

This is intentionally lightweight and resilient: if any data source fails,
leaderboard generation continues with available signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.db import (
    get_usage_stats,
    load_benchmark_results,
    load_feedback_export,
    save_benchmark_result,
    save_feedback,
)


_SORT_KEYS = {
    "quality_score",
    "approval_rate",
    "avg_latency_ms",
    "p95_latency_ms",
    "cost_per_1k_tokens",
    "safety_pass_rate",
    "total_requests",
    "composite",
    "task_type",
}

_ESTIMATED_COST_PER_1K = {
    "ollama": 0.0,
    "llm7": 0.0,
    "groq": 0.2,
    "cerebras": 0.4,
    "gemini": 0.35,
    "mistral": 0.45,
    "openrouter": 0.55,
    "cohere": 0.6,
    "github": 0.15,
    "grok": 0.7,
    "claude": 1.2,
    "openai": 1.5,
}


@dataclass
class LeaderboardEntry:
    model: str
    provider: str
    task_type: str = "chat"
    quality_score: float = 0.0      # 0.0 – 1.0 composite
    thumbs_up: int = 0
    thumbs_down: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    cost_per_1k_tokens: float = 0.0
    safety_pass_rate: float = 1.0
    total_requests: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def approval_rate(self) -> float:
        total = self.thumbs_up + self.thumbs_down
        return self.thumbs_up / total if total > 0 else 0.0


def get_leaderboard(
    sort_by: str = "quality_score",
    limit: int = 20,
    provider_filter: str | None = None,
) -> list[LeaderboardEntry]:
    """Return ranked leaderboard entries from persisted runtime signals."""
    safe_limit = max(1, min(int(limit or 20), 100))
    sort_key = (sort_by or "quality_score").strip().lower()
    if sort_key not in _SORT_KEYS:
        sort_key = "quality_score"

    usage_rows: list[dict] = []
    benchmark_rows: list[dict] = []
    feedback_rows: list[dict] = []

    try:
        usage_rows = list(get_usage_stats(days=30).get("by_provider", []))
    except Exception:
        usage_rows = []
    try:
        benchmark_rows = load_benchmark_results(limit=500)
    except Exception:
        benchmark_rows = []
    try:
        feedback_rows = load_feedback_export(limit=5000)
    except Exception:
        feedback_rows = []

    latency_by_provider: dict[str, list[float]] = {}
    for row in benchmark_rows:
        provider = str(row.get("provider") or "").strip().lower()
        if not provider:
            continue
        try:
            latency = float(row.get("latency_ms") or 0.0)
        except Exception:
            latency = 0.0
        if latency > 0:
            latency_by_provider.setdefault(provider, []).append(latency)

    feedback_by_key: dict[tuple[str, str], dict[str, int]] = {}
    for row in feedback_rows:
        provider = str(row.get("provider") or "").strip().lower()
        model = str(row.get("model") or "").strip().lower()
        if not provider or not model:
            continue
        bucket = feedback_by_key.setdefault((provider, model), {"up": 0, "down": 0})
        reaction = str(row.get("reaction") or "")
        if reaction == "thumbs_up":
            bucket["up"] += 1
        elif reaction == "thumbs_down":
            bucket["down"] += 1

    entries: list[LeaderboardEntry] = []
    for row in usage_rows:
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        if not provider or not model:
            continue
        provider_key = provider.lower()
        if provider_filter and provider_key != provider_filter.strip().lower():
            continue

        calls = int(row.get("calls") or 0)
        in_tok = int(row.get("in_tok") or 0)
        out_tok = int(row.get("out_tok") or 0)
        total_tokens = max(0, in_tok + out_tok)

        latencies = sorted(latency_by_provider.get(provider_key, []))
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        if latencies:
            p95_index = min(len(latencies) - 1, max(0, int((len(latencies) - 1) * 0.95)))
            p95_latency = latencies[p95_index]
        else:
            p95_latency = 0.0

        fb = feedback_by_key.get((provider_key, model.lower()), {"up": 0, "down": 0})
        thumbs_up = fb.get("up", 0)
        thumbs_down = fb.get("down", 0)
        total_feedback = thumbs_up + thumbs_down
        approval = (thumbs_up / total_feedback) if total_feedback else 0.5

        provider_cost = _ESTIMATED_COST_PER_1K.get(provider_key, 0.9)
        throughput_score = min(1.0, total_tokens / 50_000.0) if total_tokens else 0.0
        quality_score = max(0.0, min(1.0, (0.7 * approval) + (0.3 * throughput_score)))

        entry = LeaderboardEntry(
            model=model,
            provider=provider,
            task_type="chat",
            quality_score=quality_score,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            avg_latency_ms=round(avg_latency, 2),
            p95_latency_ms=round(p95_latency, 2),
            cost_per_1k_tokens=provider_cost,
            safety_pass_rate=1.0,
            total_requests=calls,
        )
        entries.append(entry)

    if sort_key == "composite":
        ranked = sorted(entries, key=compute_composite_score, reverse=True)
    elif sort_key == "task_type":
        ranked = sorted(entries, key=lambda e: (e.task_type, -e.total_requests, e.model.lower()))
    elif sort_key in {"avg_latency_ms", "p95_latency_ms", "cost_per_1k_tokens"}:
        ranked = sorted(entries, key=lambda e: getattr(e, sort_key), reverse=False)
    else:
        ranked = sorted(entries, key=lambda e: getattr(e, sort_key), reverse=True)

    return ranked[:safe_limit]


def record_feedback(model: str, provider: str, thumbs_up: bool) -> None:
    """
    Record a thumbs-up or thumbs-down vote.

    Persist a coarse thumbs-up/thumbs-down vote as message feedback.

    We persist with a synthetic chat/message identity because this helper is
    provider-model centric and not tied to a specific chat transcript.
    """
    reaction = "thumbs_up" if thumbs_up else "thumbs_down"
    synthetic_chat_id = f"leaderboard::{provider}::{model}"
    synthetic_idx = int(datetime.now(timezone.utc).timestamp() * 1000)
    save_feedback(
        chat_id=synthetic_chat_id,
        message_idx=synthetic_idx,
        reaction=reaction,
        provider=provider,
        model=model,
    )


def record_latency(model: str, provider: str, latency_ms: float) -> None:
    """
    Record a latency sample for a model.

    Persist a latency sample into benchmark results.
    """
    safe_latency = max(0.0, float(latency_ms or 0.0))
    save_benchmark_result(
        provider=provider,
        probe_name=f"latency:{model}",
        latency_ms=safe_latency,
        response_len=0,
    )


def compute_composite_score(entry: LeaderboardEntry) -> float:
    """
    Compute a composite ranking score for a leaderboard entry.

    Weights: quality 40%, approval_rate 30%, speed 20%, cost 10%.
    FUNCTIONAL: formula-based.
    """
    quality_w = 0.40
    approval_w = 0.30
    speed_w    = 0.20
    cost_w     = 0.10

    # Normalise speed: 0 ms = 1.0, 10_000 ms = 0.0
    speed_score = max(0.0, 1.0 - entry.avg_latency_ms / 10_000)
    # Normalise cost: $0 = 1.0, $10/1k = 0.0
    cost_score = max(0.0, 1.0 - entry.cost_per_1k_tokens / 10.0)

    return (
        quality_w * entry.quality_score
        + approval_w * entry.approval_rate
        + speed_w * speed_score
        + cost_w * cost_score
    )
