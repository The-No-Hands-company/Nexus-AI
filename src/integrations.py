"""Nexus ecosystem integrations with local state-backed behavior.

This module provides a fully functional local integration layer for Tunnel,
Guardian, and Edge flows while leaving transport details pluggable for future
remote backends.
"""

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
}

_guardian_state = {
    "registered": False,
    "instance_id": None,
    "organisation_id": None,
    "endpoint": None,
    "registered_at": None,
    "events": [],
    "event_seq": 0,
}

_edge_state = {
    "registered": False,
    "node_id": None,
    "orchestrator_url": None,
    "registered_at": None,
    "model_ids": [],
    "max_concurrent_requests": 0,
}


def connect_tunnel(config: NexusTunnelConfig) -> str:
    """Establish a local tunnel session and return the generated public URL."""
    if not config.endpoint or not config.auth_token:
        raise ValueError("Tunnel config requires 'endpoint' and 'auth_token'")

    instance_hash = hashlib.sha256(
        f"{config.endpoint}|{config.auth_token}".encode("utf-8")
    ).hexdigest()[:8]
    public_url = f"https://tunnel-{instance_hash}.nexus.local"

    with _state_lock:
        _tunnel_state["connected"] = True
        _tunnel_state["url"] = public_url
        _tunnel_state["error"] = None
        _tunnel_state["connected_at"] = datetime.now(timezone.utc).isoformat()
        _tunnel_state["endpoint"] = config.endpoint

    return public_url


def disconnect_tunnel() -> None:
    """Close any active Nexus Tunnel connection."""
    with _state_lock:
        _tunnel_state["connected"] = False
        _tunnel_state["url"] = None
        _tunnel_state["error"] = None
        _tunnel_state["connected_at"] = None
        _tunnel_state["endpoint"] = None


def get_tunnel_status() -> dict:
    """Return current tunnel connection status."""
    with _state_lock:
        return dict(_tunnel_state)


def register_with_guardian(config: GuardianConfig) -> str:
    """Register this instance with Guardian and return the instance ID."""
    if not config.endpoint or not config.api_key or not config.organisation_id:
        raise ValueError(
            "Guardian config requires 'endpoint', 'api_key', and 'organisation_id'"
        )

    instance_id = hashlib.sha256(
        f"{config.organisation_id}|{config.endpoint}".encode("utf-8")
    ).hexdigest()[:12]

    with _state_lock:
        _guardian_state["registered"] = True
        _guardian_state["instance_id"] = instance_id
        _guardian_state["organisation_id"] = config.organisation_id
        _guardian_state["endpoint"] = config.endpoint
        _guardian_state["registered_at"] = datetime.now(timezone.utc).isoformat()

    return instance_id


def push_audit_event_to_guardian(event: dict) -> dict:
    """Store an audit event in Guardian local queue and return a receipt."""
    with _state_lock:
        if not _guardian_state.get("registered"):
            raise ValueError("Guardian is not registered")

        _guardian_state["event_seq"] += 1
        receipt = {
            "event_id": f"evt-{_guardian_state['event_seq']:06d}",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": dict(event or {}),
        }
        _guardian_state["events"].append(receipt)
        _guardian_state["events"] = _guardian_state["events"][-500:]
        return receipt


def pull_policy_update() -> dict:
    """Return active Guardian policy bundle for this instance."""
    with _state_lock:
        if not _guardian_state.get("registered"):
            return {
                "policies": [],
                "version": "0.0.0",
                "last_updated": None,
                "next_sync": None,
                "registered": False,
            }

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
            "organisation_id": _guardian_state.get("organisation_id"),
        }


def get_guardian_status() -> dict:
    """Return current Guardian registration and queue status."""
    with _state_lock:
        return {
            "registered": bool(_guardian_state.get("registered")),
            "instance_id": _guardian_state.get("instance_id"),
            "organisation_id": _guardian_state.get("organisation_id"),
            "endpoint": _guardian_state.get("endpoint"),
            "registered_at": _guardian_state.get("registered_at"),
            "queued_events": len(_guardian_state.get("events") or []),
        }


def register_edge_node(config: EdgeNodeConfig) -> str:
    """Register this machine as an edge node and return node ID."""
    if not config.orchestrator_url:
        raise ValueError("Edge config requires 'orchestrator_url'")

    node_id = (config.node_id or "").strip()
    if not node_id:
        node_id = hashlib.sha256(config.orchestrator_url.encode("utf-8")).hexdigest()[:12]

    with _state_lock:
        _edge_state["registered"] = True
        _edge_state["node_id"] = node_id
        _edge_state["orchestrator_url"] = config.orchestrator_url
        _edge_state["registered_at"] = datetime.now(timezone.utc).isoformat()
        _edge_state["model_ids"] = list(config.model_ids or [])
        _edge_state["max_concurrent_requests"] = int(config.max_concurrent_requests)

    return node_id


def deregister_edge_node() -> None:
    """Gracefully deregister this edge node."""
    with _state_lock:
        _edge_state["registered"] = False
        _edge_state["node_id"] = None
        _edge_state["orchestrator_url"] = None
        _edge_state["registered_at"] = None
        _edge_state["model_ids"] = []
        _edge_state["max_concurrent_requests"] = 0


def get_edge_status() -> dict:
    """Return current edge node registration state."""
    with _state_lock:
        return dict(_edge_state)
