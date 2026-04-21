"""nexus-ai-sdk — Official Python SDK for the Nexus AI API.

Quick start::

    from nexus_ai_sdk import NexusAIClient, NexusOperator

    # Simple client
    client = NexusAIClient(base_url="http://localhost:8000", api_key="sk-…")
    response = client.chat_completions("gpt-4o", [{"role": "user", "content": "Hello!"}])

    # Production operator (retry, env-var config, health check)
    op = NexusOperator.default()
    result = op.benchmark_dataset("gsm8k", max_samples=10)

    # Async client (requires httpx: pip install nexus-ai-sdk[async])
    from nexus_ai_sdk import AsyncNexusAIClient
    async with AsyncNexusAIClient(base_url="…", api_key="…") as client:
        response = await client.chat_completions("gpt-4o", [{"role": "user", "content": "Hello!"}])
"""
from ._version import __version__, __api_version__, __min_server_version__
from .client import NexusAIClient, NexusAIError, StreamChunk, AgentTrace, AgentListing
from .operator import NexusOperator, OperatorConfig, RetryConfig
from .compat import validate as validate_compat, CompatReport, CompatibilityError

__all__ = [
    # Core client
    "NexusAIClient",
    "NexusAIError",
    "StreamChunk",
    "AgentTrace",
    "AgentListing",
    # Operator
    "NexusOperator",
    "OperatorConfig",
    "RetryConfig",
    # Compatibility
    "validate_compat",
    "CompatReport",
    "CompatibilityError",
    # Version
    "__version__",
    "__api_version__",
    "__min_server_version__",
]


def get_async_client() -> type:
    """Return AsyncNexusAIClient (lazy import to avoid requiring httpx at import time)."""
    from .async_client import AsyncNexusAIClient  # noqa: PLC0415
    return AsyncNexusAIClient


# Lazy attribute for AsyncNexusAIClient
def __getattr__(name: str):
    if name == "AsyncNexusAIClient":
        from .async_client import AsyncNexusAIClient
        return AsyncNexusAIClient
    raise AttributeError(f"module 'nexus_ai_sdk' has no attribute {name!r}")
