"""
src/providers/deepseek.py — DeepSeek provider adapter stub

Normalises DeepSeek's `reasoning_content` field (present in
DeepSeek-R1 and similar chain-of-thought models) into the standard
Nexus AI thinking block format.

Also handles DeepSeek-specific rate-limit headers and retry logic.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def normalise_deepseek_response(raw: dict) -> dict:
    """
    Normalise a DeepSeek chat-completion response dict.

    DeepSeek-R1 returns ``reasoning_content`` alongside ``content`` in
    the assistant message. Map this to Nexus AI's thinking block format.

    FUNCTIONAL: mapping is implemented.
    """
    choices = raw.get("choices", [])
    for choice in choices:
        message = choice.get("message", {})
        reasoning = message.pop("reasoning_content", None)
        if reasoning:
            # Inject into Nexus thinking block convention
            message["thinking"] = reasoning
    return raw


def extract_reasoning(response: dict) -> str | None:
    """
    Extract the reasoning / chain-of-thought from a normalised response.

    Returns the thinking string if present, else None.
    FUNCTIONAL.
    """
    choices = response.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("thinking")
    return None


# ---------------------------------------------------------------------------
# Request formatting
# ---------------------------------------------------------------------------

def format_deepseek_request(payload: dict) -> dict:
    """
    Apply DeepSeek-specific request transformations.

    - Adds ``stream_options: {include_usage: true}`` when streaming
    - Maps Nexus tool-call format to DeepSeek tool format

    STUB: raises NotImplementedError for tool-call mapping.
    """
    if payload.get("stream"):
        payload.setdefault("stream_options", {"include_usage": True})
    if "tools" in payload:
        raise NotImplementedError(
            "format_deepseek_request tool-call mapping is not yet implemented. "
            "Planned: normalise Nexus tool format → DeepSeek function_call format."
        )
    return payload


# ---------------------------------------------------------------------------
# Rate-limit header parsing
# ---------------------------------------------------------------------------

def parse_rate_limit_headers(headers: dict) -> dict:
    """
    Parse DeepSeek rate-limit response headers.

    Returns dict with remaining_requests, remaining_tokens, reset_at.
    FUNCTIONAL.
    """
    return {
        "remaining_requests": int(headers.get("x-ratelimit-remaining-requests", -1)),
        "remaining_tokens": int(headers.get("x-ratelimit-remaining-tokens", -1)),
        "reset_at": headers.get("x-ratelimit-reset-requests", ""),
    }
