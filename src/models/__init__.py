"""
src/models/ — Local model infrastructure package

Provides abstract interfaces and concrete adapters for loading and running
local models directly (GGUF via llama.cpp, HuggingFace transformers, etc.)
without going through the provider routing layer.

Modules:
    model_base.py         — abstract ModelBase interface
    model_registry.py     — local model lifecycle registry
    gguf_model.py         — GGUF model loader (llama.cpp / llama-cpp-python)
    huggingface_model.py  — HuggingFace transformers model loader
    code_llm.py           — code-specialized LLM adapter (e.g. CodeLlama, DeepSeek-Coder)
"""
