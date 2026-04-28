"""Provider package scaffold for Phase 2 refactor.

This package hosts provider routing and adapters while preserving
backward compatibility with existing module entrypoints.
"""

from .model_router import (
    ModelRouter,
    ModelSpec,
    ModelTier,
    TaskComplexity,
)

__all__ = [
    "ModelRouter",
    "ModelSpec",
    "ModelTier",
    "TaskComplexity",
]
