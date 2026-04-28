import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator

class AuthRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)

class TokenResponse(BaseModel):
    token: str
    username: str

class WebhookRequest(BaseModel):
    task: str
    repo: Optional[str] = None

class V1Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

class V1ChatCompletionsRequest(BaseModel):
    model: Optional[str] = "nexus-ai"
    messages: List[V1Message]
    stream: Optional[bool] = False
    response_format: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None

class V1EmbeddingsRequest(BaseModel):
    model: Optional[str] = "nexus-ai"
    input: Union[str, List[str], List[int], List[List[int]]]
    user: Optional[str] = None

class V1EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int

class V1EmbeddingsResponse(BaseModel):
    object: str = "list"
    data: List[V1EmbeddingData]
    model: Optional[str] = None
    usage: Dict[str, int] = {}

class ProviderCapability(BaseModel):
    id: str
    object: str = "model"
    label: str
    provider: str
    model: str
    openai_compat: bool
    keyless: bool
    available: bool
    rate_limited: bool
    capabilities: List[str]

class ModelCapabilitiesResponse(BaseModel):
    object: str = "list"
    data: List[ProviderCapability]

class APIErrorResponse(BaseModel):
    error: str
    type: str = "invalid_request"
    detail: Optional[str] = None

class SafetyIssue(BaseModel):
    code: str
    reason: str
    detail: Optional[str] = None
    severity: str = "high"
    pattern: Optional[str] = None

class SafetyCheckRequest(BaseModel):
    text: str
    allow_destructive: Optional[bool] = False

class SafetyCheckResponse(BaseModel):
    allowed: bool
    issues: List[SafetyIssue] = []
    masked_text: Optional[str] = None

class SettingsRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    persona: Optional[str] = None

class SemanticMemoryRequest(BaseModel):
    summary: str
    tags: List[str] = []

class RAGIngestRequest(BaseModel):
    text: Optional[str] = None
    path: Optional[str] = None
    metadata: Dict[str, Any] = {}
    doc_id_prefix: Optional[str] = None

class RAGQueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    filter_metadata: Optional[Dict[str, Any]] = None

class AutonomyRequest(BaseModel):
    goal: str
    strategy: Optional[str] = "parallel"
    max_subtasks: Optional[int] = 6

class ProjectCreateRequest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "New Project"
    instructions: Optional[str] = ""
    color: Optional[str] = "#7c6af7"

class CustomPersonaRequest(BaseModel):
    id: Optional[str] = None
    name: str = "Custom"
    icon: Optional[str] = "🤖"
    description: Optional[str] = ""
    prompt_prefix: Optional[str] = ""
    color: Optional[str] = "#7c6af7"
    temperature: Optional[float] = 0.2
    tier: Optional[str] = "medium"

class ReactionRequest(BaseModel):
    chat_id: str
    msg_idx: int
    reaction: str
    text: Optional[str] = ""

class SessionTokenRequest(BaseModel):
    token: str

class PrefsRequest(BaseModel):
    theme: Optional[str] = None
    font_size: Optional[str] = None


# ── Typed API error taxonomy ──────────────────────────────────────────────────

ERROR_TYPE_STATUS: Dict[str, int] = {
    "invalid_request_error":   400,
    "authentication_error":    401,
    "permission_error":        403,
    "not_found_error":         404,
    "rate_limit_error":        429,
    "provider_exhausted":      503,
    "model_error":             500,
    "context_length_exceeded": 413,
    "validation_error":        422,
    "invalid_response_format": 422,
    "consensus_error":         500,
    "server_error":            500,
}


class APIErrorDetail(BaseModel):
    message: str
    type: str = "server_error"
    code: Optional[str] = None
    param: Optional[str] = None

    @property
    def http_status(self) -> int:
        return ERROR_TYPE_STATUS.get(self.type, 500)


class TypedAPIErrorResponse(BaseModel):
    error: APIErrorDetail

    @classmethod
    def make(
        cls,
        message: str,
        error_type: str = "server_error",
        code: Optional[str] = None,
        param: Optional[str] = None,
    ) -> "TypedAPIErrorResponse":
        return cls(error=APIErrorDetail(message=message, type=error_type, code=code, param=param))


# ── OpenAI-compatible request / response normalization ────────────────────────

class TextContentPart(BaseModel):
    type: Literal["text"] = "text"
    text: str = ""


class ImageUrlDetail(BaseModel):
    url: str
    detail: Optional[str] = "auto"


class ImageContentPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrlDetail


ContentPart = Union[TextContentPart, ImageContentPart]


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]], None] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return " ".join(
                p.get("text", "") for p in self.content if p.get("type") == "text"
            )
        return ""


class ResponseFormat(BaseModel):
    type: str = "text"
    json_schema: Optional[Dict[str, Any]] = None


# ── Legacy text completions ───────────────────────────────────────────────────

class CompletionRequest(BaseModel):
    model: str = ""
    prompt: Union[str, List[str], List[int], List[List[int]]] = ""
    max_tokens: int = 256
    temperature: Optional[float] = None
    stream: bool = False
    stop: Optional[Union[str, List[str]]] = None
    n: int = 1
    echo: bool = False
    user: Optional[str] = None
    suffix: Optional[str] = None

    def prompt_text(self) -> str:
        if isinstance(self.prompt, str):
            return self.prompt
        if isinstance(self.prompt, list) and self.prompt and isinstance(self.prompt[0], str):
            return " ".join(self.prompt)  # type: ignore[arg-type]
        return ""


class CompletionChoice(BaseModel):
    text: str
    index: int = 0
    finish_reason: str = "stop"
    logprobs: Optional[Any] = None


class CompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"cmpl-{uuid.uuid4().hex[:12]}")
    object: Literal["text_completion"] = "text_completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: List[CompletionChoice]
    usage: Dict[str, int] = Field(default_factory=dict)


# ── Audio ─────────────────────────────────────────────────────────────────────

class AudioTranscriptionResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None


class AudioSpeechRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = 1.0

    @model_validator(mode="after")
    def clamp_speed(self) -> "AudioSpeechRequest":
        self.speed = max(0.25, min(4.0, self.speed))
        return self


# ── Files API ─────────────────────────────────────────────────────────────────

class FileObject(BaseModel):
    id: str
    object: Literal["file"] = "file"
    bytes: int
    created_at: int
    filename: str
    purpose: str
    status: str = "processed"
    status_details: Optional[str] = None


class FileListResponse(BaseModel):
    object: Literal["list"] = "list"
    data: List[FileObject]


# ── Fine-tuning ───────────────────────────────────────────────────────────────

class FineTuningRequest(BaseModel):
    training_file: str
    model: str = "gpt-3.5-turbo"
    validation_file: Optional[str] = None
    hyperparameters: Optional[Dict[str, Any]] = None
    suffix: Optional[str] = None


class FineTuningJob(BaseModel):
    id: str = Field(default_factory=lambda: f"ftjob-{uuid.uuid4().hex[:12]}")
    object: Literal["fine_tuning.job"] = "fine_tuning.job"
    created_at: int = Field(default_factory=lambda: int(time.time()))
    finished_at: Optional[int] = None
    model: str
    fine_tuned_model: Optional[str] = None
    organization_id: str = "org-nexus"
    status: str = "queued"
    training_file: str
    validation_file: Optional[str] = None
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    trained_tokens: Optional[int] = None
    error: Optional[Dict[str, Any]] = None
    result_files: List[str] = Field(default_factory=list)

