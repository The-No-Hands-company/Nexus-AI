import re
from dataclasses import dataclass, field
from typing import List, Optional


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


SENSITIVE_PATTERNS: List[str] = [
    r"gh[ps]_[A-Za-z0-9_]{36,}",
    r"github_pat_[A-Za-z0-9_]{80,}",
    r"sk-[A-Za-z0-9\-_]{20,}",
    r"private\s+key",
    r"api\s+key",
    r"secret\s+key",
    r"password",
]

INJECTION_PATTERNS: List[str] = [
    r"ignore previous instructions",
    r"disregard previous instructions",
    r"ignore all previous prompts",
    r"do not follow the above",
    r"override.*system instructions",
    r"ignore.*system instructions",
    r"bypass.*safety",
    r"remove.*restrictions",
    r"try to.*escape",
    r"jailbreak",
    r"prompt injection",
]

DESTRUCTIVE_PATTERNS: List[str] = [
    r"rm\s+-rf",
    r"sudo\s+rm",
    r"format\s+c:",
    r"drop\s+table",
    r"delete\s+database",
    r"shutdown\b",
    r"poweroff\b",
    r"reboot\b",
    r"kill\s+-9",
    r"curl\s+.*\|\s*bash",
]


def _contains_pattern(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def mask_sensitive_tokens(text: str) -> str:
    pattern = re.compile(r"\b(?:gh[ps]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{80,}|sk-[A-Za-z0-9\-_]{20,})\b")
    return pattern.sub("[REDACTED]", text)


def check_text_against_guardrail(text: str, allow_destructive: bool = False) -> SafetyDecision:
    masked = mask_sensitive_tokens(text)
    issues: List[SafetyIssue] = []

    sensitive_match = _contains_pattern(masked, SENSITIVE_PATTERNS)
    if sensitive_match:
        issues.append(SafetyIssue(
            code="sensitive_content",
            reason="Sensitive content detected in the user request.",
            detail="Potential secret or token found in the task.",
            pattern=sensitive_match,
        ))

    injection_match = _contains_pattern(masked, INJECTION_PATTERNS)
    if injection_match:
        issues.append(SafetyIssue(
            code="prompt_injection",
            reason="Potential prompt injection detected.",
            detail="The task appears to attempt to override system or safety instructions.",
            pattern=injection_match,
        ))

    destructive_match = None
    if not allow_destructive:
        destructive_match = _contains_pattern(masked, DESTRUCTIVE_PATTERNS)
        if destructive_match:
            issues.append(SafetyIssue(
                code="destructive_command",
                reason="Destructive actions are blocked by guardrails.",
                detail="Commands that can delete files, databases, or system state are not allowed.",
                pattern=destructive_match,
            ))

    return SafetyDecision(
        allowed=len(issues) == 0,
        issues=issues,
        masked_text=masked,
    )


def check_user_task(task: str, allow_destructive: bool = False) -> str:
    decision = check_text_against_guardrail(task, allow_destructive=allow_destructive)
    if not decision.allowed and decision.issues:
        issue = decision.issues[0]
        raise GuardrailViolation(issue.reason, issue.code, issue.detail)
    return decision.masked_text or task
