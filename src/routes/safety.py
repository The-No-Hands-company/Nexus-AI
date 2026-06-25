"""Safety & moderation routes.

Extracted from src/api/routes.py for maintainability.
Covers: input guardrail checks, PII scanning, prompt injection detection,
action checks, domain guards, safety profiles, audit log, hallucination,
watermarking, copyright, and bias evaluation.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/safety", tags=["safety"])

from ._helpers import (
    _api_error,
    _read_json_body,
    require_admin,
)
from ..agent import (
    _config,
    _push_safety_event,
    safety_log,
)


# ── Safety pipeline helpers ─────────────────────────────────────────────

_SEVERITY_ORDER = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _event_severity(event: dict) -> str:
    verdict = event.get("verdict") or {}
    issue_levels = []
    for issue in verdict.get("issues", []) or []:
        level = str(issue.get("severity") or issue.get("threat") or "").lower().strip()
        if level in _SEVERITY_ORDER:
            issue_levels.append(level)

    if issue_levels:
        return max(issue_levels, key=lambda lvl: _SEVERITY_ORDER.get(lvl, 0))

    event_type = str(event.get("type") or "")
    if event_type == "block":
        return "high"
    if event_type == "pii_scrub":
        return "medium"
    if event_type == "profile_change":
        return "low"
    return "none"


# ── Input guardrail ─────────────────────────────────────────────────────

@router.post("/check")
async def safety_check(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "").strip()
    if not text:
        return _api_error("text is required", "validation_error", 422)
    allow_destructive = bool(data.get("allow_destructive", False))
    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard") or "standard")
    from ..safety_pipeline import screen_input, get_safety_policy
    verdict = screen_input(text, allow_destructive=allow_destructive, policy_profile=profile)
    payload = verdict.to_dict()
    payload["policy_profile"] = profile
    payload["policy"] = get_safety_policy(profile)
    payload["issues"] = [
        {
            "code": issue["code"],
            "reason": issue["reason"],
            "detail": issue["detail"],
            "severity": issue["threat"],
            "pattern": issue["pattern"],
        }
        for issue in payload["issues"]
    ]
    if not verdict.allowed:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "input_guardrail",
            "label": text[:120],
            "profile": profile,
            "verdict": payload,
        })
    elif payload.get("pii_matches"):
        _push_safety_event("pii_scrub", {
            "scope": "input",
            "profile": profile,
            "count": len(payload.get("pii_matches") or []),
            "label": text[:120],
            "findings": payload.get("pii_matches") or [],
        })
    return payload


@router.post("/pii-scan")
async def pii_scan(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "")
    if not text.strip():
        return _api_error("text is required", "validation_error", 422)

    email_re = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    token_re = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)\b")
    phone_re = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

    findings = []
    for match in email_re.finditer(text):
        findings.append(
            {
                "type": "email",
                "match": match.group(0),
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in token_re.finditer(text):
        findings.append(
            {
                "type": "token",
                "match": "[REDACTED]",
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in phone_re.finditer(text):
        findings.append(
            {
                "type": "phone",
                "match": "[REDACTED]",
                "start": match.start(),
                "end": match.end(),
            }
        )

    from ..safety import scrub_pii
    redacted = email_re.sub("[REDACTED_EMAIL]", text)
    redacted = phone_re.sub("[REDACTED_PHONE]", redacted)
    redacted = scrub_pii(redacted)["redacted_text"]
    result = {
        "text": text,
        "redacted_text": redacted,
        "findings": findings,
        "total_findings": len(findings),
    }
    if result.get("total_findings", 0) > 0:
        _push_safety_event("pii_scrub", {
            "scope": "scan",
            "count": result.get("total_findings", 0),
            "label": text[:120],
            "findings": result.get("findings") or [],
        })
    return result


@router.post("/prompt-injection")
async def prompt_injection_scan(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    text = (data.get("text") or "")
    if not text.strip():
        return _api_error("text is required", "validation_error", 422)

    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard") or "standard")
    explain_mode = bool(data.get("explain", False))
    from ..safety_pipeline import screen_input, get_safety_policy, explain_prompt_injection
    verdict = screen_input(text, allow_destructive=False, policy_profile=profile)
    prompt_issues = [issue.to_dict() for issue in verdict.issues if issue.code == "prompt_injection"]
    patterns = [issue.get("pattern") for issue in prompt_issues if issue.get("pattern")]
    detected = bool(prompt_issues)

    payload = {
        "detected": detected,
        "stage": "input",
        "policy_profile": profile,
        "policy": get_safety_policy(profile),
        "action": "block" if detected else "allow",
        "threat": (prompt_issues[0].get("threat") if prompt_issues else "none"),
        "issues": [
            {
                "code": issue.get("code", "prompt_injection"),
                "reason": issue.get("reason", issue.get("message", "Prompt injection detected")),
                "detail": issue.get("detail", issue.get("message", "Prompt injection detected")),
                "severity": issue.get("threat", issue.get("severity", "high")),
                "pattern": issue.get("pattern"),
            }
            for issue in prompt_issues
        ],
        "matches": patterns,
        "explain_mode": explain_mode,
    }

    if explain_mode:
        payload["explain"] = explain_prompt_injection(text)

    if detected:
        _push_safety_event("block", {
            "scope": "prompt_injection_scan",
            "tool": "prompt_injection_scan",
            "label": text[:120],
            "profile": profile,
            "verdict": payload,
        })

    return payload


@router.post("/prompt-injection/benchmark")
async def prompt_injection_benchmark(request: Request):
    from ..safety.prompt_injection import benchmark_injection_detection

    data = await _read_json_body(request, "invalid JSON body")
    corpus_in = data.get("corpus") if isinstance(data.get("corpus"), list) else []
    corpus = tuple(str(item or "").strip() for item in corpus_in if str(item or "").strip())
    result = benchmark_injection_detection(corpus=corpus if corpus else None)
    return {
        "benchmark": result,
        "release_gate_pass": bool(float(result.get("coverage") or 0.0) >= 0.9),
        "threshold": 0.9,
    }


@router.post("/action-check")
async def safety_action_check(request: Request):
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    action_kind = str(data.get("kind") or "").strip()
    parameters = data.get("parameters") or {}
    profile = str(data.get("policy_profile") or _config.get("safety_profile", "standard"))
    if not action_kind:
        return _api_error("kind is required", "validation_error", 422)
    try:
        from ..safety_pipeline import screen_tool_action
        action_payload = {"kind": action_kind, **parameters}
        verdict = screen_tool_action(action_payload, policy_profile=profile)
        return {
            "action": action_kind,
            "allowed": verdict.allowed,
            "policy_profile": profile,
            "issues": [i.to_dict() for i in verdict.issues],
            "threat": (verdict.issues[0].threat if verdict.issues else "none"),
        }
    except Exception as exc:
        return _api_error(str(exc), "server_error", 500)


@router.get("/domain-guards")
def safety_domain_guards_get():
    rules = _config.get("domain_guards") or {
        "blocked_domains": [],
        "allowed_categories": ["informational", "productivity"],
        "block_adult": True,
        "block_malware": True,
    }
    return {"domain_guards": rules}


# ── Profiles ────────────────────────────────────────────────────────────

@router.get("/profiles")
def list_safety_profiles():
    from ..safety_pipeline import SAFETY_POLICY_PROFILES, get_safety_policy
    return {
        "active": _config.get("safety_profile", "standard"),
        "profiles": {
            name: get_safety_policy(name)
            for name in sorted(SAFETY_POLICY_PROFILES.keys())
        },
    }


# ── Audit log ───────────────────────────────────────────────────────────

@router.get("/audit")
def get_safety_audit(
    limit: int = 200,
    session_id: str = "",
    event_type: str = "",
    severity: str = "",
):
    limit = max(1, min(limit, 1000))
    session_id = (session_id or "").strip()
    event_type = (event_type or "").strip()
    severity = (severity or "").strip().lower()
    if severity and severity not in _SEVERITY_ORDER:
        allowed = ", ".join(_SEVERITY_ORDER.keys())
        return _api_error(f"severity must be one of: {allowed}", "validation_error", 422)

    from ..db import load_safety_audit_entries as db_load_safety_audit_entries
    try:
        db_entries = db_load_safety_audit_entries(limit=5000, session_id=session_id, event_type=event_type)
    except Exception:
        db_entries = []

    newest_db_ts = db_entries[-1].get("ts", 0.0) if db_entries else 0.0
    fresh_in_memory = [
        ev for ev in safety_log
        if float(ev.get("ts", 0)) > newest_db_ts
        and (not session_id or str(ev.get("session") or ev.get("session_id") or "") == session_id)
        and (not event_type or ev.get("type") == event_type)
    ]
    filtered: list = db_entries + fresh_in_memory

    events_with_severity = []
    for event in filtered:
        level = _event_severity(event)
        entry = dict(event)
        entry["severity"] = level
        events_with_severity.append(entry)

    if severity:
        threshold = _SEVERITY_ORDER[severity]
        events_with_severity = [
            event for event in events_with_severity
            if _SEVERITY_ORDER.get(event.get("severity", "none"), 0) >= threshold
        ]

    events = events_with_severity[-limit:]
    from ..db import verify_safety_audit_entries
    integrity = {"ok": None, "checked": 0, "broken_at": None, "head_hash": None}
    if not (session_id or event_type or severity):
        integrity = verify_safety_audit_entries(limit=5000)
    return {
        "events": events,
        "total": len(events_with_severity),
        "session_id": session_id or None,
        "event_type": event_type or None,
        "severity": severity or None,
        "filtered": bool(session_id or event_type or severity),
        "integrity": integrity,
    }


# ── Hallucination detection ─────────────────────────────────────────────

@router.post("/hallucination/check")
async def api_hallucination_check(request: Request):
    body = await request.json()
    response_text = str(body.get("response", ""))
    context = str(body.get("context", ""))
    if not response_text:
        return _api_error("response is required", status_code=400)
    try:
        from ..safety.hallucination import check_grounding
        result = check_grounding(response_text, context)
        return {
            "grounded": result.grounded, "score": result.score, "method": result.method,
            "ungrounded_sentences": result.ungrounded_sentences,
            "evidence_sentences": result.evidence_sentences, "details": result.details,
        }
    except Exception as exc:
        return _api_error(str(exc))


# ── Watermarking ────────────────────────────────────────────────────────

@router.post("/watermark/embed")
async def api_watermark_embed(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    session_id = str(body.get("session_id", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.watermark import watermark_text
        marked = watermark_text(text, session_id=session_id)
        return {"watermarked_text": marked, "session_id": session_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/watermark/detect")
async def api_watermark_detect(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    session_id = str(body.get("session_id", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.watermark import detect_watermark, verify_watermark
        detection = detect_watermark(text)
        if session_id:
            verification = verify_watermark(text, session_id)
            detection["verification"] = verification
        return detection
    except Exception as exc:
        return _api_error(str(exc))


# ── Copyright ───────────────────────────────────────────────────────────

@router.post("/copyright/check")
async def api_copyright_check(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.copyright import check_copyright
        result = check_copyright(text)
        return {
            "flagged": result.flagged, "matches": result.matches,
            "notice_detected": result.notice_detected,
            "notice_patterns": result.notice_patterns,
            "highest_similarity": result.highest_similarity,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/copyright/register")
async def api_copyright_register(request: Request):
    require_admin(request)
    body = await request.json()
    work_id = str(body.get("work_id", "")).strip()
    title = str(body.get("title", "")).strip()
    text = str(body.get("text", "")).strip()
    if not all([work_id, title, text]):
        return _api_error("work_id, title, and text are required", status_code=400)
    try:
        from ..safety.copyright import register_protected_work
        register_protected_work(work_id, title, text, metadata=body.get("metadata", {}))
        return {"registered": True, "work_id": work_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/copyright/works")
async def api_copyright_works(request: Request):
    require_admin(request)
    try:
        from ..safety.copyright import list_protected_works
        return {"works": list_protected_works()}
    except Exception as exc:
        return _api_error(str(exc))


# ── Bias evaluation ─────────────────────────────────────────────────────

@router.post("/bias/evaluate")
async def api_bias_evaluate(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    if not text:
        return _api_error("text is required", status_code=400)
    try:
        from ..safety.bias_eval import evaluate_bias
        report = evaluate_bias(text)
        return {
            "flagged": report.flagged, "bias_score": report.bias_score,
            "summary": report.summary,
            "stereotype_matches": report.stereotype_matches,
            "gender_disparity": report.gender_disparity,
            "race_sentiment_scores": report.race_sentiment_scores,
            "religion_sentiment_scores": report.religion_sentiment_scores,
            "text_snippet": report.text_snippet,
        }
    except Exception as exc:
        return _api_error(str(exc))
