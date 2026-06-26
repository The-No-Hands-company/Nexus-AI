"""Tests for the token optimizer module: response quality, vague prompts, truncation detection."""

from __future__ import annotations

from src.token_optimizer import (
    is_response_truncated,
    estimate_response_quality,
    is_vague_prompt,
    get_vague_prompt_clarification,
    optimize_response,
    recommend_response_tokens,
    estimate_task_tokens,
)


# ── Response truncation tests ─────────────────────────────────────────────────

def test_truncation_empty_string():
    assert is_response_truncated("") is True
    assert is_response_truncated("  ") is True


def test_truncation_too_short():
    assert is_response_truncated("ab") is True


def test_truncation_valid_response():
    assert is_response_truncated("This is a complete response with proper length.") is False


def test_truncation_ellipsis():
    assert is_response_truncated("The answer to that is...") is True
    assert is_response_truncated("Wait I need to think about this…") is True


def test_truncation_unclosed_code_block():
    assert is_response_truncated("Here is some code:\n```python\nprint(hello") is True
    assert is_response_truncated("```") is True


def test_truncation_complete_code_block():
    response = "Here is some code:\n```python\nprint('hello')\n```\nThat's it!"
    assert is_response_truncated(response) is False


def test_truncation_dangling_conjunction():
    assert is_response_truncated("The key features are speed, reliability, and") is True
    assert is_response_truncated("You could use Redis or") is True


# ── Response quality tests ────────────────────────────────────────────────────

def test_quality_empty_response():
    assert estimate_response_quality("") == 0.0


def test_quality_good_response():
    response = (
        "# Project Overview\n\n"
        "This is a well-structured response with headings and lists.\n\n"
        "- Feature one\n"
        "- Feature two\n\n"
        "The project is designed for reliability and speed. "
        "It uses modern architecture patterns and follows best practices."
    )
    score = estimate_response_quality(response)
    assert score > 0.5


def test_quality_truncated_penalty():
    response = "The answer is..."
    score = estimate_response_quality(response)
    assert score <= 0.2


def test_quality_short_response():
    score = estimate_response_quality("OK.")
    assert score < 0.5


# ── Vague prompt detection tests ──────────────────────────────────────────────

def test_vague_greeting():
    assert is_vague_prompt("hi") == "greeting"
    assert is_vague_prompt("hello") == "greeting"
    assert is_vague_prompt("  hey  ") == "greeting"


def test_vague_help():
    assert is_vague_prompt("help") == "help_request"
    assert is_vague_prompt("help me") == "help_request"


def test_vague_continue():
    assert is_vague_prompt("continue") == "continue"
    assert is_vague_prompt("go on") == "continue"


def test_vague_affirmation():
    assert is_vague_prompt("yes") == "affirmation"
    assert is_vague_prompt("yeah") == "affirmation"


def test_vague_negation():
    assert is_vague_prompt("no") == "negation"


def test_vague_short_prompt():
    assert is_vague_prompt("hmm") == "short_prompt"


def test_vague_open_ended():
    assert is_vague_prompt("what should i do") is not None
    assert is_vague_prompt("how do i build something") is not None


def test_specific_prompt_not_vague():
    assert is_vague_prompt("Write a Python script that reads a CSV file and plots a bar chart of sales data") is None
    assert is_vague_prompt("Fix the bug in src/auth.py where users can bypass login by sending empty tokens") is None
    assert is_vague_prompt("Refactor the payment processing module to use async/await patterns") is None


# ── Clarification generation tests ────────────────────────────────────────────

def test_clarification_greeting():
    result = get_vague_prompt_clarification("greeting", "hi")
    assert result is not None
    assert "hello" in result.lower()


def test_clarification_help():
    result = get_vague_prompt_clarification("help_request", "help")
    assert result is not None
    assert "help" in result.lower()


def test_clarification_unknown_category():
    result = get_vague_prompt_clarification("nonexistent", "test")
    assert result is None


# ── Response optimization tests ───────────────────────────────────────────────

def test_optimize_empty_response():
    result = optimize_response("")
    assert "rephrase" in result.lower()


def test_optimize_good_response():
    good = "This is a complete, well-formed response. It has proper structure and length."
    result = optimize_response(good)
    assert result == good


def test_optimize_long_response_truncates():
    long_response = "Sentence one. Sentence two. Sentence three. " * 200
    result = optimize_response(long_response, max_chars=200)
    assert len(result) <= 250  # Allow some room for truncation note


def test_optimize_truncated_response():
    result = optimize_response("The answer is...", max_chars=100)
    # Should keep the content but note potential issue
    assert "The answer is..." in result


# ── Token estimation tests ────────────────────────────────────────────────────

def test_estimate_task_tokens():
    assert estimate_task_tokens("hello") > 0
    assert estimate_task_tokens("a" * 100) > estimate_task_tokens("a")


def test_recommend_response_tokens_minimal():
    tokens = recommend_response_tokens(100, "minimal")
    assert tokens <= 512


def test_recommend_response_tokens_detailed():
    tokens = recommend_response_tokens(500, "detailed")
    assert tokens >= 1024
    assert tokens <= 4096
