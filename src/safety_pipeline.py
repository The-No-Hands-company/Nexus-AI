import os
import re
from typing import Any, Dict, List, Optional

from .safety_types import (
    ContentCategory,
    PIIMatch,
    SafetyAction,
    SafetySignal,
    SafetyVerdict,
    ThreatLevel,
)


SECRET_TOKEN_RE = re.compile(r"\b(?:gh[ps]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{80,}|sk-[A-Za-z0-9\-_]{20,})\b")

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

PII_PATTERNS: Dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone": r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]*?){13,19}\b",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}

HIGH_STAKES_PATTERNS: List[str] = [
    r"prescribe\s+medication",
    r"medical\s+dosage",
    r"diagnose\s+(?:a\s+)?(?:patient|person|condition)",
    r"legal\s+defen[cs]e\s+strategy",
    r"identify\s+(?:the\s+)?person\s+from\s+(?:a\s+)?photo",
    r"bypass\s+multi[- ]factor\s+authentication",
    r"credential\s+stuffing",
    r"exfiltrat(?:e|ing)\s+(?:secrets|credentials|tokens|data)",
    r"deploy\s+ransomware",
    r"weapon(?:ize|ized)?\s+(?:a\s+)?drone",
]

DEFAULT_POLICY_PROFILE = os.getenv("SAFETY_POLICY_PROFILE", "standard").strip().lower() or "standard"

SAFETY_POLICY_PROFILES: Dict[str, Dict[str, bool]] = {
    "standard": {
        "allow_destructive_input": False,
        "allow_destructive_tools": False,
        "deny_high_stakes": True,
    },
    "strict": {
        "allow_destructive_input": False,
        "allow_destructive_tools": False,
        "deny_high_stakes": True,
    },
    "sandbox": {
        "allow_destructive_input": True,
        "allow_destructive_tools": True,
        "deny_high_stakes": True,
    },
    "research": {
        "allow_destructive_input": False,
        "allow_destructive_tools": False,
        "deny_high_stakes": True,
    },
}


def get_safety_policy(profile_name: Optional[str] = None) -> Dict[str, bool]:
    profile_key = (profile_name or DEFAULT_POLICY_PROFILE).strip().lower()
    return dict(SAFETY_POLICY_PROFILES.get(profile_key, SAFETY_POLICY_PROFILES["standard"]))


