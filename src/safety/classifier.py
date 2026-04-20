"""Content harm classifier used by the safety pipeline.

Supports multiple backends:
- keyword: deterministic and lightweight
- embedding: lightweight proxy over keyword signals
- openai_moderation: OpenAI moderation endpoint when API key is present
- local_transformers: optional local transformer classifier when installed
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass


HARM_CATEGORIES = [
    "violence",
    "hate_speech",
    "self_harm",
    "sexual_explicit",
    "dangerous_instructions",
    "deception",
    "misinformation",
    "privacy_violation",
    "code_injection",
    "jailbreak",
]


@dataclass
class ClassificationResult:
    text: str
    flagged: bool
    categories: dict[str, float]   # category → confidence (0.0 – 1.0)
    worst_category: str
    worst_score: float
    model_used: str = "keyword"


def classify(text: str, backend: str = "auto") -> ClassificationResult:
    """
    Classify *text* for harm across all categories.

    Backends:
    - "keyword": simple keyword lookup
    - "embedding": scaled keyword proxy
    - "openai_moderation": OpenAI moderation API
    - "local_transformers": local text-classification model
    - "auto": openai_moderation -> local_transformers -> embedding -> keyword
    """
    source = text or ""
    mode = (backend or "auto").strip().lower()

    if mode == "auto":
        for candidate in ("openai_moderation", "local_transformers", "embedding", "keyword"):
            try:
                return classify(source, candidate)
            except Exception:
                continue
        return _keyword_classify(source)

    if backend == "keyword":
        return _keyword_classify(source)
    if backend == "embedding":
        # Lightweight proxy: scale keyword signal down to represent weaker confidence.
        base = _keyword_classify(source)
        scaled = {k: round(v * 0.8, 4) for k, v in base.categories.items()}
        worst_cat = max(scaled, key=lambda c: scaled[c])
        worst_score = float(scaled[worst_cat])
        return ClassificationResult(
            text=base.text,
            flagged=worst_score >= 0.5,
            categories=scaled,
            worst_category=worst_cat,
            worst_score=worst_score,
            model_used="embedding-proxy",
        )
    if mode == "openai_moderation":
        result = _openai_moderation_classify(source)
        if result is not None:
            return result
        raise RuntimeError("openai moderation unavailable")
    if mode == "local_transformers":
        result = _local_transformers_classify(source)
        if result is not None:
            return result
        raise RuntimeError("local transformers backend unavailable")
    raise ValueError(
        f"Unsupported backend '{backend}'. Use one of: auto, keyword, embedding, openai_moderation, local_transformers"
    )


def _keyword_classify(text: str) -> ClassificationResult:
    """Fast keyword-based harm detection. Low recall, zero latency."""
    lower = text.lower()
    scores: dict[str, float] = {}

    _HATE_KEYWORDS = ["slur", "genocide", "ethnic cleansing"]
    _VIOLENCE_KEYWORDS = ["kill", "bomb", "murder", "shoot", "stab"]
    _SELF_HARM_KEYWORDS = ["suicide", "self-harm", "overdose"]
    _INJECT_KEYWORDS = ["<script>", "'; drop table", "os.system", "subprocess.call"]

    scores["hate_speech"] = 0.9 if any(k in lower for k in _HATE_KEYWORDS) else 0.0
    scores["violence"] = 0.8 if any(k in lower for k in _VIOLENCE_KEYWORDS) else 0.0
    scores["self_harm"] = 0.9 if any(k in lower for k in _SELF_HARM_KEYWORDS) else 0.0
    scores["code_injection"] = 0.95 if any(k in lower for k in _INJECT_KEYWORDS) else 0.0
    # Other categories default to 0
    for cat in HARM_CATEGORIES:
        scores.setdefault(cat, 0.0)

    worst_cat = max(scores, key=lambda c: scores[c])
    worst_score = scores[worst_cat]
    flagged = worst_score >= 0.5

    return ClassificationResult(
        text=text[:200],
        flagged=flagged,
        categories=scores,
        worst_category=worst_cat,
        worst_score=worst_score,
        model_used="keyword",
    )


def _openai_moderation_classify(text: str) -> ClassificationResult | None:
    api_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    payload = json.dumps({"model": "omni-moderation-latest", "input": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/moderations",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    results = data.get("results") or []
    if not results:
        return None
    first = results[0] or {}
    categories_raw = first.get("category_scores") or {}

    mapped = {
        "violence": float(categories_raw.get("violence", 0.0) or 0.0),
        "hate_speech": float(categories_raw.get("hate", 0.0) or 0.0),
        "self_harm": float(categories_raw.get("self-harm", 0.0) or 0.0),
        "sexual_explicit": float(categories_raw.get("sexual", 0.0) or 0.0),
        "dangerous_instructions": float(categories_raw.get("violence/graphic", 0.0) or 0.0),
        "deception": 0.0,
        "misinformation": 0.0,
        "privacy_violation": float(categories_raw.get("illicit", 0.0) or 0.0),
        "code_injection": float(categories_raw.get("illicit", 0.0) or 0.0),
        "jailbreak": float(categories_raw.get("illicit", 0.0) or 0.0),
    }
    for cat in HARM_CATEGORIES:
        mapped.setdefault(cat, 0.0)

    worst_cat = max(mapped, key=lambda c: mapped[c])
    worst_score = float(mapped[worst_cat])
    flagged = bool(first.get("flagged", False)) or worst_score >= 0.55
    return ClassificationResult(
        text=text[:200],
        flagged=flagged,
        categories=mapped,
        worst_category=worst_cat,
        worst_score=worst_score,
        model_used="openai-moderation",
    )


def _local_transformers_classify(text: str) -> ClassificationResult | None:
    model_name = (os.getenv("SAFETY_LOCAL_CLASSIFIER_MODEL", "unitary/toxic-bert") or "unitary/toxic-bert").strip()
    try:
        from transformers import pipeline  # type: ignore
    except Exception:
        return None

    try:
        clf = pipeline("text-classification", model=model_name, return_all_scores=True)
        scored = clf(text[:4000])
    except Exception:
        return None

    rows = scored[0] if scored and isinstance(scored, list) else []
    label_scores = {str(item.get("label", "")).lower(): float(item.get("score", 0.0) or 0.0) for item in rows}
    mapped = {
        "violence": label_scores.get("threat", 0.0),
        "hate_speech": label_scores.get("identity_hate", 0.0),
        "self_harm": label_scores.get("self_harm", 0.0),
        "sexual_explicit": label_scores.get("sexual_explicit", 0.0),
        "dangerous_instructions": label_scores.get("severe_toxic", 0.0),
        "deception": 0.0,
        "misinformation": 0.0,
        "privacy_violation": 0.0,
        "code_injection": 0.0,
        "jailbreak": label_scores.get("toxic", 0.0),
    }
    for cat in HARM_CATEGORIES:
        mapped.setdefault(cat, 0.0)

    worst_cat = max(mapped, key=lambda c: mapped[c])
    worst_score = float(mapped[worst_cat])
    flagged = worst_score >= 0.6
    return ClassificationResult(
        text=text[:200],
        flagged=flagged,
        categories=mapped,
        worst_category=worst_cat,
        worst_score=worst_score,
        model_used=f"local-transformers:{model_name}",
    )
