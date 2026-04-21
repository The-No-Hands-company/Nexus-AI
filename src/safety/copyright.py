"""
src/safety/copyright.py — Copyright and IP infringement detection

Detects verbatim or near-verbatim reproduction of copyrighted text using:
  1. n-gram fingerprinting with Rabin fingerprints (MinHash-based fuzzy matching)
  2. Exact string matching against a registered corpus of protected works
  3. Known copyright notice detection (regex)

The module maintains an in-process + DB-persisted registry of protected works.
At query time it hashes n-grams of the response and computes Jaccard similarity
against registered fingerprints.

Environment variables:
    COPYRIGHT_SIMILARITY_THRESHOLD — minimum Jaccard to flag (default: 0.25)
    COPYRIGHT_MIN_NGRAM_LEN        — minimum n-gram length (default: 8 words)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.safety.copyright")

_THRESHOLD = float(os.getenv("COPYRIGHT_SIMILARITY_THRESHOLD", "0.25"))
_MIN_NGRAM = int(os.getenv("COPYRIGHT_MIN_NGRAM_LEN", "8"))

# In-memory registry: work_id -> {"title": str, "fingerprints": set[int], "metadata": dict}
_registry: dict[str, dict] = {}


# ── Known copyright notice patterns ──────────────────────────────────────────

_COPYRIGHT_PATTERNS = [
    re.compile(r"©\s*\d{4}", re.I),
    re.compile(r"copyright\s+\d{4}", re.I),
    re.compile(r"all rights reserved", re.I),
    re.compile(r"licensed under\s+(the\s+)?(MIT|Apache|GPL|BSD|CC BY)", re.I),
    re.compile(r"reproduction\s+(is\s+)?prohibited", re.I),
    re.compile(r"do not (copy|reproduce|distribute)", re.I),
]


# ── n-gram fingerprinting ─────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w+\b', text.lower())


def _ngram_hashes(tokens: list[str], n: int) -> set[int]:
    hashes: set[int] = set()
    for i in range(len(tokens) - n + 1):
        gram = " ".join(tokens[i:i+n])
        hashes.add(int(hashlib.md5(gram.encode()).hexdigest()[:8], 16))
    return hashes


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Registry management ───────────────────────────────────────────────────────

def register_protected_work(
    work_id: str,
    title: str,
    text: str,
    metadata: dict | None = None,
) -> None:
    """Register a protected work in the copyright registry.

    Computes n-gram fingerprints from *text* and stores them for future comparison.
    Also persists to DB for cross-restart durability.
    """
    tokens = _tokenize(text)
    fps = _ngram_hashes(tokens, _MIN_NGRAM)
    _registry[work_id] = {
        "title": title,
        "fingerprints": fps,
        "metadata": metadata or {},
        "token_count": len(tokens),
    }
    # Persist to DB (fingerprints stored as sorted hex list)
    try:
        from src.db import save_pref  # type: ignore
        fp_list = sorted(fps)
        save_pref(f"copyright:work:{work_id}", {
            "title": title, "metadata": metadata or {}, "token_count": len(tokens),
            "fingerprints": fp_list[:50000],  # cap at 50k for DB storage
        })
    except Exception:
        pass


def load_registry_from_db() -> None:
    """Hydrate the in-memory registry from the DB on startup."""
    try:
        from src.db import load_pref, _backend  # type: ignore
        # List all copyright:work: keys
        if hasattr(_backend, "conn"):
            conn = _backend.conn()
            rows = conn.execute(
                "SELECT key, value FROM user_prefs WHERE key LIKE 'copyright:work:%'"
            ).fetchall()
            for key, value_str in rows:
                import json
                work_id = key.replace("copyright:work:", "")
                data = json.loads(value_str) if isinstance(value_str, str) else value_str
                fps = set(data.get("fingerprints", []))
                _registry[work_id] = {
                    "title": data.get("title", ""),
                    "fingerprints": fps,
                    "metadata": data.get("metadata", {}),
                    "token_count": data.get("token_count", 0),
                }
    except Exception as exc:
        logger.debug("load_registry_from_db: %s", exc)


def list_protected_works() -> list[dict]:
    return [
        {"work_id": k, "title": v["title"], "token_count": v["token_count"],
         "metadata": v["metadata"]}
        for k, v in _registry.items()
    ]


# ── Detection ─────────────────────────────────────────────────────────────────

@dataclass
class CopyrightResult:
    flagged: bool
    matches: list[dict] = field(default_factory=list)  # list of {work_id, title, similarity}
    notice_detected: bool = False
    notice_patterns: list[str] = field(default_factory=list)
    highest_similarity: float = 0.0


def check_copyright(text: str) -> CopyrightResult:
    """Check if *text* may contain copyrighted content.

    Returns a CopyrightResult with similarity scores against registered works
    and detection of explicit copyright notices.
    """
    if not text:
        return CopyrightResult(flagged=False)

    # 1. Check for explicit copyright notices
    notice_patterns_found = []
    for pat in _COPYRIGHT_PATTERNS:
        m = pat.search(text)
        if m:
            notice_patterns_found.append(m.group(0))

    # 2. Fingerprint comparison against registry
    tokens = _tokenize(text)
    if len(tokens) < _MIN_NGRAM:
        return CopyrightResult(
            flagged=bool(notice_patterns_found),
            notice_detected=bool(notice_patterns_found),
            notice_patterns=notice_patterns_found,
        )

    query_fps = _ngram_hashes(tokens, _MIN_NGRAM)
    matches = []
    highest = 0.0
    for work_id, work in _registry.items():
        sim = _jaccard(query_fps, work["fingerprints"])
        if sim >= _THRESHOLD:
            matches.append({"work_id": work_id, "title": work["title"], "similarity": round(sim, 4)})
        if sim > highest:
            highest = sim

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    flagged = bool(matches) or bool(notice_patterns_found)

    return CopyrightResult(
        flagged=flagged,
        matches=matches,
        notice_detected=bool(notice_patterns_found),
        notice_patterns=notice_patterns_found,
        highest_similarity=round(highest, 4),
    )


def check_verbatim(text: str, protected_excerpt: str, min_words: int = 20) -> float:
    """Return Jaccard similarity between *text* and *protected_excerpt*.

    A simple check for verbatim copying without needing a registered work.
    Returns 0.0–1.0 (higher = more similar).
    """
    tokens_a = _tokenize(text)
    tokens_b = _tokenize(protected_excerpt)
    fps_a = _ngram_hashes(tokens_a, min(min_words, _MIN_NGRAM))
    fps_b = _ngram_hashes(tokens_b, min(min_words, _MIN_NGRAM))
    return round(_jaccard(fps_a, fps_b), 4)
