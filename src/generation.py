"""
src/generation.py — Media generation stub (video, local image)

This module is a STUB — all functions raise NotImplementedError until implemented.

Planned capabilities:
- Local video generation via diffusion models
- Local image generation via Flux / SD3 (Ollama or ComfyUI)
- Image-to-image (style transfer)
- Image inpainting / editing
- Video-to-text (frame sampling + vision description)
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from typing import Optional


# ---------------------------------------------------------------------------
# Local image generation
# ---------------------------------------------------------------------------

IMAGE_BACKENDS = ["pollinations", "ollama_flux", "comfyui", "stability_api"]


def generate_image_local(
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    backend: str = "ollama_flux",
    model: str = "auto",
) -> bytes:
    """
    Generate a deterministic PNG placeholder for local image generation flows.

    This provides a working local image path without a heavyweight runtime
    dependency. The output is deterministic for a given prompt/model/backend
    combination so tests can assert the endpoint contract reliably.
    """
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("prompt is required")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width > 2048 or height > 2048:
        raise ValueError("width and height must be <= 2048")
    if steps <= 0:
        raise ValueError("steps must be positive")

    backend_name = backend if backend in IMAGE_BACKENDS else "ollama_flux"
    seed = hashlib.sha256(
        f"{clean_prompt}|{negative_prompt}|{model}|{backend_name}|{width}x{height}|{steps}".encode("utf-8")
    ).digest()
    red_base, green_base, blue_base = seed[0], seed[1], seed[2]

    rows = bytearray()
    width_divisor = max(width - 1, 1)
    height_divisor = max(height - 1, 1)
    prompt_mod = max(len(clean_prompt), 1)

    for y in range(height):
        rows.append(0)
        for x in range(width):
            red = (red_base + (x * 255) // width_divisor) % 256
            green = (green_base + (y * 255) // height_divisor) % 256
            blue = (blue_base + ((x + y + seed[(x + y) % len(seed)]) * prompt_mod) // max(width + height, 1)) % 256
            rows.extend((red, green, blue))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), level=9)

    def _chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        return (
            struct.pack(">I", len(chunk_data))
            + chunk_type
            + chunk_data
            + struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
        )

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", idat),
            _chunk(b"IEND", b""),
        ]
    )


def edit_image(
    image_bytes: bytes,
    mask_bytes: bytes | None = None,
    prompt: str = "",
    backend: str = "comfyui",
) -> bytes:
    """Edit/inpaint image bytes with deterministic placeholder behavior."""
    if not image_bytes:
        raise ValueError("image_bytes is required")
    style_hint = (prompt or "edit").strip()[:120]
    # Deterministic fallback: regenerate a new image keyed by prompt and source length.
    return generate_image_local(
        prompt=f"edited:{style_hint}:{len(image_bytes)}",
        negative_prompt="mask" if mask_bytes else "",
        width=512,
        height=512,
        steps=12,
        backend=backend,
        model="edit-fallback",
    )


def image_to_image(
    image_bytes: bytes,
    style_prompt: str,
    strength: float = 0.75,
    backend: str = "comfyui",
) -> bytes:
    """Apply deterministic style-transfer placeholder using local generator."""
    if not image_bytes:
        raise ValueError("image_bytes is required")
    if not style_prompt.strip():
        raise ValueError("style_prompt is required")
    safe_strength = min(max(float(strength), 0.0), 1.0)
    return generate_image_local(
        prompt=f"img2img:{style_prompt.strip()}:{safe_strength}:{len(image_bytes)}",
        width=512,
        height=512,
        steps=max(8, int(8 + safe_strength * 24)),
        backend=backend,
        model="img2img-fallback",
    )


# ---------------------------------------------------------------------------
# Video generation
# ---------------------------------------------------------------------------

VIDEO_BACKENDS = ["wan_local", "cogvideo_local", "runway_api"]


def generate_video(
    prompt: str,
    duration_seconds: float = 4.0,
    fps: int = 8,
    width: int = 512,
    height: int = 512,
    backend: str = "wan_local",
) -> bytes:
    """
    Generate a short video clip from a text prompt.

    Returns raw video bytes (MP4 format with metadata).
    Currently generates a placeholder MP4 containing metadata about the generation request.
    Future implementations will use Wan 2.1, CogVideoX, or Runway API.

    Args:
        prompt: Text description of video content
        duration_seconds: Target duration in seconds (default: 4.0)
        fps: Frames per second (default: 8)
        width: Video width in pixels (default: 512)
        height: Video height in pixels (default: 512)
        backend: Generation backend (default: "wan_local")

    Returns:
        MP4 file bytes

    Raises:
        ValueError: If parameters are invalid
    """
    import struct
    import hashlib

    # Validate inputs
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if duration_seconds <= 0 or duration_seconds > 60:
        raise ValueError("duration_seconds must be between 0 and 60")
    if fps <= 0 or fps > 60:
        raise ValueError("fps must be between 0 and 60")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width > 4096 or height > 4096:
        raise ValueError("width and height must be <= 4096")

    # Generate minimal MP4 structure
    prompt_hash = hashlib.md5(prompt.encode("utf-8")).hexdigest()
    timecode = int(duration_seconds * fps)  # Total frame count

    # MP4 atoms are in format: [4-byte size][4-byte type][data]
    def _mp4_atom(atom_type: bytes, data: bytes) -> bytes:
        size = len(data) + 8  # data + size + type
        return struct.pack(">I", size) + atom_type + data

    # Create minimal ftyp (file type) atom
    ftyp_data = b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41"
    ftyp = _mp4_atom(b"ftyp", ftyp_data)

    # Create minimal mdat (media data) atom with placeholder
    mdata_content = f"Video: {prompt[:60]} | {width}x{height} @ {fps}fps | {timecode} frames".encode("utf-8")
    mdata_content = mdata_content.ljust(512, b"\x00")[:512]  # Pad to 512 bytes
    mdat = _mp4_atom(b"mdat", mdata_content)

    # Combine atoms into minimal MP4
    mp4_data = ftyp + mdat

    return mp4_data


# ---------------------------------------------------------------------------
# Video understanding
# ---------------------------------------------------------------------------

def video_to_text(
    video_bytes: bytes,
    frame_sample_rate: int = 4,
    prompt: str = "Describe what is happening in this video.",
) -> str:
    """Produce deterministic textual summary from video bytes metadata."""
    if not video_bytes:
        raise ValueError("video_bytes is required")
    sample_rate = max(1, int(frame_sample_rate))
    digest = hashlib.sha256(video_bytes[:2048]).hexdigest()[:16]
    return (
        f"Video summary ({len(video_bytes)} bytes, sample_rate={sample_rate}): "
        f"{prompt.strip()} | fingerprint={digest}"
    )


def detect_video_chapters(video_url: str) -> list[dict]:
    """Return deterministic mock chapters for a video URL."""
    if not video_url.strip():
        raise ValueError("video_url is required")
    seed = int(hashlib.sha256(video_url.encode("utf-8")).hexdigest()[:6], 16)
    base = (seed % 4) + 3
    chapters = []
    start = 0.0
    for idx in range(3):
        length = float(base + idx * 2)
        chapters.append({
            "start": round(start, 2),
            "end": round(start + length, 2),
            "title": f"Chapter {idx + 1}",
        })
        start += length
    return chapters
