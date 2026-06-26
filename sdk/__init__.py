"""Nexus AI SDK — Python client for the Nexus AI API.

```python
from nexus_ai import NexusClient

client = NexusClient(base_url="http://localhost:8000")

# Chat
response = client.chat.completions.create(
    messages=[{"role": "user", "content": "Hello!"}],
    stream=False,
)

# Agent
run = client.agent.run("Plan a deployment strategy for our microservices")
result = client.agent.stream("Explain quantum computing in simple terms")

# Memory
client.memory.add("User prefers dark mode", category="preferences")
memories = client.memory.search("preferences")

# RAG
client.rag.ingest("Nexus was founded in 2024...")
results = client.rag.query("When was Nexus founded?")

# Audio
client.audio.transcribe("speech.mp3")
client.audio.synthesize("Hello, world!", voice="alloy")

# Browser
session = client.browser.create_session("https://example.com")
step = client.browser.step(session["session_id"], action="navigate", params={"url": "/docs"})

# Safety
result = client.safety.check("Is this prompt safe?")

# Async
async with AsyncNexusClient() as async_client:
    response = await async_client.chat.completions.create(messages=[...])
```

For installation: `pip install -e .` or add to requirements.
"""

from __future__ import annotations

import io
import json as _json
import os
import warnings
from pathlib import Path
from typing import Any, AsyncGenerator, BinaryIO, Generator, List, Optional, Union

# ── HTTP backends (sync: urllib, async: httpx is optional) ──────────────

import urllib.request as _urlrequest
import urllib.error as _urlerror
import urllib.parse as _urlparse
import ssl as _ssl
import http.client as _httpclient


# ── Base HTTP client ────────────────────────────────────────────────────


class _HTTPError(Exception):
    """Raised by the SDK when the API returns a non-2xx status code."""

    def __init__(self, status_code: int, message: str, body: Any = None) -> None:
        self.status_code = status_code
        self.message = message
        self.body = body
        super().__init__(f"{status_code}: {message}")


class _BaseClient:
    """Shared HTTP transport for sync and async clients."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        session_token: str | None = None,
        timeout: int = 120,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_token = session_token
        self.timeout = timeout
        self._ctx = _ssl.create_default_context() if verify_ssl else _ssl._create_unverified_context()

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        if self.session_token:
            h["Authorization"] = f"Bearer {self.session_token}"
        if extra:
            h.update(extra)
        return h

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, json_body: dict | None = None, headers: dict | None = None) -> dict:
        url = self._build_url(path)
        data = _json.dumps(json_body).encode("utf-8") if json_body else None
        req = _urlrequest.Request(url, data=data, method=method.upper(), headers=self._headers(headers))
        try:
            with _urlrequest.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if not body:
                    return {}
                return _json.loads(body)
        except _urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            try:
                parsed = _json.loads(body)
            except Exception:
                parsed = {"error": body or str(exc)}
            raise _HTTPError(exc.code, parsed.get("error", exc.reason), parsed)
        except Exception as exc:
            raise _HTTPError(0, str(exc), {}) from exc

    def _get(self, path: str, params: dict | None = None) -> dict:
        if params:
            qs = _urlparse.urlencode({k: str(v) for k, v in params.items() if v is not None})
            path = f"{path}?{qs}"
        return self._request("GET", path)

    def _post(self, path: str, body: dict | None = None) -> dict:
        return self._request("POST", path, json_body=body)

    def _delete(self, path: str, params: dict | None = None) -> dict:
        if params:
            qs = _urlparse.urlencode({k: str(v) for k, v in params.items() if v is not None})
            path = f"{path}?{qs}"
        return self._request("DELETE", path)

    def _stream(self, path: str, body: dict | None = None, extra_headers: dict | None = None) -> Generator[str, None, None]:
        url = self._build_url(path)
        data = _json.dumps(body).encode("utf-8") if body else None
        headers = self._headers(extra_headers)
        req = _urlrequest.Request(url, data=data, method="POST", headers=headers)
        try:
            with _urlrequest.urlopen(req, timeout=max(self.timeout, 600), context=self._ctx) as resp:
                for line in resp:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    if decoded.startswith("data: "):
                        yield decoded[6:]
        except _urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            try:
                parsed = _json.loads(body)
            except Exception:
                parsed = {"error": body or str(exc)}
            raise _HTTPError(exc.code, parsed.get("error", exc.reason), parsed)

    def login(self, username: str, password: str) -> dict:
        """Authenticate and store a session token."""
        resp = self._post("/login", {"username": username, "password": password})
        self.session_token = resp.get("access_token") or resp.get("token", "")
        return resp


# ── Domain-specific client objects ──────────────────────────────────────


class ChatCompletionsClient:
    """OpenAI-compatible chat completions."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def create(
        self,
        messages: list[dict],
        model: str = "nexus-auto",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict:
        body = {"messages": messages, "model": model, "temperature": temperature, "stream": stream}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if kwargs:
            body.update(kwargs)
        if stream:
            return self._p._stream("/v1/chat/completions", body)
        return self._p._post("/v1/chat/completions", body)


