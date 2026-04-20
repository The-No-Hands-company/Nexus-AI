"""Vision helpers for OCR, screenshot capture, and image understanding."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile


VISION_CAPABLE_PROVIDERS = [
    "ollama",
    "claude",
    "gemini",
    "openrouter",
    "github_models",
]


def is_vision_request(messages: list[dict]) -> bool:
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def route_vision_provider(messages: list[dict], preferred_provider: str | None = None) -> str:
    if preferred_provider and preferred_provider in VISION_CAPABLE_PROVIDERS:
        return preferred_provider
    return VISION_CAPABLE_PROVIDERS[0]


def ocr_image_bytes(image_bytes: bytes, mime_type: str = "image/png") -> str:
    ocr_prompt = (
        "You are an OCR engine. Extract and return ALL visible text from this image, "
        "preserving line breaks and formatting as much as possible. "
        "Include any text in signs, documents, code, captions, or any other visible text. "
        "Return only the extracted text, nothing else."
    )
    return describe_image(image_bytes, mime_type=mime_type, prompt=ocr_prompt)


def ocr_image_path(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    mime_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return ocr_image_bytes(data, mime_type=mime_type)


def _capture_with_playwright(url: str, width: int, height: int) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle", timeout=45000)
            image_bytes = page.screenshot(type="png", full_page=True)
            browser.close()
            return image_bytes
    except Exception:
        return None


def _capture_with_browser_binary(url: str, width: int, height: int) -> bytes | None:
    browser_candidates = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "firefox",
    ]
    binary = next((candidate for candidate in browser_candidates if shutil.which(candidate)), None)
    if not binary:
        return None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        output_path = tmp.name
    try:
        if "firefox" in binary:
            cmd = [binary, "--headless", "--screenshot", output_path, "--window-size", f"{width},{height}", url]
        else:
            cmd = [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                f"--screenshot={output_path}",
                url,
            ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(output_path):
            return None
        with open(output_path, "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        try:
            os.unlink(output_path)
        except Exception:
            pass


def capture_screenshot(url: str, width: int = 1280, height: int = 800) -> bytes:
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width > 4096 or height > 4096:
        raise ValueError("width and height must be <= 4096")

    screenshot = _capture_with_playwright(url, width, height)
    if screenshot is None:
        screenshot = _capture_with_browser_binary(url, width, height)
    if screenshot is None:
        raise RuntimeError(
            "No screenshot backend available. Install Playwright or ensure a headless browser binary is present in PATH"
        )
    return screenshot


def describe_image(
    image_bytes: bytes,
    mime_type: str = "image/png",
    prompt: str = "Describe this image in detail.",
    provider: str | None = None,
) -> str:
    from .agent import AllProvidersExhausted, call_llm_with_fallback

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
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
        response, _provider_used = call_llm_with_fallback(messages, task="image_description")
        if isinstance(response, dict):
            return response.get("content", str(response))
        return str(response)
    except AllProvidersExhausted:
        raise
    except Exception as e:
        raise RuntimeError(f"Vision description failed: {e}") from e


def describe_image_path(path: str, prompt: str = "Describe this image in detail.") -> str:
    with open(path, "rb") as f:
        data = f.read()
    mime_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return describe_image(data, mime_type=mime_type, prompt=prompt)
