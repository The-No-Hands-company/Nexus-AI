from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


class NexusAIError(RuntimeError):
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


@dataclass
class StreamChunk:
    delta: str = ""
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTrace:
    trace_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    status: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentListing:
    total: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


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
            method=method,
            url=url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise NexusAIError(
                f"{method} {path} failed: {response.status_code} {response.text[:300]}",
                status=response.status_code,
            )
        if not response.text:
            return {}
        data = response.json()
        if isinstance(data, dict):
            return data
        return {"data": data}

    def chat_completions(self, model: str, messages: list[dict[str, Any]], stream: bool = False, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        payload.update(kwargs)
        return self._request("POST", "/v1/chat/completions", payload)

    def run_agent(self, task: str, session_id: str = "", history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = {"task": task, "session_id": session_id, "history": history or []}
        return self._request("POST", "/v1/agent", payload)

    def autonomy_plan(self, goal: str, max_subtasks: int = 6) -> dict[str, Any]:
        payload = {"goal": goal, "max_subtasks": max_subtasks}
        return self._request("POST", "/v1/autonomy/plan", payload)

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models")

    def benchmark_regression(self) -> dict[str, Any]:
        return self._request("GET", "/benchmark/regression")

    def benchmark_dataset(
        self,
        dataset: str,
        provider: str = "",
        model: str = "",
        max_samples: int = 10,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/benchmark/dataset/run",
            {
                "dataset": dataset,
                "provider": provider,
                "model": model,
                "max_samples": max_samples,
            },
        )

    def benchmark_dataset_suite(
        self,
        datasets: list[str] | None = None,
        provider: str = "",
        model: str = "",
        max_samples_per_dataset: int = 10,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/benchmark/dataset/suite",
            {
                "datasets": datasets,
                "provider": provider,
                "model": model,
                "max_samples_per_dataset": max_samples_per_dataset,
            },
        )

    def benchmark_export(self, run_id: str, formats: list[str] | None = None) -> dict[str, Any]:
        suffix = f"?formats={','.join(formats)}" if formats else ""
        return self._request("GET", f"/benchmark/export/{run_id}{suffix}")

    def benchmark_dataset_history(self, dataset: str, limit: int = 20) -> dict[str, Any]:
        return self._request("GET", f"/benchmark/dataset/history/{dataset}?limit={limit}")

    def get_agent_trace(self, trace_id: str) -> AgentTrace:
        data = self._request("GET", f"/agent/trace/{trace_id}")
        return AgentTrace(
            trace_id=trace_id,
            steps=data.get("steps") or [],
            status=data.get("status") or "unknown",
            raw=data,
        )

    def list_agents(self, limit: int = 20) -> AgentListing:
        data = self._request("GET", f"/agent/runs?limit={limit}")
        items = data.get("items") or data.get("runs") or []
        return AgentListing(total=int(data.get("total") or len(items)), items=items, raw=data)
