"""Compatibility bridge to the existing model router implementation.

Phase 2 introduces src/providers/ as the canonical import path while
preserving runtime behavior from src/model_router.py.
"""

from ..model_router import (  # noqa: F401
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
