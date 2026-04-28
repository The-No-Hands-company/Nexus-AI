"""
src/models/huggingface_model.py — HuggingFace transformers model loader stub

Loads models from the HuggingFace Hub (or local cache) using the
transformers library with optional bitsandbytes quantisation.

This module is a STUB — all methods raise NotImplementedError.
"""

from __future__ import annotations

from typing import AsyncIterator

from .model_base import GenerateOptions, GenerateResult, ModelBase


class HuggingFaceModel(ModelBase):
    """
    Local HuggingFace transformers model.

    STUB: all methods raise NotImplementedError.
    Implementation plan:
    - from transformers import AutoModelForCausalLM, AutoTokenizer
    - load(): AutoModelForCausalLM.from_pretrained(model_id, device_map="auto", ...)
    - generate(): tokenizer + model.generate() + decode
    - stream(): TextIteratorStreamer integration
    """

    def __init__(
        self,
        model_id: str,
        device: str = "auto",
        load_in_4bit: bool = False,
        load_in_8bit: bool = False,
        trust_remote_code: bool = False,
    ) -> None:
        self.model_id = model_id
        self.model_path = model_id
        self.device = device
        self.load_in_4bit = load_in_4bit
        self.load_in_8bit = load_in_8bit
        self.trust_remote_code = trust_remote_code
        self._model = None
        self._tokenizer = None
        self.loaded = False

    def load(self) -> None:
        """
        Load model and tokenizer from HuggingFace Hub / local cache.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "HuggingFaceModel.load() is not yet implemented. "
            "Planned: AutoModelForCausalLM + AutoTokenizer from_pretrained with "
            "optional bitsandbytes quantisation."
        )

    def unload(self) -> None:
        """
        Release model and tokenizer from memory.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "HuggingFaceModel.unload() is not yet implemented. "
            "Planned: del self._model, self._tokenizer; gc.collect(); cuda empty_cache."
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
            "HuggingFaceModel.generate() is not yet implemented. "
            "Planned: tokenizer encode → model.generate() → decode."
        )

    async def stream(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream generated tokens asynchronously via TextIteratorStreamer.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "HuggingFaceModel.stream() is not yet implemented. "
            "Planned: TextIteratorStreamer in background thread + async queue."
        )
        yield  # type: ignore[misc]
