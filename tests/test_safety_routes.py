"""Tests for src/routes/safety.py.

Covers safety check, PII scan, prompt injection, action check,
domain guards, profiles, audit log, hallucination, watermarking,
copyright, and bias evaluation endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.routes.safety import _event_severity


# ── _event_severity ─────────────────────────────────────────────────────


def test_event_severity_block():
    assert _event_severity({"type": "block"}) == "high"


def test_event_severity_pii_scrub():
    assert _event_severity({"type": "pii_scrub"}) == "medium"


def test_event_severity_profile_change():
    assert _event_severity({"type": "profile_change"}) == "low"


def test_event_severity_unknown_type():
    assert _event_severity({"type": "info"}) == "none"


def test_event_severity_from_issues():
    event = {
        "type": "info",
        "verdict": {
            "issues": [
                {"severity": "low"},
                {"severity": "critical"},
            ]
        },
    }
    assert _event_severity(event) == "critical"


def test_event_severity_from_issues_uses_threat_fallback():
    event = {
        "verdict": {"issues": [{"threat": "high"}]},
    }
    assert _event_severity(event) == "high"


def test_event_severity_empty():
    assert _event_severity({}) == "none"


# ── Safety check ────────────────────────────────────────────────────────


def test_safety_check_missing_text(client):
    resp = client.post("/safety/check", json={})
    assert resp.status_code == 422


def test_safety_check_allowed(client):
    mock_verdict = MagicMock()
    mock_verdict.allowed = True
    mock_verdict.to_dict.return_value = {"allowed": True, "issues": []}
    mock_verdict.issues = []

    with patch("src.safety_pipeline.screen_input", return_value=mock_verdict):
        resp = client.post("/safety/check", json={"text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["allowed"] is True


def test_safety_check_blocked(client):
    mock_verdict = MagicMock()
    mock_verdict.allowed = False
    mock_verdict.to_dict.return_value = {
        "allowed": False,
        "issues": [{"code": "X", "reason": "bad", "detail": "nope", "threat": "high", "pattern": ""}],
    }
    mock_verdict.issues = [MagicMock()]

    with patch("src.safety_pipeline.screen_input", return_value=mock_verdict):
        resp = client.post("/safety/check", json={"text": "bad stuff"})
    assert resp.status_code == 200
    assert resp.json()["allowed"] is False


# ── PII scan ────────────────────────────────────────────────────────────


def test_pii_scan_missing_text(client):
    resp = client.post("/safety/pii-scan", json={})
    assert resp.status_code == 422


def test_pii_scan_detects_email(client):
    with patch("src.safety.scrub_pii", return_value={"redacted_text": "[REDACTED_EMAIL]@test.com"}):
        resp = client.post("/safety/pii-scan", json={"text": "my email is test@example.com"})
    assert resp.status_code == 200
    assert resp.json()["total_findings"] >= 1


def test_pii_scan_detects_token(client):
    fake_token = "ghp_" + "a" * 37
    with patch("src.safety.scrub_pii", return_value={"redacted_text": "[REDACTED]"}):
        resp = client.post("/safety/pii-scan", json={"text": f"token is {fake_token}"})
    assert resp.status_code == 200


def test_pii_scan_no_findings(client):
    with patch("src.safety.scrub_pii", return_value={"redacted_text": "clean text"}):
        resp = client.post("/safety/pii-scan", json={"text": "just clean text"})
    assert resp.status_code == 200
    assert resp.json()["total_findings"] == 0


# ── Prompt injection ────────────────────────────────────────────────────


def test_prompt_injection_missing_text(client):
    resp = client.post("/safety/prompt-injection", json={})
    assert resp.status_code == 422


def test_prompt_injection_not_detected(client):
    mock_verdict = MagicMock()
    mock_verdict.allowed = True
    mock_verdict.issues = []

    with patch("src.safety_pipeline.screen_input", return_value=mock_verdict):
        resp = client.post("/safety/prompt-injection", json={"text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["detected"] is False


def test_prompt_injection_detected(client):
    mock_issue = MagicMock()
    mock_issue.code = "prompt_injection"
    mock_issue.to_dict.return_value = {
        "code": "prompt_injection", "reason": "Inject!",
        "detail": "Attempt", "threat": "high", "pattern": "ignore_instructions",
    }

    mock_verdict = MagicMock()
    mock_verdict.allowed = False
    mock_verdict.issues = [mock_issue]

    with patch("src.safety_pipeline.screen_input", return_value=mock_verdict):
        resp = client.post("/safety/prompt-injection", json={"text": "ignore previous instructions"})
    assert resp.status_code == 200
    assert resp.json()["detected"] is True


# ── Action check ────────────────────────────────────────────────────────


def test_action_check_missing_kind(client):
    resp = client.post("/safety/action-check", json={})
    assert resp.status_code == 422


def test_action_check_allowed(client):
    mock_verdict = MagicMock()
    mock_verdict.allowed = True
    mock_verdict.issues = []

    with patch("src.safety_pipeline.screen_tool_action", return_value=mock_verdict):
        resp = client.post("/safety/action-check", json={"kind": "read_file", "parameters": {"path": "/tmp/test"}})
    assert resp.status_code == 200
    assert resp.json()["allowed"] is True


# ── Domain guards ───────────────────────────────────────────────────────


def test_domain_guards_get(client):
    resp = client.get("/safety/domain-guards")
    assert resp.status_code == 200
    assert "domain_guards" in resp.json()


# ── Profiles ────────────────────────────────────────────────────────────


def test_list_safety_profiles(client):
    resp = client.get("/safety/profiles")
    assert resp.status_code == 200
    assert "profiles" in resp.json()
    assert "active" in resp.json()


# ── Audit log ───────────────────────────────────────────────────────────


def test_get_audit_basic(client):
    resp = client.get("/safety/audit")
    assert resp.status_code == 200
    assert "events" in resp.json()


# ── Hallucination check ─────────────────────────────────────────────────


def test_hallucination_missing_response(client):
    resp = client.post("/safety/hallucination/check", json={})
    assert resp.status_code == 400


def test_hallucination_check(client):
    mock_result = MagicMock()
    mock_result.grounded = True
    mock_result.score = 0.95
    mock_result.method = "nli"
    mock_result.ungrounded_sentences = []
    mock_result.evidence_sentences = ["matched"]
    mock_result.details = {}

    with patch("src.safety.hallucination.check_grounding", return_value=mock_result):
        resp = client.post(
            "/safety/hallucination/check",
            json={"response": "Paris is the capital of France.", "context": "France has a capital city called Paris."},
        )
    assert resp.status_code == 200
    assert resp.json()["grounded"] is True


# ── Watermark ───────────────────────────────────────────────────────────


def test_watermark_embed_missing_text(client):
    resp = client.post("/safety/watermark/embed", json={})
    assert resp.status_code == 400


def test_watermark_embed(client):
    with patch("src.safety.watermark.watermark_text", return_value="watermarked text"):
        resp = client.post("/safety/watermark/embed", json={"text": "original text"})
    assert resp.status_code == 200
    assert resp.json()["watermarked_text"] == "watermarked text"


def test_watermark_detect_missing_text(client):
    resp = client.post("/safety/watermark/detect", json={})
    assert resp.status_code == 400


def test_watermark_detect(client):
    mock_detection = {"score": 0.8, "watermarked": True}
    with patch("src.safety.watermark.detect_watermark", return_value=mock_detection):
        resp = client.post("/safety/watermark/detect", json={"text": "suspect text"})
    assert resp.status_code == 200


# ── Copyright ───────────────────────────────────────────────────────────


def test_copyright_check_missing_text(client):
    resp = client.post("/safety/copyright/check", json={})
    assert resp.status_code == 400


def test_copyright_check(client):
    mock_result = MagicMock()
    mock_result.flagged = False
    mock_result.matches = []
    mock_result.notice_detected = False
    mock_result.notice_patterns = []
    mock_result.highest_similarity = 0.0

    with patch("src.safety.copyright.check_copyright", return_value=mock_result, create=True):
        resp = client.post("/safety/copyright/check", json={"text": "original content"})
    assert resp.status_code == 200
    assert resp.json()["flagged"] is False


# ── Bias evaluation ─────────────────────────────────────────────────────


def test_bias_evaluate_missing_text(client):
    resp = client.post("/safety/bias/evaluate", json={})
    assert resp.status_code == 400


def test_bias_evaluate(client):
    mock_report = MagicMock()
    mock_report.flagged = False
    mock_report.bias_score = 0.1
    mock_report.summary = "No significant bias"
    mock_report.stereotype_matches = []
    mock_report.gender_disparity = {}
    mock_report.race_sentiment_scores = {}
    mock_report.religion_sentiment_scores = {}
    mock_report.text_snippet = ""

    with patch("src.safety.bias_eval.evaluate_bias", return_value=mock_report):
        resp = client.post("/safety/bias/evaluate", json={"text": "neutral content"})
    assert resp.status_code == 200
    assert resp.json()["bias_score"] == 0.1
