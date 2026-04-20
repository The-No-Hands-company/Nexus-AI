"""Mixture-of-Experts (MoE) router for Nexus AI.

Routes tasks to the best-fit specialist model based on task complexity,
domain classification, and current provider performance.

Reasoning modes:
- hypothesis  : structured hypothesis → evidence → conclusion flow
- socratic    : question-driven decomposition
- formal_proof: step-by-step verifiable proofs for math/code
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Expert definitions ────────────────────────────────────────────────────────

@dataclass
class Expert:
    name: str
    domains: list[str]
    model_hint: str          # preferred model/provider tag
    tier: str = "standard"   # fast | standard | advanced
    weight: float = 1.0

    def score(self, domain_scores: dict[str, float]) -> float:
        return sum(domain_scores.get(d, 0.0) * self.weight for d in self.domains)


EXPERTS: list[Expert] = [
    Expert("code",        ["code", "debug", "programming", "test", "refactor"],   "codestral",  "standard"),
    Expert("math",        ["math", "proof", "equation", "formula", "calculation"], "mathstral",  "advanced"),
    Expert("research",    ["research", "rag", "literature", "citation", "fact"],   "gemini",     "standard"),
    Expert("creative",    ["creative", "story", "poem", "design", "brainstorm"],   "claude",     "standard"),
    Expert("reasoning",   ["logic", "reasoning", "plan", "strategy", "analysis"],  "gpt-4o",     "advanced"),
    Expert("data",        ["data", "sql", "csv", "chart", "statistics", "pandas"], "gpt-4o-mini","standard"),
    Expert("safety",      ["safety", "compliance", "legal", "audit", "policy"],    "claude",     "advanced"),
    Expert("devops",      ["docker", "kubernetes", "infra", "ci", "deploy"],       "gpt-4o",     "standard"),
    Expert("general",     [],                                                       "default",    "fast"),
]

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "code":       ["def ", "function", "class ", "import ", "```python", "```js", "bug", "error", "exception"],
    "math":       ["prove", "theorem", "equation", "integral", "derivative", "formula", "$$"],
    "research":   ["research", "literature", "paper", "source", "citation", "study", "according to"],
    "creative":   ["story", "poem", "creative", "imagine", "write a", "character", "plot"],
    "reasoning":  ["analyze", "compare", "evaluate", "why", "how", "explain", "plan", "strategy"],
    "data":       ["select ", "from ", "group by", "dataframe", "csv", "json", "chart", "graph"],
    "safety":     ["compliance", "regulation", "policy", "legal", "privacy", "audit", "gdpr"],
    "devops":     ["docker", "kubernetes", "helm", "ci/cd", "pipeline", "deploy", "container"],
}


def classify_domain(text: str) -> dict[str, float]:
    """Classify text into domain scores 0-1."""
    text_lower = text.lower()
    scores: dict[str, float] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        scores[domain] = min(1.0, hits / max(len(keywords) * 0.3, 1))
    return scores


def route_to_expert(prompt: str, persona: str | None = None,
                    complexity: str | None = None) -> dict:
    """Select the best expert for the given prompt.

    Returns:
        {expert_name, model_hint, tier, domain_scores, confidence}
    """
    domain_scores = classify_domain(prompt)

    # Score all experts
    scored = [(e, e.score(domain_scores)) for e in EXPERTS]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_expert, best_score = scored[0]

    # Fall back to general if no clear winner
    if best_score < 0.05:
        best_expert = next(e for e in EXPERTS if e.name == "general")
        best_score  = 0.0

    # Override tier if complexity is specified
    tier = complexity or best_expert.tier

    return {
        "expert":        best_expert.name,
        "model_hint":    best_expert.model_hint,
        "tier":          tier,
        "domain_scores": {k: round(v, 3) for k, v in domain_scores.items() if v > 0},
        "confidence":    round(best_score, 3),
        "candidates":    [{"expert": e.name, "score": round(s, 3)} for e, s in scored[:3]],
    }


# ── Hypothesis testing flow ───────────────────────────────────────────────────

def build_hypothesis_prompt(question: str, context: str = "") -> str:
    """Wrap a question in a structured hypothesis-evidence-conclusion prompt."""
    ctx_block = f"\n\nContext:\n{context}" if context else ""
    return f"""You are a rigorous analytical reasoner. Follow this exact structure:

## Hypothesis
State a clear, testable hypothesis that directly addresses the question.

## Evidence
List 3-5 pieces of evidence (facts, data, logical derivations) that support or refute the hypothesis.
For each piece of evidence, rate its reliability: [strong | moderate | weak].

## Analysis
Synthesize the evidence. Note any contradictions or gaps.

## Conclusion
State whether the hypothesis is supported, refuted, or inconclusive. Provide a confidence level (0-100%).

---
Question: {question}{ctx_block}"""


def build_socratic_prompt(topic: str, depth: int = 3) -> str:
    """Build a Socratic question-decomposition prompt."""
    return f"""You are a Socratic tutor. Your goal is to lead the learner to understanding through questions rather than direct answers.

Topic: {topic}

Instructions:
1. Identify the core assumption or knowledge gap in this topic.
2. Ask {depth} probing questions that lead toward deeper understanding.
3. For each question, explain BRIEFLY why it matters (1 sentence).
4. After the questions, provide a "Guided Path" — a sequence of concepts to explore in order.
5. Do NOT give the final answer directly. Guide the learner to discover it.

Respond in this format:
## Core Assumption
[what underlies this topic]

## Guiding Questions
1. [question] — [why it matters]
2. [question] — [why it matters]
3. [question] — [why it matters]

## Guided Path
[concept 1] → [concept 2] → [concept 3] → [insight]"""


def build_formal_proof_prompt(statement: str, proof_type: str = "mathematical") -> str:
    """Build a formal step-by-step proof verification prompt."""
    style_guide = {
        "mathematical": "Use standard mathematical notation. Each step must cite the rule or axiom applied.",
        "code":         "Use formal program logic. Each step must reference the code invariant being maintained.",
        "logical":      "Use propositional/predicate logic. Each step must cite the logical law applied.",
    }.get(proof_type, "Each step must be justified with a cited rule or principle.")

    return f"""You are a formal verification engine. Prove or disprove the following statement with complete rigor.

Statement: {statement}

Rules:
- {style_guide}
- Mark each step: [axiom | theorem | definition | hypothesis | derived]
- If you find the statement FALSE, provide a counterexample.
- End with a QED block summarising the proof.

## Proof

Step 1 [type]: ...
Step 2 [type]: ...
...

## QED
[summary of what was proven/disproven]
[validity: PROVEN | DISPROVEN | UNDECIDABLE]"""


# ── Reasoning session log ─────────────────────────────────────────────────────

_reasoning_sessions: list[dict] = []


def log_reasoning_session(mode: str, input_text: str, output_text: str,
                           model: str = "", latency_ms: float = 0.0) -> dict:
    entry = {
        "id":         str(time.time_ns())[-8:],
        "mode":       mode,
        "model":      model,
        "input_len":  len(input_text),
        "output_len": len(output_text),
        "latency_ms": latency_ms,
        "ts":         datetime.now(timezone.utc).isoformat(),
    }
    _reasoning_sessions.append(entry)
    if len(_reasoning_sessions) > 200:
        _reasoning_sessions.pop(0)
    return entry


def list_reasoning_sessions(mode: str | None = None, limit: int = 50) -> list[dict]:
    items = _reasoning_sessions
    if mode:
        items = [s for s in items if s["mode"] == mode]
    return list(reversed(items[-limit:]))