class AgentClient:
    """Agent execution, streaming, and introspection."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def run(self, task: str, **kwargs) -> dict:
        """Run an agent task synchronously."""
        body: dict[str, Any] = {"task": task}
        body.update(kwargs)
        return self._p._post("/agent", body)

    def stream(self, task: str, **kwargs) -> Generator[str, None, None]:
        """Stream an agent task via SSE."""
        body: dict[str, Any] = {"task": task}
        body.update(kwargs)
        return self._p._stream("/agent/stream", body)

    def warmup(self) -> dict:
        return self._p._post("/agent/warmup", {})

    def stop(self, stream_id: str) -> dict:
        return self._p._post(f"/agent/stop/{stream_id}")

    def trace(self, trace_id: str) -> dict:
        return self._p._get(f"/agent/trace/{trace_id}")

    def self_correct(self, task: str, response: str, error: str) -> dict:
        return self._p._post("/agent/self-correct", {"task": task, "response": response, "error": error})

    def self_review(self, text: str) -> dict:
        return self._p._post("/agent/self-review", {"text": text})

    def test_cases_generate(self, task: str) -> dict:
        return self._p._post("/agent/test-cases/generate", {"task": task})

    def test_cases_run(self, test_cases: list[dict]) -> dict:
        return self._p._post("/agent/test-cases/run", {"test_cases": test_cases})


class ModelsClient:
    """Provider and model availability."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def list(self) -> list[dict]:
        return self._p._get("/v1/models").get("data", [])

    def capabilities(self) -> dict:
        return self._p._get("/v1/models/capabilities")

    def providers(self) -> dict:
        return self._p._get("/providers")

    def provider_health(self) -> dict:
        return self._p._get("/providers/health")


class MemoryClient:
    """Long-term, semantic, and episodic memory."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def add(self, content: str, category: str = "general", importance: float = 0.5) -> dict:
        return self._p._post("/memory", {"content": content, "category": category, "importance": importance})

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self._p._get("/memory", {"q": query, "limit": limit}).get("items", [])

    def update(self, memory_id: str, **fields) -> dict:
        return self._p._request("PATCH", f"/memory/{memory_id}", json_body=fields)

    def delete(self, memory_id: str) -> dict:
        return self._p._delete(f"/memory/{memory_id}")

    def export(self) -> dict:
        return self._p._post("/memory/export")

    def import_bundle(self, bundle: dict) -> dict:
        return self._p._post("/memory/import", bundle)

    def semantic(self, query: str, top_k: int = 10) -> list[dict]:
        return self._p._get("/memory/semantic", {"q": query, "k": top_k}).get("results", [])


class BrowserClient:
    """Browser automation sessions."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def create_session(self, start_url: str = "https://example.com", **kwargs) -> dict:
        return self._p._post("/browser/sessions", {"start_url": start_url, **kwargs})

    def list_sessions(self) -> dict:
        return self._p._get("/browser/sessions")

    def get_session(self, session_id: str) -> dict:
        return self._p._get(f"/browser/sessions/{session_id}")

    def step(self, session_id: str, action: str, params: dict | None = None) -> dict:
        return self._p._post(f"/browser/sessions/{session_id}/step", {"action": action, "params": params or {}})

    def confirm(self, session_id: str, approve: bool = True, actor: str = "") -> dict:
        return self._p._post(f"/browser/sessions/{session_id}/confirm", {"approve": approve, "actor": actor})

    def pause(self, session_id: str, reason: str = "manual") -> dict:
        return self._p._post(f"/browser/sessions/{session_id}/pause", {"reason": reason})

    def resume(self, session_id: str) -> dict:
        return self._p._post(f"/browser/sessions/{session_id}/resume")

    def history(self, session_id: str) -> dict:
        return self._p._get(f"/browser/sessions/{session_id}/history")


