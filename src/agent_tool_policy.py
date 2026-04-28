"""
src/agent_tool_policy.py — Per-agent tool-use policy enforcement

Defines which tools each agent persona is allowed to call, enforced at the
agent dispatch layer before any tool is executed.

Policy levels:
  - allowlist: agent can only call listed tools
  - denylist:  agent can call anything EXCEPT listed tools
  - unrestricted: agent can call any tool (default when no policy defined)

Policies are registered per persona_id and persisted to DB for cross-restart
consistency.

Usage:
    from src.agent_tool_policy import get_policy, check_tool_allowed, set_policy

    policy = get_policy("code_review_agent")
    if not check_tool_allowed("code_review_agent", "run_command"):
        raise PermissionError("Tool not allowed for this agent persona")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.agent_tool_policy")


@dataclass
class ToolPolicy:
    persona_id: str
    mode: str = "unrestricted"              # "allowlist" | "denylist" | "unrestricted"
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    max_calls_per_session: int = 0          # 0 = unlimited
    require_approval_for: list[str] = field(default_factory=list)  # tools that need HITL
    description: str = ""


# ── Pre-built policies for common persona types ───────────────────────────────

DEFAULT_POLICIES: dict[str, ToolPolicy] = {
    "readonly_agent": ToolPolicy(
        persona_id="readonly_agent",
        mode="allowlist",
        allowed_tools=["search", "browse_web", "read_file", "list_files", "query_db",
                       "inspect_sqlite", "sqlite_query", "rag_search", "get_memory"],
        description="Read-only agent: can search and read but not write or execute.",
    ),
    "coding_agent": ToolPolicy(
        persona_id="coding_agent",
        mode="denylist",
        denied_tools=["delete_user", "drop_table", "admin_reset", "send_email"],
        require_approval_for=["run_command", "write_file"],
        max_calls_per_session=100,
        description="Coding agent: can use most tools but requires HITL for shell and writes.",
    ),
    "research_agent": ToolPolicy(
        persona_id="research_agent",
        mode="allowlist",
        allowed_tools=["search", "browse_web", "rag_search", "get_memory",
                       "summarize", "translate", "extract_pdf", "read_file"],
        max_calls_per_session=50,
        description="Research agent: web and document access only.",
    ),
    "admin_agent": ToolPolicy(
        persona_id="admin_agent",
        mode="unrestricted",
        require_approval_for=["delete_user", "admin_reset", "run_command"],
        description="Admin agent: unrestricted tools but sensitive ops need HITL approval.",
    ),
    "customer_support_agent": ToolPolicy(
        persona_id="customer_support_agent",
        mode="allowlist",
        allowed_tools=["search", "rag_search", "query_db", "get_user_info",
                       "send_email", "create_ticket", "get_memory"],
        max_calls_per_session=30,
        description="Support agent: CRM and search tools only.",
    ),
}

# Runtime registry (in-memory + DB)
_policies: dict[str, ToolPolicy] = dict(DEFAULT_POLICIES)


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_policy(policy: ToolPolicy) -> None:
    _policies[policy.persona_id] = policy
    try:
        from src.db import load_pref, save_pref  # type: ignore
        all_policies = load_pref("agent_tool_policies") or {}
        all_policies[policy.persona_id] = {
            "persona_id": policy.persona_id, "mode": policy.mode,
            "allowed_tools": policy.allowed_tools, "denied_tools": policy.denied_tools,
            "max_calls_per_session": policy.max_calls_per_session,
            "require_approval_for": policy.require_approval_for,
            "description": policy.description,
        }
        save_pref("agent_tool_policies", all_policies)
    except Exception:
        pass


def _load_policies_from_db() -> None:
    try:
        from src.db import load_pref  # type: ignore
        saved = load_pref("agent_tool_policies") or {}
        for pid, data in saved.items():
            _policies[pid] = ToolPolicy(
                persona_id=data.get("persona_id", pid),
                mode=data.get("mode", "unrestricted"),
                allowed_tools=data.get("allowed_tools", []),
                denied_tools=data.get("denied_tools", []),
                max_calls_per_session=data.get("max_calls_per_session", 0),
                require_approval_for=data.get("require_approval_for", []),
                description=data.get("description", ""),
            )
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def set_policy(policy: ToolPolicy) -> None:
    """Register or update a tool policy for a persona."""
    _save_policy(policy)


def get_policy(persona_id: str) -> ToolPolicy | None:
    """Retrieve the tool policy for a persona. Returns None if no policy set."""
    return _policies.get(persona_id)


def check_tool_allowed(persona_id: str, tool_name: str) -> tuple[bool, str]:
    """Check if *tool_name* is allowed for *persona_id*.

    Returns (allowed: bool, reason: str).
    """
    policy = _policies.get(persona_id)
    if policy is None:
        return True, "no policy defined — all tools allowed"

    if policy.mode == "allowlist":
        if tool_name in policy.allowed_tools:
            return True, "tool in allowlist"
        return False, f"tool '{tool_name}' not in allowlist for persona '{persona_id}'"

    if policy.mode == "denylist":
        if tool_name in policy.denied_tools:
            return False, f"tool '{tool_name}' is denied for persona '{persona_id}'"
        return True, "tool not in denylist"

    # unrestricted
    return True, "unrestricted policy"


def requires_approval(persona_id: str, tool_name: str) -> bool:
    """Check if *tool_name* requires HITL approval for *persona_id*."""
    policy = _policies.get(persona_id)
    if policy is None:
        return False
    return tool_name in policy.require_approval_for


def list_policies() -> list[dict]:
    """List all registered tool policies."""
    return [
        {
            "persona_id": p.persona_id, "mode": p.mode,
            "allowed_tools": p.allowed_tools, "denied_tools": p.denied_tools,
            "max_calls_per_session": p.max_calls_per_session,
            "require_approval_for": p.require_approval_for,
            "description": p.description,
        }
        for p in _policies.values()
    ]


def delete_policy(persona_id: str) -> bool:
    """Remove a policy (reverts to unrestricted). Does not delete DEFAULT_POLICIES."""
    if persona_id in DEFAULT_POLICIES:
        return False
    if persona_id in _policies:
        _policies.pop(persona_id)
        try:
            from src.db import load_pref, save_pref  # type: ignore
            all_policies = load_pref("agent_tool_policies") or {}
            all_policies.pop(persona_id, None)
            save_pref("agent_tool_policies", all_policies)
        except Exception:
            pass
        return True
    return False


def get_allowed_tools(persona_id: str, all_tool_names: list[str]) -> list[str]:
    """Given a list of all available tools, return the subset allowed for persona."""
    policy = _policies.get(persona_id)
    if policy is None or policy.mode == "unrestricted":
        return all_tool_names
    if policy.mode == "allowlist":
        return [t for t in all_tool_names if t in policy.allowed_tools]
    if policy.mode == "denylist":
        return [t for t in all_tool_names if t not in policy.denied_tools]
    return all_tool_names
