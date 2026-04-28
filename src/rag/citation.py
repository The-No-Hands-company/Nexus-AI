"""
src/rag/citation.py — Citation attribution for RAG responses

Maps each sentence in a RAG response to the retrieved document chunk that
most likely supports it, enabling source attribution in enterprise knowledge
management use cases.

Attribution methods (tried in order):
  1. Cross-encoder reranker (sentence-transformers) — most accurate
  2. BM25 term overlap — fast fallback
  3. n-gram Jaccard — last resort

Output formats:
  - Inline citations: "The revenue grew 12% [1]. This exceeded expectations [2]."
  - Footnotes: list of source references at end of response
  - Structured attribution: per-sentence JSON with source chunk + confidence
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.rag.citation")

_cross_encoder = None
_ce_load_attempted = False


# ── Cross-encoder attribution ─────────────────────────────────────────────────

def _load_cross_encoder():
    global _cross_encoder, _ce_load_attempted
    if _ce_load_attempted:
        return _cross_encoder
    _ce_load_attempted = True
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception as exc:
        logger.debug("Citation cross-encoder unavailable: %s", exc)
    return _cross_encoder


# ── n-gram Jaccard ────────────────────────────────────────────────────────────

def _ngram_overlap(a: str, b: str, n: int = 3) -> float:
    def ngrams(text: str) -> set:
        tokens = re.findall(r'\w+', text.lower())
        return {tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}
    sa, sb = ngrams(a), ngrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ── BM25 attribution ──────────────────────────────────────────────────────────

def _bm25_scores(query: str, corpus: list[str]) -> list[float]:
    try:
        from rank_bm25 import BM25Okapi  # type: ignore
        tokenized_corpus = [re.findall(r'\w+', doc.lower()) for doc in corpus]
        tokenized_query = re.findall(r'\w+', query.lower())
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(tokenized_query)
        return list(scores)
    except ImportError:
        return [_ngram_overlap(query, doc) for doc in corpus]


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 10]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Citation:
    chunk_index: int
    chunk_content: str
    source_title: str = ""
    source_url: str = ""
    page: int | None = None
    confidence: float = 0.0


@dataclass
class AttributedSentence:
    sentence: str
    citation: Citation | None
    citation_number: int | None = None


@dataclass
class AttributionResult:
    attributed_sentences: list[AttributedSentence] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    inline_text: str = ""
    footnotes: str = ""
    method: str = "none"


# ── Attribution logic ─────────────────────────────────────────────────────────

def _attribute_sentence_to_chunk(
    sentence: str,
    chunks: list[dict],
    method: str,
) -> tuple[int | None, float]:
    """Return (best_chunk_index, confidence) for a sentence."""
    if not chunks:
        return None, 0.0

    corpus = [c.get("content", "") for c in chunks]

    if method == "cross_encoder":
        model = _load_cross_encoder()
        if model:
            pairs = [(sentence, c) for c in corpus]
            try:
                scores = model.predict(pairs)
                if hasattr(scores, 'tolist'):
                    scores = scores.tolist()
                best_idx = max(range(len(scores)), key=lambda i: scores[i])
                conf = float(max(0.0, min(1.0, (scores[best_idx] + 5) / 10)))
                return best_idx, conf
            except Exception:
                pass

    scores = _bm25_scores(sentence, corpus)
    if not scores:
        return None, 0.0
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    max_score = scores[best_idx]
    # Normalize BM25 score to [0, 1] heuristically
    conf = min(1.0, max_score / max(1.0, max(scores) + 1e-8))
    return best_idx, round(conf, 3)


# ── Public API ────────────────────────────────────────────────────────────────

def attribute_response(
    response: str,
    chunks: list[dict],
    method: str = "auto",
    min_confidence: float = 0.1,
) -> AttributionResult:
    """Attribute each sentence in *response* to the most relevant retrieved chunk.

    chunks: list of {"content": str, "metadata": {"title": str, "url": str, "page": int}}.
    method: "auto" | "cross_encoder" | "bm25" | "ngram"
    min_confidence: minimum confidence to assign a citation (below = no citation).

    Returns an AttributionResult with inline_text and footnotes.
    """
    if not response or not chunks:
        return AttributionResult(inline_text=response, method="none")

    if method == "auto":
        method = "cross_encoder" if _load_cross_encoder() else "bm25"

    sentences = _split_sentences(response)
    cited_sources: dict[int, dict] = {}
    attributed: list[AttributedSentence] = []

    for sentence in sentences:
        chunk_idx, confidence = _attribute_sentence_to_chunk(sentence, chunks, method)
        if chunk_idx is not None and confidence >= min_confidence:
            chunk = chunks[chunk_idx]
            meta = chunk.get("metadata", {})
            # Assign a footnote number
            if chunk_idx not in cited_sources:
                cited_sources[chunk_idx] = {
                    "number": len(cited_sources) + 1,
                    "title": meta.get("title", f"Source {chunk_idx + 1}"),
                    "url": meta.get("url", ""),
                    "page": meta.get("page"),
                    "content_snippet": chunk.get("content", "")[:200],
                }
            num = cited_sources[chunk_idx]["number"]
            citation = Citation(
                chunk_index=chunk_idx,
                chunk_content=chunk.get("content", "")[:200],
                source_title=meta.get("title", ""),
                source_url=meta.get("url", ""),
                page=meta.get("page"),
                confidence=confidence,
            )
            attributed.append(AttributedSentence(sentence=sentence, citation=citation, citation_number=num))
        else:
            attributed.append(AttributedSentence(sentence=sentence, citation=None))

    # Build inline text with citation superscripts
    inline_parts = []
    for a in attributed:
        if a.citation_number:
            inline_parts.append(f"{a.sentence} [{a.citation_number}]")
        else:
            inline_parts.append(a.sentence)
    inline_text = " ".join(inline_parts)

    # Build footnotes
    footnote_lines = []
    for chunk_idx, src in sorted(cited_sources.items(), key=lambda x: x[1]["number"]):
        num = src["number"]
        title = src.get("title", "Unknown")
        url = src.get("url", "")
        page = src.get("page")
        line = f"[{num}] {title}"
        if url:
            line += f" — {url}"
        if page:
            line += f", p. {page}"
        footnote_lines.append(line)
    footnotes = "\n".join(footnote_lines)

    sources = [
        {
            "number": s["number"], "title": s["title"],
            "url": s["url"], "page": s.get("page"),
            "content_snippet": s["content_snippet"],
        }
        for s in sorted(cited_sources.values(), key=lambda x: x["number"])
    ]

    return AttributionResult(
        attributed_sentences=attributed,
        sources=sources,
        inline_text=inline_text,
        footnotes=footnotes,
        method=method,
    )


def format_cited_response(response: str, chunks: list[dict]) -> str:
    """Convenience wrapper: return a fully cited response string with footnotes."""
    result = attribute_response(response, chunks)
    if not result.sources:
        return response
    return f"{result.inline_text}\n\n---\n{result.footnotes}"