class RAGClient:
    """RAG ingestion, querying, and document management."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def ingest(self, text: str = "", path: str = "", metadata: dict | None = None, **kwargs) -> dict:
        return self._p._post("/rag/ingest", {"text": text, "path": path, "metadata": metadata or {}, **kwargs})

    def query(self, query: str, top_k: int | None = None, include_answer: bool = True) -> dict:
        body: dict = {"query": query, "include_answer": include_answer}
        if top_k is not None:
            body["top_k"] = top_k
        return self._p._post("/rag/query", body)

    def status(self) -> dict:
        return self._p._get("/rag/status")

    def list_documents(self, limit: int = 200, query: str = "") -> dict:
        return self._p._get("/rag/documents", {"limit": limit, "q": query})

    def delete_document(self, doc_id: str) -> dict:
        return self._p._delete(f"/rag/documents/{doc_id}")

    def create_snapshot(self, label: str | None = None) -> dict:
        return self._p._post("/rag/snapshots", {"label": label})

    def rollback_snapshot(self, snapshot_id: str) -> dict:
        return self._p._post(f"/rag/snapshots/{snapshot_id}/rollback")

    def cite(self, text: str, chunks: list[dict] | None = None) -> dict:
        return self._p._post("/rag/cite", {"response": text, "chunks": chunks or []})


class KnowledgeGraphClient:
    """Knowledge graph CRUD and query operations."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def store(self, name: str, entity_type: str = "concept", facts: dict | None = None, relations: list | None = None) -> dict:
        return self._p._post("/kg/store", {"name": name, "entity_type": entity_type, "facts": facts or {}, "relations": relations or []})

    def query(self, q: str, limit: int = 10) -> dict:
        return self._p._get("/kg/query", {"q": q, "limit": limit})

    def list_entities(self, entity_type: str = "", limit: int = 100) -> dict:
        return self._p._get("/kg/entities", {"entity_type": entity_type, "limit": limit})

    def get_entity(self, name: str) -> dict:
        return self._p._get(f"/kg/entities/{name}")

    def delete_entity(self, name: str) -> dict:
        return self._p._delete(f"/kg/entities/{name}")

    def graph(self, limit: int = 500) -> dict:
        return self._p._get("/kg/graph", {"limit": limit})

    def merge(self, primary: str, duplicate: str) -> dict:
        return self._p._post("/kg/merge", {"primary": primary, "duplicate": duplicate})

    def import_ontology(self, content: str, format: str = "auto", limit: int = 2000) -> dict:
        return self._p._post("/kg/import", {"content": content, "format": format, "limit": limit})

    def hybrid_search(self, q: str, limit: int = 10) -> dict:
        return self._p._get("/kg/hybrid-search", {"q": q, "limit": limit})


class AudioClient:
    """Speech-to-text and text-to-speech."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def transcribe(self, file_path: str, language: str = "en") -> dict:
        """Transcribe audio file. Uses the API's file upload endpoint."""
        url = self._p._build_url("/v1/audio/transcriptions")
        boundary = "---nexus_boundary_audio"
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_data = f.read()
        body_parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime_type or "application/octet-stream"}\r\n\r\n'.encode() + file_data + b'\r\n--' + boundary + b'--\r\n']
        req = _urlrequest.Request(url, data=body_parts[0], method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **self._p._headers({})})
        try:
            with _urlrequest.urlopen(req, timeout=self._p.timeout, context=self._p._ctx) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return _json.loads(body) if body else {}
        except _urlerror.HTTPError as exc:
            raise _HTTPError(exc.code, exc.reason)

    def synthesize(self, text: str, voice: str = "alloy", model: str = "tts-1", response_format: str = "mp3") -> bytes:
        """Synthesize speech and return raw audio bytes."""
        result = self._p._post("/v1/audio/speech", {"input": text, "voice": voice, "model": model, "response_format": response_format})
        if isinstance(result, bytes):
            return result
        return _json.dumps(result).encode()


