"""
src/models/code_llm.py — Code-specialised LLM adapter stub

Wraps a base model (GGUF or HuggingFace) with code-specific
prompt formatting, fill-in-the-middle (FIM) support,
code extraction, and language-aware stop sequences.

Supports: CodeLlama, DeepSeek-Coder, Qwen-Coder, Starcoder2.

This module is a STUB — most methods raise NotImplementedError.
"""

from __future__ import annotations

from .model_base import GenerateOptions, GenerateResult, ModelBase


# Language-specific stop sequences (avoid cutting off mid-block)
LANGUAGE_STOPS: dict[str, list[str]] = {
    "python": ["\nclass ", "\ndef ", "\n# ---"],
    "javascript": ["\nfunction ", "\nconst ", "\n// ---"],
    "typescript": ["\nfunction ", "\nconst ", "\ninterface "],
    "go": ["\nfunc ", "\ntype "],
    "rust": ["\nfn ", "\npub fn ", "\nimpl "],
}

# FIM tokens for supported models
FIM_TOKENS: dict[str, dict] = {
    "deepseek-coder": {"prefix": "<｜fim▁begin｜>", "suffix": "<｜fim▁end｜>", "middle": "<｜fim▁hole｜>"},
    "starcoder2":     {"prefix": "<fim_prefix>", "suffix": "<fim_suffix>", "middle": "<fim_middle>"},
    "codellama":      {"prefix": "<PRE>", "suffix": "<SUF>", "middle": "<MID>"},
}


class CodeLLM:
    """
    Code-specialised wrapper around a base ModelBase instance.

    STUB: generate_code / complete_code raise NotImplementedError.
    """

    def __init__(self, model: ModelBase, model_family: str = "generic") -> None:
        self.model = model
        self.model_family = model_family

    def generate_code(
        self,
        instruction: str,
        language: str = "python",
        context: str = "",
        options: GenerateOptions | None = None,
    ) -> str:
        """
        Generate code from a natural-language *instruction*.

        STUB: raises NotImplementedError.
        Implementation plan:
        - Build code-specific prompt with language header
        - Set language stop sequences
        - Call model.generate()
        - Extract code block from response
        """
        raise NotImplementedError(
            "CodeLLM.generate_code() is not yet implemented. "
            "Planned: structured code prompt + stop sequences + code extraction."
        )

    def complete_code(
        self,
        prefix: str,
        suffix: str,
        language: str = "python",
        options: GenerateOptions | None = None,
    ) -> str:
        """
        Fill-in-the-middle (FIM) completion.

        STUB: raises NotImplementedError.
        Implementation plan:
        - Format FIM prompt using FIM_TOKENS for the model family
        - Call model.generate()
        - Return only the middle section
        """
        raise NotImplementedError(
            "CodeLLM.complete_code() is not yet implemented. "
            "Planned: FIM token formatting + model.generate()."
        )

    def explain_code(self, code: str, language: str = "python") -> str:
        """
        Return a natural-language explanation of *code*.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "CodeLLM.explain_code() is not yet implemented. "
            "Planned: explanation prompt + model.generate()."
        )

    def review_code(self, code: str, language: str = "python") -> dict:
        """
        Return a structured code review dict with issues and suggestions.

        STUB: raises NotImplementedError.
        """
        raise NotImplementedError(
            "CodeLLM.review_code() is not yet implemented. "
            "Planned: structured review prompt + JSON output parsing."
        )

    @staticmethod
    def extract_code_block(text: str, language: str | None = None) -> str:
        """
        Extract the first code block from a markdown response.

        FUNCTIONAL: not a stub — useful immediately.
        """
        import re
        if language:
            pattern = rf"```{language}\s*\n(.*?)```"
        else:
            pattern = r"```(?:\w+)?\s*\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: return stripped text if no fences found
        return text.strip()
