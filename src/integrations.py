"""Nexus ecosystem integrations with remote-first behavior and local fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import threading


@dataclass
class NexusTunnelConfig:
    enabled: bool = False
    server_url: str = "https://tunnel.nexus-ai.dev"
    local_port: int = 8000
    subdomain: str = ""
    auth_token: str = ""
    auto_reconnect: bool = True
    endpoint: str = ""


@dataclass
class GuardianConfig:
    enabled: bool = False
    endpoint: str = ""
    api_key: str = ""
    organisation_id: str = ""
    enforce_policies: bool = True


@dataclass
class EdgeNodeConfig:
    node_id: str = ""
    orchestrator_url: str = ""
    model_ids: list[str] = field(default_factory=list)
    heartbeat_interval_s: int = 30
    max_concurrent_requests: int = 4
    api_key: str = ""


_state_lock = threading.Lock()

_tunnel_state = {
    "connected": False,
    "url": None,
    "error": None,
    "connected_at": None,
    "endpoint": None,
    "mode": "local",
}

_guardian_state = {
    "registered": False,
    "instance_id": None,
    "organisation_id": None,
    "endpoint": None,
    "registered_at": None,
    "events": [],
    "event_seq": 0,
    "api_key": None,
    "mode": "local",
}

_edge_state = {
    "registered": False,
    "node_id": None,
    "orchestrator_url": None,
    "registered_at": None,
    "model_ids": [],
    "max_concurrent_requests": 0,
    "mode": "local",
}


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 30) -> dict | None:
    try:
        import requests
        resp = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
    except Exception:
        return None
    return None


def _get_json(url: str, headers: dict | None = None, timeout: int = 15) -> dict | None:
    try:
        import requests
        resp = requests.get(url, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
    except Exception:
        return None
    return None


def connect_tunnel(config: NexusTunnelConfig) -> str:
    if not config.endpoint or not config.auth_token:
        raise ValueError("Tunnel config requires 'endpoint' and 'auth_token'")

    remote = _post_json(
        config.endpoint.rstrip("/") + "/connect",
        {
            "local_port": config.local_port,
            "subdomain": config.subdomain,
            "auto_reconnect": config.auto_reconnect,
        },
        headers={"Authorization": f"Bearer {config.auth_token}"},
        timeout=30,
    )
    public_url = remote.get("public_url") if remote else None
    mode = "remote" if public_url else "local"
    if not public_url:
        instance_hash = hashlib.sha256(
            f"{config.endpoint}|{config.auth_token}|{config.local_port}|{config.subdomain}".encode("utf-8")
        ).hexdigest()[:8]
        public_url = f"https://tunnel-{instance_hash}.nexus.local"

    with _state_lock:
        _tunnel_state.update({
            "connected": True,
            "url": public_url,
            "error": None,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": config.endpoint,
            "mode": mode,
        })

    return public_url


def disconnect_tunnel() -> None:
    with _state_lock:
        _tunnel_state["connected"] = False
        _tunnel_state["url"] = None
        _tunnel_state["error"] = None
        _tunnel_state["connected_at"] = None
        _tunnel_state["endpoint"] = None
        _tunnel_state["mode"] = "local"


def get_tunnel_status() -> dict:
    with _state_lock:
        return dict(_tunnel_state)


def register_with_guardian(config: GuardianConfig) -> str:
    if not config.endpoint or not config.api_key or not config.organisation_id:
        raise ValueError("Guardian config requires 'endpoint', 'api_key', and 'organisation_id'")

    remote = _post_json(
        config.endpoint.rstrip("/") + "/register",
        {
            "organisation_id": config.organisation_id,
            "enforce_policies": config.enforce_policies,
        },
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=30,
    )
    instance_id = (remote or {}).get("instance_id")
    mode = "remote" if instance_id else "local"
    if not instance_id:
        instance_id = hashlib.sha256(
            f"{config.organisation_id}|{config.endpoint}".encode("utf-8")
        ).hexdigest()[:12]

    with _state_lock:
        _guardian_state.update({
            "registered": True,
            "instance_id": instance_id,
            "organisation_id": config.organisation_id,
            "endpoint": config.endpoint,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "api_key": config.api_key,
            "mode": mode,
        })

    return instance_id


def push_audit_event_to_guardian(event: dict) -> dict:
    with _state_lock:
        if not _guardian_state.get("registered"):
            raise ValueError("Guardian is not registered")
        endpoint = _guardian_state.get("endpoint")
        api_key = _guardian_state.get("api_key")
        mode = _guardian_state.get("mode", "local")

    if endpoint and api_key and mode == "remote":
        remote = _post_json(
            str(endpoint).rstrip("/") + "/events",
            {"event": dict(event or {})},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if remote:
            return remote

    with _state_lock:
        _guardian_state["event_seq"] += 1
        receipt = {
            "event_id": f"evt-{_guardian_state['event_seq']:06d}",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": dict(event or {}),
            "mode": "local",
        }
        _guardian_state["events"].append(receipt)
        _guardian_state["events"] = _guardian_state["events"][-500:]
        return receipt


def pull_policy_update() -> dict:
    with _state_lock:
        if not _guardian_state.get("registered"):
            return {
                "policies": [],
                "version": "0.0.0",
                "last_updated": None,
                "next_sync": None,
                "registered": False,
            }
        endpoint = _guardian_state.get("endpoint")
        api_key = _guardian_state.get("api_key")
        mode = _guardian_state.get("mode", "local")
        organisation_id = _guardian_state.get("organisation_id")

    if endpoint and api_key and mode == "remote":
        remote = _get_json(
            str(endpoint).rstrip("/") + "/policies",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if remote:
            remote.setdefault("registered", True)
            remote.setdefault("organisation_id", organisation_id)
            remote.setdefault("mode", "remote")
            return remote

    now = datetime.now(timezone.utc).isoformat()
    return {
        "policies": [
            {
                "id": "default-deny-unsafe-shell",
                "severity": "high",
                "enabled": True,
                "scope": "tool_actions",
            },
            {
                "id": "mask-sensitive-outputs",
                "severity": "medium",
                "enabled": True,
                "scope": "output",
            },
        ],
        "version": "1.0.0",
        "last_updated": now,
        "next_sync": now,
        "registered": True,
        "organisation_id": organisation_id,
        "mode": "local",
    }


def get_guardian_status() -> dict:
    with _state_lock:
        return {
            "registered": bool(_guardian_state.get("registered")),
            "instance_id": _guardian_state.get("instance_id"),
            "organisation_id": _guardian_state.get("organisation_id"),
            "endpoint": _guardian_state.get("endpoint"),
            "registered_at": _guardian_state.get("registered_at"),
            "queued_events": len(_guardian_state.get("events") or []),
            "mode": _guardian_state.get("mode", "local"),
        }


def register_edge_node(config: EdgeNodeConfig) -> str:
    if not config.orchestrator_url:
        raise ValueError("Edge config requires 'orchestrator_url'")

    remote = _post_json(
        config.orchestrator_url.rstrip("/") + "/edge/register",
        {
            "node_id": config.node_id,
            "model_ids": list(config.model_ids or []),
            "heartbeat_interval_s": int(config.heartbeat_interval_s),
            "max_concurrent_requests": int(config.max_concurrent_requests),
        },
        headers={"Authorization": f"Bearer {config.api_key}"} if config.api_key else None,
        timeout=30,
    )

    node_id = (remote or {}).get("node_id") or (config.node_id or "").strip()
    mode = "remote" if remote else "local"
    if not node_id:
        node_id = hashlib.sha256(config.orchestrator_url.encode("utf-8")).hexdigest()[:12]

    with _state_lock:
        _edge_state.update({
            "registered": True,
            "node_id": node_id,
            "orchestrator_url": config.orchestrator_url,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "model_ids": list(config.model_ids or []),
            "max_concurrent_requests": int(config.max_concurrent_requests),
            "mode": mode,
        })

    return node_id


def deregister_edge_node() -> None:
    with _state_lock:
        _edge_state["registered"] = False
        _edge_state["node_id"] = None
        _edge_state["orchestrator_url"] = None
        _edge_state["registered_at"] = None
        _edge_state["model_ids"] = []
        _edge_state["max_concurrent_requests"] = 0
        _edge_state["mode"] = "local"


def get_edge_status() -> dict:
    with _state_lock:
        return dict(_edge_state)
