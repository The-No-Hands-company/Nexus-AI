"""Tests for src/routes/reasoning.py.

Covers citation scoring, adaptive routing, and endpoint validation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.routes.reasoning import (
    _adaptive_routing_config,
    _call_llm_adaptive,
    _extract_citation_urls,
    _score_citation_confidence,
)


# ── _extract_citation_urls ─────────────────────────────────────────────────


def test_extract_markdown_links():
    text = "See [example](https://example.com) and [docs](https://docs.example.org/page)."
    assert _extract_citation_urls(text) == [
        "https://example.com",
        "https://docs.example.org/page",
    ]


def test_extract_bare_urls():
    text = "Source: https://example.com/paper Result: ok"
    assert _extract_citation_urls(text) == ["https://example.com/paper"]


def test_extract_mixed_urls():
    text = (
        "According to [source](https://example.com) "
        "and https://raw.org/data the answer is clear."
    )
    urls = _extract_citation_urls(text)
    assert "https://example.com" in urls
    assert "https://raw.org/data" in urls


def test_extract_empty_text():
    assert _extract_citation_urls("") == []
    assert _extract_citation_urls(None) == []


def test_extract_no_urls():
    assert _extract_citation_urls("Just plain text without any links.") == []


def test_extract_deduplicates():
    text = "See [here](https://example.com) and also https://example.com"
    assert _extract_citation_urls(text) == ["https://example.com"]


def test_extract_urls_with_parentheses():
    text = "See [example](https://en.wikipedia.org/wiki/Test_(disambiguation))."
    urls = _extract_citation_urls(text)
    assert len(urls) == 1
    assert "wikipedia.org" in urls[0]


def test_extract_urls_handles_trailing_punctuation():
    text = "Source: https://example.com/page more at https://other.org"
    urls = _extract_citation_urls(text)
    assert "https://example.com/page" in urls
    assert "https://other.org" in urls


# ── _score_citation_confidence ──────────────────────────────────────────────


def test_score_no_citations_no_expected():
    result = _score_citation_confidence("Just text.", expected_sources=[])
    assert result["score"] == 0.25
    assert result["citations"] == []
    assert result["expected_source_coverage"] == 0.0


def test_score_no_citations_with_expected():
    result = _score_citation_confidence(
        "Just text.", expected_sources=["https://example.com"]
    )
    assert result["score"] == 0.1
    assert result["citations"] == []
    assert result["expected_source_coverage"] == 0.0


def test_score_citations_no_expected():
    text = "See [source](https://example.com) and [another](https://other.org)"
    result = _score_citation_confidence(text, expected_sources=[])
    assert 0.35 <= result["score"] <= 0.9
    assert len(result["citations"]) == 2
    assert result["expected_source_coverage"] is None


def test_score_partial_coverage():
    text = "Per [source](https://example.com) the answer is clear."
    result = _score_citation_confidence(
        text,
        expected_sources=["https://example.com", "https://unreferenced.org"],
    )
    assert result["expected_source_coverage"] == 0.5
    assert "example.com" in result["matched_expected_sources"]


def test_score_full_coverage():
    text = (
        "According to [A](https://alpha.dev) and [B](https://beta.dev) "
        "the results are conclusive."
    )
    result = _score_citation_confidence(
        text,
        expected_sources=["https://alpha.dev", "https://beta.dev"],
    )
    assert result["expected_source_coverage"] == 1.0
    assert len(result["matched_expected_sources"]) == 2


def test_score_domain_overlap():
    text = "See [docs](https://docs.example.com/page)"
    result = _score_citation_confidence(
        text,
        expected_sources=["https://example.com"],
    )
    assert result["expected_source_coverage"] >= 0.5


def test_score_confidence_clamped_max():
    text = "See [a](https://a.dev) [b](https://b.dev)"
    for _ in range(10):
        result = _score_citation_confidence(text, expected_sources=["https://a.dev"])
        assert result["score"] <= 1.0


# ── _call_llm_adaptive ──────────────────────────────────────────────────────


def test_adaptive_returns_initial_result_if_high_confidence():
    mock_llm = MagicMock(return_value=({"content": '{"confidence": 0.9}'}, "openai"))
    with patch("src.routes.reasoning.call_llm_with_fallback", mock_llm):
        result, provider, escalated, confidence = _call_llm_adaptive(
            [{"role": "user", "content": "test"}]
        )
    assert result["content"] == '{"confidence": 0.9}'
    assert provider == "openai"
    assert escalated is False
    assert confidence == 0.9


def test_adaptive_returns_initial_if_disabled():
    _adaptive_routing_config["enabled"] = False
    mock_llm = MagicMock(return_value=({"content": "low confidence text"}, "openai"))
    with patch("src.routes.reasoning.call_llm_with_fallback", mock_llm):
        result, provider, escalated, confidence = _call_llm_adaptive(
            [{"role": "user", "content": "test"}]
        )
    assert escalated is False
    _adaptive_routing_config["enabled"] = True


def test_adaptive_defaults_unique_provider_fallback():
    _adaptive_routing_config["confidence_threshold"] = 0.9
    _adaptive_routing_config["escalation_tries"] = 1

    call_count = [0]

    def _side_effect(messages, task=""):
        call_count[0] += 1
        if call_count[0] == 1:
            return ({"content": '{"confidence": 0.3}'}, "openai")
        return ({"content": '{"confidence": 0.95}'}, "claude")

    with patch("src.routes.reasoning.call_llm_with_fallback", _side_effect):
        result, provider, escalated, confidence = _call_llm_adaptive(
            [{"role": "user", "content": "test"}]
        )
    assert escalated is True
    assert call_count[0] == 2
    _adaptive_routing_config["confidence_threshold"] = 0.6


def test_adaptive_escalation_tries_zero_skips():
    _adaptive_routing_config["escalation_tries"] = 0

    mock_llm = MagicMock(return_value=({"content": '{"confidence": 0.3}'}, "openai"))
    with patch("src.routes.reasoning.call_llm_with_fallback", mock_llm):
        result, provider, escalated, _confidence = _call_llm_adaptive(
            [{"role": "user", "content": "test"}]
        )
    assert escalated is False
    _adaptive_routing_config["escalation_tries"] = 2


def test_adaptive_malformed_json_treated_as_high_confidence():
    mock_llm = MagicMock(return_value=({"content": "plain text response"}, "openai"))
    with patch("src.routes.reasoning.call_llm_with_fallback", mock_llm):
        _result, _provider, escalated, confidence = _call_llm_adaptive(
            [{"role": "user", "content": "test"}]
        )
    assert escalated is False
    assert confidence == 1.0


# ── Adaptive routing config ─────────────────────────────────────────────────


def test_adaptive_routing_config_defaults():
    from src.routes.reasoning import _ADAPTIVE_ROUTING_DEFAULTS

    assert _ADAPTIVE_ROUTING_DEFAULTS["enabled"] is True
    assert _ADAPTIVE_ROUTING_DEFAULTS["confidence_threshold"] == 0.6
    assert _ADAPTIVE_ROUTING_DEFAULTS["escalation_tries"] == 2


def test_get_adaptive_routing_returns_current():
    from src.routes.reasoning import get_adaptive_routing

    result = get_adaptive_routing()
    assert "enabled" in result
    assert "confidence_threshold" in result
    assert "escalation_tries" in result


def test_adaptive_routing_threshold_clamping():
    assert 0.0 <= _adaptive_routing_config.get("confidence_threshold", 0.6) <= 1.0
