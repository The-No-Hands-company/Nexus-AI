from __future__ import annotations

import re

from ..safety_types import SafetyAction, SafetyDecision, SafetyIssue


_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)\b")


class GuardrailViolation(RuntimeError):
    def __init__(self, message: str, code: str = "guardrail_violation") -> None:
        self.code = code
        super().__init__(message)

    @property
    def reason(self) -> str:
        return str(self.args[0]) if self.args else ""

    @property
    def detail(self) -> str:
        return self.code
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def _scrub_text_str(text: str) -> str:
    """Return redacted text as a plain string (internal use)."""
    text = _TOKEN_RE.sub("[REDACTED]", text or "")
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    return text


def scrub_pii(text: str) -> str:
    """Scan text for PII and return a structured result dict.

    Also callable as a plain string redactor via scrub_pii(text)["redacted_text"].
    """
    raw = text or ""
    findings = []
    for m in _EMAIL_RE.finditer(raw):
        findings.append({"type": "email", "match": m.group(0), "start": m.start(), "end": m.end()})
    for m in _TOKEN_RE.finditer(raw):
        findings.append({"type": "token", "match": "[REDACTED]", "start": m.start(), "end": m.end()})
    for m in _CARD_RE.finditer(raw):
        findings.append({"type": "card", "match": "[REDACTED]", "start": m.start(), "end": m.end()})
    redacted = _scrub_text_str(raw)
    return {"redacted_text": redacted, "findings": findings, "total_findings": len(findings)}  # type: ignore[return-value]


def check_text_against_guardrail(text: str, allow_destructive: bool = False, policy_profile: str = "standard") -> SafetyDecision:
    issues: list[SafetyIssue] = []
    masked = _scrub_text_str(text)
    lower = (text or "").lower()
    if lower != (masked or "").lower():
        issues.append(SafetyIssue(code="secret_token", message="Sensitive token detected", severity="high"))
    injection_terms = (
        "ignore previous instructions",
        "leak all data",
        "reveal hidden policies",
        "developer mode",
        "system prompt",
        "jailbreak",
        "remove restrictions",
        "bypass safeguards",
    )
    matched_injection = next((term for term in injection_terms if term in lower), None)
    if matched_injection:
        issues.append(
            SafetyIssue(
                code="prompt_injection",
                message="Prompt injection pattern detected",
                severity="high",
                pattern=matched_injection,
            )
        )
    if not allow_destructive and any(term in lower for term in ("rm -rf", "delete all files", "purge the database", "drop table")):
        issues.append(SafetyIssue(code="destructive_command", message="Destructive command detected", severity="high"))
    if issues:
        block_codes = {"prompt_injection", "destructive_command"}
        allowed = all(issue.code not in block_codes for issue in issues)
        action = SafetyAction.REDACT if allowed and masked != text else SafetyAction.BLOCK
        if allowed:
            action = SafetyAction.REDACT if masked != text else SafetyAction.ALLOW
        return SafetyDecision(allowed=allowed, action=action, stage="input", issues=issues, masked_text=masked if masked != text else None)
    return SafetyDecision(allowed=True, action=SafetyAction.ALLOW, stage="input", issues=[], masked_text=masked if masked != text else None)


def check_user_task(task: str, policy_profile: str = "standard") -> str:
    decision = check_text_against_guardrail(task, allow_destructive=policy_profile == "sandbox", policy_profile=policy_profile)
    blocked_codes = {issue.code for issue in decision.issues if issue.code in {"prompt_injection", "destructive_command"}}
    if blocked_codes and policy_profile != "sandbox":
        # Prioritize prompt_injection over destructive_command for user-facing error code
        if "prompt_injection" in blocked_codes:
            raise GuardrailViolation("Potential prompt injection detected.", code="prompt_injection")
        raise GuardrailViolation("Destructive command detected.", code="destructive_command")
    return task