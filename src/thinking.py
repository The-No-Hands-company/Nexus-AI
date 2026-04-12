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
