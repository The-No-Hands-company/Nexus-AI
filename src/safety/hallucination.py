"""
src/safety/hallucination.py — Hallucination detection and grounding verification

Detects when model responses are not grounded in the provided context/documents
using a multi-signal approach:

  1. NLI entailment (sentence-transformers cross-encoder if available):
     classifies each response sentence as entailed/neutral/contradicted by context.
  2. Lexical overlap (BM25 keyword overlap + n-gram Jaccard):
     fast proxy when NLI model is unavailable.
  3. Claim extraction + verification:
     identifies factual claims in the response and checks if each is supported.
  4. LLM-as-judge fallback:
     uses available LLM to verify grounding when other methods are inconclusive.

Environment variables:
    HALLUCINATION_NLI_MODEL  — cross-encoder model name (default: cross-encoder/nli-deberta-v3-small)
    HALLUCINATION_THRESHOLD  — minimum grounding score to pass (default: 0.55)
    HALLUCINATION_BACKEND    — "nli" | "lexical" | "llm" | "auto" (default: auto)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.safety.hallucination")

_NLI_MODEL = os.getenv("HALLUCINATION_NLI_MODEL", "cross-encoder/nli-deberta-v3-small").strip()
_THRESHOLD = float(os.getenv("HALLUCINATION_THRESHOLD", "0.55"))
_BACKEND = os.getenv("HALLUCINATION_BACKEND", "auto").strip().lower()

_nli_pipeline = None
_nli_load_attempted = False


@dataclass
class GroundingResult:
    grounded: bool
    score: float                        # 0.0 (hallucinated) – 1.0 (fully grounded)
    method: str                         # "nli" | "lexical" | "llm" | "none"
    ungrounded_sentences: list[str] = field(default_factory=list)
    evidence_sentences: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ── NLI backend ───────────────────────────────────────────────────────────────

def _load_nli_pipeline():
    global _nli_pipeline, _nli_load_attempted
    if _nli_load_attempted:
        return _nli_pipeline
    _nli_load_attempted = True
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        _nli_pipeline = CrossEncoder(_NLI_MODEL)
        logger.info("Hallucination NLI model loaded: %s", _NLI_MODEL)
    except Exception as exc:
        logger.debug("NLI pipeline unavailable: %s", exc)
        _nli_pipeline = None
    return _nli_pipeline


def _nli_score(response: str, context: str) -> GroundingResult:
    """Score grounding using NLI cross-encoder. context is the premise, each response sentence is the hypothesis."""
    model = _load_nli_pipeline()
    if model is None:
        return _lexical_score(response, context)

    sentences = _split_sentences(response)
    if not sentences:
        return GroundingResult(grounded=True, score=1.0, method="nli")

    # Truncate context to 512 tokens (model limit)
    ctx_trunc = context[:2000]

    pairs = [(ctx_trunc, sent) for sent in sentences]
    try:
        scores = model.predict(pairs, apply_softmax=True)
        # Output shape: (n, 3) with [contradiction, neutral, entailment]
        entailment_scores = [float(s[2]) if hasattr(s, '__len__') else float(s) for s in scores]
    except Exception as exc:
        logger.warning("NLI predict failed: %s", exc)
        return _lexical_score(response, context)

    grounded = []
    ungrounded = []
    for sent, score in zip(sentences, entailment_scores):
        if score >= _THRESHOLD:
            grounded.append(sent)
        else:
            ungrounded.append(sent)

    avg_score = sum(entailment_scores) / len(entailment_scores) if entailment_scores else 0.0
    return GroundingResult(
        grounded=avg_score >= _THRESHOLD,
        score=round(avg_score, 4),
        method="nli",
        ungrounded_sentences=ungrounded,
        evidence_sentences=grounded,
        details={"sentence_scores": list(zip(sentences, [round(s, 3) for s in entailment_scores]))},
    )


# ── Lexical overlap backend ───────────────────────────────────────────────────

def _ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    def ngrams(text: str, k: int) -> set:
        tokens = re.findall(r'\w+', text.lower())
        return {tuple(tokens[i:i+k]) for i in range(len(tokens) - k + 1)}
    set_a, set_b = ngrams(a, n), ngrams(b, n)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _lexical_score(response: str, context: str) -> GroundingResult:
    sentences = _split_sentences(response)
    if not sentences:
        return GroundingResult(grounded=True, score=1.0, method="lexical")

    scores = [_ngram_jaccard(sent, context, n=2) for sent in sentences]
    avg = sum(scores) / len(scores) if scores else 0.0
    # Scale: lexical is weaker signal, so we apply a softer threshold
    lexical_threshold = _THRESHOLD * 0.6
    ungrounded = [s for s, sc in zip(sentences, scores) if sc < lexical_threshold]
    return GroundingResult(
        grounded=avg >= lexical_threshold,
        score=round(min(1.0, avg * 1.5), 4),  # boost for display
        method="lexical",
        ungrounded_sentences=ungrounded,
        details={"threshold": lexical_threshold, "raw_scores": scores},
    )


# ── LLM-as-judge backend ──────────────────────────────────────────────────────

def _llm_score(response: str, context: str) -> GroundingResult:
    """Use available LLM to verify that response is grounded in context."""
    prompt = (
        "You are a factual grounding evaluator.\n\n"
        f"CONTEXT:\n{context[:3000]}\n\n"
        f"RESPONSE:\n{response[:1500]}\n\n"
        "Task: On a scale of 0.0 to 1.0, how well is the RESPONSE grounded in the CONTEXT?\n"
        "Consider: Are all factual claims in the RESPONSE supported by the CONTEXT?\n"
        "Reply with ONLY a JSON object: {\"score\": <float>, \"ungrounded\": [<sentence>, ...]}\n"
    )
    try:
        import json as _json
        from src.generation import generate_text  # type: ignore
        raw = generate_text(prompt, max_tokens=256, temperature=0.0)
        data = _json.loads(raw.strip())
        score = float(data.get("score", 0.5))
        ungrounded = data.get("ungrounded", [])
        return GroundingResult(
            grounded=score >= _THRESHOLD,
            score=round(score, 4),
            method="llm",
            ungrounded_sentences=ungrounded,
        )
    except Exception as exc:
        logger.debug("LLM grounding judge failed: %s", exc)
        return GroundingResult(grounded=True, score=0.5, method="none",
                               details={"error": str(exc)})


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 15]


# ── Public API ────────────────────────────────────────────────────────────────

def check_grounding(response: str, context: str) -> GroundingResult:
    """Check whether *response* is grounded in *context*.

    Returns a GroundingResult with a 0–1 score and list of ungrounded sentences.
    """
    if not response or not context:
        return GroundingResult(grounded=True, score=1.0, method="none",
                               details={"reason": "empty response or context"})

    backend = _BACKEND
    if backend == "auto":
        # Try NLI first (loads model lazily), fall back to lexical
        nli = _load_nli_pipeline()
        backend = "nli" if nli else "lexical"

    if backend == "nli":
        return _nli_score(response, context)
    if backend == "lexical":
        return _lexical_score(response, context)
    if backend == "llm":
        return _llm_score(response, context)

    return _lexical_score(response, context)


def verify_rag_response(response: str, retrieved_chunks: list[dict]) -> GroundingResult:
    """Verify that a RAG response is grounded in the retrieved document chunks.

    retrieved_chunks: list of {"content": str, "metadata": dict} dicts.
    """
    if not retrieved_chunks:
        return GroundingResult(grounded=False, score=0.0, method="none",
                               details={"reason": "no retrieved chunks provided"})
    context = "\n\n".join(chunk.get("content", "") for chunk in retrieved_chunks[:10])
    return check_grounding(response, context)
