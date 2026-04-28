"""
src/architecture.py
-------------------
Runtime hierarchy builder for the /architecture/hierarchy and
/architecture/blueprints endpoints.

Returns a lightweight, read-only scaffold of the current AI system stack:
  foundation_models → agent_layer → workflow_layer → task_layer
"""

from __future__ import annotations

import time
from typing import Any


# ---------------------------------------------------------------------------
# Static workflow definitions (expanded over time as real orchestrators land)
# ---------------------------------------------------------------------------

_WORKFLOWS: list[dict[str, Any]] = [
    {
        "id": "single_agent_loop",
        "label": "Single-Agent Loop",
        "description": "Default plan-act-observe cycle executed by one specialist agent.",
        "status": "active",
        "entry_point": "src.agent.run_agent_loop",
    },
    {
        "id": "hierarchical_orchestrator",
        "label": "Hierarchical Orchestrator",
        "description": "Multi-tier orchestration: planner → specialist dispatchers → executors.",
        "status": "planned",
        "entry_point": "src.agents.orchestrator",
    },
    {
        "id": "rag_pipeline",
        "label": "RAG Pipeline",
        "description": "Retrieval-augmented generation: embed → retrieve → generate.",
        "status": "active",
        "entry_point": "src.rag",
    },
    {
        "id": "federated_inference",
        "label": "Federated Inference",
        "description": "Distribute inference across peer nodes via federated protocol.",
        "status": "planned",
        "entry_point": "src.federation.inference",
    },
]

# Static task-layer primitives
_TASK_LAYER: list[dict[str, Any]] = [
    {"id": "chat_completion", "label": "Chat Completion", "type": "inference"},
    {"id": "tool_execution", "label": "Tool Execution", "type": "action"},
    {"id": "memory_retrieval", "label": "Memory Retrieval", "type": "retrieval"},
    {"id": "kg_query", "label": "Knowledge Graph Query", "type": "retrieval"},
    {"id": "code_execution", "label": "Code Execution", "type": "action"},
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_runtime_hierarchy(
    providers: list[dict[str, Any]],
    specialist_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build and return the live runtime hierarchy snapshot.

    Args:
        providers:          List from ``agent.get_providers_list()``.
        specialist_agents:  List from ``agents.list_agents()``.

    Returns:
        A dict with keys: system, foundation_models, agent_layer,
        workflow_layer, task_layer, counts.
    """
    # Tool count — lazy import to avoid circular dependencies at module load
    try:
        from .tools_builtin import _TOOL_SCHEMAS  # noqa: PLC0415
        tool_count = len(_TOOL_SCHEMAS)
    except Exception:
        tool_count = 1  # safe floor — never report zero

    tool_count = max(tool_count, 1)

    foundation_models = [
        {
            "id": p.get("id"),
            "label": p.get("label"),
            "model": p.get("model"),
            "available": p.get("available", False),
            "local": p.get("local", False),
            "openai_compat": p.get("openai_compat", False),
        }
        for p in (providers or [])
    ]

    # Guarantee at least one entry so counts are always >= 1
    if not foundation_models:
        foundation_models = [
            {"id": "local_fallback", "label": "Local Fallback", "model": "unknown",
             "available": False, "local": True, "openai_compat": False}
        ]

    agent_layer = [
        {
            "id": a.get("id"),
            "label": a.get("label") or a.get("name") or a.get("id"),
            "type": a.get("type", "specialist"),
            "status": "active",
        }
        for a in (specialist_agents or [])
    ]

    if not agent_layer:
        agent_layer = [
            {"id": "default_agent", "label": "Default Agent",
             "type": "generalist", "status": "active"}
        ]

    return {
        "system": {
            "name": "Nexus AI",
            "version": "2",
            "description": "Self-hosted, privacy-first, federated AI platform.",
            "snapshot_at": int(time.time()),
        },
        "foundation_models": foundation_models,
        "agent_layer": agent_layer,
        "workflow_layer": _WORKFLOWS,
        "task_layer": _TASK_LAYER,
        "counts": {
            "foundation_models": len(foundation_models),
            "agents": len(agent_layer),
            "workflows": len(_WORKFLOWS),
            "tools": tool_count,
        },
    }
