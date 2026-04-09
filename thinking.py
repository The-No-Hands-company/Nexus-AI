"""
Phase 1 reasoning helpers — Tree-of-Thought, self-critique, cross-model consensus.
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
