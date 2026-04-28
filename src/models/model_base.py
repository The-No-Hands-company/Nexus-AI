"""
src/models/model_base.py — Abstract local model interface stub

All local model adapters subclass ModelBase, which defines a unified
generate/stream contract independent of backend (GGUF, HuggingFace, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class GenerateOptions:
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 1.0
    top_k: int = 40
    repeat_penalty: float = 1.1
    stop: list[str] | None = None
    seed: int | None = None
    system_prompt: str = ""


@dataclass
class GenerateResult:
    text: str
    tokens_prompt: int = 0
    tokens_generated: int = 0
    stop_reason: str = ""       # "stop", "max_tokens", "error"
    model_path: str = ""


class ModelBase(ABC):
    """
    Abstract base for all locally-loaded model adapters.

    Subclasses must implement:
    - load()
    - unload()
    - generate()
    - stream()
    """

    name: str = "model"
    model_path: str = ""
    loaded: bool = False
    vram_required_gb: float = 0.0

    @abstractmethod
    def load(self) -> None:
        """
        Load the model into memory.

        STUB: must be implemented by subclass.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.load() not implemented.")

    @abstractmethod
    def unload(self) -> None:
        """
        Release model from memory.

        STUB: must be implemented by subclass.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.unload() not implemented.")

    @abstractmethod
    def generate(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> GenerateResult:
        """
        Generate text from *prompt* synchronously.

        STUB: must be implemented by subclass.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.generate() not implemented.")

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream generated tokens from *prompt* asynchronously.

        STUB: must be implemented by subclass.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.stream() not implemented.")
        yield  # make linters happy

    def is_loaded(self) -> bool:
        return self.loaded

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} loaded={self.loaded}>"
