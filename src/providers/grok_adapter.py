"""
src/providers/grok_adapter.py — xAI Grok provider adapter stub

Handles Grok-specific quirks:
- Grok async deferred responses (Grok can return a task ID and poll)
- Grok Live Search tool integration
- Response normalisation to OpenAI-compat format

This module is a STUB — most functions raise NotImplementedError.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Request formatting
# ---------------------------------------------------------------------------

def format_grok_request(payload: dict) -> dict:
    """
    Apply Grok-specific request transformations.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Add search_parameters for Grok Live Search if requested
    - Handle deferred / async mode flag
    """
    raise NotImplementedError(
        "format_grok_request is not yet implemented. "
        "Planned: Live Search + deferred response mode handling."
    )


# ---------------------------------------------------------------------------
# Deferred response polling
# ---------------------------------------------------------------------------

async def poll_deferred_response(task_id: str, api_key: str, max_polls: int = 10) -> dict:
    """
    Poll Grok's deferred response endpoint until complete.

    STUB: raises NotImplementedError.
    Implementation plan:
    - GET https://api.x.ai/v1/responses/{task_id}
    - Exponential backoff
    - Return completed response or raise after max_polls
    """
    raise NotImplementedError(
        "poll_deferred_response is not yet implemented. "
        "Planned: poll xAI deferred response endpoint with backoff."
    )


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def normalise_grok_response(raw: dict) -> dict:
    """
    Normalise a Grok API response to OpenAI-compatible format.

    FUNCTIONAL: Grok API is largely OpenAI-compatible — minor adjustments only.
    """
    # Grok API is OpenAI-compat; pass through with minor cleanup
    choices = raw.get("choices", [])
    for choice in choices:
        message = choice.get("message", {})
        # Normalise any Grok-specific search citation annotations
        annotations = message.pop("annotations", None)
        if annotations:
            message["search_citations"] = annotations
    return raw


# ---------------------------------------------------------------------------
# Live Search result extraction
# ---------------------------------------------------------------------------

def extract_search_citations(response: dict) -> list[dict]:
    """
    Extract Grok Live Search citations from a response.

    FUNCTIONAL: returns search_citations from normalised message.
    """
    choices = response.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("search_citations", [])
    return []
