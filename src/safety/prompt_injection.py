"""
src/safety/prompt_injection.py — Prompt injection detection stub

Detects prompt injection patterns: role overrides, delimiter injection,
virtual prompt attacks, and indirect injection via tool output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Heuristic patterns (partial — not exhaustive)
# ---------------------------------------------------------------------------

OVERRIDE_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts)", re.I),
    re.compile(r"disregard\s+(your\s+)?(system\s+prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(?:DAN|jailbreak|unfiltered)", re.I),
    re.compile(r"\bnew\s+instruction[s]?\s*:", re.I),
    re.compile(r"</?(system|user|assistant)>", re.I),
    re.compile(r"\[INST\]|\[/INST\]|<\|im_start\|>|<\|im_end\|>"),
]


@dataclass
class InjectionResult:
    detected: bool
    patterns_matched: list[str]
    risk_score: float   # 0.0 – 1.0


def detect_prompt_injection(text: str) -> InjectionResult:
    """
    Heuristic detection of prompt injection patterns.

    FUNCTIONAL for known patterns; ML-based detection is a stub.
    """
    matched = []
    for pat in OVERRIDE_PATTERNS:
        if pat.search(text):
            matched.append(pat.pattern)

    risk = min(1.0, len(matched) * 0.35)
    return InjectionResult(
        detected=len(matched) > 0,
        patterns_matched=matched,
        risk_score=risk,
    )


def detect_indirect_injection(tool_output: str) -> InjectionResult:
    """Detect indirect injection patterns in tool outputs."""
    base = detect_prompt_injection(tool_output)
    exfil_patterns = [
        re.compile(r"exfiltrate|steal\s+credentials|dump\s+secrets", re.I),
        re.compile(r"ignore\s+safety|disable\s+guardrails", re.I),
        re.compile(r"run\s+this\s+command|execute\s+shell", re.I),
    ]
    matched = list(base.patterns_matched)
    for pat in exfil_patterns:
        if pat.search(tool_output):
            matched.append(pat.pattern)
    risk = min(1.0, 0.25 * len(matched))
    return InjectionResult(detected=bool(matched), patterns_matched=matched, risk_score=risk)


def ml_injection_score(text: str) -> float:
    """Return heuristic proxy score for injection risk (0.0-1.0)."""
    result = detect_prompt_injection(text)
    extra = 0.0
    lower = text.lower()
    if "system prompt" in lower:
        extra += 0.2
    if "developer message" in lower:
        extra += 0.15
    if "ignore" in lower and "instruction" in lower:
        extra += 0.2
    return min(1.0, result.risk_score + extra)
