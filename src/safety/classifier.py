"""
src/safety/classifier.py — Content harm classifier stub

Multi-category harm classifier for both inputs and outputs.
Categories: violence, hate, self-harm, sexual, dangerous, deception,
misinformation, privacy, code_injection, jailbreak.

This module is a STUB — classify() raises NotImplementedError.
"""

from __future__ import annotations

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


def classify(text: str, backend: str = "keyword") -> ClassificationResult:
    """
    Classify *text* for harm across all categories.

    STUB: keyword backend is partially functional; ML backend raises NotImplementedError.

    Implementation plan:
    - "keyword": simple keyword lookup → fast but low recall
    - "embedding": cosine similarity to harm example embeddings
    - "openai_moderation": call OpenAI Moderation API (cloud only)
    - "local_classifier": fine-tuned BERT/DeBERTa classifier
    """
    if backend == "keyword":
        return _keyword_classify(text)
    if backend == "embedding":
        # Lightweight proxy: scale keyword signal down to represent weaker confidence.
        base = _keyword_classify(text)
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
    raise ValueError(
        f"Unsupported backend '{backend}'. Use one of: keyword, embedding"
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
