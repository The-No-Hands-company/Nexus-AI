from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .safety_pipeline import find_pii_matches, screen_input, scrub_pii_text


@dataclass
class SafetyIssue:
    code: str
    reason: str
    detail: Optional[str] = None
    severity: str = "high"
    pattern: Optional[str] = None


@dataclass
class SafetyDecision:
    allowed: bool
    issues: List[SafetyIssue] = field(default_factory=list)
    masked_text: Optional[str] = None


@dataclass
class GuardrailViolation(Exception):
    reason: str
    code: str = "guardrail_violation"
    detail: Optional[str] = None

    def __str__(self) -> str:
        return self.reason


def scrub_pii(text: str) -> Dict[str, Any]:
    """Redact common PII patterns and return structured findings.

    Returns:
      {
        "redacted_text": "...",
        "findings": [{"type": "email", "count": 2}, ...],
        "total_findings": 3
      }
    """
    findings: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for match in find_pii_matches(text or ""):
        counts[match.pii_type] = counts.get(match.pii_type, 0) + 1
    for pii_type, count in counts.items():
        findings.append({"type": pii_type, "count": count})
    return {
        "redacted_text": scrub_pii_text(text or ""),
        "findings": findings,
        "total_findings": sum(f["count"] for f in findings),
    }


def check_text_against_guardrail(text: str, allow_destructive: bool = False, policy_profile: Optional[str] = None) -> SafetyDecision:
    verdict = screen_input(text, allow_destructive=allow_destructive, policy_profile=policy_profile)
    issues = [
        SafetyIssue(
            code=issue.code,
            reason=issue.reason,
            detail=issue.detail,
            severity=issue.threat.value,
            pattern=issue.pattern,
        )
        for issue in verdict.issues
    ]

    return SafetyDecision(
        allowed=verdict.allowed,
        issues=issues,
        masked_text=verdict.masked_text,
    )


def check_user_task(task: str, allow_destructive: bool = False, policy_profile: Optional[str] = None) -> str:
    decision = check_text_against_guardrail(task, allow_destructive=allow_destructive, policy_profile=policy_profile)
    if not decision.allowed and decision.issues:
        issue = decision.issues[0]
        raise GuardrailViolation(issue.reason, issue.code, issue.detail)
    return decision.masked_text or task
