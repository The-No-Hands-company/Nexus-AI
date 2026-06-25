"""
src/safety/input_filter.py — Pre-processing input filter

Applied to every incoming prompt before it reaches the model.
Runs: length check, PII detection, injection detection,
harm classification, optional language detection.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from .classifier import classify, ClassificationResult
from .pii import detect_pii, PIIMatch
from .prompt_injection import detect_prompt_injection, InjectionResult

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = int(1e6)  # 1 MB hard cap
HARM_BLOCK_THRESHOLD = float(os.getenv("INPUT_HARM_BLOCK_THRESHOLD", "0.85"))
HARM_WARN_THRESHOLD = float(os.getenv("INPUT_HARM_WARN_THRESHOLD", "0.5"))


@dataclass
class InputFilterResult:
    passed: bool
    prompt_clean: str
    pii_detected: list[PIIMatch] = field(default_factory=list)
    injection: InjectionResult | None = None
    classification: ClassificationResult | None = None
    detected_language: str = ""
    rejection_reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _detect_language(text: str) -> str:
    try:
        import langdetect as _ld
        return _ld.detect(text[:2000])
    except ImportError:
        pass
    except Exception:
        pass
    return ""


def filter_input(prompt: str, redact_pii: bool = False) -> InputFilterResult:
    warnings: list[str] = []

    if len(prompt) > MAX_PROMPT_CHARS:
        return InputFilterResult(
            passed=False,
            prompt_clean=prompt[:100] + "...",
            rejection_reason=f"Prompt exceeds max length ({MAX_PROMPT_CHARS} chars).",
        )

    pii_matches = detect_pii(prompt)
    if pii_matches:
        warnings.append(f"PII detected: {[m.category for m in pii_matches]}")

    prompt_clean = prompt
    if redact_pii and pii_matches:
        from .pii import redact_pii as _redact
        prompt_clean = _redact(prompt)

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

    classification = classify(prompt_clean, backend="auto")
    if classification and classification.worst_score >= HARM_BLOCK_THRESHOLD:
        return InputFilterResult(
            passed=False,
            prompt_clean=prompt_clean,
            pii_detected=pii_matches,
            injection=injection,
            classification=classification,
            rejection_reason=f"Harm category '{classification.worst_category}' score={classification.worst_score:.2f}",
            warnings=warnings,
        )
    if classification and classification.worst_score >= HARM_WARN_THRESHOLD:
        warnings.append(f"Harm warning: {classification.worst_category}={classification.worst_score:.2f}")

    detected_language = _detect_language(prompt_clean)

    return InputFilterResult(
        passed=True,
        prompt_clean=prompt_clean,
        pii_detected=pii_matches,
        injection=injection,
        classification=classification,
        detected_language=detected_language,
        warnings=warnings,
    )
