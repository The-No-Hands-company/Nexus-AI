"""
src/providers/gemini_adapter.py — Gemini provider adapter stub

Handles Gemini-specific quirks:
- Function-call ID mapping (Gemini uses ``name`` not ``id`` in tool_call responses)
- Multi-turn safety rating normalisation
- Gemini 1.5 Pro system instruction format (not system role message)

This module is a STUB — request formatting raises NotImplementedError.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def normalise_gemini_response(raw: dict) -> dict:
    """
    Normalise a Gemini API response to OpenAI-compatible format.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Map candidates[0].content.parts → choices[0].message
    - Map function_call parts to tool_calls with generated IDs
    - Map finishReason → finish_reason (STOP → stop, MAX_TOKENS → length, etc.)
    - Add usage dict from usageMetadata
    """
    raise NotImplementedError(
        "normalise_gemini_response is not yet implemented. "
        "Planned: full Gemini → OpenAI-compat response mapping."
    )


def format_gemini_request(payload: dict) -> dict:
    """
    Convert an OpenAI-style request payload to Gemini API format.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Extract system message → systemInstruction field
    - Convert messages array → contents array (role: user/model)
    - Convert tools → Gemini FunctionDeclaration format
    """
    raise NotImplementedError(
        "format_gemini_request is not yet implemented. "
        "Planned: OpenAI messages → Gemini contents + systemInstruction conversion."
    )


# ---------------------------------------------------------------------------
# Tool call ID generation (Gemini doesn't include IDs)
# ---------------------------------------------------------------------------

def assign_tool_call_ids(response: dict) -> dict:
    """
    Assign synthetic IDs to Gemini tool_call items that lack them.

    STUB: raises NotImplementedError.
    Implementation plan: generate deterministic call_<uuid> IDs for each tool part.
    """
    raise NotImplementedError(
        "assign_tool_call_ids is not yet implemented. "
        "Planned: inject synthetic call_<uuid> for each function_call part."
    )


# ---------------------------------------------------------------------------
# Safety rating normalisation
# ---------------------------------------------------------------------------

def parse_safety_ratings(ratings: list[dict]) -> dict:
    """
    Parse Gemini safety ratings into a normalised dict.

    FUNCTIONAL.
    """
    result = {}
    for r in ratings:
        category = r.get("category", "UNKNOWN").replace("HARM_CATEGORY_", "").lower()
        result[category] = r.get("probability", "UNKNOWN")
    return result
