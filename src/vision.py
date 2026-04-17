"""
src/vision.py — Vision understanding stub

Handles image input routing and vision model dispatch.
This module is a STUB — all functions raise NotImplementedError until implemented.

Planned capabilities:
- Route requests containing images to vision-capable providers
- Local vision model support via Ollama (LLaVA, Qwen-VL, Llama 4 Vision)
- OCR (text extraction from images)
- Screenshot capture via headless browser
- Image description and analysis
"""

from __future__ import annotations

import base64
import os
from typing import Optional


# ---------------------------------------------------------------------------
# Vision provider routing
# ---------------------------------------------------------------------------

VISION_CAPABLE_PROVIDERS = [
    "ollama",   # LLaVA / Qwen-VL / Llama 4 Vision
    "claude",   # Claude 3 family
    "gemini",   # Gemini 1.5+ family
    "openrouter",
    "github_models",
]


def is_vision_request(messages: list[dict]) -> bool:
    """Return True if any message in the list contains an image_url content part."""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def route_vision_provider(messages: list[dict], preferred_provider: str | None = None) -> str:
    """
    Return the best available provider name for a vision request.

    STUB: currently returns the first entry in VISION_CAPABLE_PROVIDERS
    that matches the preferred_provider or just the default list order.
    """
    # TODO: integrate with model_router to check which vision providers
    #       are not in cooldown and have a loaded vision model available.
    if preferred_provider and preferred_provider in VISION_CAPABLE_PROVIDERS:
        return preferred_provider
    return VISION_CAPABLE_PROVIDERS[0]


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_image_bytes(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """
    Extract text from an image using OCR via a vision model.

    Uses a vision LLM with an OCR-specific prompt to extract all visible text.
    This avoids requiring additional ML libraries while leveraging existing vision models.
    """
    ocr_prompt = (
        "You are an OCR engine. Extract and return ALL visible text from this image, "
        "preserving line breaks and formatting as much as possible. "
        "Include any text in signs, documents, code, captions, or any other visible text. "
        "Return only the extracted text, nothing else."
    )
    return describe_image(image_bytes, mime_type=mime_type, prompt=ocr_prompt)


def ocr_image_path(path: str) -> str:
    """Extract text from an image file at *path*. STUB."""
    with open(path, "rb") as f:
        data = f.read()
    mime_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return ocr_image_bytes(data, mime_type=mime_type)


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def capture_screenshot(url: str, width: int = 1280, height: int = 800) -> bytes:
    """
    Capture a screenshot of *url* using a headless browser.

    Returns PNG bytes representing the rendered page.
    For now, returns a deterministic placeholder that includes the URL in the image.
    Future: integrate with Playwright or Puppeteer for real rendering.

    Args:
        url: URL to screenshot
        width: viewport width in pixels (default: 1280)
        height: viewport height in pixels (default: 800)

    Returns:
        PNG bytes
    """
    import struct
    import zlib
    import hashlib

    # Validate inputs
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width > 4096 or height > 4096:
        raise ValueError("width and height must be <= 4096")

    # Generate deterministic colors based on URL hash
    url_hash = hashlib.sha256(url.encode("utf-8")).digest()
    red_base = url_hash[0]
    green_base = url_hash[1]
    blue_base = url_hash[2]

    # Create PNG image data with gradient
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # Filter type for this row
        for x in range(width):
            red = (red_base + (x * 255) // max(width - 1, 1)) % 256
            green = (green_base + (y * 255) // max(height - 1, 1)) % 256
            blue = (blue_base + ((x + y) * 100) // max(width + height, 1)) % 256
            rows.extend((red, green, blue))

    # Build PNG structure
    def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        return (
            struct.pack(">I", len(chunk_data))
            + chunk_type
            + chunk_data
            + struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), level=9)

    return b"".join([
        b"\x89PNG\r\n\x1a\n",
        _png_chunk(b"IHDR", ihdr),
        _png_chunk(b"IDAT", idat),
        _png_chunk(b"IEND", b""),
    ])


# ---------------------------------------------------------------------------
# Image description
# ---------------------------------------------------------------------------

def describe_image(
    image_bytes: bytes,
    mime_type: str = "image/png",
    prompt: str = "Describe this image in detail.",
    provider: str | None = None,
) -> str:
    """
    Send an image to a vision-capable LLM and return its description.

    Takes raw image bytes, encodes as base64, routes to a vision-capable provider,
    and returns the LLM's description of the image content.
    """
    import base64
    from .agent import call_llm_with_fallback, get_best_vision_model, AllProvidersExhausted
    
    # Encode image to base64
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    
    # Build message with vision-format content
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
            ],
        }
    ]
    
    try:
        response, provider_used = call_llm_with_fallback(messages, task="image_description")
        if isinstance(response, dict):
            return response.get("content", str(response))
        return str(response)
    except AllProvidersExhausted:
        raise
    except Exception as e:
        raise RuntimeError(f"Vision description failed: {e}") from e


def describe_image_path(path: str, prompt: str = "Describe this image in detail.") -> str:
    """Describe an image file at *path*. STUB."""
    with open(path, "rb") as f:
        data = f.read()
    mime_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return describe_image(data, mime_type=mime_type, prompt=prompt)
