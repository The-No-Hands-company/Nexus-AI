from __future__ import annotations

import json
from typing import Any


def _json_or_none(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_tot_prompt(task: str, candidates: int = 3) -> str:
    return (
        f"Tree-of-Thought planner. Generate exactly {candidates} candidate solution paths for: {task}\n"
        "Return strict JSON with steps."
    )


def parse_tot_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return parsed
    return {"steps": [response], "confidence": 0.5}


def build_critique_prompt(answer: str, question: str) -> str:
    return (
        "You are a self-critique assistant. Review the answer against the question, identify gaps, "
        "and return JSON with critique, revised, confidence.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}"
    )


def parse_critique_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return {
            "critique": str(parsed.get("critique", "")),
            "revised": str(parsed.get("revised", parsed.get("answer", ""))),
            "confidence": float(parsed.get("confidence", 0.5)),
        }
    return {"critique": response, "revised": response, "confidence": 0.5}


def build_got_prompt(task: str) -> str:
    return (
        "Graph-of-Thought reasoning agent. Respond in JSON with nodes, edges, merges, conclusion, confidence.\n"
        f"Task: {task}"
    )


def parse_got_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        nodes = list(parsed.get("nodes", []))
        edges = list(parsed.get("edges", []))
        merges = list(parsed.get("merges", []))
        reasoning = json.dumps({"nodes": nodes, "edges": edges, "merges": merges}, ensure_ascii=False)
        return {
            "nodes": nodes,
            "edges": edges,
            "merges": merges,
            "conclusion": str(parsed.get("conclusion", "")),
            "confidence": float(parsed.get("confidence", 0.5)),
            "reasoning": reasoning,
        }
    return {
        "nodes": [],
        "edges": [],
        "merges": [],
        "conclusion": response,
        "confidence": 0.5,
        "reasoning": response,
    }


def parse_consensus_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return {
            "approach1": parsed.get("approach1", ""),
            "approach2": parsed.get("approach2", ""),
            "approach3": parsed.get("approach3", ""),
            "consensus": str(parsed.get("consensus", "")),
            "confidence": float(parsed.get("confidence", 0.5)),
        }
    return {"approach1": "", "approach2": "", "approach3": "", "consensus": response, "confidence": 0.5}


def build_verification_prompt(claim: str, steps: list[str] | None = None, domain: str = "general") -> str:
    steps_blob = ""
    if steps:
        steps_blob = "\nProof steps: " + json.dumps(steps, ensure_ascii=False)
    return (
        f"You are a formal verification agent. Verify the following claim in the domain of {domain} "
        "and return strict JSON.\n"
        "JSON schema: {\"steps\": [{\"step\": int, \"valid\": bool, \"issue\": string}], "
        "\"overall\": \"valid|invalid|uncertain\", \"confidence\": number, "
        "\"corrected_claim\": string, \"explanation\": string}\n"
        f"Claim: {claim}{steps_blob}"
    )


def parse_verification_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return parsed
    return {"overall": "unknown", "confidence": 0.5, "explanation": response, "steps": []}


def build_reflection_prompt(answer: str, task: str, tool_trace: list | None = None) -> str:
    trace_blob = ""
    if tool_trace:
        trace_blob = "\nTool trace: " + json.dumps(list(tool_trace), ensure_ascii=False)
    return f"Reflect on whether this answer fully solves the task.\nTask: {task}\nAnswer: {answer}{trace_blob}"


def parse_reflection_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return parsed
    return {"reflection": response, "confidence": 0.5}


def build_socratic_prompt(topic: str, depth: int = 3) -> str:
    return (
        f"Socratic reasoning agent. Decompose the following topic into a recursive "
        f"question hierarchy (depth={depth}) and return strict JSON.\n"
        "JSON schema: {\"root_question\": string, \"sub_questions\": "
        "[{\"question\": string, \"sub_questions\": [...]}]}\n"
        f"Topic: {topic}"
    )


def parse_socratic_response(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if isinstance(parsed, dict):
        return {
            "root_question": str(parsed.get("root_question", "")),
            "sub_questions": list(parsed.get("sub_questions", [])),
        }
    return {"root_question": str(response), "sub_questions": []}


def build_socratic_answer_prompt(topic: str, question_tree: dict[str, Any]) -> str:
    tree_blob = json.dumps(question_tree, ensure_ascii=False)
    return (
        "Answer the following question hierarchy with a concise synthesis.\n"
        f"Topic: {topic}\nQuestion tree: {tree_blob}"
    )


def build_mcts_steps_prompt(goal: str, branching: int) -> str:
    return (
        f"Monte Carlo Tree Search planner. Generate exactly {branching} concrete action steps "
        f"as a JSON object with a 'steps' key containing a list of strings.\n"
        f"Goal: {goal}"
    )


def build_mcts_score_prompt(goal: str, steps: list[str]) -> str:
    steps_blob = json.dumps(steps, ensure_ascii=False)
    return (
        "Score this plan on a 0.0–1.0 scale for feasibility and completeness.\n"
        "Return JSON: {\"score\": number, \"rationale\": string}\n"
        f"Goal: {goal}\nPlan: {steps_blob}"
    )


def run_mcts_planning(
    goal: str,
    llm_fn: Any = None,
    iterations: int = 3,
    max_depth: int = 2,
    branching: int = 3,
) -> dict[str, Any]:
    """LLM-backed MCTS-inspired planner.

    When *llm_fn* is provided it is used to generate and score candidate plans.
    Falls back to a deterministic split when no LLM callback is available.
    """
    if llm_fn is None:
        # Deterministic fallback (no LLM available)
        steps = [
            segment.strip()
            for segment in str(goal).replace(" and ", ",").split(",")
            if segment.strip()
        ]
        steps = steps or [goal]
        plan = steps[: max(1, min(max_depth, len(steps)))]
        return {
            "best_plan": plan,
            "best_score": 0.5,
            "best_rationale": "deterministic fallback",
            "tree_size": len(plan),
            "iterations": iterations,
            "all_plans": [plan],
        }

    all_plans: list[dict[str, Any]] = []
    best_score = -1.0
    best_plan: list[str] = []
    best_rationale = ""

    for _ in range(max(1, iterations)):
        # --- expansion: ask the LLM to generate candidate steps ---
        steps_raw = llm_fn(build_mcts_steps_prompt(goal, branching))
        steps_parsed = _json_or_none(steps_raw) if isinstance(steps_raw, str) else steps_raw
        if isinstance(steps_parsed, dict):
            candidate_steps = [str(s) for s in steps_parsed.get("steps", [])]
        else:
            candidate_steps = [str(steps_raw)] if steps_raw else [goal]

        candidate_steps = candidate_steps[:max_depth] or [goal]

        # --- evaluation: score this plan ---
        score_raw = llm_fn(build_mcts_score_prompt(goal, candidate_steps))
        score_parsed = _json_or_none(score_raw) if isinstance(score_raw, str) else score_raw
        if isinstance(score_parsed, dict):
            score = float(score_parsed.get("score", 0.5))
            rationale = str(score_parsed.get("rationale", ""))
        else:
            score = 0.5
            rationale = str(score_raw)

        all_plans.append({"steps": candidate_steps, "score": score, "rationale": rationale})

        if score > best_score:
            best_score = score
            best_plan = candidate_steps
            best_rationale = rationale

    return {
        "best_plan": best_plan,
        "best_score": best_score,
        "best_rationale": best_rationale,
        "tree_size": len(all_plans),
        "iterations": iterations,
        "all_plans": all_plans,
    }


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, v))


