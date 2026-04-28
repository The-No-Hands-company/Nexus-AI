"""
src/hardware.py — Hardware detection and routing stub

This module is a STUB — all functions raise NotImplementedError until implemented.

Planned capabilities:
- Detect available hardware (CUDA GPU, Apple Silicon MPS, CPU)
- GPU VRAM check for model fit
- Hardware-aware provider routing (prefer GPU-backed if available)
- System resource tracking (RAM / VRAM / CPU load)
- User-contributed compute opt-in (federated inference)
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import threading


# ---------------------------------------------------------------------------
# Hardware capability report
# ---------------------------------------------------------------------------

@dataclass
class HardwareReport:
    cpu_cores: int
    ram_gb: float
    gpu_count: int
    gpu_vram_gb: list[float]   # per GPU
    gpu_names: list[str]
    has_cuda: bool
    has_mps: bool              # Apple Silicon Metal
    inference_backend: str     # "cuda" | "mps" | "cpu"


def detect_hardware() -> HardwareReport:
    """Detect local hardware with graceful optional dependency fallbacks."""
    cpu_cores = os.cpu_count() or 1
    ram_gb = 0.0
    gpu_count = 0
    gpu_vram_gb: list[float] = []
    gpu_names: list[str] = []
    has_cuda = False

    try:
        import psutil  # type: ignore
        ram_gb = round(float(psutil.virtual_memory().total) / (1024 ** 3), 2)
    except Exception:
        ram_gb = 0.0

    try:
        import torch  # type: ignore
        has_cuda = bool(torch.cuda.is_available())
        if has_cuda:
            gpu_count = int(torch.cuda.device_count())
            for idx in range(gpu_count):
                props = torch.cuda.get_device_properties(idx)
                gpu_names.append(str(props.name))
                gpu_vram_gb.append(round(float(props.total_memory) / (1024 ** 3), 2))
    except Exception:
        has_cuda = False

    system_name = platform.system().lower()
    machine = platform.machine().lower()
    has_mps = system_name == "darwin" and ("arm" in machine or "apple" in machine)

    backend = "cuda" if has_cuda else ("mps" if has_mps else "cpu")
    return HardwareReport(
        cpu_cores=cpu_cores,
        ram_gb=ram_gb,
        gpu_count=gpu_count,
        gpu_vram_gb=gpu_vram_gb,
        gpu_names=gpu_names,
        has_cuda=has_cuda,
        has_mps=has_mps,
        inference_backend=backend,
    )


def get_recommended_model_size(task: str = "general") -> str:
    """
    Return the largest model size class that fits in available VRAM.

    Returns one of: ``"3b"`` | ``"7b"`` | ``"13b"`` | ``"32b"`` | ``"70b"``

    Uses detected backend and VRAM to choose a practical local model tier.
    """
    report = detect_hardware()
    vram = max(report.gpu_vram_gb) if report.gpu_vram_gb else 0.0

    if report.has_cuda and vram >= 40:
        return "70b"
    if report.has_cuda and vram >= 20:
        return "32b"
    if report.has_cuda and vram >= 10:
        return "13b"
    if report.has_cuda and vram >= 6:
        return "7b"
    if report.has_mps:
        return "7b"
    return "3b"


def can_run_model(model_name: str) -> bool:
    """
    Return True if the current hardware can run *model_name* locally.

    Parses common parameter markers (e.g. 7b, 13b, 70b) and compares against
    local hardware recommendation.
    """
    if not model_name.strip():
        return False

    model = model_name.lower()
    size_match = re.search(r"(\d+)\s*b", model)
    if not size_match:
        return prefer_local_inference()

    requested_b = int(size_match.group(1))
    allowed = get_recommended_model_size()
    allowed_match = re.search(r"(\d+)\s*b", allowed)
    allowed_b = int(allowed_match.group(1)) if allowed_match else 3
    return requested_b <= allowed_b


# ---------------------------------------------------------------------------
# Hardware-aware provider routing
# ---------------------------------------------------------------------------

def prefer_local_inference() -> bool:
    """
    Return True if local inference should be preferred over cloud providers.

    STUB: reads PREFER_LOCAL env var, defaults to False.
    """
    return os.environ.get("PREFER_LOCAL", "").lower() in ("1", "true", "yes")


def get_hardware_routing_hint() -> dict:
    """
    Return a routing hint dict for use by the model router.

    Returns current hardware capability summary for router decisions.
    """
    report = detect_hardware()
    max_vram = max(report.gpu_vram_gb) if report.gpu_vram_gb else 0.0
    preferred_tier = "high" if report.has_cuda and max_vram >= 20 else ("medium" if report.has_cuda or report.has_mps else "low")
    return {
        "prefer_local": prefer_local_inference(),
        "has_gpu": bool(report.has_cuda or report.gpu_count > 0),
        "vram_gb": max_vram,
        "backend": report.inference_backend,
        "recommended_model_size": get_recommended_model_size(),
        "recommended_tier": preferred_tier,
    }


# ---------------------------------------------------------------------------
# Federated / contributed compute (future)
# ---------------------------------------------------------------------------

def register_contributed_compute(
    endpoint: str,
    api_key: str,
    max_concurrent: int = 1,
) -> dict:
    """Register this machine as a contributed compute node (local placeholder)."""
    if not endpoint.strip():
        raise ValueError("endpoint is required")
    if not api_key.strip():
        raise ValueError("api_key is required")
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be >= 1")

    report = detect_hardware()
    node_fingerprint = hashlib.sha256(
        f"{platform.node()}|{endpoint}|{report.inference_backend}|{max_concurrent}".encode("utf-8")
    ).hexdigest()[:12]
    node_id = f"edge-{node_fingerprint}"
    registration = {
        "status": "registered",
        "node_id": node_id,
        "endpoint": endpoint,
        "max_concurrent": int(max_concurrent),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "hardware": {
            "cpu_cores": report.cpu_cores,
            "ram_gb": report.ram_gb,
            "gpu_count": report.gpu_count,
            "inference_backend": report.inference_backend,
        },
    }
    with _contrib_lock:
        _contributed_nodes[node_id] = registration
    return registration


_contributed_nodes: dict[str, dict] = {}
_contrib_lock = threading.Lock()


def list_contributed_compute_nodes() -> list[dict]:
    """List all locally registered contributed compute nodes."""
    with _contrib_lock:
        return [dict(v) for v in _contributed_nodes.values()]


def deregister_contributed_compute(node_id: str) -> bool:
    """Remove a contributed compute registration by node ID."""
    with _contrib_lock:
        return _contributed_nodes.pop(node_id, None) is not None
