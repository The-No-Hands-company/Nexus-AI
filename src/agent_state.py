"""
src/agent_state.py — Persistent agent state for long-horizon multi-session planning

Implements a persistent agent context store that survives HTTP request boundaries
and container restarts. Enables multi-day, multi-session planning by storing:
  - Planning graph: nodes (goals/subgoals) with edges (dependencies)
  - Working memory: current context and intermediate results
  - Execution history: completed actions and their outputs
  - Checkpoint state: last stable state for resumption after failure

State is persisted to DB using the existing _load_json_pref/_save_json_pref pattern.
Each agent run updates its persistent state at configurable checkpoints.

Environment variables:
    AGENT_STATE_MAX_HISTORY   — max history entries per agent (default: 500)
    AGENT_STATE_CHECKPOINT_N  — steps between automatic checkpoints (default: 5)
    AGENT_STATE_TTL_DAYS      — days before idle agent state is pruned (default: 30)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nexus.agent_state")

_MAX_HISTORY = int(__import__('os').getenv("AGENT_STATE_MAX_HISTORY", "500"))
_CHECKPOINT_EVERY = int(__import__('os').getenv("AGENT_STATE_CHECKPOINT_N", "5"))


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class PlanNode:
    node_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str = ""
    status: str = "pending"             # pending | in_progress | done | failed | skipped
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    result: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


@dataclass
class HistoryEntry:
    step: int
    action: str
    tool: str = ""
    tool_input: dict = field(default_factory=dict)
    output: str = ""
    success: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentState:
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id: str = ""
    username: str = ""
    persona_id: str = ""
    objective: str = ""
    status: str = "idle"                # idle | planning | executing | paused | done | failed
    plan_nodes: dict[str, PlanNode] = field(default_factory=dict)
    current_node_id: str | None = None
    working_memory: dict = field(default_factory=dict)
    history: list[HistoryEntry] = field(default_factory=list)
    step_count: int = 0
    checkpoint: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)


# ── Serialisation ─────────────────────────────────────────────────────────────

def _state_to_dict(state: AgentState) -> dict:
    return {
        "agent_id": state.agent_id, "session_id": state.session_id,
        "username": state.username, "persona_id": state.persona_id,
        "objective": state.objective, "status": state.status,
        "plan_nodes": {
            nid: {
                "node_id": n.node_id, "goal": n.goal, "status": n.status,
                "parent_id": n.parent_id, "children": n.children,
                "dependencies": n.dependencies, "result": n.result,
                "created_at": n.created_at, "completed_at": n.completed_at,
            }
            for nid, n in state.plan_nodes.items()
        },
        "current_node_id": state.current_node_id,
        "working_memory": state.working_memory,
        "history": [
            {
                "step": h.step, "action": h.action, "tool": h.tool,
                "tool_input": h.tool_input, "output": h.output[:500],
                "success": h.success, "timestamp": h.timestamp,
            }
            for h in state.history[-_MAX_HISTORY:]
        ],
        "step_count": state.step_count,
        "checkpoint": state.checkpoint,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "metadata": state.metadata,
    }


def _dict_to_state(d: dict) -> AgentState:
    plan_nodes = {
        nid: PlanNode(
            node_id=n.get("node_id", nid), goal=n.get("goal", ""),
            status=n.get("status", "pending"), parent_id=n.get("parent_id"),
            children=n.get("children", []), dependencies=n.get("dependencies", []),
            result=n.get("result", ""), created_at=n.get("created_at", ""),
            completed_at=n.get("completed_at"),
        )
        for nid, n in d.get("plan_nodes", {}).items()
    }
    history = [
        HistoryEntry(
            step=h.get("step", 0), action=h.get("action", ""),
            tool=h.get("tool", ""), tool_input=h.get("tool_input", {}),
            output=h.get("output", ""), success=h.get("success", True),
            timestamp=h.get("timestamp", ""),
        )
        for h in d.get("history", [])
    ]
    return AgentState(
        agent_id=d.get("agent_id", str(uuid.uuid4())[:12]),
        session_id=d.get("session_id", ""), username=d.get("username", ""),
        persona_id=d.get("persona_id", ""), objective=d.get("objective", ""),
        status=d.get("status", "idle"), plan_nodes=plan_nodes,
        current_node_id=d.get("current_node_id"),
        working_memory=d.get("working_memory", {}),
        history=history, step_count=d.get("step_count", 0),
        checkpoint=d.get("checkpoint", {}),
        created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
        metadata=d.get("metadata", {}),
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _save(state: AgentState) -> None:
    state.updated_at = datetime.now(timezone.utc).isoformat()
    try:
        from src.db import save_pref  # type: ignore
        save_pref(f"agent_state:{state.agent_id}", _state_to_dict(state))
    except Exception as exc:
        logger.error("agent_state save failed: %s", exc)


def _load(agent_id: str) -> AgentState | None:
    try:
        from src.db import load_pref  # type: ignore
        data = load_pref(f"agent_state:{agent_id}")
        if data:
            return _dict_to_state(data)
    except Exception as exc:
        logger.error("agent_state load failed: %s", exc)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def create_agent_state(
    objective: str,
    session_id: str = "",
    username: str = "",
    persona_id: str = "",
    metadata: dict | None = None,
) -> AgentState:
    """Create and persist a new agent state for a long-horizon task."""
    state = AgentState(
        session_id=session_id, username=username,
        persona_id=persona_id, objective=objective,
        metadata=metadata or {},
    )
    _save(state)
    return state


def get_agent_state(agent_id: str) -> AgentState | None:
    """Retrieve a persistent agent state by ID."""
    return _load(agent_id)


def add_plan_node(
    state: AgentState,
    goal: str,
    parent_id: str | None = None,
    dependencies: list[str] | None = None,
) -> PlanNode:
    """Add a new goal node to the agent's planning graph."""
    node = PlanNode(goal=goal, parent_id=parent_id, dependencies=dependencies or [])
    if parent_id and parent_id in state.plan_nodes:
        state.plan_nodes[parent_id].children.append(node.node_id)
    state.plan_nodes[node.node_id] = node
    _save(state)
    return node


