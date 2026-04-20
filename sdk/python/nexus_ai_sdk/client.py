from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Generator

import requests


class NexusAIError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


# ── Response types ────────────────────────────────────────────────────────────

@dataclass
class StreamChunk:
    delta: str
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTrace:
    trace_id: str
    steps: list[dict[str, Any]]
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentListing:
    agent_id: str
    name: str
    description: str
    capabilities: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


# ── Client ────────────────────────────────────────────────────────────────────

@dataclass
class NexusAIClient:
    base_url: str
    api_key: str = ""
    timeout_s: int = 30

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}{path}"
        response = requests.request(
            method=method, url=url, json=payload,
            headers=self._headers(), timeout=self.timeout_s,
        )
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

    def chat_completions(
        self, model: str, messages: list[dict[str, Any]], stream: bool = False, **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        payload.update(kwargs)
        return self._request("POST", "/v1/chat/completions", payload)

    def chat_stream(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any,
    ) -> Generator[StreamChunk, None, None]:
        """Yield ``StreamChunk`` objects from a streaming chat completion."""
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        payload.update(kwargs)
        with requests.post(url, json=payload, headers=self._headers(),
                           stream=True, timeout=self.timeout_s) as resp:
            if resp.status_code >= 400:
                raise NexusAIError(
                    f"POST /v1/chat/completions failed: {resp.status_code} {resp.text[:300]}",
                    status=resp.status_code,
                )
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
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

    def run_agent(
        self, task: str, session_id: str = "", history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/agent", {"task": task, "session_id": session_id, "history": history or []})

    def stream_agent(
        self, task: str, session_id: str = "", history: list[dict[str, Any]] | None = None,
    ) -> Generator[StreamChunk, None, None]:
        """Yield ``StreamChunk`` objects from a streaming agent task."""
        url = f"{self.base_url.rstrip('/')}/agent/stream"
        payload = {"task": task, "session_id": session_id, "history": history or []}
        with requests.post(url, json=payload, headers=self._headers(),
                           stream=True, timeout=self.timeout_s) as resp:
            if resp.status_code >= 400:
                raise NexusAIError(
                    f"POST /agent/stream failed: {resp.status_code} {resp.text[:300]}",
                    status=resp.status_code,
                )
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                    delta = obj.get("content") or obj.get("delta") or ""
                    yield StreamChunk(delta=delta, finish_reason=obj.get("finish_reason"), raw=obj)
                except json.JSONDecodeError:
                    continue

    def get_agent_trace(self, trace_id: str) -> AgentTrace:
        data = self._request("GET", f"/agent/trace/{trace_id}")
        return AgentTrace(trace_id=trace_id, steps=data.get("steps") or [],
                          status=data.get("status") or "unknown", raw=data)

    def stop_agent(self, stream_id: str) -> dict[str, Any]:
        return self._request("POST", f"/agent/stop/{stream_id}")

    # ── Agent marketplace ─────────────────────────────────────────────────────

    def list_agents(self) -> list[AgentListing]:
        data = self._request("GET", "/agents")
        agents = data.get("agents") or data.get("data") or []
        return [
            AgentListing(
                agent_id=str(a.get("id") or a.get("agent_id") or ""),
                name=str(a.get("name") or ""),
                description=str(a.get("description") or ""),
                capabilities=list(a.get("capabilities") or []),
                raw=a,
            )
            for a in agents
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/agents/{agent_id}")

    def run_named_agent(self, agent_id: str, task: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", f"/agents/{agent_id}/run", {"task": task, **kwargs})

    # ── Autonomy ──────────────────────────────────────────────────────────────

    def autonomy_plan(self, goal: str, max_subtasks: int = 6) -> dict[str, Any]:
        return self._request("POST", "/v1/autonomy/plan", {"goal": goal, "max_subtasks": max_subtasks})

    def autonomy_execute(self, plan: dict[str, Any], stream: bool = False) -> dict[str, Any]:
        return self._request("POST", "/autonomy/execute", {**plan, "stream": stream})

    def get_autonomy_trace(self, trace_id: str) -> AgentTrace:
        data = self._request("GET", f"/autonomy/trace/{trace_id}")
        return AgentTrace(trace_id=trace_id, steps=data.get("steps") or [],
                          status=data.get("status") or "unknown", raw=data)

    # ── Models ────────────────────────────────────────────────────────────────

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models")

    # ── Benchmarks ────────────────────────────────────────────────────────────

    def benchmark_run(self, providers: list[str] | None = None) -> dict[str, Any]:
        return self._request("POST", "/benchmark/run", {"providers": providers or []})

    def benchmark_regression(self) -> dict[str, Any]:
        return self._request("GET", "/benchmark/regression")

    def benchmark_set_baseline(self, baseline: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/benchmark/regression/baseline", baseline)

    def benchmark_history(
        self, provider: str = "", model: str = "", task_type: str = "", limit: int = 500,
    ) -> dict[str, Any]:
        qs = f"?provider={provider}&model={model}&task_type={task_type}&limit={limit}"
        return self._request("GET", f"/benchmark/history{qs}")

    def benchmark_safety(self, test_cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._request("POST", "/benchmark/safety", {"test_cases": test_cases or []})

    # ── Compliance ────────────────────────────────────────────────────────────

    def get_compliance_config(self) -> dict[str, Any]:
        return self._request("GET", "/admin/compliance")

    def update_compliance_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", "/admin/compliance", config)
