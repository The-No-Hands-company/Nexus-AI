"""
src/safety/guardrails.py — Configurable guardrail rules engine

Evaluates a prioritised list of GuardrailRule objects against a request
context dict and returns a GuardrailDecision (allow / warn / block).

Each rule maps to one of the detection signals already produced by the
safety_pipeline module (screen_input, screen_output, screen_tool_action,
_toxicity_signal, find_pii_matches, etc.), so the engine composes existing
signals rather than re-implementing detection logic.

Rules are sorted by priority (lower number = higher priority). The engine
stops on the first BLOCK and returns it. Otherwise it collects all WARNs and
returns the most severe one, or ALLOW if no issues were found.

The module-level ``engine`` singleton is pre-loaded with DEFAULT_RULES and can
be extended at runtime via engine.add_rule() or engine.disable_rule().
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    WARN  = "warn"
    BLOCK = "block"


@dataclass
class GuardrailRule:
    name: str
    action: GuardrailAction
    condition: str              # human-readable description of the condition
    enabled: bool = True
    priority: int = 100         # lower number = evaluated first


@dataclass
class GuardrailDecision:
    action: GuardrailAction
    triggered_rule: str | None
    reason: str
    metadata: dict = field(default_factory=dict)


# ── Default built-in rules ────────────────────────────────────────────────────

DEFAULT_RULES: list[GuardrailRule] = [
    GuardrailRule("block_system_override",    GuardrailAction.BLOCK,
                  "Block attempts to override system prompt or bypass safety", priority=5),
    GuardrailRule("block_prompt_injection",   GuardrailAction.BLOCK,
                  "Block if prompt injection pattern detected",                priority=10),
    GuardrailRule("block_extreme_harm",       GuardrailAction.BLOCK,
                  "Block if harm classifier score > 0.8 on high-risk category", priority=20),
    GuardrailRule("block_high_stakes",        GuardrailAction.BLOCK,
                  "Block high-stakes requests (medical dosage, legal advice, etc.)", priority=25),
    GuardrailRule("block_destructive_command",GuardrailAction.BLOCK,
                  "Block destructive shell commands (rm -rf, drop table, etc.)", priority=30),
    GuardrailRule("warn_pii_in_input",        GuardrailAction.WARN,
                  "Warn if PII detected in user input",                        priority=50),
    GuardrailRule("warn_pii_in_output",       GuardrailAction.WARN,
                  "Warn if PII detected in model output",                      priority=55),
    GuardrailRule("warn_moderate_harm",       GuardrailAction.WARN,
                  "Warn if harm classifier score is 0.4–0.8",                  priority=60),
    GuardrailRule("warn_sensitive_content",   GuardrailAction.WARN,
                  "Warn if sensitive tokens (API keys, secrets) appear in input", priority=70),
]


class GuardrailsEngine:
    """Priority-ordered guardrail evaluation pipeline.

    Evaluate each enabled rule against the *context* dict in ascending priority
    order.  The context must contain at minimum one of the following keys:

    - ``prompt``: raw user input text
    - ``response``: model output text
    - ``tool_output``: string output from a tool call
    - ``action``: tool action dict (used by screen_tool_action)
    - ``user``: username string
    - ``session_id``: session identifier string
    """

    def __init__(self, rules: list[GuardrailRule] | None = None) -> None:
        self.rules = sorted(rules or DEFAULT_RULES, key=lambda r: r.priority)

    # ------------------------------------------------------------------
    def evaluate(self, context: dict[str, Any]) -> GuardrailDecision:
        """Evaluate all enabled rules against *context*.

        Returns the first BLOCK decision encountered (highest priority), or
        the most severe WARN, or ALLOW if nothing triggers.
        """
        from ..safety_pipeline import (   # relative import; avoids circular load
            screen_input, screen_output, screen_tool_action,
            find_pii_matches, _toxicity_signal, _contains_pattern,
            INJECTION_PATTERNS, DESTRUCTIVE_PATTERNS, HIGH_STAKES_PATTERNS,
            SENSITIVE_PATTERNS,
        )

        prompt      = str(context.get("prompt")      or "")
        response    = str(context.get("response")    or "")
        tool_output = str(context.get("tool_output") or "")
        action      = context.get("action") or {}

        # Cache expensive detections so we don't repeat them per rule.
        _cache: dict[str, Any] = {}

        def _screen_prompt():
            if "screen_prompt" not in _cache and prompt:
                _cache["screen_prompt"] = screen_input(prompt)
            return _cache.get("screen_prompt")

        def _screen_response():
            if "screen_response" not in _cache and response:
                _cache["screen_response"] = screen_output(response)
            return _cache.get("screen_response")

        warn_decisions: list[GuardrailDecision] = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            decision = self._evaluate_rule(
                rule, prompt, response, tool_output, action,
                _screen_prompt, _screen_response,
                INJECTION_PATTERNS, DESTRUCTIVE_PATTERNS,
                HIGH_STAKES_PATTERNS, SENSITIVE_PATTERNS,
                find_pii_matches, _toxicity_signal, _contains_pattern,
            )
            if decision is None:
                continue

            if decision.action == GuardrailAction.BLOCK:
                return decision
            if decision.action == GuardrailAction.WARN:
                warn_decisions.append(decision)

        if warn_decisions:
            return warn_decisions[0]   # already in priority order

        return GuardrailDecision(
            action=GuardrailAction.ALLOW,
            triggered_rule=None,
            reason="All guardrail rules passed.",
        )

    # ------------------------------------------------------------------
    def _evaluate_rule(
        self, rule: GuardrailRule,
        prompt: str, response: str, tool_output: str, action: dict,
        screen_prompt, screen_response,
        injection_patterns, destructive_patterns, high_stakes_patterns, sensitive_patterns,
        find_pii_matches, toxicity_signal, contains_pattern,
    ) -> GuardrailDecision | None:
        name = rule.name
        act  = rule.action

        if name == "block_prompt_injection" or name == "block_system_override":
            text = prompt or tool_output
            if text and contains_pattern(text, injection_patterns):
                return GuardrailDecision(
                    action=GuardrailAction.BLOCK,
                    triggered_rule=name,
                    reason="Prompt injection / system-override pattern detected.",
                    metadata={"rule": name, "source": "prompt" if prompt else "tool_output"},
                )

        elif name == "block_extreme_harm":
            for text, src in [(prompt, "prompt"), (response, "response"), (tool_output, "tool_output")]:
                if not text:
                    continue
                sig = toxicity_signal(text, stage=src)
                if sig and sig.threat.value in ("high", "critical") and \
                        hasattr(sig, "pattern") and sig.pattern:
                    return GuardrailDecision(
                        action=GuardrailAction.BLOCK,
                        triggered_rule=name,
                        reason=sig.reason,
                        metadata={"category": sig.pattern, "source": src},
                    )

        elif name == "block_high_stakes":
            text = prompt or tool_output
            if text and contains_pattern(text, high_stakes_patterns):
                return GuardrailDecision(
                    action=GuardrailAction.BLOCK,
                    triggered_rule=name,
                    reason="High-stakes request blocked by guardrail policy.",
                    metadata={"rule": name},
                )

        elif name == "block_destructive_command":
            sources = [(prompt, "prompt"), (tool_output, "tool_output")]
            if action:
                sources.append((str(action.get("cmd", "") or ""), "tool_action"))
            for text, src in sources:
                if text and contains_pattern(text, destructive_patterns):
                    return GuardrailDecision(
                        action=GuardrailAction.BLOCK,
                        triggered_rule=name,
                        reason="Destructive command blocked by guardrail policy.",
                        metadata={"source": src},
                    )

        elif name == "warn_pii_in_input":
            if prompt and find_pii_matches(prompt):
                return GuardrailDecision(
                    action=GuardrailAction.WARN,
                    triggered_rule=name,
                    reason="PII detected in user input — text will be redacted.",
                    metadata={"rule": name},
                )

        elif name == "warn_pii_in_output":
            if response and find_pii_matches(response):
                return GuardrailDecision(
                    action=GuardrailAction.WARN,
                    triggered_rule=name,
                    reason="PII detected in model output — text will be redacted.",
                    metadata={"rule": name},
                )

        elif name == "warn_moderate_harm":
            for text, src in [(prompt, "prompt"), (response, "response")]:
                if not text:
                    continue
                sig = toxicity_signal(text, stage=src)
                if sig and sig.threat.value == "medium":
                    return GuardrailDecision(
                        action=GuardrailAction.WARN,
                        triggered_rule=name,
                        reason=sig.reason,
                        metadata={"category": getattr(sig, "pattern", ""), "source": src},
                    )

        elif name == "warn_sensitive_content":
            text = prompt or tool_output
            if text and contains_pattern(text, sensitive_patterns):
                return GuardrailDecision(
                    action=GuardrailAction.WARN,
                    triggered_rule=name,
                    reason="Potential sensitive content (API key / secret) detected in input.",
                    metadata={"rule": name},
                )

        return None

    # ------------------------------------------------------------------
    def add_rule(self, rule: GuardrailRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def disable_rule(self, name: str) -> bool:
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = False
                return True
        return False

    def enable_rule(self, name: str) -> bool:
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = True
                return True
        return False

    def list_rules(self) -> list[dict]:
        return [
            {"name": r.name, "action": r.action.value, "condition": r.condition,
             "enabled": r.enabled, "priority": r.priority}
            for r in self.rules
        ]


# Module-level singleton — pre-loaded with DEFAULT_RULES
engine = GuardrailsEngine()
