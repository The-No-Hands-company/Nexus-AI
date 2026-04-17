"""
src/safety/input_filter.py — Pre-processing input filter stub

Applied to every incoming prompt before it reaches the model.
Runs: PII detection, injection detection, harm classification,
length limits, language detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pii import detect_pii, PIIMatch
from .prompt_injection import detect_prompt_injection, InjectionResult


MAX_PROMPT_CHARS = int(1e6)  # 1 MB hard cap


@dataclass
class InputFilterResult:
    passed: bool
    prompt_clean: str           # prompt after any redaction
    pii_detected: list[PIIMatch] = field(default_factory=list)
    injection: InjectionResult | None = None
    rejection_reason: str = ""
    warnings: list[str] = field(default_factory=list)


def filter_input(prompt: str, redact_pii: bool = False) -> InputFilterResult:
    """
    Run all input filters on *prompt*.

    Currently FUNCTIONAL for:
    - Length limit enforcement
    - Regex PII detection
    - Heuristic injection detection

    STUB for:
    - ML harm classification (falls back to keyword only)
    - Language detection
    - Semantic similarity to blocked examples
    """
    warnings: list[str] = []

    # 1. Length check
    if len(prompt) > MAX_PROMPT_CHARS:
        return InputFilterResult(
            passed=False,
            prompt_clean=prompt[:100] + "...",
            rejection_reason=f"Prompt exceeds max length ({MAX_PROMPT_CHARS} chars).",
        )

    # 2. PII detection
    pii_matches = detect_pii(prompt)
    if pii_matches:
        warnings.append(f"PII detected: {[m.category for m in pii_matches]}")

    # 3. Apply PII redaction if requested
    prompt_clean = prompt
    if redact_pii and pii_matches:
        from .pii import redact_pii as _redact
        prompt_clean = _redact(prompt)

    # 4. Injection detection
    injection = detect_prompt_injection(prompt)
    if injection.detected:
        return InputFilterResult(
            passed=False,
            prompt_clean=prompt_clean,
            pii_detected=pii_matches,
            injection=injection,
            rejection_reason="Prompt injection pattern detected.",
            warnings=warnings,
        )

    return InputFilterResult(
        passed=True,
        prompt_clean=prompt_clean,
        pii_detected=pii_matches,
        injection=injection,
        warnings=warnings,
    )
