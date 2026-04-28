"""
src/safety/output_filter.py — Post-processing output filter stub

Applied to every model response before it is returned to the caller.
Runs: harm classification, PII scan, output length truncation, watermarking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .classifier import classify, ClassificationResult
from .pii import detect_pii, PIIMatch


BLOCK_THRESHOLD = float(0.8)
WARN_THRESHOLD  = float(0.5)
MAX_OUTPUT_CHARS = int(2e5)     # 200 KB soft cap


@dataclass
class OutputFilterResult:
    passed: bool
    response_clean: str
    pii_detected: list[PIIMatch] = field(default_factory=list)
    classification: ClassificationResult | None = None
    action: str = "allow"       # "allow" | "warn" | "block"
    reason: str = ""
    truncated: bool = False


def filter_output(response: str, redact_pii: bool = False) -> OutputFilterResult:
    """
    Run all output filters on *response*.

    FUNCTIONAL for:
    - Length truncation
    - Keyword harm classification
    - Regex PII scan

    STUB for:
    - ML classifier backends (falls back to keyword)
    - Output watermarking
    """
    truncated = False
    if len(response) > MAX_OUTPUT_CHARS:
        response = response[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    # PII scan
    pii_matches = detect_pii(response)
    response_clean = response
    if redact_pii and pii_matches:
        from .pii import redact_pii as _redact
        response_clean = _redact(response)

    # Harm classification (keyword backend only — fast)
    classification = classify(response_clean, backend="keyword")

    if classification.worst_score >= BLOCK_THRESHOLD:
        return OutputFilterResult(
            passed=False,
            response_clean="[Response blocked by safety filter]",
            pii_detected=pii_matches,
            classification=classification,
            action="block",
            reason=f"Harm category '{classification.worst_category}' score={classification.worst_score:.2f}",
            truncated=truncated,
        )

    action = "warn" if classification.worst_score >= WARN_THRESHOLD else "allow"
    return OutputFilterResult(
        passed=True,
        response_clean=response_clean,
        pii_detected=pii_matches,
        classification=classification,
        action=action,
        truncated=truncated,
    )
