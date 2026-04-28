"""Nexus AI Hub — multi-instance management.

Provides registration, health tracking, and passthrough proxying
for multiple Nexus AI instances under a single control plane.
"""
from __future__ import annotations

import os
import uuid
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NEXUS_HUB_URL    = os.getenv("NEXUS_HUB_URL", "")
NEXUS_HUB_TOKEN  = os.getenv("NEXUS_HUB_TOKEN", "")
THIS_INSTANCE_ID = os.getenv("NEXUS_INSTANCE_ID", str(uuid.uuid4())[:12])
THIS_INSTANCE_LABEL = os.getenv("NEXUS_INSTANCE_LABEL", "default")

_lock       = threading.Lock()
_instances: dict[str, dict] = {}       # instance_id -> metadata
_passthrough_log: list[dict] = []


# ── Instance registry ─────────────────────────────────────────────────────────

@dataclass
class NexusInstance:
    instance_id: str
    label: str
    url: str
    api_key: str = ""
    version: str = ""
    status: str = "unknown"      # healthy | degraded | offline
    last_seen: str = ""
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    capabilities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "instance_id":   self.instance_id,
            "label":         self.label,
            "url":           self.url,
            "version":       self.version,
            "status":        self.status,
            "last_seen":     self.last_seen,
            "registered_at": self.registered_at,
            "capabilities":  self.capabilities,
            "metadata":      self.metadata,
        }


def register_instance(instance_id: str, label: str, url: str, api_key: str = "",
                      version: str = "", capabilities: list[str] | None = None,
                      metadata: dict | None = None) -> NexusInstance:
    """Register or update a Nexus AI instance in the hub."""
    with _lock:
        inst = NexusInstance(
            instance_id=instance_id,
            label=label,
            url=url.rstrip("/"),
            api_key=api_key,
            version=version,
            status="registered",
            last_seen=datetime.now(timezone.utc).isoformat(),
            capabilities=capabilities or [],
            metadata=metadata or {},
        )
        _instances[instance_id] = inst.to_dict()
        _instances[instance_id]["api_key"] = api_key   # store for passthrough
        logger.info("Hub: registered instance %s (%s)", instance_id, label)
        return inst


def list_instances(include_offline: bool = True) -> list[dict]:
    with _lock:
        items = [
            {k: v for k, v in inst.items() if k != "api_key"}
            for inst in _instances.values()
        ]
    if not include_offline:
        items = [i for i in items if i.get("status") != "offline"]
    return sorted(items, key=lambda x: x.get("registered_at", ""))


def get_instance(instance_id: str) -> dict | None:
    with _lock:
        inst = _instances.get(instance_id)
    if inst is None:
        return None
    return {k: v for k, v in inst.items() if k != "api_key"}


def deregister_instance(instance_id: str) -> bool:
    with _lock:
        if instance_id not in _instances:
            return False
        del _instances[instance_id]
    return True


def ping_instance(instance_id: str) -> dict:
    """Ping a registered instance's health endpoint."""
    with _lock:
        inst = _instances.get(instance_id)
    if not inst:
        return {"ok": False, "error": "instance not found"}

    url = inst.get("url", "")
    api_key = inst.get("api_key", "")
    try:
        import requests  # type: ignore
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = requests.get(f"{url}/health/live", headers=headers, timeout=10)
        status = "healthy" if resp.ok else "degraded"
        last_seen = datetime.now(timezone.utc).isoformat()
        with _lock:
            if instance_id in _instances:
                _instances[instance_id]["status"] = status
                _instances[instance_id]["last_seen"] = last_seen
        return {"ok": True, "instance_id": instance_id, "status": status, "http_code": resp.status_code}
    except Exception as exc:
        with _lock:
            if instance_id in _instances:
                _instances[instance_id]["status"] = "offline"
        return {"ok": False, "instance_id": instance_id, "status": "offline", "error": str(exc)}


def ping_all_instances() -> list[dict]:
    """Ping all registered instances and return health summary."""
    return [ping_instance(iid) for iid in list(_instances.keys())]


# ── Passthrough proxy ─────────────────────────────────────────────────────────

def passthrough_request(instance_id: str, method: str, path: str,
                        body: dict | None = None, headers: dict | None = None) -> dict:
    """Forward a request to a remote Nexus instance and return its response."""
    with _lock:
        inst = _instances.get(instance_id)
    if not inst:
        return {"ok": False, "error": f"Instance '{instance_id}' not found", "status_code": 404}

    url     = inst.get("url", "")
    api_key = inst.get("api_key", "")
    target  = f"{url}/{path.lstrip('/')}"

    req_headers = {"Content-Type": "application/json"}
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"
    if headers:
        # Only forward safe headers; drop Authorization to avoid leaking caller tokens
        safe = {k: v for k, v in headers.items()
                if k.lower() not in {"authorization", "host", "content-length"}}
        req_headers.update(safe)

    log_entry = {
        "id":          str(uuid.uuid4())[:8],
        "ts":          datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id,
        "method":      method.upper(),
        "path":        path,
        "status_code": None,
        "error":       None,
    }

    try:
        import requests  # type: ignore
        resp = requests.request(
            method.upper(), target,
            json=body, headers=req_headers, timeout=60,
        )
        log_entry["status_code"] = resp.status_code
        _passthrough_log.append(log_entry)
        if len(_passthrough_log) > 200:
            _passthrough_log.pop(0)

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {"ok": resp.ok, "status_code": resp.status_code, "data": data}
    except Exception as exc:
        log_entry["error"] = str(exc)
        _passthrough_log.append(log_entry)
        return {"ok": False, "error": str(exc), "status_code": 502}


def get_passthrough_log(limit: int = 50) -> list[dict]:
    return list(reversed(_passthrough_log[-limit:]))


# ── Nexus Systems API passthrough ─────────────────────────────────────────────

NEXUS_SYSTEMS_URL   = os.getenv("NEXUS_SYSTEMS_URL", "https://api.nexus-systems.io")
NEXUS_SYSTEMS_TOKEN = os.getenv("NEXUS_SYSTEMS_TOKEN", "")


def nexus_systems_passthrough(method: str, endpoint: str, body: dict | None = None) -> dict:
    """Proxy a request to the upstream Nexus Systems control-plane API."""
    if not NEXUS_SYSTEMS_TOKEN:
        return {"ok": False, "error": "NEXUS_SYSTEMS_TOKEN not configured"}

    target = f"{NEXUS_SYSTEMS_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {NEXUS_SYSTEMS_TOKEN}",
        "Content-Type":  "application/json",
        "X-Nexus-Instance": THIS_INSTANCE_ID,
    }
    try:
        import requests  # type: ignore
        resp = requests.request(method.upper(), target, json=body, headers=headers, timeout=30)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        return {"ok": resp.ok, "status_code": resp.status_code, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "status_code": 502}
