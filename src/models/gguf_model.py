"""
src/models/gguf_model.py — GGUF local model loader stub

Loads GGUF-format models via llama-cpp-python.
Supports all llama.cpp-compatible quantisations (Q4_K_M, Q5_K_M, Q8_0, etc.).

This module is a STUB — load/generate/stream raise NotImplementedError.
"""

from __future__ import annotations

from typing import AsyncIterator

from .model_base import GenerateOptions, GenerateResult, ModelBase


class GGUFModel(ModelBase):
    """
    Local GGUF model loader backed by llama-cpp-python.

    STUB: all methods raise NotImplementedError.
    Implementation plan:
    - from llama_cpp import Llama
    - load(): Llama(model_path=..., n_gpu_layers=-1, n_ctx=8192)
    - generate(): llama(prompt, max_tokens=..., temperature=..., stop=...)
    - stream(): llama(prompt, stream=True, ...) generator
    """

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,   # -1 = all layers on GPU
        verbose: bool = False,
    ) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llama = None
        self.loaded = False

    def load(self) -> None:
        """
        Load the GGUF model.

        STUB: raises NotImplementedError.
        Implementation plan: from llama_cpp import Llama; self._llama = Llama(...)
        """
        raise NotImplementedError(
            "GGUFModel.load() is not yet implemented. "
            "Planned: llama_cpp.Llama(model_path=self.model_path, ...)."
        )

    def unload(self) -> None:
        """
        Free the GGUF model from memory.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "GGUFModel.unload() is not yet implemented. "
            "Planned: del self._llama; gc.collect(); torch.cuda.empty_cache()."
        )

    def generate(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> GenerateResult:
        """
        Generate text synchronously.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "GGUFModel.generate() is not yet implemented. "
            "Planned: self._llama(prompt, max_tokens=..., temperature=..., stop=...)."
        )

    async def stream(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream generated tokens asynchronously.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "GGUFModel.stream() is not yet implemented. "
            "Planned: async generator wrapping llama_cpp stream=True."
        )
        yield  # type: ignore[misc]
