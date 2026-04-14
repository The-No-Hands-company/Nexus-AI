"""
Phase 1 reasoning helpers — Tree-of-Thought, Graph-of-Thought, self-critique,
cross-model consensus.
"""
import json


def build_tot_prompt(query: str, mode: str = "tree") -> str:
    """Build a Tree-of-Thought reasoning prompt."""
    question = "Question: " + query
    steps = (
        "Think step by step, exploring multiple reasoning branches.\n"
        "For each branch, note: assumption, reasoning, and conclusion.\n"
        "Then choose the best path and explain why."
    )
    json_fmt = (
        'Reply ONLY with valid JSON: '
        '{"action":"think","thought":"<your reasoning>",'
        '"steps":["<step1>","<step2>",...],"best_path":"<why this path>"}'
    )
    return question + "\n\n" + steps + "\n\n" + json_fmt


def build_critique_prompt(answer: str, question: str) -> str:
    """Build a self-critique prompt."""
    return (
        "You are reviewing your own answer for quality and accuracy.\n\n"
        "Original question: " + question + "\n\n"
        "Your answer:\n" + answer + "\n\n"
        "Critique: Identify weaknesses, gaps, and suggest improvements.\n"
        "Then provide a revised, better answer.\n\n"
        'Reply ONLY with valid JSON: '
        '{"critique":"<your critique>","revised":"<improved answer>","confidence":0.85}'
    )


def build_consensus_prompt(task: str, n_models: int = 3) -> str:
    """Build a cross-model consensus prompt."""
    return (
        "You are running a cross-model consensus check.\n"
        "Run this task with " + str(n_models) + " different reasoning approaches:\n\n"
        + task + "\n\n"
        "Approach 1: <your first approach and result>\n"
        "Approach 2: <a different approach>\n"
        "Approach 3: <yet another angle>\n\n"
        "Then reconcile into the most reliable consensus answer.\n\n"
        'Reply ONLY with valid JSON: '
        '{"approach1":"<result1>","approach2":"<result2>","approach3":"<result3>",'
        '"consensus":"<final reconciled answer>","confidence":0.9}'
    )


def parse_tot_response(response: str) -> dict:
    """Parse a Tree-of-Thought LLM response."""
    try:
        data = json.loads(response)
        thought = data.get("thought", "")
        steps = data.get("steps", [])
        best_path = data.get("best_path", "")
        reasoning = thought
        if steps:
            reasoning += "\n\nSteps:\n" + "\n".join("  %d. %s" % (i + 1, s) for i, s in enumerate(steps))
        if best_path:
            reasoning += "\n\nBest path: " + best_path
        return {"reasoning": reasoning, "data": data}
    except Exception:
        return {"reasoning": response, "data": {}}


def parse_critique_response(response: str) -> dict:
    """Parse a self-critique LLM response."""
    try:
        return json.loads(response)
    except Exception:
        return {"critique": response, "revised": response, "confidence": 0.5}


def build_got_prompt(query: str) -> str:
    """Build a Graph-of-Thought reasoning prompt.

    Unlike Tree-of-Thought (which only branches), GoT allows thoughts to
    merge back and cross-reference, enabling richer synthesis.
    """
    return (
        "You are performing Graph-of-Thought reasoning.\n\n"
        "Question: " + query + "\n\n"
        "Build a directed reasoning graph:\n"
        "  - NODES: individual atomic thoughts / sub-conclusions\n"
        "  - EDGES: which node's insight feeds into which\n"
        "  - MERGES: where multiple branches converge\n"
        "  - CONCLUSION: the final synthesised answer after traversing the graph\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"nodes": [{"id": "n1", "thought": "..."}], '
        '"edges": [{"from": "n1", "to": "n2", "relation": "supports"}], '
        '"merges": [{"inputs": ["n2", "n3"], "output": "n4", "synthesis": "..."}], '
        '"conclusion": "<final answer>", "confidence": 0.9}'
    )


def parse_got_response(response: str) -> dict:
    """Parse a Graph-of-Thought LLM response.

    Returns a dict with at minimum:
        nodes, edges, merges, conclusion, confidence, reasoning (human-readable)
    """
    try:
        data = json.loads(response)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        merges = data.get("merges", [])
        conclusion = data.get("conclusion", "")

        lines = []
        if nodes:
            lines.append("**Thought nodes:**")
            for n in nodes:
                lines.append(f"  [{n.get('id','?')}] {n.get('thought','')}")
        if edges:
            lines.append("\n**Reasoning edges:**")
            for e in edges:
                lines.append(
                    f"  {e.get('from','?')} → {e.get('to','?')}"
                    + (f" ({e.get('relation','')})" if e.get("relation") else "")
                )
        if merges:
            lines.append("\n**Merge points:**")
            for m in merges:
                inputs = ", ".join(m.get("inputs", []))
                lines.append(f"  [{inputs}] → [{m.get('output','?')}]: {m.get('synthesis','')}")
        if conclusion:
            lines.append(f"\n**Conclusion:** {conclusion}")

        reasoning = "\n".join(lines) if lines else str(data)
        return {"nodes": nodes, "edges": edges, "merges": merges,
                "conclusion": conclusion, "confidence": data.get("confidence", 0.8),
                "reasoning": reasoning, "data": data}
    except Exception:
        return {"nodes": [], "edges": [], "merges": [], "conclusion": response,
                "confidence": 0.5, "reasoning": response, "data": {}}


