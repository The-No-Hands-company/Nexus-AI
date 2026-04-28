"""src/model_router.py — lightweight budget-aware provider routing helpers.

Consumed by TestSprintF (Part 6: Budget-Aware Routing) and indirectly by
the /agents/{id}/run endpoint cascade logic.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Static provider metadata (latency in seconds, cost per 1k tokens, tools)
# ---------------------------------------------------------------------------
_PROVIDER_META: dict[str, dict] = {
    "groq":    {"avg_latency": 0.5,  "cost_per_1k": 0.01,  "supports_tools": True},
    "openai":  {"avg_latency": 1.0,  "cost_per_1k": 0.15,  "supports_tools": True},
    "anthropic": {"avg_latency": 1.2, "cost_per_1k": 0.15, "supports_tools": True},
    "ollama":  {"avg_latency": 2.0,  "cost_per_1k": 0.0,   "supports_tools": False},
    "cohere":  {"avg_latency": 1.5,  "cost_per_1k": 0.08,  "supports_tools": False},
    "mistral": {"avg_latency": 0.8,  "cost_per_1k": 0.04,  "supports_tools": True},
    "together": {"avg_latency": 0.9, "cost_per_1k": 0.02,  "supports_tools": True},
}

# Default fallback chain per provider (excludes the provider itself)
_FALLBACK_CHAINS: dict[str, list[str]] = {
    "groq":     ["mistral", "together", "openai", "ollama"],
    "openai":   ["anthropic", "groq", "mistral", "ollama"],
    "anthropic": ["openai", "groq", "mistral", "ollama"],
    "ollama":   ["groq", "mistral", "together", "openai"],
    "cohere":   ["groq", "mistral", "openai", "ollama"],
    "mistral":  ["groq", "together", "openai", "ollama"],
    "together": ["groq", "mistral", "openai", "ollama"],
}


def route_to_best_provider(
    providers: list[str],
    budget_tokens: int,
    require_tools: bool = False,
    latency_critical: bool = False,
    time_budget_s: float | None = None,
) -> str:
    """Return the best provider from *providers* given routing constraints.

    Selection priority:
    1. Filter out providers that don't support tools when *require_tools* is True.
    2. If *latency_critical* is True (or *time_budget_s* is set and tight),
       prefer the provider with the lowest avg_latency.
    3. Otherwise prefer the lowest cost_per_1k.
    4. Fall back to the first remaining provider if metadata is unknown.
    """
    candidates = list(providers)

    if require_tools:
        candidates = [
            p for p in candidates
            if _PROVIDER_META.get(p, {}).get("supports_tools", True)
        ]
    if not candidates:
        candidates = list(providers)  # relax constraint if nothing left

    # If latency is the primary concern pick the fastest
    if latency_critical or (time_budget_s is not None and time_budget_s <= 1.0):
        candidates.sort(key=lambda p: _PROVIDER_META.get(p, {}).get("avg_latency", 9999))
    else:
        candidates.sort(key=lambda p: _PROVIDER_META.get(p, {}).get("cost_per_1k", 9999))

    return candidates[0]


def can_satisfy_within_budget(
    request_tokens: int,
    budget_tokens: int,
    expected_output_tokens: int,
) -> bool:
    """Return True iff *request_tokens* + *expected_output_tokens* fits within *budget_tokens*."""
    return (request_tokens + expected_output_tokens) <= budget_tokens


def get_fallback_providers(provider: str) -> list[str]:
    """Return an ordered fallback list for *provider*, excluding *provider* itself."""
    chain = _FALLBACK_CHAINS.get(provider)
    if chain:
        return [p for p in chain if p != provider]
    # Generic fallback: every known provider except the requested one
    return [p for p in _PROVIDER_META if p != provider]