def build_debate_position_prompt(claim: str, role: str, prior_round: str = "") -> str:
    side = "PROPONENT"
    direction = "FOR"
    if str(role).strip().lower() == "critic":
        side = "CRITIC"
        direction = "AGAINST"
    opponent = f"\nOpponent prior argument: {prior_round}" if prior_round else ""
    return (
        f"You are the {side}. Argue {direction} this claim and respond as strict JSON.\n"
        "JSON schema: {\"argument\": string, \"key_points\": [string], \"confidence\": number}\n"
        f"Claim: {claim}{opponent}"
    )


def parse_debate_turn(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is not None:
        return {
            "argument": str(parsed.get("argument", "")),
            "key_points": [str(x) for x in list(parsed.get("key_points", []))],
            "confidence": _clamp01(parsed.get("confidence", 0.5)),
        }
    return {"argument": str(response), "key_points": [], "confidence": 0.5}


def build_debate_verdict_prompt(claim: str, transcript: list[dict[str, Any]]) -> str:
    rounds_blob = json.dumps(transcript, ensure_ascii=False)
    return (
        "You are an impartial judge. Evaluate the debate and return strict JSON.\n"
        "JSON schema: "
        "{\"verdict\": \"supported|refuted|inconclusive\", \"synthesis\": string, "
        "\"strongest_proponent_point\": string, \"strongest_critic_point\": string, "
        "\"confidence\": number}\n"
        f"Claim: {claim}\nTranscript: {rounds_blob}"
    )


def parse_debate_verdict(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is None:
        return {
            "verdict": "inconclusive",
            "synthesis": str(response),
            "strongest_proponent_point": "",
            "strongest_critic_point": "",
            "confidence": 0.5,
        }
    verdict = str(parsed.get("verdict", "inconclusive")).strip().lower()
    if verdict not in {"supported", "refuted", "inconclusive"}:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "synthesis": str(parsed.get("synthesis", "")),
        "strongest_proponent_point": str(parsed.get("strongest_proponent_point", "")),
        "strongest_critic_point": str(parsed.get("strongest_critic_point", "")),
        "confidence": _clamp01(parsed.get("confidence", 0.5)),
    }


def build_hypothesis_generation_prompt(observation: str, max_hypotheses: int = 4) -> str:
    cap = max(1, min(int(max_hypotheses), 8))
    return (
        "Generate candidate hypotheses as strict JSON.\n"
        "JSON schema: {\"hypotheses\": [{\"id\": int, \"statement\": string, "
        "\"initial_reasoning\": string, \"plausibility\": number}]}\n"
        f"Observation: {observation}\nMaximum hypotheses: {cap}"
    )


def parse_hypothesis_generation(response: str) -> list[dict[str, Any]]:
    parsed = _json_or_none(response)
    if parsed is None:
        return [{
            "id": 1,
            "statement": str(response),
            "initial_reasoning": "",
            "plausibility": 0.5,
        }]

    raw_hypotheses = list(parsed.get("hypotheses", []))
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_hypotheses, start=1):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": int(item.get("id", idx)),
                "statement": str(item.get("statement", "")),
                "initial_reasoning": str(item.get("initial_reasoning", "")),
                "plausibility": _clamp01(item.get("plausibility", 0.5)),
            }
        )
    if not result:
        return [{"id": 1, "statement": str(response), "initial_reasoning": "", "plausibility": 0.5}]
    return result