class SafetyClient:
    """Safety checks, PII scanning, and compliance."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def check(self, text: str, allow_destructive: bool = False, policy_profile: str = "standard") -> dict:
        return self._p._post("/safety/check", {"text": text, "allow_destructive": allow_destructive, "policy_profile": policy_profile})

    def pii_scan(self, text: str) -> dict:
        return self._p._post("/safety/pii-scan", {"text": text})

    def prompt_injection(self, text: str, explain: bool = False) -> dict:
        return self._p._post("/safety/prompt-injection", {"text": text, "explain": explain})

    def hallucination_check(self, response: str, context: str = "") -> dict:
        return self._p._post("/safety/hallucination/check", {"response": response, "context": context})

    def watermark_embed(self, text: str, session_id: str = "") -> dict:
        return self._p._post("/safety/watermark/embed", {"text": text, "session_id": session_id})

    def watermark_detect(self, text: str, session_id: str = "") -> dict:
        return self._p._post("/safety/watermark/detect", {"text": text, "session_id": session_id})

    def copyright_check(self, text: str) -> dict:
        return self._p._post("/safety/copyright/check", {"text": text})

    def bias_evaluate(self, text: str) -> dict:
        return self._p._post("/safety/bias/evaluate", {"text": text})


class WorkspaceClient:
    """Chat sessions, projects, and user preferences."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def list_sessions(self, limit: int = 100) -> dict:
        return self._p._get("/session", {"limit": limit})

    def create_session(self) -> dict:
        return self._p._post("/session")

    def delete_session(self, session_id: str) -> dict:
        return self._p._delete(f"/session/{session_id}")

    def list_chats(self, session_id: str, limit: int = 100) -> dict:
        return self._p._get(f"/chats", {"session_id": session_id, "limit": limit})

    def get_chat(self, chat_id: str) -> dict:
        return self._p._get(f"/chats/{chat_id}")

    def search_chats(self, q: str, limit: int = 20) -> dict:
        return self._p._get("/chats/search", {"q": q, "limit": limit})

    def create_share(self, chat_id: str) -> dict:
        return self._p._post(f"/chats/{chat_id}/share")

    def get_usage(self, period: str = "daily") -> dict:
        return self._p._get(f"/usage", {"period": period})

    def set_persona(self, persona_name: str) -> dict:
        return self._p._post("/personas/switch", {"persona": persona_name})

    def list_custom_instructions(self) -> dict:
        return self._p._get("/instructions")


class OrganizationClient:
    """Multi-tenant organization management."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def create_org(self, name: str, slug: str = "") -> dict:
        return self._p._post("/orgs", {"name": name, "slug": slug})

    def list_orgs(self) -> dict:
        return self._p._get("/orgs")

    def get_org(self, org_id: str) -> dict:
        return self._p._get(f"/orgs/{org_id}")

    def delete_org(self, org_id: str) -> dict:
        return self._p._delete(f"/orgs/{org_id}")

    def list_members(self, org_id: str) -> dict:
        return self._p._get(f"/orgs/{org_id}/members")

    def invite(self, org_id: str, email: str, role: str = "member") -> dict:
        return self._p._post(f"/orgs/{org_id}/invite", {"email": email, "role": role})


class AdminClient:
    """Administrative operations (requires admin privileges)."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def list_users(self) -> dict:
        return self._p._get("/admin/users")

    def get_user(self, username: str) -> dict:
        return self._p._get(f"/admin/users/{username}")

    def update_user_role(self, username: str, role: str) -> dict:
        return self._p._request("PATCH", f"/admin/users/{username}", json_body={"role": role})

    def quota_override(self, username: str, daily_limit: int) -> dict:
        return self._p._post("/admin/quota-override", {"username": username, "daily_limit": daily_limit})

    def feature_flags(self) -> dict:
        return self._p._get("/admin/feature-flags")

    def set_feature_flag(self, name: str, enabled: bool) -> dict:
        return self._p._post("/admin/feature-flags", {"name": name, "enabled": enabled})

    def system_resources(self) -> dict:
        return self._p._get("/api/system/resources")

    def backup(self) -> dict:
        return self._p._post("/api/backup")

    def restore(self, backup_data: dict) -> dict:
        return self._p._post("/api/restore", backup_data)


class FineTuningClient:
    """Fine-tuning job management."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def create_job(self, model: str, training_file: str, **kwargs) -> dict:
        return self._p._post("/v1/fine-tuning/jobs", {"model": model, "training_file": training_file, **kwargs})

    def list_jobs(self, limit: int = 100) -> dict:
        return self._p._get("/v1/fine-tuning/jobs", {"limit": limit})

    def get_job(self, job_id: str) -> dict:
        return self._p._get(f"/v1/fine-tuning/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict:
        return self._p._post(f"/v1/fine-tuning/jobs/{job_id}/cancel")


class MCPClient:
    """Model Context Protocol tools."""

    def __init__(self, parent: _BaseClient) -> None:
        self._p = parent

    def server_status(self) -> dict:
        return self._p._get("/mcp/server/status")

    def list_tools(self) -> dict:
        return self._p._get("/mcp/tools")

    def call_tool(self, name: str, args: dict | None = None) -> dict:
        return self._p._post("/mcp/tools/call", {"name": name, "args": args or {}})

    def rpc(self, method: str, params: dict | None = None) -> dict:
        return self._p._post("/mcp/server", {"method": method, "params": params or {}})


# ── Public client class ──────────────────────────────────────────────────


class NexusClient(_BaseClient):
    """Synchronous Nexus AI API client.

    Usage:
        client = NexusClient(base_url="http://localhost:8000", api_key="nxk_...")
        response = client.chat.completions.create(messages=[{"role": "user", "content": "Hi"}])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        session_token: str | None = None,
        timeout: int = 120,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(base_url=base_url, api_key=api_key, session_token=session_token, timeout=timeout, verify_ssl=verify_ssl)
        self.chat = _ChatFacade(self)
        self.agent = AgentClient(self)
        self.models = ModelsClient(self)
        self.memory = MemoryClient(self)
        self.browser = BrowserClient(self)
        self.rag = RAGClient(self)
        self.kg = KnowledgeGraphClient(self)
        self.audio = AudioClient(self)
        self.safety = SafetyClient(self)
        self.workspace = WorkspaceClient(self)
        self.orgs = OrganizationClient(self)
        self.admin = AdminClient(self)
        self.finetuning = FineTuningClient(self)
        self.mcp = MCPClient(self)

    def health(self) -> dict:
        return self._get("/health")


