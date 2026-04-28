from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List


class HierarchyValidationError(ValueError):
    """Raised when hierarchy links are invalid."""


@dataclass
class FoundationModelNode:
    id: str
    label: str
    provider: str
    model: str
    capabilities: List[str] = field(default_factory=list)


@dataclass
class AgentNode:
    id: str
    name: str
    role: str
    model_ids: List[str] = field(default_factory=list)
    workflow_ids: List[str] = field(default_factory=list)
    tool_ids: List[str] = field(default_factory=list)


@dataclass
class WorkflowNode:
    id: str
    name: str
    pattern: str
    description: str
    agent_ids: List[str] = field(default_factory=list)
    tool_ids: List[str] = field(default_factory=list)


@dataclass
class ToolNode:
    id: str
    name: str
    layer: str = "task_tool"


class AISystemHierarchy:
    """In-memory scaffold for AI-system hierarchy planning and introspection."""

    DEFAULT_TOOL_IDS = [
        "calculate", "weather", "currency", "convert", "regex", "base64", "json_format",
        "select_model", "rag_ingest", "rag_query", "rag_status", "inspect_db", "query_db",
        "cron_schedule", "cron_list", "cron_cancel", "kg_store", "kg_query", "kg_list",
        "read_page", "api_call", "youtube_transcript", "generate_image", "diff",
        "read_csv", "write_csv",
    ]

    def __init__(self, system_name: str = "Nexus AI"):
        self.system_name = system_name
        self._lock = RLock()
        self.foundation_models: Dict[str, FoundationModelNode] = {}
        self.agents: Dict[str, AgentNode] = {}
        self.workflows: Dict[str, WorkflowNode] = {}
        self.tools: Dict[str, ToolNode] = {}

    def clear(self) -> None:
        with self._lock:
            self.foundation_models.clear()
            self.agents.clear()
            self.workflows.clear()
            self.tools.clear()

    def register_foundation_model(self, node: FoundationModelNode) -> None:
        with self._lock:
            self.foundation_models[node.id] = node

    def register_tool(self, node: ToolNode) -> None:
        with self._lock:
            self.tools[node.id] = node

    def register_agent(self, node: AgentNode) -> None:
        with self._lock:
            missing_models = [model_id for model_id in node.model_ids if model_id not in self.foundation_models]
            if missing_models:
                raise HierarchyValidationError(
                    f"Agent '{node.id}' references missing foundation models: {missing_models}"
                )
            missing_tools = [tool_id for tool_id in node.tool_ids if tool_id not in self.tools]
            if missing_tools:
                raise HierarchyValidationError(f"Agent '{node.id}' references missing tools: {missing_tools}")
            self.agents[node.id] = node

    def register_workflow(self, node: WorkflowNode) -> None:
        with self._lock:
            missing_agents = [agent_id for agent_id in node.agent_ids if agent_id not in self.agents]
            if missing_agents:
                raise HierarchyValidationError(
                    f"Workflow '{node.id}' references missing agents: {missing_agents}"
                )
            missing_tools = [tool_id for tool_id in node.tool_ids if tool_id not in self.tools]
            if missing_tools:
                raise HierarchyValidationError(f"Workflow '{node.id}' references missing tools: {missing_tools}")
            self.workflows[node.id] = node

    def bootstrap_runtime(
        self,
        providers: List[Dict[str, Any]],
        specialist_agents: List[Dict[str, Any]],
    ) -> None:
        self.clear()

        for provider in providers:
            pid = str(provider.get("id") or "").strip()
            if not pid:
                continue
            self.register_foundation_model(
                FoundationModelNode(
                    id=pid,
                    label=str(provider.get("label") or pid),
                    provider=pid,
                    model=str(provider.get("model") or ""),
                    capabilities=["chat"],
                )
            )

        for tool_id in self.DEFAULT_TOOL_IDS:
            self.register_tool(ToolNode(id=tool_id, name=tool_id))

        model_ids = list(self.foundation_models.keys())
        for agent in specialist_agents:
            aid = str(agent.get("id") or "").strip()
            if not aid:
                continue
            self.register_agent(
                AgentNode(
                    id=aid,
                    name=str(agent.get("name") or aid),
                    role=str(agent.get("description") or "specialist"),
                    model_ids=model_ids,
                    workflow_ids=["single_agent_loop", "hierarchical_orchestrator"],
                    tool_ids=[],
                )
            )

        self.register_workflow(
            WorkflowNode(
                id="single_agent_loop",
                name="Single Agent Loop",
                pattern="react",
                description="One agent reasons, calls tools, and iterates to completion.",
                agent_ids=[],
                tool_ids=self.DEFAULT_TOOL_IDS,
            )
        )

        self.register_workflow(
            WorkflowNode(
                id="hierarchical_orchestrator",
                name="Hierarchical Orchestrator",
                pattern="hierarchical",
                description="Planner -> Executor -> Reviewer -> Verifier specialist chain.",
                agent_ids=list(self.agents.keys()),
                tool_ids=[],
            )
        )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "system": {
                    "name": self.system_name,
                    "hierarchy": [
                        "ai_system",
                        "foundation_models",
                        "agent_framework",
                        "agent_workflows",
                        "tasks_tools_actions",
                    ],
                    "note": "Agents use models as reasoning engines; models do not use agents.",
                },
                "foundation_models": [vars(node) for node in self.foundation_models.values()],
                "agent_layer": [vars(node) for node in self.agents.values()],
                "workflow_layer": [vars(node) for node in self.workflows.values()],
                "task_layer": [vars(node) for node in self.tools.values()],
                "counts": {
                    "foundation_models": len(self.foundation_models),
                    "agents": len(self.agents),
                    "workflows": len(self.workflows),
                    "tools": len(self.tools),
                },
            }


def build_runtime_hierarchy(providers: List[Dict[str, Any]], specialist_agents: List[Dict[str, Any]]) -> Dict[str, Any]:
    hierarchy = AISystemHierarchy(system_name="Nexus AI")
    hierarchy.bootstrap_runtime(providers=providers, specialist_agents=specialist_agents)
    return hierarchy.snapshot()
