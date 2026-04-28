"""
src/agents/tools/rag_query.py — Typed RAG query wrapper stub

Thin typed wrapper around the RAG retrieval pipeline with
structured result types and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RAGChunk:
    content: str
    source: str
    score: float
    chunk_id: str = ""
    metadata: dict = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RAGResult:
    query: str
    chunks: list[RAGChunk]
    context: str      # pre-formatted string ready for prompt injection
    collection: str
    retrieved_at: str = ""


def rag_query(
    query: str,
    collection: str = "default",
    n_results: int = 5,
    min_score: float = 0.5,
    filter_metadata: dict | None = None,
) -> RAGResult:
    """
    Query the RAG vector store and return typed results.

    STUB: raises NotImplementedError until RAG pipeline is connected.
    Implementation plan:
    - Call src/rag/retriever.retrieve() with query and collection
    - Filter by min_score
    - Format chunks into context string
    - Return RAGResult
    """
    raise NotImplementedError(
        "rag_query is not yet implemented as typed wrapper. "
        "Planned: call src/rag/retriever.retrieve() → RAGResult."
    )


def format_rag_context(chunks: list[RAGChunk], max_chars: int = 4000) -> str:
    """Format a list of RAGChunks into a context string for prompt injection."""
    if not chunks:
        return ""
    parts = []
    total = 0
    for i, chunk in enumerate(chunks, 1):
        header = f"[Source {i}: {chunk.source} (score={chunk.score:.2f})]"
        body = chunk.content.strip()
        block = f"{header}\n{body}\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n---\n".join(parts)


def ingest_text(
    text: str,
    source: str,
    collection: str = "default",
    metadata: dict | None = None,
) -> str:
    """
    Ingest a text chunk into the RAG vector store.

    STUB: raises NotImplementedError.
    Implementation plan: call src/rag/ingestion.ingest_text().
    """
    raise NotImplementedError(
        "ingest_text is not yet implemented. "
        "Planned: call src/rag/ingestion.ingest_text()."
    )
