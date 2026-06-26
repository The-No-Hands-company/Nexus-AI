"""Tests for token optimization features: history compression, system prompt, memory context."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.agent import (
    _maybe_compress_history,
    _messages_token_estimate,
    get_system_prompt,
    _estimate_tokens,
)


# ── Token estimation tests ────────────────────────────────────────────────────

def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 1


def test_estimate_tokens_short():
    tokens = _estimate_tokens("hello world")
    assert tokens > 0


def test_estimate_tokens_longer():
    text = "A longer piece of text that should produce more tokens than a short one."
    tokens = _estimate_tokens(text)
    assert tokens > 0


def test_messages_token_estimate_empty():
    assert _messages_token_estimate([]) == 0


def test_messages_token_estimate_with_content():
    msgs = [{"role": "user", "content": "Hello, how are you?"}]
    tokens = _messages_token_estimate(msgs)
    assert tokens > 0


def test_messages_token_estimate_with_vision():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "Describe this"}]}]
    tokens = _messages_token_estimate(msgs)
    assert tokens > 0


def test_messages_token_estimate_multiple():
    msgs = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
    ]
    tokens = _messages_token_estimate(msgs)
    assert tokens > 0


# ── Token-aware history compression tests ─────────────────────────────────────

def test_compress_history_under_limit():
    """Short history should not be compressed."""
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = _maybe_compress_history(history)
    assert len(result) == 2


def test_compress_history_long_triggers_compression():
    """Long history should trigger token-aware compression."""
    history = []
    for i in range(60):
        history.append({"role": "user", "content": f"Message {i} with some filler text to use tokens. " * 10})
        history.append({"role": "assistant", "content": f"Response {i} with more filler text to consume tokens. " * 10})

    # Mock the LLM compression path to fail so we test the token-aware fallback
    with patch("src.agent.CONTEXT_WINDOW.compress_history_with_llm", side_effect=Exception("mock fail")):
        result = _maybe_compress_history(history)

    # Should return fewer messages than the original
    assert len(result) < len(history)
    # Should include at least some messages
    assert len(result) > 0


def test_compress_history_adds_omission_note():
    """When messages are omitted, an omission note should be added."""
    history = []
    for i in range(60):
        history.append({"role": "user", "content": f"Long message number {i} with padding. " * 15})

    with patch("src.agent.CONTEXT_WINDOW.compress_history_with_llm", side_effect=Exception("mock fail")):
        result = _maybe_compress_history(history)

    if len(result) < len(history):
        # First message should be the omission note
        assert any("omitted" in str(m.get("content", "")).lower() for m in result), \
            f"Expected omission note in: {[m.get('content', '')[:80] for m in result]}"


# ── System prompt tests ───────────────────────────────────────────────────────

def test_get_system_prompt_default():
    prompt = get_system_prompt()
    assert "Nexus AI" in prompt or "Nexus" in prompt
    assert len(prompt) > 0


def test_get_system_prompt_minimal():
    prompt = get_system_prompt(context="minimal")
    assert len(prompt) > 0
    # Minimal should be shorter than standard
    standard = get_system_prompt(context="standard")
    assert len(prompt) < len(standard)


def test_get_system_prompt_standard():
    prompt = get_system_prompt(context="standard")
    assert len(prompt) > 0
    assert "Nexus" in prompt or "Nexus AI" in prompt


def test_get_system_prompt_detailed():
    prompt = get_system_prompt(context="detailed")
    assert len(prompt) > 0
    # Detailed should include standard content plus more
    standard = get_system_prompt(context="standard")
    assert len(prompt) >= len(standard)


def test_get_system_prompt_invalid_context_falls_back():
    """Invalid context should fall back to standard."""
    prompt = get_system_prompt(context="nonexistent")
    standard = get_system_prompt(context="standard")
    assert len(prompt) == len(standard)
