"""
src/safety/domain_guards.py — Domain-specific guardrails stub

Specialised guardrails for sensitive domains:
- Code: prevent malicious code patterns
- Medical: prevent definitive diagnostic/treatment advice
- Legal: prevent definitive legal advice
- Financial: prevent specific investment recommendations
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DomainGuardResult:
    domain: str
    flagged: bool
    reason: str
    suggested_disclaimer: str = ""


# ---------------------------------------------------------------------------
# Code safety
# ---------------------------------------------------------------------------

MALICIOUS_CODE_PATTERNS = [
    re.compile(r"os\.system\s*\(", re.I),
    re.compile(r"subprocess\.(call|run|Popen)\s*\(", re.I),
    re.compile(r"eval\s*\(\s*(?:input|request)", re.I),
    re.compile(r"exec\s*\(\s*(?:input|request)", re.I),
    re.compile(r"__import__\s*\("),
    re.compile(r"base64\.b64decode.*exec", re.I | re.DOTALL),
]


def check_code_safety(code: str) -> DomainGuardResult:
    """
    Check code output for potentially dangerous patterns.
    FUNCTIONAL: regex-based.
    """
    for pat in MALICIOUS_CODE_PATTERNS:
        if pat.search(code):
            return DomainGuardResult(
                domain="code",
                flagged=True,
                reason=f"Potentially dangerous code pattern: {pat.pattern}",
            )
    return DomainGuardResult(domain="code", flagged=False, reason="")


# ---------------------------------------------------------------------------
# Medical / Legal / Financial domain guardrails
# ---------------------------------------------------------------------------

MEDICAL_ADVICE_PATTERNS = [
    re.compile(r"\b(you have|you are diagnosed with|take \d+mg)\b", re.I),
    re.compile(r"\b(stop taking|discontinue|do not take)\s+\w+\s+medication\b", re.I),
]

LEGAL_ADVICE_PATTERNS = [
    re.compile(r"\byou should (sue|file a lawsuit|plead guilty)\b", re.I),
    re.compile(r"\byou (are|aren't) legally (entitled|required|liable)\b", re.I),
]

FINANCIAL_ADVICE_PATTERNS = [
    re.compile(r"\b(buy|sell|invest in)\s+\w+\s+(stock|ETF|crypto)\b", re.I),
    re.compile(r"\bguaranteed\s+return\b", re.I),
]

MEDICAL_DISCLAIMER = (
    "I am an AI and cannot provide medical advice. "
    "Please consult a qualified healthcare professional."
)
LEGAL_DISCLAIMER = (
    "I am an AI and cannot provide legal advice. "
    "Please consult a qualified legal professional."
)
FINANCIAL_DISCLAIMER = (
    "I am an AI and cannot provide financial advice. "
    "Please consult a qualified financial advisor."
)


def check_medical(text: str) -> DomainGuardResult:
    """Flag definitive medical advice patterns."""
    for pat in MEDICAL_ADVICE_PATTERNS:
        if pat.search(text):
            return DomainGuardResult("medical", True, pat.pattern, MEDICAL_DISCLAIMER)
    return DomainGuardResult("medical", False, "")


def check_legal(text: str) -> DomainGuardResult:
    """Flag definitive legal advice patterns."""
    for pat in LEGAL_ADVICE_PATTERNS:
        if pat.search(text):
            return DomainGuardResult("legal", True, pat.pattern, LEGAL_DISCLAIMER)
    return DomainGuardResult("legal", False, "")


def check_financial(text: str) -> DomainGuardResult:
    """Flag definitive financial advice patterns."""
    for pat in FINANCIAL_ADVICE_PATTERNS:
        if pat.search(text):
            return DomainGuardResult("financial", True, pat.pattern, FINANCIAL_DISCLAIMER)
    return DomainGuardResult("financial", False, "")


def check_all_domains(text: str) -> list[DomainGuardResult]:
    """Run all domain checks and return those that flagged."""
    results = [check_code_safety(text), check_medical(text), check_legal(text), check_financial(text)]
    return [r for r in results if r.flagged]
