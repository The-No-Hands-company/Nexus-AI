from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class ModelTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    tier: ModelTier = ModelTier.MEDIUM
    ram_required_gb: int = 8
    strengths: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)


class ModelRouter:
    """Small provider/model selector used by tests and built-in tools."""

    def __init__(self, registry: dict[str, ModelSpec] | None = None) -> None:
        self._registry = registry or {
            "llm7": ModelSpec(
                name="LLM7",
                tier=ModelTier.LOW,
                ram_required_gb=4,
                strengths=["speed", "general"],
                languages=["en"],
            ),
            "gpt-4o": ModelSpec(
                name="GPT-4o",
                tier=ModelTier.HIGH,
                ram_required_gb=16,
                strengths=["coding", "reasoning", "multimodal"],
                languages=["en", "sv", "de"],
            ),
            "claude": ModelSpec(
                name="Claude",
                tier=ModelTier.HIGH,
                ram_required_gb=16,
                strengths=["writing", "reasoning"],
                languages=["en"],
            ),
        }

    def list_models(self) -> list[tuple[str, ModelSpec]]:
        return list(self._registry.items())

    def select_model(
        self,
        task: str,
        prefer_speed: bool = False,
        prefer_quality: bool = False,
    ) -> tuple[str, ModelSpec]:
        task_lower = (task or "").lower()
        if prefer_speed:
            return "llm7", self._registry["llm7"]
        if prefer_quality or any(word in task_lower for word in ("deploy", "architecture", "reason", "code")):
            return "gpt-4o", self._registry["gpt-4o"]
        return "claude", self._registry["claude"]

    def choose_for_complexity(self, complexity: TaskComplexity) -> tuple[str, ModelSpec]:
        mapping = {
            TaskComplexity.LOW: "llm7",
            TaskComplexity.MEDIUM: "claude",
            TaskComplexity.HIGH: "gpt-4o",
        }
        model_id = mapping[complexity]
        return model_id, self._registry[model_id]

    def iter_models(self) -> Iterable[tuple[str, ModelSpec]]:
        return iter(self._registry.items())