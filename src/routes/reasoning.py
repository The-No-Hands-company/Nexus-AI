"""Reasoning routes.

Extracted from src/api/routes.py for maintainability.
Covers: consensus, graph-of-thought, MCTS, socratic, verify,
generator-critic, hypothesis testing, and adaptive routing settings.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Request

from ._helpers import _api_error
from ..agent import (
    _config,
    _push_safety_event,
    call_llm_with_fallback,
)
from ..safety import GuardrailViolation, check_user_task

router = APIRouter(prefix="", tags=["reasoning"])


# ── Consensus reasoning endpoint ──────────────────────────────────────────────
@router.post("/reason/consensus")
async def reason_consensus(request: Request):
    """Run a task through multiple providers and return a reconciled consensus answer.

    POST body: {"task": "...", "providers": [...optional list...]}
    """
    from ..ensemble import call_llm_consensus
    from ..agent import (
        _call_single, _is_rate_limited, _mark_rate_limited,
        _smart_order, get_system_resources,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        consensus_text, winning_pid, meta = call_llm_consensus(
            messages=[{"role": "user", "content": task}],
            task=task,
            providers_fn=lambda t: _smart_order(t, get_system_resources()),
            call_single_fn=_call_single,
            is_rate_limited_fn=_is_rate_limited,
            mark_rate_limited_fn=_mark_rate_limited,
        )
        from ..ensemble import explain_consensus
        explanation = explain_consensus(
            chosen={"action": "respond", "content": consensus_text},
            winning_pid=winning_pid,
            unanimous=meta.get("unanimous", True),
            meta=meta,
        )
        return {
            "consensus": consensus_text,
            "provider":  winning_pid,
            "ensemble":  meta.get("ensemble", False),
            "unanimous": meta.get("unanimous"),
            "polled":    meta.get("polled", []),
            "explanation": explanation,
        }
    except Exception:
        fallback = f"Summary: {task}"
        return {
            "consensus": fallback,
            "provider": "offline-fallback",
            "ensemble": False,
            "unanimous": True,
            "polled": [],
            "explanation": "No provider available; returned deterministic fallback.",
        }


@router.post("/reason/graph-of-thought")
async def reason_graph_of_thought(request: Request):
    from ..thinking import build_got_prompt, parse_got_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or body.get("query") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        safe_task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
        raw_resp, provider = call_llm_with_fallback(
            [{"role": "user", "content": build_got_prompt(safe_task)}],
            safe_task,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    raw_text = raw_resp.get("content") or str(raw_resp)
    parsed = parse_got_response(raw_text)
    return {"task": safe_task, "provider": provider, **parsed, "raw_response": raw_text}


@router.post("/reason/mcts")
async def reason_mcts(request: Request):
    from ..thinking import run_mcts_planning

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    goal = (body.get("goal") or body.get("task") or "").strip()
    if not goal:
        return _api_error("goal is required", "validation_error", 422)

    iterations = max(2, min(int(body.get("iterations", 8)), 24))
    max_depth = max(1, min(int(body.get("max_depth", 4)), 8))
    branching = max(2, min(int(body.get("branching", 3)), 5))

    try:
        safe_goal = check_user_task(goal, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)

    providers_used: List[str] = []

    def _llm_fn(prompt: str) -> str:
        result, provider = call_llm_with_fallback([{"role": "user", "content": prompt}], safe_goal)
        providers_used.append(provider)
        return result.get("content") or str(result)

    try:
        outcome = run_mcts_planning(
            safe_goal,
            llm_fn=_llm_fn,
            iterations=iterations,
            max_depth=max_depth,
            branching=branching,
        )
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    return {
        "goal": safe_goal,
        "best_plan": outcome.get("best_plan", []),
        "best_score": outcome.get("best_score", 0.0),
        "best_rationale": outcome.get("best_rationale", ""),
        "tree_size": outcome.get("tree_size", 0),
        "iterations": outcome.get("iterations", iterations),
        "all_plans": outcome.get("all_plans", []),
        "providers": providers_used,
    }


@router.post("/reason/socratic")
async def reason_socratic(request: Request):
    from ..thinking import (
        build_socratic_prompt,
        parse_socratic_response,
        build_socratic_answer_prompt,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    topic = (body.get("topic") or body.get("task") or "").strip()
    if not topic:
        return _api_error("topic is required", "validation_error", 422)

    depth = max(1, min(int(body.get("depth", 3)), 6))

    try:
        safe_topic = check_user_task(topic, policy_profile=_config.get("safety_profile", "standard"))
        tree_resp, tree_provider = call_llm_with_fallback(
            [{"role": "user", "content": build_socratic_prompt(safe_topic, depth=depth)}],
            safe_topic,
        )
        question_tree = parse_socratic_response(tree_resp.get("content") or str(tree_resp))
        answer_resp, answer_provider = call_llm_with_fallback(
            [{"role": "user", "content": build_socratic_answer_prompt(safe_topic, question_tree)}],
            safe_topic,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    answer_text = answer_resp.get("content") or str(answer_resp)
    return {
        "topic": safe_topic,
        "depth": depth,
        "question_tree": question_tree,
        "answer": answer_text,
        "providers": {"question_tree": tree_provider, "answer": answer_provider},
    }


@router.post("/reason/verify")
async def reason_verify(request: Request):
    from ..thinking import build_verification_prompt, parse_verification_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    claim = (body.get("claim") or "").strip()
    steps = body.get("steps") or []
    domain = str(body.get("domain", "general") or "general")
    if not claim:
        return _api_error("claim is required", "validation_error", 422)
    if not isinstance(steps, list):
        return _api_error("steps must be an array", "validation_error", 422)

    try:
        safe_claim = check_user_task(claim, policy_profile=_config.get("safety_profile", "standard"))
        resp, provider = call_llm_with_fallback(
            [{"role": "user", "content": build_verification_prompt(safe_claim, steps, domain=domain)}],
            safe_claim,
        )
    except GuardrailViolation as exc:
        return _api_error(exc.reason, exc.code, 422)
    except Exception as exc:
        return _api_error(str(exc), "reasoning_error", 500)

    raw_text = resp.get("content") or str(resp)
    parsed = parse_verification_response(raw_text)
    return {
        "claim": safe_claim,
        "domain": domain,
        "provider": provider,
        **parsed,
        "raw_response": raw_text,
    }


def _extract_citation_urls(text: str) -> list[str]:
    import re as _re

    source = text or ""
    urls = []

    for m in _re.finditer(r"\[[^\]]+\]\((https?://[^)\s]+)\)", source):
        urls.append(m.group(1))

    for m in _re.finditer(r"\bhttps?://[^\s)]+", source):
        urls.append(m.group(0))

    unique = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _score_citation_confidence(answer: str, expected_sources: list[str] | None = None) -> dict:
    from urllib.parse import urlparse as _urlparse

    citations = _extract_citation_urls(answer)
    expected = [str(s).strip() for s in (expected_sources or []) if str(s).strip()]

    if not citations:
        return {
            "score": 0.1 if expected else 0.25,
            "citations": [],
            "matched_expected_sources": [],
            "expected_source_coverage": 0.0,
        }

    if not expected:
        score = min(0.9, 0.35 + 0.12 * len(citations))
        return {
            "score": round(score, 3),
            "citations": citations,
            "matched_expected_sources": [],
            "expected_source_coverage": None,
        }

    expected_domains = {(_urlparse(u).netloc or u).lower() for u in expected}
    citation_domains = [(_urlparse(u).netloc or u).lower() for u in citations]

    matched = []
    for domain in expected_domains:
        if any(domain in cd or cd in domain for cd in citation_domains):
            matched.append(domain)

    coverage = len(matched) / max(1, len(expected_domains))
    score = 0.35 + 0.65 * coverage
    return {
        "score": round(min(1.0, score), 3),
        "citations": citations,
        "matched_expected_sources": matched,
        "expected_source_coverage": round(coverage, 3),
    }


@router.post("/reason/generator-critic")
async def reason_generator_critic(request: Request):
    """Generator-critic research flow with citation confidence scoring.

    POST body:
      {"task": "...", "sources": ["https://...", ...]}
    """
    from ..thinking import build_critique_prompt, parse_critique_response

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    sources = body.get("sources") or []
    if not task:
        return _api_error("task is required", "validation_error", 422)

    try:
        safe_task = check_user_task(task, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "reason_generator_critic",
            "label": task[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    generator_task = (
        safe_task
        + "\n\nProvide a concise research answer. Include citations as markdown links when available."
    )
    try:
        generated_resp, generator_provider = call_llm_with_fallback(
            [{"role": "user", "content": generator_task}],
            generator_task,
        )
        generated_answer = generated_resp.get("content") or str(generated_resp)

        critique_prompt = build_critique_prompt(generated_answer, task) + (
            "\n\nEnsure the revised answer preserves or improves citation quality with source links."
        )
        critic_resp, critic_provider = call_llm_with_fallback(
            [{"role": "user", "content": critique_prompt}],
            task,
        )
        critic_raw = critic_resp.get("content") or str(critic_resp)
        critique_data = parse_critique_response(critic_raw)
    except Exception:
        generated_answer = f"Initial draft: {task}"
        generator_provider = "offline-fallback"
        critic_provider = "offline-fallback"
        critique_data = {
            "revised": generated_answer,
            "critique": "No provider available; returned deterministic fallback.",
            "confidence": 0.5,
        }

    revised_answer = (critique_data.get("revised") or "").strip() or generated_answer
    critique_text = (critique_data.get("critique") or "").strip()
    try:
        confidence = float(critique_data.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    citation_meta = _score_citation_confidence(revised_answer, expected_sources=sources)

    return {
        "task": task,
        "generated_answer": generated_answer,
        "critique": critique_text,
        "revised_answer": revised_answer,
        "confidence": round(confidence, 3),
        "citation_confidence": citation_meta.get("score", 0.0),
        "citations": citation_meta.get("citations", []),
        "expected_source_coverage": citation_meta.get("expected_source_coverage"),
        "matched_expected_sources": citation_meta.get("matched_expected_sources", []),
        "providers": {
            "generator": generator_provider,
            "critic": critic_provider,
        },
    }


# ── Adaptive confidence routing helper ────────────────────────────────────

_ADAPTIVE_ROUTING_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "confidence_threshold": 0.6,
    "escalation_tries": 2,
}
_adaptive_routing_config: Dict[str, Any] = dict(_ADAPTIVE_ROUTING_DEFAULTS)

_ESCALATION_PROVIDERS = ["claude", "openai", "groq", "cerebras", "gemini", "mistral"]


def _call_llm_adaptive(messages: List[Dict], task: str = "") -> tuple:
    cfg = _adaptive_routing_config
    threshold = float(cfg.get("confidence_threshold", 0.6))
    tries = int(cfg.get("escalation_tries", 2))
    enabled = bool(cfg.get("enabled", True))

    result, provider = call_llm_with_fallback(messages, task)

    confidence = 1.0
    content = result.get("content", "")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            confidence = float(parsed.get("confidence", 1.0))
        except Exception:
            confidence = 1.0

    if not enabled or confidence >= threshold or tries <= 0:
        return result, provider, False, confidence

    escalated = False
    for attempt in range(tries):
        escalation_order = [p for p in _ESCALATION_PROVIDERS if p != provider]
        if not escalation_order:
            break
        try:
            better_result, better_provider = call_llm_with_fallback(
                messages,
                task,
            )
            better_content = better_result.get("content", "")
            better_confidence = 1.0
            if isinstance(better_content, str):
                try:
                    parsed2 = json.loads(better_content)
                    better_confidence = float(parsed2.get("confidence", 1.0))
                except Exception:
                    better_confidence = 1.0

            if better_confidence > confidence:
                result, provider, confidence = better_result, better_provider, better_confidence
                escalated = True

            if confidence >= threshold:
                break
        except Exception:
            break

    return result, provider, escalated, confidence


@router.get("/settings/adaptive-routing")
def get_adaptive_routing():
    return dict(_adaptive_routing_config)


@router.post("/settings/adaptive-routing")
async def update_adaptive_routing(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if "enabled" in body:
        _adaptive_routing_config["enabled"] = bool(body["enabled"])
    if "confidence_threshold" in body:
        val = float(body["confidence_threshold"])
        if not (0.0 <= val <= 1.0):
            return _api_error("confidence_threshold must be 0–1", "validation_error", 422)
        _adaptive_routing_config["confidence_threshold"] = val
    if "escalation_tries" in body:
        val = int(body["escalation_tries"])
        if not (0 <= val <= 5):
            return _api_error("escalation_tries must be 0–5", "validation_error", 422)
        _adaptive_routing_config["escalation_tries"] = val

    return dict(_adaptive_routing_config)


# ── Hypothesis testing loop endpoint ──────────────────────────────────────

@router.post("/reason/hypothesis")
async def reason_hypothesis(request: Request):
    """Structured hypothesis testing loop.

    POST body:
      {
        "observation": "The server response time increased 3x after the last deploy.",
        "max_hypotheses": 4
      }

    Returns generated hypotheses, test results for each, plus a final conclusion.
    """
    from ..thinking import (
        build_hypothesis_generation_prompt,
        build_hypothesis_test_prompt,
        build_hypothesis_conclusion_prompt,
        parse_hypothesis_generation,
        parse_hypothesis_test,
        parse_hypothesis_conclusion,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    observation = (body.get("observation") or "").strip()
    if not observation:
        return _api_error("observation is required", "validation_error", 422)

    try:
        safe_obs = check_user_task(observation, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input", "tool": "reason_hypothesis",
            "label": observation[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    max_h = max(1, min(int(body.get("max_hypotheses", 4)), 8))

    gen_prompt = build_hypothesis_generation_prompt(safe_obs, max_h)
    gen_resp, gen_provider = call_llm_with_fallback(
        [{"role": "user", "content": gen_prompt}], safe_obs
    )
    hypotheses = parse_hypothesis_generation(gen_resp.get("content") or str(gen_resp))

    tested: List[Dict[str, Any]] = []
    test_providers: List[str] = []
    for hyp in hypotheses:
        test_prompt = build_hypothesis_test_prompt(hyp["statement"], safe_obs)
        test_resp, test_provider = call_llm_with_fallback(
            [{"role": "user", "content": test_prompt}], safe_obs
        )
        test_result = parse_hypothesis_test(test_resp.get("content") or str(test_resp))
        tested.append({
            "id":               hyp["id"],
            "statement":        hyp["statement"],
            "initial_reasoning": hyp["initial_reasoning"],
            "initial_plausibility": hyp["plausibility"],
            **test_result,
        })
        test_providers.append(test_provider)

    conc_prompt = build_hypothesis_conclusion_prompt(safe_obs, tested)
    conc_resp, conc_provider = call_llm_with_fallback(
        [{"role": "user", "content": conc_prompt}], safe_obs
    )
    conclusion = parse_hypothesis_conclusion(conc_resp.get("content") or str(conc_resp))

    return {
        "observation":         safe_obs,
        "hypotheses_tested":   tested,
        "conclusion":          conclusion.get("conclusion", ""),
        "best_hypothesis_id":  conclusion.get("best_hypothesis_id", 0),
        "uncertainty":         conclusion.get("uncertainty", ""),
        "next_steps":          conclusion.get("next_steps", []),
        "overall_confidence":  conclusion.get("overall_confidence", 0.5),
        "providers": {
            "generator":    gen_provider,
            "testers":      test_providers,
            "conclusion":   conc_provider,
        },
    }
