"""nexus_ai_sdk.async_client — Async client for the Nexus AI API.

Requires ``httpx`` (``pip install nexus-ai-sdk[async]``).
Drop-in async counterpart to ``NexusAIClient`` — same methods, awaitable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from ._version import __version__

try:
    import httpx
except ImportError as _e:
    raise ImportError(
        "AsyncNexusAIClient requires httpx. Install with: pip install nexus-ai-sdk[async]"
    ) from _e

from .client import NexusAIError, StreamChunk, AgentTrace, AgentListing


@dataclass
class AsyncNexusAIClient:
    """Async Nexus AI API client backed by ``httpx.AsyncClient``."""

    base_url: str
    api_key: str = ""
    timeout_s: float = 30.0
    max_retries: int = 3
    _http: httpx.AsyncClient | None = field(default=None, repr=False, compare=False)

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "User-Agent": f"nexus-ai-python/{__version__} async",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def __aenter__(self) -> "AsyncNexusAIClient":
        self._http = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers=self._headers(),
                timeout=self.timeout_s,
            )
        return self._http

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = self._client()
        response = await client.request(method, path, json=payload)
        if response.status_code >= 400:
            raise NexusAIError(
                f"{method} {path} failed: {response.status_code} {response.text[:300]}",
                status=response.status_code,
            )
        if not response.text:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def chat_completions(
        self, model: str, messages: list[dict[str, Any]], stream: bool = False, **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        payload.update(kwargs)
        return await self._request("POST", "/v1/chat/completions", payload)

    async def chat_stream(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        payload.update(kwargs)
        async with self._client().stream("POST", "/v1/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise NexusAIError(
                    f"POST /v1/chat/completions failed: {resp.status_code} {body[:300].decode()}",
                    status=resp.status_code,
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                    choice = (obj.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                    yield StreamChunk(delta=delta, finish_reason=choice.get("finish_reason"), raw=obj)
                except json.JSONDecodeError:
                    continue

    # ── Agent ─────────────────────────────────────────────────────────────────

    async def run_agent(
        self, task: str, session_id: str = "", history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", "/v1/agent", {"task": task, "session_id": session_id, "history": history or []})

    async def stream_agent(
        self, task: str, session_id: str = "", history: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        payload = {"task": task, "session_id": session_id, "history": history or []}
        async with self._client().stream("POST", "/agent/stream", json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise NexusAIError(
                    f"POST /agent/stream failed: {resp.status_code} {body[:300].decode()}",
                    status=resp.status_code,
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                    delta = obj.get("content") or obj.get("delta") or ""
                    yield StreamChunk(delta=delta, finish_reason=obj.get("finish_reason"), raw=obj)
                except json.JSONDecodeError:
                    continue

    async def get_agent_trace(self, trace_id: str) -> AgentTrace:
        data = await self._request("GET", f"/agent/trace/{trace_id}")
        return AgentTrace(trace_id=trace_id, steps=data.get("steps") or [],
                          status=data.get("status") or "unknown", raw=data)

    # ── Models ────────────────────────────────────────────────────────────────

    async def list_models(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/models")

    # ── Benchmarks ────────────────────────────────────────────────────────────

    async def benchmark_run(self, providers: list[str] | None = None) -> dict[str, Any]:
        return await self._request("POST", "/benchmark/run", {"providers": providers or []})

    async def benchmark_dataset(self, dataset: str, provider: str = "", model: str = "", max_samples: int = 10) -> dict[str, Any]:
        return await self._request("POST", "/benchmark/dataset/run", {
            "dataset": dataset, "provider": provider, "model": model, "max_samples": max_samples,
        })

    async def benchmark_dataset_suite(
        self, datasets: list[str] | None = None, provider: str = "", model: str = "", max_samples_per_dataset: int = 10,
    ) -> dict[str, Any]:
        return await self._request("POST", "/benchmark/dataset/suite", {
            "datasets": datasets, "provider": provider, "model": model,
            "max_samples_per_dataset": max_samples_per_dataset,
        })

    async def benchmark_export(self, run_id: str, formats: list[str] | None = None) -> dict[str, Any]:
        qs = f"?formats={','.join(formats)}" if formats else ""
        return await self._request("GET", f"/benchmark/export/{run_id}{qs}")

    # ── Health ────────────────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