def build_hypothesis_test_prompt(statement: str, observation: str) -> str:
    return (
        "Test this hypothesis against the observation and return strict JSON.\n"
        "JSON schema: {\"evidence_for\": [string], \"evidence_against\": [string], "
        "\"assumptions\": [string], \"verdict\": string, \"confidence\": number, "
        "\"explanation\": string}\n"
        f"Observation: {observation}\nHypothesis: {statement}"
    )


def parse_hypothesis_test(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is None:
        return {
            "evidence_for": [],
            "evidence_against": [],
            "assumptions": [],
            "verdict": "inconclusive",
            "confidence": 0.5,
            "explanation": str(response),
        }
    return {
        "evidence_for": [str(x) for x in list(parsed.get("evidence_for", []))],
        "evidence_against": [str(x) for x in list(parsed.get("evidence_against", []))],
        "assumptions": [str(x) for x in list(parsed.get("assumptions", []))],
        "verdict": str(parsed.get("verdict", "inconclusive")),
        "confidence": _clamp01(parsed.get("confidence", 0.5)),
        "explanation": str(parsed.get("explanation", "")),
    }


def build_hypothesis_conclusion_prompt(observation: str, tested: list[dict[str, Any]]) -> str:
    tested_blob = json.dumps(tested, ensure_ascii=False)
    return (
        "Synthesize tested hypotheses and return strict JSON.\n"
        "JSON schema: {\"conclusion\": string, \"best_hypothesis_id\": int, "
        "\"uncertainty\": string, \"next_steps\": [string], \"overall_confidence\": number}\n"
        f"Observation: {observation}\nTested hypotheses: {tested_blob}"
    )


def parse_hypothesis_conclusion(response: str) -> dict[str, Any]:
    parsed = _json_or_none(response)
    if parsed is None:
        return {
            "conclusion": str(response),
            "best_hypothesis_id": 0,
            "uncertainty": "unknown",
            "next_steps": [],
            "overall_confidence": 0.5,
        }
    return {
        "conclusion": str(parsed.get("conclusion", "")),
        "best_hypothesis_id": int(parsed.get("best_hypothesis_id", 0) or 0),
        "uncertainty": str(parsed.get("uncertainty", "")),
        "next_steps": [str(x) for x in list(parsed.get("next_steps", []))],
        "overall_confidence": _clamp01(parsed.get("overall_confidence", 0.5)),
    }