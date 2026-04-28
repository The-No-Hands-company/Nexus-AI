from __future__ import annotations

import pathlib
import re
from typing import Any
import time
import uuid

from pydantic import BaseModel, ConfigDict


class GenericSchema(BaseModel):
    model_config = ConfigDict(extra="allow")


def _build_schema(name: str):
    return type(name, (GenericSchema,), {})


# ---------------------------------------------------------------------------
# Explicit schemas (take priority over the dynamic fallback below)
# ---------------------------------------------------------------------------

__all__: list[str] = ["V1ChatMessage", "V1ChatCompletionsRequest"]
__all__ += ["FineTuningRequest", "FineTuningJob"]

class V1ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str = "user"
    content: Any = ""
    name: str | None = None


class V1ChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    messages: list[V1ChatMessage] = []
    model: str | None = None
    stream: bool = False
    response_format: Any = None
    user: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: Any = None
    tools: list[Any] | None = None
    tool_choice: Any = None


_SKIP = {
    "APIRouter", "Request", "HTTPException", "WebSocket", "WebSocketDisconnect",
    "FileResponse", "StreamingResponse", "HTMLResponse", "JSONResponse", "Response",
    "ValidationError", "AuthManager", "GuardrailViolation", "Orchestrator", "PlanningSystem",
    "ModelRouter", "ModelSpec", "ModelTier", "TaskComplexity", "CriticAgent", "SafetyPipelineMiddleware",
    "Exception", "BaseException", "KeyboardInterrupt", "SystemExit",
}
# All Python built-in exceptions + common third-party types used in routes
class FineTuningRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    training_file: str = ""
    model: str = "gpt-3.5-turbo"
    validation_file: str | None = None
    hyperparameters: dict[str, Any] | None = None
    suffix: str | None = None


class FineTuningJob(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = ""
    object: str = "fine_tuning.job"
    model: str = ""
    training_file: str = ""
    validation_file: str | None = None
    hyperparameters: dict[str, Any] = {}
    status: str = "queued"
    created_at: int = 0
    finished_at: int | None = None
    fine_tuned_model: str | None = None
    organization_id: str = "org-nexus"
    trained_tokens: int | None = None
    error: dict[str, Any] | None = None
    result_files: list[str] = []

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = f"ftjob-{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = int(time.time())


_SKIP |= {
    "ArithmeticError", "AssertionError", "AttributeError", "BlockingIOError",
    "BrokenPipeError", "BufferError", "BytesWarning", "ChildProcessError",
    "ConnectionAbortedError", "ConnectionError", "ConnectionRefusedError",
    "ConnectionResetError", "DeprecationWarning", "EOFError", "EnvironmentError",
    "FileExistsError", "FileNotFoundError", "FloatingPointError",
    "FutureWarning", "GeneratorExit", "IOError", "ImportError", "ImportWarning",
    "IndentationError", "IndexError", "InterruptedError", "IsADirectoryError",
    "LookupError", "MemoryError", "ModuleNotFoundError",
    "NameError", "NotADirectoryError", "NotImplementedError", "OSError",
    "OverflowError", "PendingDeprecationWarning", "PermissionError",
    "ProcessLookupError", "RecursionError", "ReferenceError", "ResourceWarning",
    "RuntimeError", "RuntimeWarning", "StopAsyncIteration", "StopIteration",
    "SyntaxError", "SyntaxWarning", "TimeoutError", "TypeError",
    "UnboundLocalError", "UnicodeDecodeError", "UnicodeEncodeError",
    "UnicodeError", "UnicodeTranslateError", "UnicodeWarning", "UserWarning",
    "ValueError", "Warning", "ZeroDivisionError", "KeyError",
    "AllProvidersExhausted", "AudioProviderError",
}

_text = pathlib.Path(__file__).with_name("routes.py").read_text(encoding="utf-8", errors="ignore")
_names = sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9_]+)\b", _text)))

for _name in _names:
    # Avoid shadowing runtime constants imported in routes.py (for example
    # SAFETY_POLICY_PROFILES), which can break endpoint logic at runtime.
    if _name in _SKIP or _name.startswith("JWT") or _name.isupper() or "_" in _name:
        continue
    if _name not in globals():
        globals()[_name] = _build_schema(_name)
        __all__.append(_name)