def parse_consensus_response(response: str) -> dict:
    """Parse a cross-model consensus LLM response (from build_consensus_prompt)."""
    try:
        data = json.loads(response)
        return {
            "approach1":  data.get("approach1", ""),
            "approach2":  data.get("approach2", ""),
            "approach3":  data.get("approach3", ""),
            "consensus":  data.get("consensus", ""),
            "confidence": float(data.get("confidence", 0.8)),
        }
    except Exception:
        return {
            "approach1": "", "approach2": "", "approach3": "",
            "consensus": response, "confidence": 0.5,
        }


# ── Multi-agent debate helpers ─────────────────────────────────────────────

def build_debate_position_prompt(claim: str, role: str, prior_round: str = "") -> str:
    """Build a debate round prompt for 'proponent' or 'critic' role.

    ``role`` must be ``"proponent"`` or ``"critic"``.
    ``prior_round`` is the opponent's previous argument (empty for round 1).
    """
    if role == "proponent":
        persona = (
            "You are the PROPONENT.  Your job is to argue strongly in FAVOUR of "
            "the following claim, presenting the best possible evidence and reasoning."
        )
        stance = "Argue FOR"
    else:
        persona = (
            "You are the CRITIC.  Your job is to argue strongly AGAINST the "
            "following claim, identifying weaknesses, counter-evidence, and risks."
        )
        stance = "Argue AGAINST"

    prior_section = (
        f"\n\nOpponent's previous argument:\n{prior_round}\n\nRespond directly to the "
        "opponent's points and advance your own position.\n"
        if prior_round else ""
    )

    return (
        persona + "\n\n"
        "Claim: " + claim + "\n"
        + prior_section
        + f"\n{stance} the claim above.\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"argument": "<your argument>", "key_points": ["<point1>", "<point2>"], '
        '"confidence": 0.8}'
    )


def build_debate_verdict_prompt(claim: str, rounds: list) -> str:
    """Build a final verdict prompt that synthesises the full debate transcript."""
    transcript_parts = []
    for i, r in enumerate(rounds, 1):
        transcript_parts.append(f"Round {i} — Proponent: {r.get('proponent', '')}")
        transcript_parts.append(f"Round {i} — Critic: {r.get('critic', '')}")
    transcript = "\n\n".join(transcript_parts)

    return (
        "You are an impartial judge evaluating the following debate.\n\n"
        "Claim: " + claim + "\n\n"
        "Complete debate transcript:\n" + transcript + "\n\n"
        "Weigh the arguments on both sides. "
        "Provide a verdict, overall confidence, and a nuanced synthesis.\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"verdict": "supported|refuted|inconclusive", "synthesis": "<balanced summary>", '
        '"strongest_proponent_point": "<best argument for>", '
        '"strongest_critic_point": "<best argument against>", '
        '"confidence": 0.75}'
    )


def parse_debate_turn(response: str) -> dict:
    """Parse a single debate turn response."""
    try:
        data = json.loads(response)
        return {
            "argument":    data.get("argument", response),
            "key_points":  data.get("key_points", []),
            "confidence":  float(data.get("confidence", 0.5)),
        }
    except Exception:
        return {"argument": response, "key_points": [], "confidence": 0.5}


def parse_debate_verdict(response: str) -> dict:
    """Parse the final judge verdict response."""
    try:
        data = json.loads(response)
        return {
            "verdict":                    data.get("verdict", "inconclusive"),
            "synthesis":                  data.get("synthesis", response),
            "strongest_proponent_point":  data.get("strongest_proponent_point", ""),
            "strongest_critic_point":     data.get("strongest_critic_point", ""),
            "confidence":                 float(data.get("confidence", 0.5)),
        }
    except Exception:
        return {
            "verdict":                    "inconclusive",
            "synthesis":                  response,
            "strongest_proponent_point":  "",
            "strongest_critic_point":     "",
            "confidence":                 0.5,
        }


# ── Hypothesis testing helpers ──────────────────────────────────────────────

