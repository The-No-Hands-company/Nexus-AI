from __future__ import annotations

import gc
from typing import AsyncIterator

from .model_base import GenerateOptions, GenerateResult, ModelBase


class GGUFModel(ModelBase):

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llama = None
        self.loaded = False

    def load(self) -> None:
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "llama-cpp-python is required for GGUF models. "
                "Install with: pip install llama-cpp-python"
            )
        self._llama = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=self.verbose,
        )
        self.loaded = True

    def unload(self) -> None:
        self._llama = None
        self.loaded = False
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def generate(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> GenerateResult:
        if not self._llama or not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        opts = options or GenerateOptions()
        stop = opts.stop or []
        response = self._llama(
            prompt,
            max_tokens=opts.max_tokens,
            temperature=opts.temperature,
            top_p=opts.top_p,
            top_k=opts.top_k,
            repeat_penalty=opts.repeat_penalty,
            stop=stop,
            seed=opts.seed,
            stream=False,
        )
        choice = response["choices"][0]
        text = choice.get("text", choice.get("content", "")).strip()
        return GenerateResult(
            text=text,
            tokens_prompt=response.get("usage", {}).get("prompt_tokens", 0),
            tokens_generated=response.get("usage", {}).get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason", "stop"),
            model_path=self.model_path,
        )

    async def stream(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> AsyncIterator[str]:
        if not self._llama or not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        opts = options or GenerateOptions()
        stop = opts.stop or []
        stream = self._llama(
            prompt,
            max_tokens=opts.max_tokens,
            temperature=opts.temperature,
            top_p=opts.top_p,
            top_k=opts.top_k,
            repeat_penalty=opts.repeat_penalty,
            stop=stop,
            seed=opts.seed,
            stream=True,
        )
        for chunk in stream:
            choice = chunk.get("choices", [{}])[0]
            token = choice.get("text", choice.get("delta", {}).get("content", ""))
            if token:
                yield token