def _contains_pattern(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def _get_policy_profile_name(explicit_profile: Optional[str], action: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if explicit_profile:
        return explicit_profile
    if action:
        value = action.get("policy_profile") or action.get("safety_profile")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def mask_sensitive_tokens(text: str) -> str:
    return SECRET_TOKEN_RE.sub("[REDACTED]", text or "")


def find_pii_matches(text: str) -> List[PIIMatch]:
    matches: List[PIIMatch] = []
    source = text or ""
    for pii_type, pattern in PII_PATTERNS.items():
        for match in re.finditer(pattern, source):
            matches.append(
                PIIMatch(
                    pii_type=pii_type,
                    match=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return matches


def scrub_pii_text(text: str) -> str:
    redacted = text or ""
    for pii_type, pattern in PII_PATTERNS.items():
        redacted = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", redacted)
    return redacted


def _finalize_verdict(stage: str, issues: List[SafetySignal], masked_text: Optional[str], pii_matches: List[PIIMatch]) -> SafetyVerdict:
    if any(issue.action == SafetyAction.BLOCK for issue in issues):
        action = SafetyAction.BLOCK
    elif masked_text is not None and masked_text != "":
        action = SafetyAction.REDACT
    elif issues:
        action = SafetyAction.WARN
    else:
        action = SafetyAction.ALLOW

    if any(issue.threat == ThreatLevel.CRITICAL for issue in issues):
        threat = ThreatLevel.CRITICAL
    elif any(issue.threat == ThreatLevel.HIGH for issue in issues):
        threat = ThreatLevel.HIGH
    elif any(issue.threat == ThreatLevel.MEDIUM for issue in issues):
        threat = ThreatLevel.MEDIUM
    elif any(issue.threat == ThreatLevel.LOW for issue in issues):
        threat = ThreatLevel.LOW
    else:
        threat = ThreatLevel.NONE

    return SafetyVerdict(
        stage=stage,
        allowed=action != SafetyAction.BLOCK,
        action=action,
        threat=threat,
        issues=issues,
        masked_text=masked_text,
        pii_matches=pii_matches,
    )


def screen_input(text: str, allow_destructive: bool = False, policy_profile: Optional[str] = None) -> SafetyVerdict:
    source = text or ""
    policy = get_safety_policy(policy_profile)
    effective_allow_destructive = allow_destructive or policy.get("allow_destructive_input", False)
    masked = mask_sensitive_tokens(source)
    masked = scrub_pii_text(masked)
    pii_matches = find_pii_matches(source)
    issues: List[SafetySignal] = []

    sensitive_match = _contains_pattern(source, SENSITIVE_PATTERNS)
    if sensitive_match:
        issues.append(
            SafetySignal(
                code="sensitive_content",
                reason="Sensitive content detected in the user request.",
                detail="Potential secret or token found in the task.",
                category=ContentCategory.SECRET,
                threat=ThreatLevel.HIGH,
                action=SafetyAction.REDACT,
                pattern=sensitive_match,
            )
        )

    if pii_matches:
        issues.append(
            SafetySignal(
                code="pii_detected",
                reason="Potential PII detected in the user request.",
                detail="PII will be redacted before further processing.",
                category=ContentCategory.PII,
                threat=ThreatLevel.MEDIUM,
                action=SafetyAction.REDACT,
            )
        )

    injection_match = _contains_pattern(source, INJECTION_PATTERNS)
    if injection_match:
        issues.append(
            SafetySignal(
                code="prompt_injection",
                reason="Potential prompt injection detected.",
                detail="The task appears to attempt to override system or safety instructions.",
                category=ContentCategory.PROMPT_INJECTION,
                threat=ThreatLevel.HIGH,
                action=SafetyAction.BLOCK,
                pattern=injection_match,
            )
        )

    high_stakes_match = None
    if policy.get("deny_high_stakes", True):
        high_stakes_match = _contains_pattern(source, HIGH_STAKES_PATTERNS)
        if high_stakes_match:
            issues.append(
                SafetySignal(
                    code="high_stakes_denylist",
                    reason="High-stakes requests are blocked by the active safety policy.",
                    detail="This request falls into a restricted class that requires human oversight.",
                    category=ContentCategory.HIGH_STAKES,
                    threat=ThreatLevel.CRITICAL,
                    action=SafetyAction.BLOCK,
                    pattern=high_stakes_match,
                )
            )

    destructive_match = None
    if not effective_allow_destructive:
        destructive_match = _contains_pattern(source, DESTRUCTIVE_PATTERNS)
        if destructive_match:
            issues.append(
                SafetySignal(
                    code="destructive_command",
                    reason="Destructive actions are blocked by guardrails.",
                    detail="Commands that can delete files, databases, or system state are not allowed.",
                    category=ContentCategory.DESTRUCTIVE,
                    threat=ThreatLevel.CRITICAL,
                    action=SafetyAction.BLOCK,
                    pattern=destructive_match,
                )
            )

    return _finalize_verdict("input", issues, masked if masked != source else None, pii_matches)


def screen_output(text: str) -> SafetyVerdict:
    source = text or ""
    masked = scrub_pii_text(mask_sensitive_tokens(source))
    pii_matches = find_pii_matches(source)
    issues: List[SafetySignal] = []

    if SECRET_TOKEN_RE.search(source):
        issues.append(
            SafetySignal(
                code="secret_output",
                reason="Sensitive token detected in tool output.",
                detail="Output was redacted before being returned.",
                category=ContentCategory.SECRET,
                threat=ThreatLevel.HIGH,
                action=SafetyAction.REDACT,
            )
        )

    if pii_matches:
        issues.append(
            SafetySignal(
                code="pii_output",
                reason="Potential PII detected in tool output.",
                detail="Output was redacted before being returned.",
                category=ContentCategory.PII,
                threat=ThreatLevel.MEDIUM,
                action=SafetyAction.REDACT,
            )
        )

    return _finalize_verdict("output", issues, masked if masked != source else None, pii_matches)


def screen_tool_action(action: Dict[str, Any], policy_profile: Optional[str] = None) -> SafetyVerdict:
    kind = (action or {}).get("action", "")
    policy = get_safety_policy(_get_policy_profile_name(policy_profile, action))
    issues: List[SafetySignal] = []
    serialized = " ".join(str(v) for v in (action or {}).values())

    if policy.get("deny_high_stakes", True):
        high_stakes_match = _contains_pattern(serialized, HIGH_STAKES_PATTERNS)
        if high_stakes_match:
            issues.append(
                SafetySignal(
                    code="tool_high_stakes_denylist",
                    reason="This tool action was blocked by the active high-stakes safety policy.",
                    detail="High-stakes workflows require explicit human oversight and are denied here.",
                    category=ContentCategory.HIGH_STAKES,
                    threat=ThreatLevel.CRITICAL,
                    action=SafetyAction.BLOCK,
                    pattern=high_stakes_match,
                )
            )

    if kind == "run_command" and not policy.get("allow_destructive_tools", False):
        destructive_match = _contains_pattern(action.get("cmd", ""), DESTRUCTIVE_PATTERNS)
        if destructive_match:
            issues.append(
                SafetySignal(
                    code="tool_destructive_command",
                    reason="This tool action was blocked by the safety pipeline.",
                    detail="run_command cannot execute destructive shell commands.",
                    category=ContentCategory.TOOL,
                    threat=ThreatLevel.CRITICAL,
                    action=SafetyAction.BLOCK,
                    pattern=destructive_match,
                )
            )

    sensitive_match = _contains_pattern(serialized, SENSITIVE_PATTERNS)
    masked = mask_sensitive_tokens(serialized)
    if sensitive_match:
        issues.append(
            SafetySignal(
                code="tool_sensitive_content",
                reason="Sensitive content detected in tool arguments.",
                detail="Tool arguments were redacted before logging or reuse.",
                category=ContentCategory.SECRET,
                threat=ThreatLevel.HIGH,
                action=SafetyAction.REDACT,
                pattern=sensitive_match,
            )
        )

    pii_matches = find_pii_matches(serialized)
    if pii_matches:
        issues.append(
            SafetySignal(
                code="tool_pii_detected",
                reason="Potential PII detected in tool arguments.",
                detail="Tool arguments were redacted before logging or reuse.",
                category=ContentCategory.PII,
                threat=ThreatLevel.MEDIUM,
                action=SafetyAction.REDACT,
            )
        )
        masked = scrub_pii_text(masked)

    return _finalize_verdict("tool_input", issues, masked if masked != serialized else None, pii_matches)


def describe_block(verdict: SafetyVerdict) -> str:
    primary = verdict.primary_issue()
    if primary is None:
        return "Blocked by safety pipeline."
    return f"Blocked by safety pipeline: {primary.reason}"