def build_hypothesis_generation_prompt(observation: str, num_hypotheses: int = 4) -> str:
    """Build a prompt that generates multiple competing hypotheses for an observation."""
    return (
        "You are a scientific thinker.  Given the observation below, generate "
        f"{num_hypotheses} distinct, competing hypotheses that could explain it.\n\n"
        "Observation: " + observation + "\n\n"
        "For each hypothesis, provide: a concise statement, the reasoning that "
        "supports it, and an initial plausibility score (0-1).\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"hypotheses": ['
        '{"id": 1, "statement": "...", "initial_reasoning": "...", "plausibility": 0.7}, '
        '{"id": 2, "statement": "...", "initial_reasoning": "...", "plausibility": 0.5}'
        ']}'
    )


def build_hypothesis_test_prompt(hypothesis: str, observation: str) -> str:
    """Build a prompt that rigorously tests a single hypothesis against evidence."""
    return (
        "You are a rigorous scientist testing a hypothesis.\n\n"
        "Observation: " + observation + "\n"
        "Hypothesis: " + hypothesis + "\n\n"
        "1. List evidence that SUPPORTS this hypothesis.\n"
        "2. List evidence that CONTRADICTS this hypothesis.\n"
        "3. Identify assumptions required for this hypothesis to hold.\n"
        "4. Provide a final verdict: accept / reject / uncertain.\n"
        "5. Provide a revised confidence score (0-1).\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"evidence_for": ["<ev1>", "<ev2>"], '
        '"evidence_against": ["<ev1>", "<ev2>"], '
        '"assumptions": ["<a1>", "<a2>"], '
        '"verdict": "accept", '
        '"confidence": 0.8, '
        '"explanation": "<brief explanation>"}'
    )


def build_hypothesis_conclusion_prompt(observation: str, results: list) -> str:
    """Build a prompt that draws a final conclusion from all tested hypotheses."""
    summaries = []
    for r in results:
        summaries.append(
            f"  H{r.get('id', '?')}: {r.get('statement', '')} → "
            f"{r.get('verdict', '?')} (confidence {r.get('confidence', 0):.2f})"
        )
    summary_text = "\n".join(summaries)

    return (
        "You are drawing a final scientific conclusion.\n\n"
        "Observation: " + observation + "\n\n"
        "Tested hypotheses and results:\n" + summary_text + "\n\n"
        "Based on the evidence, state the most supported conclusion, "
        "note any remaining uncertainty, and suggest next investigative steps.\n\n"
        'Reply ONLY with valid JSON:\n'
        '{"conclusion": "<final conclusion>", '
        '"best_hypothesis_id": 1, '
        '"uncertainty": "<remaining uncertainty>", '
        '"next_steps": ["<step1>", "<step2>"], '
        '"overall_confidence": 0.75}'
    )


def parse_hypothesis_generation(response: str) -> list:
    """Parse the hypothesis generation LLM response."""
    try:
        data = json.loads(response)
        hyps = data.get("hypotheses", [])
        out = []
        for h in hyps:
            out.append({
                "id":                int(h.get("id", 0)),
                "statement":         str(h.get("statement", "")),
                "initial_reasoning": str(h.get("initial_reasoning", "")),
                "plausibility":      float(h.get("plausibility", 0.5)),
            })
        return out
    except Exception:
        return [{"id": 1, "statement": response, "initial_reasoning": "", "plausibility": 0.5}]


def parse_hypothesis_test(response: str) -> dict:
    """Parse a single hypothesis test response."""
    try:
        data = json.loads(response)
        return {
            "evidence_for":     data.get("evidence_for", []),
            "evidence_against": data.get("evidence_against", []),
            "assumptions":      data.get("assumptions", []),
            "verdict":          data.get("verdict", "uncertain"),
            "confidence":       float(data.get("confidence", 0.5)),
            "explanation":      data.get("explanation", ""),
        }
    except Exception:
        return {
            "evidence_for": [], "evidence_against": [], "assumptions": [],
            "verdict": "uncertain", "confidence": 0.5, "explanation": response,
        }


def parse_hypothesis_conclusion(response: str) -> dict:
    """Parse the final hypothesis conclusion response."""
    try:
        data = json.loads(response)
        return {
            "conclusion":         data.get("conclusion", response),
            "best_hypothesis_id": int(data.get("best_hypothesis_id", 0)),
            "uncertainty":        data.get("uncertainty", ""),
            "next_steps":         data.get("next_steps", []),
            "overall_confidence": float(data.get("overall_confidence", 0.5)),
        }
    except Exception:
        return {
            "conclusion":         response,
            "best_hypothesis_id": 0,
            "uncertainty":        "",
            "next_steps":         [],
            "overall_confidence": 0.5,
        }
