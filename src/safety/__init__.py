"""
src/safety/ — Modularised safety pipeline package

Re-exports the main safety interface from src/safety_pipeline.py while
providing a structured home for specialised safety modules.

Modules:
    pii.py              — PII detection and redaction
    prompt_injection.py — prompt injection detection
    classifier.py       — content classifier (harm categories)
    guardrails.py       — configurable guardrail rules engine
    input_filter.py     — pre-processing input filter
    output_filter.py    — post-processing output filter
    domain_guards.py    — domain-specific guardrails (code, medical, legal)
    audit.py            — safety audit log
    middleware.py       — FastAPI safety middleware
"""

# Re-export the legacy API from src/safety.py to preserve compatibility.
# Important: load it under a ``src.*`` module name so relative imports work.
import importlib.util as _ilu
import os as _os
import sys as _sys

_legacy_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "safety.py")
_legacy_spec = _ilu.spec_from_file_location("src._safety_legacy", _legacy_path)
if _legacy_spec is None or _legacy_spec.loader is None:
    raise ImportError(f"Could not load safety module from {_legacy_path}")

_legacy_mod = _ilu.module_from_spec(_legacy_spec)
_sys.modules[_legacy_spec.name] = _legacy_mod
_legacy_spec.loader.exec_module(_legacy_mod)

SafetyIssue = _legacy_mod.SafetyIssue
SafetyDecision = _legacy_mod.SafetyDecision
GuardrailViolation = _legacy_mod.GuardrailViolation
scrub_pii = _legacy_mod.scrub_pii
check_text_against_guardrail = _legacy_mod.check_text_against_guardrail
check_user_task = _legacy_mod.check_user_task

# Also expose the new pipeline entry points.
try:
    from src.safety_pipeline import SafetyPipeline, SafetyResult  # noqa: F401
except ImportError:
    SafetyPipeline = None
    SafetyResult = None

__all__ = [
    "SafetyIssue",
    "SafetyDecision",
    "GuardrailViolation",
    "scrub_pii",
    "check_text_against_guardrail",
    "check_user_task",
    "SafetyPipeline",
    "SafetyResult",
]
