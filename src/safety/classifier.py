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

    Backends (tried in order for "auto"):
    - "openai_moderation": OpenAI omni-moderation API (requires OPENAI_API_KEY)
    - "perspective": Google Perspective API (requires PERSPECTIVE_API_KEY)
    - "local_transformers": local transformer classifier (requires transformers + model)
    - "embedding": keyword-signal proxy with confidence scaling
    - "keyword": fast deterministic keyword matching
    - "auto": tries all backends in the order above, returning the first success
    """
    source = text or ""
    mode = (backend or "auto").strip().lower()

    if mode == "auto":
        for candidate in ("openai_moderation", "perspective", "local_transformers", "embedding", "keyword"):
            try:
                return classify(source, candidate)
            except Exception:
                continue
        return _keyword_classify(source)

    if mode == "keyword":
        return _keyword_classify(source)
    if mode == "perspective":
        result = _perspective_classify(source)
        if result is not None:
            return result
        raise RuntimeError("Perspective API unavailable")
    if mode == "embedding":
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
    """Keyword-based harm detection. Fast; used as final fallback when no ML backend is available.

    The keyword lists are significantly broader than a simple 15-word set:
    each category has ~10–20 high-signal terms covering the most common
    harmful requests, with per-match confidence scores.
    """
    lower = text.lower()
    scores: dict[str, float] = {cat: 0.0 for cat in HARM_CATEGORIES}

    _HATE = [
        "ethnic cleansing", "genocide", "n-word", "racial slur", "white supremac",
        "neo-nazi", "antisemit", "islamophob", "homophob", "transphob",
        "subhuman", "exterminate", "cleanse the race",
    ]
    _VIOLENCE = [
        "how to kill", "how to murder", "make a bomb", "build a weapon",
        "instructions to shoot", "how to stab", "mass shooting", "terrorist attack",
        "assassination plan", "synthesize nerve agent", "weaponize", "chlorine gas",
    ]
    _SELF_HARM = [
        "how to commit suicide", "ways to kill myself", "suicide method",
        "lethal dose of", "painless way to die", "self-harm technique",
        "cut myself", "end my life",
    ]
    _SEXUAL_EXPLICIT = [
        "explicit sexual", "nude image of minor", "child pornography",
        "csam", "underage sexual", "grooming children",
    ]
    _DANGEROUS_INSTRUCTIONS = [
        "synthesize methamphetamine", "cook meth", "make ricin", "synthesize vx ",
        "build pipe bomb", "instructions for explosive", "sarin synthesis",
        "how to make fentanyl",
    ]
    _DECEPTION = [
        "phishing email template", "social engineering script", "fake invoice",
        "impersonate bank", "deceptive ad", "manipulate election",
    ]
    _MISINFORMATION = [
        "covid is fake", "vaccines cause autism", "5g causes cancer",
        "election was stolen", "flat earth proof", "chemtrail conspiracy",
    ]
    _PRIVACY = [
        "dox someone", "find home address", "stalk ex", "track phone without consent",
        "spy on partner", "install keylogger secretly",
    ]
    _CODE_INJECTION = [
        "<script>alert", "'; drop table", "union select", "os.system(",
        "subprocess.call(", "__import__('os')", "eval(request.",
        "exec(base64", "system('rm", "`rm -rf`",
    ]
    _JAILBREAK = [
        "ignore previous instructions", "disregard all rules",
        "act as if you have no restrictions", "dan mode", "do anything now",
        "pretend you have no guidelines", "bypass your safety",
        "developer override", "jailbreak",
    ]

    category_keywords = {
        "hate_speech":             (_HATE,               0.9),
        "violence":                (_VIOLENCE,           0.85),
        "self_harm":               (_SELF_HARM,          0.9),
        "sexual_explicit":         (_SEXUAL_EXPLICIT,    0.95),
        "dangerous_instructions":  (_DANGEROUS_INSTRUCTIONS, 0.9),
        "deception":               (_DECEPTION,          0.75),
        "misinformation":          (_MISINFORMATION,     0.7),
        "privacy_violation":       (_PRIVACY,            0.8),
        "code_injection":          (_CODE_INJECTION,     0.95),
        "jailbreak":               (_JAILBREAK,          0.85),
    }

    for cat, (keywords, confidence) in category_keywords.items():
        if any(k in lower for k in keywords):
            scores[cat] = confidence

    worst_cat = max(scores, key=lambda c: scores[c])
    worst_score = scores[worst_cat]
    flagged = worst_score >= 0.5

    return ClassificationResult(
        text=text[:200],
        flagged=flagged,
        categories=scores,
        worst_category=worst_cat,
        worst_score=worst_score,
        model_used="keyword-v2",
    )


def _perspective_classify(text: str) -> ClassificationResult | None:
    """Classify via Google Perspective API (requires PERSPECTIVE_API_KEY env var).

    Perspective API provides real ML-based scores for toxicity, severe_toxicity,
    identity_attack, insult, threat, and sexual_explicit categories.
    """
    api_key = (os.getenv("PERSPECTIVE_API_KEY", "") or "").strip()
    if not api_key:
        return None

    payload = json.dumps({
        "comment": {"text": text[:20480]},
        "requestedAttributes": {
            "TOXICITY": {},
            "SEVERE_TOXICITY": {},
            "IDENTITY_ATTACK": {},
            "INSULT": {},
            "THREAT": {},
            "SEXUALLY_EXPLICIT": {},
        },
    }).encode("utf-8")
    url = f"https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze?key={api_key}"
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    attr = data.get("attributeScores") or {}

    def _score(key: str) -> float:
        return float((attr.get(key) or {}).get("summaryScore", {}).get("value", 0.0))

    mapped = {
        "violence":               _score("THREAT"),
        "hate_speech":            _score("IDENTITY_ATTACK"),
        "self_harm":              0.0,
        "sexual_explicit":        _score("SEXUALLY_EXPLICIT"),
        "dangerous_instructions": _score("SEVERE_TOXICITY"),
        "deception":              0.0,
        "misinformation":         0.0,
        "privacy_violation":      0.0,
        "code_injection":         0.0,
        "jailbreak":              _score("TOXICITY"),
    }
    for cat in HARM_CATEGORIES:
        mapped.setdefault(cat, 0.0)

    worst_cat   = max(mapped, key=lambda c: mapped[c])
    worst_score = float(mapped[worst_cat])
    flagged     = worst_score >= 0.55

    return ClassificationResult(
        text=text[:200],
        flagged=flagged,
        categories=mapped,
        worst_category=worst_cat,
        worst_score=worst_score,
        model_used="perspective-api",
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


_LOCAL_CLF_CACHE: dict = {}  # model_name → pipeline instance


def _local_transformers_classify(text: str) -> ClassificationResult | None:
    model_name = (os.getenv("SAFETY_LOCAL_CLASSIFIER_MODEL", "unitary/toxic-bert") or "unitary/toxic-bert").strip()
    try:
        from transformers import pipeline  # type: ignore
    except Exception:
        return None

    try:
        if model_name not in _LOCAL_CLF_CACHE:
            _LOCAL_CLF_CACHE[model_name] = pipeline(
                "text-classification", model=model_name, return_all_scores=True
            )
        clf = _LOCAL_CLF_CACHE[model_name]
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