class _ChatFacade:
    """Namespace for chat-related endpoints."""

    def __init__(self, client: _BaseClient) -> None:
        self.completions = ChatCompletionsClient(client)


# ── Async client ─────────────────────────────────────────────────────────

try:
    import anyio
    import httpx
    _HAS_ASYNC = True
except ImportError:
    _HAS_ASYNC = False


if _HAS_ASYNC:
    class _AsyncBaseClient:
        def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None, session_token: str | None = None, timeout: int = 120) -> None:
            self.base_url = base_url.rstrip("/")
            self.api_key = api_key
            self.session_token = session_token
            self.timeout = timeout
            self._client: httpx.AsyncClient | None = None

        async def __aenter__(self):
            self._client = httpx.AsyncClient(timeout=self.timeout)
            return self

        async def __aexit__(self, *args):
            if self._client:
                await self._client.aclose()

        def _headers(self, extra: dict | None = None) -> dict:
            h = {"Content-Type": "application/json"}
            if self.api_key:
                h["X-API-Key"] = self.api_key
            if self.session_token:
                h["Authorization"] = f"Bearer {self.session_token}"
            if extra:
                h.update(extra)
            return h

        async def _get(self, path: str, params: dict | None = None) -> dict:
            assert self._client
            url = f"{self.base_url}{path}"
            resp = await self._client.get(url, headers=self._headers(), params=params)
            return resp.json()

        async def _post(self, path: str, body: dict | None = None) -> dict:
            assert self._client
            url = f"{self.base_url}{path}"
            resp = await self._client.post(url, json=body, headers=self._headers())
            return resp.json()

        async def _stream(self, path: str, body: dict | None = None) -> AsyncGenerator[str, None]:
            assert self._client
            url = f"{self.base_url}{path}"
            async with self._client.stream("POST", url, json=body, headers=self._headers(), timeout=max(self.timeout, 600)) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line[6:]

    class AsyncAgentClient:
        def __init__(self, parent: _AsyncBaseClient) -> None:
            self._p = parent

        async def run(self, task: str, **kwargs) -> dict:
            body: dict[str, Any] = {"task": task}
            body.update(kwargs)
            return await self._p._post("/agent", body)

        async def stream(self, task: str, **kwargs) -> AsyncGenerator[str, None]:
            body: dict[str, Any] = {"task": task}
            body.update(kwargs)
            async for chunk in self._p._stream("/agent/stream", body):
                yield chunk

    class AsyncChatClient:
        def __init__(self, parent: _AsyncBaseClient) -> None:
            self._p = parent

        async def create(self, messages: list[dict], model: str = "nexus-auto", **kwargs) -> dict:
            return await self._p._post("/v1/chat/completions", {"messages": messages, "model": model, **kwargs})

    class AsyncNexusClient(_AsyncBaseClient):
        def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None, session_token: str | None = None, timeout: int = 120) -> None:
            super().__init__(base_url=base_url, api_key=api_key, session_token=session_token, timeout=timeout)
            self.chat = _AsyncChatFacade(self)
            self.agent = AsyncAgentClient(self)

    class _AsyncChatFacade:
        def __init__(self, client: _AsyncBaseClient) -> None:
            self.completions = AsyncChatClient(client)

else:
    class AsyncNexusClient:
        def __init__(self, *args, **kwargs):
            raise ImportError("AsyncNexusClient requires 'httpx' and 'anyio'. Install with: pip install httpx anyio")