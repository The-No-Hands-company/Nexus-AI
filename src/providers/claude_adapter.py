"""
src/providers/claude_adapter.py — Anthropic Claude provider adapter stub

Handles Claude-specific message format:
- tool_use / tool_result content block conversion to/from OpenAI format
- Thinking block extraction (extended thinking / budget_tokens)
- System prompt formatting (only one system message allowed)
- Vision content block formatting (base64 or url)

This module is a STUB — most functions raise NotImplementedError.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Request formatting
# ---------------------------------------------------------------------------

def format_claude_request(payload: dict) -> dict:
    """
    Convert an OpenAI-style request payload to Anthropic Messages API format.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Extract system message(s) → top-level ``system`` field
    - Convert ``tool_calls`` in assistant messages → tool_use content blocks
    - Convert ``tool`` role messages → tool_result content blocks
    - Convert vision content (url/base64) → Anthropic image source format
    - Add ``betas`` for extended thinking if requested
    """
    raise NotImplementedError(
        "format_claude_request is not yet implemented. "
        "Planned: full OpenAI → Anthropic Messages API format conversion."
    )


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def normalise_claude_response(raw: dict) -> dict:
    """
    Normalise a Claude Messages API response to OpenAI-compatible format.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Map content blocks → choices[0].message
    - tool_use blocks → tool_calls with id, type, function
    - thinking blocks → message.thinking (Nexus convention)
    - Map stop_reason → finish_reason (end_turn → stop, max_tokens → length)
    - Map usage (input_tokens, output_tokens) → prompt_tokens, completion_tokens
    """
    raise NotImplementedError(
        "normalise_claude_response is not yet implemented. "
        "Planned: full Anthropic response → OpenAI-compat mapping."
    )


# ---------------------------------------------------------------------------
# Thinking block extraction
# ---------------------------------------------------------------------------

def extract_thinking(raw: dict) -> str | None:
    """
    Extract Claude's extended thinking text from a raw response.

    FUNCTIONAL: basic content block traversal.
    """
    content = raw.get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            return block.get("thinking", "")
    return None


# ---------------------------------------------------------------------------
# Tool result formatting
# ---------------------------------------------------------------------------

def format_tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    """
    Build a Claude tool_result content block.

    FUNCTIONAL.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }
