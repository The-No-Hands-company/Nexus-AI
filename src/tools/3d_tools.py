from __future__ import annotations

"""3D model generation tool stubs (feature-flag gated)."""

import time
import uuid

from ..config.feature_flags import ENABLE_CREATIVE_TOOLS
from ..feature_flags import is_enabled


def generate_3d_model(prompt: str, format: str = "glb") -> dict:
    if not is_enabled(ENABLE_CREATIVE_TOOLS, default=False):
        return {
            "ok": False,
            "error": "creative_tools_disabled",
            "message": "Creative tools are disabled. Enable ENABLE_CREATIVE_TOOLS to use 3D generation.",
        }

    # Stub response for future TripoSR / Hunyuan3D backend integration.
    return {
        "ok": True,
        "job_id": f"model3d_{uuid.uuid4().hex[:12]}",
        "backend": "stub",
        "model": "placeholder",
        "prompt": prompt,
        "format": format,
        "status": "queued",
        "created_at": time.time(),
    }
