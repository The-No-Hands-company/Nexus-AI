"""
Nexus-AI Systems API contract helper.

Provides the canonical registration payload builder for Nexus-Cloud Systems API
tool registration. Intentionally kept isolated from the main app — the startup
lifecycle wires this in separately so it does not conflict with active development.
"""
from typing import TypedDict, Literal

HealthState = Literal["healthy", "degraded", "offline"]
ModeState = Literal["orchestrated", "standalone"]


class NexusAIRegistrationPayload(TypedDict):
    id: str
    name: str
    description: str
    upstreamUrl: str
    mode: ModeState
    exposed: bool
    health: HealthState
    capabilities: list[str]
    metadata: dict


def build_systems_api_registration_payload(
    upstream_url: str,
    tool_id: str = "nexus-ai",
    tool_name: str = "Nexus AI",
    health: HealthState = "healthy",
) -> NexusAIRegistrationPayload:
    """Build the Systems API registration payload for Nexus-AI."""
    return {
        "id": tool_id,
        "name": tool_name,
        "description": "AI orchestration platform — model routing, prompt governance, and safety pipeline",
        "upstreamUrl": upstream_url,
        "mode": "orchestrated",
        "exposed": True,
        "health": health,
        "capabilities": [
            "model-routing",
            "prompt-governance",
            "safety-pipeline",
            "agent-orchestration",
            "ensemble-inference",
            "rag",
            "tool-execution",
            "observability",
        ],
        "metadata": {
            "aiVersion": "v1",
            "supportsModelRouting": True,
            "supportsPromptGovernance": True,
            "supportsSafetyPipeline": True,
            "supportsRAG": True,
        },
    }
