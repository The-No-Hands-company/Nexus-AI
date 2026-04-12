from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

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
    response_format: Optional[str] = None

class V1EmbeddingsRequest(BaseModel):
    model: Optional[str] = "nexus-ai"
    input: Union[str, List[str]]
    user: Optional[str] = None

class V1EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int

class V1EmbeddingsResponse(BaseModel):
    object: str = "list"
    data: List[V1EmbeddingData]
    model: Optional[str] = None

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
