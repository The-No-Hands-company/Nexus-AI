"""Nexus AI — Specialist Agent Library (Phase 2)."""
from .registry import (
    SPECIALIST_AGENTS,
    SpecialistAgent,
    classify_to_specialist,
    get_specialist,
    list_agents as _list_agents_registry,
)


def list_agents():
    """Legacy package-level contract: return the core eight specialists."""
    return _list_agents_registry(include_extended=False)

__all__ = [
    "SPECIALIST_AGENTS",
    "SpecialistAgent",
    "classify_to_specialist",
    "get_specialist",
    "list_agents",
]
