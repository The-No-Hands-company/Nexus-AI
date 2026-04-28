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