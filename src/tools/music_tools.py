from __future__ import annotations

"""Music generation tool stubs (feature-flag gated)."""

import time
import uuid

from ..config.feature_flags import ENABLE_CREATIVE_TOOLS
from ..feature_flags import is_enabled


def generate_music(prompt: str, duration: int = 15, style: str = "ambient") -> dict:
    if not is_enabled(ENABLE_CREATIVE_TOOLS, default=False):
        return {
            "ok": False,
            "error": "creative_tools_disabled",
            "message": "Creative tools are disabled. Enable ENABLE_CREATIVE_TOOLS to use music generation.",
        }

    # Stub response for future ACE-Step / DiffRhythm backend integration.
    return {
        "ok": True,
        "job_id": f"music_{uuid.uuid4().hex[:12]}",
        "backend": "stub",
        "model": "placeholder",
        "prompt": prompt,
        "style": style,
        "duration_seconds": int(max(1, duration)),
        "status": "queued",
        "created_at": time.time(),
    }
