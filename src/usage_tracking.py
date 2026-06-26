"""Usage tracking and cost analytics for LLM calls.

Provides aggregated usage statistics and cost estimation across all providers
and models, used by admin routes for dashboards and billing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import log_usage as db_log_usage

logger = logging.getLogger(__name__)


# ── Per-model pricing (USD per 1K tokens, input and output) ───────────────────

_MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "o1": {"input": 0.015, "output": 0.06},
    "o1-mini": {"input": 0.003, "output": 0.012},
    "o3-mini": {"input": 0.0011, "output": 0.0044},
    # Anthropic
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    # Google
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    # DeepSeek
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    # Mistral
    "mistral-large": {"input": 0.004, "output": 0.012},
    "mistral-small": {"input": 0.001, "output": 0.003},
    "mistral-nemo": {"input": 0.00015, "output": 0.00015},
    # Meta
    "llama-3.3-70b": {"input": 0.00059, "output": 0.00079},
    "llama-3.1-8b": {"input": 0.00006, "output": 0.00006},
    # Cohere
    "command-r-plus": {"input": 0.003, "output": 0.015},
    "command-r": {"input": 0.0005, "output": 0.0015},
}

# Provider-level fallback pricing (when model not found)
_PROVIDER_PRICING: Dict[str, Dict[str, float]] = {
    "openai": {"input": 0.0025, "output": 0.01},
    "claude": {"input": 0.003, "output": 0.015},
    "grok": {"input": 0.002, "output": 0.008},
    "deepseek": {"input": 0.00014, "output": 0.00028},
    "moonshot": {"input": 0.001, "output": 0.001},
    "dashscope": {"input": 0.001, "output": 0.001},
    "perplexity": {"input": 0.005, "output": 0.005},
    "openrouter": {"input": 0.00015, "output": 0.0006},
}


def get_model_cost(model_name: str, provider_id: str = "") -> Optional[Dict[str, float]]:
    """Get per-model pricing, falling back to provider-level pricing."""
    # Exact match first
    if model_name in _MODEL_PRICING:
        return _MODEL_PRICING[model_name]
    # Partial match
    for md, pricing in _MODEL_PRICING.items():
        if md in model_name or model_name in md:
            return pricing
    # Provider fallback
    if provider_id and provider_id in _PROVIDER_PRICING:
        return _PROVIDER_PRICING[provider_id]
    return None


def estimate_cost_usd(model: str, provider: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for an LLM call.

    Uses per-model pricing when available, falls back to provider-level pricing.
    Returns 0.0 for free-tier providers.
    """
    pricing = get_model_cost(model, provider)
    if not pricing:
        return 0.0
    input_cost = (input_tokens / 1000.0) * pricing["input"]
    output_cost = (output_tokens / 1000.0) * pricing["output"]
    return round(input_cost + output_cost, 8)


def track_usage_event(
    provider: str,
    model: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float = 0.0,
    status: str = "ok",
    usage_principal: str = "",
) -> None:
    """Record an LLM usage event with cost estimation.

    This is called for every LLM call (not just final respond actions).
    """
    cost = estimate_cost_usd(model, provider, input_tokens, output_tokens)
    try:
        db_log_usage(
            provider=provider,
            model=model,
            task_type=task_type,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            status=status,
            usage_principal=usage_principal,
        )
    except Exception:
        logger.warning("Failed to register task type: %s (provider=%s)", task_type, provider, exc_info=True)


@dataclass
class UsageStats:
    """Aggregated usage statistics for a time period."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    by_provider: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_model: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    period_start: float = 0.0
    period_end: float = 0.0


def get_usage_stats(hours: int = 24) -> UsageStats:
    """Get aggregated usage statistics for the last N hours.

    Reads from the usage_log table via db module.
    Returns empty stats if no data or if DB is unavailable.
    """
    stats = UsageStats()
    stats.period_end = time.time()
    stats.period_start = stats.period_end - (hours * 3600)
    try:
        from .db import _sql_fetchall
        cutoff = stats.period_start
        rows = _sql_fetchall(
            "SELECT * FROM usage_log WHERE created_at > ? ORDER BY created_at DESC LIMIT 10000",
            (cutoff,),
        )
        for row in rows:
            stats.total_calls += 1
            provider = row.get("provider", "unknown")
            model = row.get("model", "unknown")
            tokens_in = int(row.get("tokens_in") or 0)
            tokens_out = int(row.get("tokens_out") or 0)
            stats.total_input_tokens += tokens_in
            stats.total_output_tokens += tokens_out
            cost = float(row.get("cost_usd") or 0)
            stats.total_cost_usd += cost
            if provider not in stats.by_provider:
                stats.by_provider[provider] = {"calls": 0, "tokens": 0, "cost": 0.0}
            stats.by_provider[provider]["calls"] += 1
            stats.by_provider[provider]["tokens"] += tokens_in + tokens_out
            stats.by_provider[provider]["cost"] += cost
            if model not in stats.by_model:
                stats.by_model[model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            stats.by_model[model]["calls"] += 1
            stats.by_model[model]["tokens"] += tokens_in + tokens_out
            stats.by_model[model]["cost"] += cost
    except Exception:
        logger.warning("Failed to fetch usage stats", exc_info=True)
    return stats


def get_providers_cost_summary() -> List[Dict[str, Any]]:
    """Return a cost summary for each provider with pricing info.

    Used by the admin dashboard to show provider costs.
    """
    from .agent import PROVIDERS, PROVIDER_CAPABILITIES
    result = []
    for pid, cfg in PROVIDERS.items():
        models = []
        if pid == "openai":
            models = ["gpt-4o", "gpt-4o-mini"]
        elif pid == "claude":
            models = ["claude-3-5-sonnet", "claude-3-haiku"]
        elif pid == "deepseek":
            models = ["deepseek-chat"]
        elif pid == "grok":
            models = ["grok-2"]
        else:
            models = [cfg.get("default_model", "unknown")]

        model_costs = {}
        for m in models:
            pricing = get_model_cost(m, pid)
            if pricing:
                model_costs[m] = pricing

        result.append({
            "id": pid,
            "label": cfg.get("label", pid),
            "models": models,
            "pricing": model_costs,
            "keyless": cfg.get("keyless", False),
            "capabilities": list(PROVIDER_CAPABILITIES.get(pid, [])),
        })
    return result


def get_usage_daily(days: int = 7) -> List[Dict[str, Any]]:
    """Return per-day usage aggregates for the last N days.

    Compatibility wrapper that delegates to :func:`src.db.get_usage_daily`.
    Each entry has ``date``, ``calls``, ``in_tok`` and ``out_tok`` keys.
    Returns an empty list when the DB is unavailable.
    """
    try:
        from .db import get_usage_daily as db_get_usage_daily
        return db_get_usage_daily(days=days)
    except Exception:
        logger.warning("Failed to fetch daily usage", exc_info=True)
        return []
