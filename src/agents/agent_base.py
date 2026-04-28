"""
src/agents/agent_base.py — Base class for all Nexus AI specialist agents

All specialist agents should subclass AgentBase and implement `run()`.
Provides shared infrastructure: context injection, tool dispatch,
safety screening, execution tracing, and bus publishing.

This module is a STUB — `run()` raises NotImplementedError by default.
Subclasses must implement `run()`.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional


# ---------------------------------------------------------------------------
# Agent capability descriptor
# ---------------------------------------------------------------------------

@dataclass
class AgentCapabilities:
    """Declares what an agent can do."""
    tools: list[str] = field(default_factory=list)      # tool names this agent may call
    max_steps: int = 16                                  # max tool-call loop iterations
    supports_streaming: bool = True
    requires_approval: bool = False                      # always request HITL approval
    allowed_providers: list[str] = field(default_factory=list)  # empty = all providers


# ---------------------------------------------------------------------------
# Agent base class
# ---------------------------------------------------------------------------

class AgentBase(ABC):
    """
    Abstract base for all Nexus AI specialist agents.

    Subclasses must implement:
    - ``run(task, context, **kwargs)``

    Subclasses may override:
    - ``system_prompt`` property
    - ``pre_run_check(task, context)``
    - ``post_run_hook(result)``
    """

    name: str = "base"
    description: str = ""
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)

    def __init__(self) -> None:
        self._run_id: str | None = None

    # ---- lifecycle ---------------------------------------------------------

    def pre_run_check(self, task: str, context: dict) -> None:
        """
        Called before run(). Raise ValueError to abort.
        Default: no-op.
        """
        pass

    def post_run_hook(self, result: dict) -> None:
        """
        Called after run() completes. Default: no-op.
        Can be used to publish to agent_bus, update KG, log metrics.
        """
        pass

    @property
    def system_prompt(self) -> str:
        """Return the system prompt injected for this agent's LLM calls."""
        return f"You are {self.name}. {self.description}"

    # ---- execution ---------------------------------------------------------

    @abstractmethod
    async def run(
        self,
        task: str,
        context: dict | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> dict:
        """
        Execute the agent on *task*.

        Must return::
            {
                "output": str,
                "trace_id": str,
                "steps": list[dict],
                "status": "completed" | "failed" | "needs_approval"
            }
        """
        raise NotImplementedError(
            f"Agent '{self.name}' has not implemented run(). "
            "Subclass AgentBase and provide a run() method."
        )

    async def stream(
        self,
        task: str,
        context: dict | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> AsyncIterator[dict]:
        """
        Streaming variant of run(). Yields SSE-style event dicts.

        Default: falls back to non-streaming run() and yields a single done event.
        Override in subclass for true streaming.
        """
        result = await self.run(task, context=context, session_id=session_id, **kwargs)
        yield {"type": "done", "data": result}

    # ---- helpers -----------------------------------------------------------

    def _new_run_id(self) -> str:
        self._run_id = str(uuid.uuid4())
        return self._run_id

    def _trace_step(self, step_type: str, payload: dict) -> dict:
        return {
            "run_id": self._run_id,
            "agent": self.name,
            "step_type": step_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
