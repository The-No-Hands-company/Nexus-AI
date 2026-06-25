from __future__ import annotations

import gc
from dataclasses import dataclass
from datetime import datetime, timezone

from .model_base import ModelBase
from .gguf_model import GGUFModel
from .huggingface_model import HuggingFaceModel


@dataclass
class RegisteredModel:
    model_id: str
    model_path: str
    backend: str
    vram_gb: float = 0.0
    loaded: bool = False
    loaded_at: str | None = None
    last_used_at: str | None = None
    use_count: int = 0
    instance: ModelBase | None = None


class ModelRegistry:

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
        entry = self._registry.get(model_id)
        if not entry:
            raise ValueError(f"Model '{model_id}' not registered. Call register() first.")

        if entry.loaded and entry.instance:
            entry.last_used_at = datetime.now(timezone.utc).isoformat()
            entry.use_count += 1
            return entry.instance

        if entry.backend == "gguf":
            instance: ModelBase = GGUFModel(
                model_path=entry.model_path,
                n_ctx=8192,
                n_gpu_layers=-1,
            )
        elif entry.backend == "huggingface":
            instance = HuggingFaceModel(
                model_id=entry.model_path,
                device="auto",
            )
        else:
            raise ValueError(f"Unsupported backend: {entry.backend}")

        vram_needed = entry.vram_gb or _estimate_vram(entry.model_path)
        self._ensure_vram_budget(vram_needed)

        instance.load()
        entry.instance = instance
        entry.loaded = True
        entry.loaded_at = datetime.now(timezone.utc).isoformat()
        entry.last_used_at = entry.loaded_at
        entry.use_count = 1
        entry.vram_gb = vram_needed

        return instance

    def unload(self, model_id: str) -> bool:
        entry = self._registry.get(model_id)
        if not entry or not entry.loaded or not entry.instance:
            return False

        entry.instance.unload()
        entry.instance = None
        entry.loaded = False
        entry.loaded_at = None

        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        return True

    def _ensure_vram_budget(self, vram_needed: float) -> None:
        loaded = [m for m in self._registry.values() if m.loaded]
        current_vram = sum(m.vram_gb for m in loaded)

        if current_vram + vram_needed <= self.max_vram_gb and len(loaded) < self.max_loaded:
            return

        evictable = sorted(
            loaded,
            key=lambda m: (
                m.last_used_at or datetime.min.replace(tzinfo=timezone.utc),
                -m.use_count,
            ),
        )

        for model in evictable:
            if current_vram + vram_needed <= self.max_vram_gb and len(self._loaded_count()) < self.max_loaded:
                break
            self.unload(model.model_id)
            current_vram -= model.vram_gb

    def _loaded_count(self) -> list[str]:
        return [mid for mid, m in self._registry.items() if m.loaded]

    def total_vram_used(self) -> float:
        return sum(m.vram_gb for m in self._registry.values() if m.loaded)

    def swap(self, unload_model_id: str, load_model_id: str) -> tuple[bool, ModelBase | None]:
        self.unload(unload_model_id)
        instance = self.load(load_model_id)
        return True, instance


def _estimate_vram(model_path: str) -> float:
    params_markers = {"70b": 70, "32b": 32, "13b": 13, "7b": 7, "3b": 3, "1b": 1}
    model_lower = model_path.lower()
    for marker, params in params_markers.items():
        if marker in model_lower:
            return round(params * 0.6, 1)
    return 4.0


registry = ModelRegistry()