def update_node_status(state: AgentState, node_id: str, status: str, result: str = "") -> bool:
    """Update the status and result of a plan node."""
    node = state.plan_nodes.get(node_id)
    if node is None:
        return False
    node.status = status
    node.result = result
    if status in ("done", "failed", "skipped"):
        node.completed_at = datetime.now(timezone.utc).isoformat()
    _save(state)
    return True


def record_step(
    state: AgentState,
    action: str,
    tool: str = "",
    tool_input: dict | None = None,
    output: str = "",
    success: bool = True,
) -> None:
    """Record an execution step in the agent's history."""
    state.step_count += 1
    entry = HistoryEntry(
        step=state.step_count, action=action, tool=tool,
        tool_input=tool_input or {}, output=output, success=success,
    )
    state.history.append(entry)
    # Auto-checkpoint
    if state.step_count % _CHECKPOINT_EVERY == 0:
        state.checkpoint = {
            "step": state.step_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_statuses": {nid: n.status for nid, n in state.plan_nodes.items()},
            "working_memory_snapshot": dict(state.working_memory),
        }
    _save(state)


def set_working_memory(state: AgentState, key: str, value: Any) -> None:
    state.working_memory[key] = value
    _save(state)


def get_working_memory(state: AgentState, key: str, default: Any = None) -> Any:
    return state.working_memory.get(key, default)


def complete_agent(state: AgentState, final_result: str = "") -> None:
    """Mark the agent run as completed."""
    state.status = "done"
    state.working_memory["final_result"] = final_result
    _save(state)


def get_plan_summary(state: AgentState) -> dict:
    """Return a concise summary of the planning graph status."""
    nodes = list(state.plan_nodes.values())
    return {
        "objective": state.objective,
        "status": state.status,
        "total_nodes": len(nodes),
        "done": sum(1 for n in nodes if n.status == "done"),
        "in_progress": sum(1 for n in nodes if n.status == "in_progress"),
        "pending": sum(1 for n in nodes if n.status == "pending"),
        "failed": sum(1 for n in nodes if n.status == "failed"),
        "step_count": state.step_count,
        "current_node": state.plan_nodes.get(state.current_node_id, {}).goal if state.current_node_id else None,
    }


def list_active_agents(username: str | None = None) -> list[dict]:
    """List active agent states from DB."""
    try:
        from src.db import _backend  # type: ignore
        conn = _backend._get_conn() if hasattr(_backend, "_get_conn") else None
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT key, value FROM user_prefs WHERE key LIKE 'agent_state:%'"
        ).fetchall()
        result = []
        for key, value_str in rows:
            try:
                data = json.loads(value_str) if isinstance(value_str, str) else value_str
                if username and data.get("username") != username:
                    continue
                if data.get("status") in ("idle", "done", "failed"):
                    continue
                result.append({
                    "agent_id": data.get("agent_id"),
                    "objective": data.get("objective", "")[:100],
                    "status": data.get("status"),
                    "username": data.get("username"),
                    "step_count": data.get("step_count", 0),
                    "updated_at": data.get("updated_at"),
                })
            except Exception:
                continue
        return result
    except Exception as exc:
        logger.debug("list_active_agents: %s", exc)
        return []
