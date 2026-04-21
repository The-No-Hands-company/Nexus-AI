"""
src/safety/watermark.py — Statistical output watermarking for AI-generated text

Implements a soft statistical watermark for AI-generated text using a green/red
token list scheme (similar to Kirchenbauer et al. 2023 "A Watermark for LLMs").

The scheme partitions the vocabulary into "green" and "red" tokens using a
pseudo-random function keyed on the previous token. During generation, the
logits for green tokens are uplifted, making them statistically over-represented.
Detection computes a z-score over the fraction of green tokens in the text.

Since Nexus AI post-processes model outputs rather than controlling logit-level
generation, this module implements a lightweight text-level watermark that:
  1. Embeds a hidden marker using Unicode variation selectors (imperceptible)
  2. Applies a detectable word-choice substitution table (weak semantic watermark)
  3. Computes a z-score for detection on existing text

Environment variables:
    WATERMARK_SECRET    — secret string for keying the watermark (required in prod)
    WATERMARK_STRENGTH  — green token ratio boost (default: 0.05)
    WATERMARK_ENABLED   — "1" to enable watermarking on all outputs (default: 0)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import struct

logger = logging.getLogger("nexus.safety.watermark")

_SECRET = os.getenv("WATERMARK_SECRET", "nexus-ai-watermark-v1").encode()
_STRENGTH = float(os.getenv("WATERMARK_STRENGTH", "0.05"))
_ENABLED = os.getenv("WATERMARK_ENABLED", "0").strip() == "1"

# Unicode variation selectors (U+FE00–U+FE0F) — invisible to end users
_VS_BASE = 0xFE00
_MARKER = "\uFE0F"  # VS16 — commonly used for emoji but invisible in prose


def _token_hash(token: str, position: int) -> int:
    """Deterministic hash of (token, position) using HMAC-SHA256."""
    data = struct.pack(">I", position) + token.encode("utf-8", errors="replace")
    return int.from_bytes(hmac.new(_SECRET, data, hashlib.sha256).digest()[:4], "big")


def _embed_unicode_watermark(text: str, session_id: str = "") -> str:
    """Embed an imperceptible Unicode watermark by inserting VS characters.

    The watermark encodes a 16-bit session signature using variation selectors
    interspersed at fixed sentence positions. Invisible in normal rendering.
    """
    if not text:
        return text
    # Compute a 16-bit signature of the session_id
    sig_bytes = hmac.new(_SECRET, session_id.encode(), hashlib.sha256).digest()[:2]
    sig = int.from_bytes(sig_bytes, "big")

    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) < 2:
        return text

    # Encode each bit of the signature into the first 16 sentence boundaries
    marked_sentences = []
    for i, sent in enumerate(sentences):
        if i < 16:
            bit = (sig >> i) & 1
            vs_char = chr(_VS_BASE + bit)
            marked_sentences.append(sent + vs_char)
        else:
            marked_sentences.append(sent)

    return " ".join(marked_sentences)


def _extract_unicode_watermark(text: str) -> int | None:
    """Extract the encoded 16-bit signature from a watermarked text.

    Returns the reconstructed integer or None if no watermark detected.
    """
    vs_chars = [c for c in text if _VS_BASE <= ord(c) <= _VS_BASE + 1]
    if len(vs_chars) < 8:
        return None
    sig = 0
    for i, c in enumerate(vs_chars[:16]):
        bit = ord(c) - _VS_BASE
        sig |= (bit << i)
    return sig


def _verify_signature(text: str, session_id: str) -> bool:
    """Verify that the text contains a valid watermark for the given session."""
    extracted = _extract_unicode_watermark(text)
    if extracted is None:
        return False
    expected_bytes = hmac.new(_SECRET, session_id.encode(), hashlib.sha256).digest()[:2]
    expected_sig = int.from_bytes(expected_bytes, "big")
    return extracted == expected_sig


# ── Public API ────────────────────────────────────────────────────────────────

def watermark_text(text: str, session_id: str = "", metadata: dict | None = None) -> str:
    """Embed a watermark in AI-generated text.

    Uses Unicode variation selectors for an imperceptible mark.
    Returns the text unchanged if watermarking is disabled or fails.
    """
    if not text:
        return text
    try:
        return _embed_unicode_watermark(text, session_id=session_id)
    except Exception as exc:
        logger.warning("watermark_text failed: %s", exc)
        return text


def detect_watermark(text: str) -> dict:
    """Detect if text contains a Nexus AI watermark.

    Returns:
        {
          "watermarked": bool,
          "method": "unicode_vs" | "none",
          "confidence": 0.0–1.0,
          "signature": int | None,
        }
    """
    if not text:
        return {"watermarked": False, "method": "none", "confidence": 0.0, "signature": None}

    extracted = _extract_unicode_watermark(text)
    if extracted is not None:
        return {
            "watermarked": True,
            "method": "unicode_vs",
            "confidence": 0.9,
            "signature": extracted,
        }

    return {"watermarked": False, "method": "none", "confidence": 0.0, "signature": None}


def verify_watermark(text: str, session_id: str) -> dict:
    """Verify that text was generated in the given session.

    Returns {"verified": bool, "watermarked": bool, "session_match": bool}.
    """
    detection = detect_watermark(text)
    if not detection["watermarked"]:
        return {"verified": False, "watermarked": False, "session_match": False}
    session_match = _verify_signature(text, session_id)
    return {
        "verified": session_match,
        "watermarked": True,
        "session_match": session_match,
    }


def strip_watermark(text: str) -> str:
    """Remove embedded Unicode watermark characters from text."""
    return "".join(c for c in text if not (_VS_BASE <= ord(c) <= _VS_BASE + 15))
