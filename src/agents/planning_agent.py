"""
src/agents/planning_agent.py — Dedicated planning agent stub

Specialised agent that decomposes high-level goals into ordered,
verifiable subtask graphs for execution by other specialist agents.

This is a STUB — run() raises NotImplementedError until implemented.
"""

from __future__ import annotations

from .agent_base import AgentBase, AgentCapabilities


class PlanningAgent(AgentBase):
    """
    Decomposes a high-level goal into an ordered subtask graph.

    Returns a structured plan JSON that can be fed directly into
    ``src/autonomy.Orchestrator`` for execution.

    STUB: run() raises NotImplementedError.
    Implementation plan:
    - Use high-capability LLM with structured output / JSON mode
    - Validate plan schema (subtasks have: id, description, depends_on, tool, agent)
    - Estimate complexity and assign each subtask to best specialist agent
    - Return plan for caller to approve or execute
    """

    name = "planning_agent"
    description = (
        "Decomposes complex goals into ordered, verifiable subtask graphs "
        "with dependency tracking and agent assignment."
    )
    capabilities = AgentCapabilities(
        tools=[],           # planning agent does not call tools directly
        max_steps=8,
        supports_streaming=True,
        requires_approval=False,
        allowed_providers=[],
    )

    async def run(
        self,
        task: str,
        context: dict | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> dict:
        """Decompose task into a deterministic, dependency-ordered plan."""
        raw = (task or "").strip()
        if not raw:
            return {
                "task": task,
                "status": "invalid",
                "error": "task is required",
                "subtasks": [],
            }

        chunks = [
            c.strip(" .")
            for c in raw.replace(" then ", " and ").split(" and ")
            if c.strip(" .")
        ]
        if not chunks:
            chunks = [raw]

        subtasks = []
        for idx, chunk in enumerate(chunks, start=1):
            tool = "general"
            lowered = chunk.lower()
            if "test" in lowered:
                tool = "run_tests"
            elif "implement" in lowered or "code" in lowered:
                tool = "edit_code"
            elif "document" in lowered or "readme" in lowered:
                tool = "write_docs"

            subtasks.append(
                {
                    "id": f"step-{idx}",
                    "description": chunk,
                    "depends_on": [f"step-{idx - 1}"] if idx > 1 else [],
                    "tool": tool,
                    "agent": "coding_agent",
                }
            )

        return {
            "task": raw,
            "status": "ok",
            "subtasks": subtasks,
            "estimated_steps": len(subtasks),
            "session_id": session_id,
            "context_keys": sorted((context or {}).keys()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton for import convenience
# ---------------------------------------------------------------------------

planning_agent = PlanningAgent()
