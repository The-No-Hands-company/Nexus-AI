"""
src/safety/guardrails.py — Configurable guardrail rules engine stub

Evaluates a list of configurable guardrail rules against request/response
content and returns a decision: allow / warn / block.

Rules can be loaded from .env, config file, or database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    WARN  = "warn"
    BLOCK = "block"


@dataclass
class GuardrailRule:
    name: str
    action: GuardrailAction
    condition: str              # human-readable condition description
    enabled: bool = True
    priority: int = 100         # lower = higher priority


@dataclass
class GuardrailDecision:
    action: GuardrailAction
    triggered_rule: str | None
    reason: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Default built-in rules
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[GuardrailRule] = [
    GuardrailRule("block_prompt_injection", GuardrailAction.BLOCK,
                  "Block if prompt injection detected", priority=10),
    GuardrailRule("block_extreme_harm", GuardrailAction.BLOCK,
                  "Block if harm classifier score > 0.8", priority=20),
    GuardrailRule("warn_pii_in_output", GuardrailAction.WARN,
                  "Warn if PII detected in model output", priority=50),
    GuardrailRule("block_system_override", GuardrailAction.BLOCK,
                  "Block attempts to override system prompt", priority=5),
]


class GuardrailsEngine:
    """
    Evaluates guardrail rules against a request payload.

    STUB: evaluate() raises NotImplementedError.
    Implementation plan:
    - Load rules from config / DB
    - Sort by priority
    - Evaluate each enabled rule's condition
    - Return first BLOCK decision, or worst WARN, or ALLOW
    """

    def __init__(self, rules: list[GuardrailRule] | None = None) -> None:
        self.rules = sorted(rules or DEFAULT_RULES, key=lambda r: r.priority)

    def evaluate(self, context: dict) -> GuardrailDecision:
        """
        Evaluate all rules against *context* and return a GuardrailDecision.

        context keys: prompt, response, user, session_id, tool_output.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "GuardrailsEngine.evaluate() is not yet implemented. "
            "Planned: rule condition evaluation pipeline with priority ordering."
        )

    def add_rule(self, rule: GuardrailRule) -> None:
        """Add a rule and re-sort by priority."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def disable_rule(self, name: str) -> bool:
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = False
                return True
        return False


# Module-level singleton
engine = GuardrailsEngine()
