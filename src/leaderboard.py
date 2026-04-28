from __future__ import annotations

from dataclasses import dataclass

from .benchmark import get_benchmark_leaderboard


@dataclass
class LeaderboardEntry:
    model: str
    provider: str
    task_type: str
    quality_score: float
    latency_ms: float = 0.0


def get_leaderboard(limit: int = 10) -> list[LeaderboardEntry]:
    rows = get_benchmark_leaderboard(limit=limit).get("entries", [])
    return [
        LeaderboardEntry(
            model=str(row.get("model", f"entry-{idx}")),
            provider=str(row.get("provider", "unknown")),
            task_type=str(row.get("task_type", "general")),
            quality_score=float(row.get("quality_score", 0.0)),
            latency_ms=float(row.get("latency_ms", 0.0)),
        )
        for idx, row in enumerate(rows)
    ]