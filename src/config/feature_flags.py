from __future__ import annotations

"""Static feature-flag names used across the runtime."""

ENABLE_CREATIVE_TOOLS = "ENABLE_CREATIVE_TOOLS"
ENABLE_FEDERATED_LLM = "ENABLE_FEDERATED_LLM"

DEFAULT_FLAGS: dict[str, dict] = {
    ENABLE_CREATIVE_TOOLS: {
        "enabled": False,
        "description": "Enable music + 3D creative generation tools.",
    },
    ENABLE_FEDERATED_LLM: {
        "enabled": False,
        "description": "Enable federated LLM coordination and routing paths.",
    },
}
