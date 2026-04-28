"""
src/models/model_registry.py — Local model lifecycle registry stub

Tracks which local models are loaded, their VRAM usage,
and provides load/unload/swap lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .model_base import ModelBase


@dataclass
class RegisteredModel:
    model_id: str
    model_path: str
    backend: str        # "gguf" | "huggingface" | "code_llm"
    vram_gb: float = 0.0
    loaded: bool = False
    loaded_at: str | None = None
    last_used_at: str | None = None
    use_count: int = 0
    instance: ModelBase | None = None


class ModelRegistry:
    """
    Manages a pool of locally loaded models with LRU eviction.

    STUB: load/unload raise NotImplementedError.
    Implementation plan:
    - Track registered models in a dict
    - On load: check available VRAM (via hardware.py), unload LRU if needed
    - On unload: call instance.unload(), free VRAM accounting
    """

    def __init__(self, max_loaded: int = 3, max_vram_gb: float = 24.0) -> None:
        self._registry: dict[str, RegisteredModel] = {}
        self.max_loaded = max_loaded
        self.max_vram_gb = max_vram_gb

    def register(
        self,
        model_id: str,
        model_path: str,
        backend: str,
        vram_gb: float = 0.0,
    ) -> RegisteredModel:
        """Register a model so it can be loaded later."""
        entry = RegisteredModel(
            model_id=model_id,
            model_path=model_path,
            backend=backend,
            vram_gb=vram_gb,
        )
        self._registry[model_id] = entry
        return entry

    def get(self, model_id: str) -> RegisteredModel | None:
        return self._registry.get(model_id)

    def list_models(self, loaded_only: bool = False) -> list[RegisteredModel]:
        models = list(self._registry.values())
        if loaded_only:
            models = [m for m in models if m.loaded]
        return models

    def load(self, model_id: str) -> ModelBase:
        """
        Load the model identified by *model_id* and return its instance.

        STUB: raises NotImplementedError.
        Implementation plan:
        - Lookup RegisteredModel
        - Instantiate appropriate backend (GGUFModel, HuggingFaceModel, etc.)
        - Check VRAM budget → evict LRU loaded model if needed
        - Call instance.load(), update registry
        """
        raise NotImplementedError(
            "ModelRegistry.load() is not yet implemented. "
            "Planned: backend dispatch → VRAM check → LRU evict → instance.load()."
        )

    def unload(self, model_id: str) -> bool:
        """
        Unload a loaded model and free memory.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "ModelRegistry.unload() is not yet implemented. "
            "Planned: instance.unload() → update registry."
        )

    def total_vram_used(self) -> float:
        return sum(m.vram_gb for m in self._registry.values() if m.loaded)


# Module-level singleton
registry = ModelRegistry()
