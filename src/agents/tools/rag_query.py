from __future__ import annotations

from dataclasses import dataclass

from src.rag import (
    AdaptiveRetriever,
    EmbeddingModel,
    EmbeddingConfig,
    RetrieverConfig,
    RetrievalStrategy,
    VectorStore,
    VectorStoreConfig,
    VectorStoreType,
)


@dataclass
class RAGChunk:
    content: str
    source: str
    score: float
    chunk_id: str = ""
    metadata: dict = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RAGResult:
    query: str
    chunks: list[RAGChunk]
    context: str
    collection: str
    retrieved_at: str = ""


_rag_system = None


def _get_rag_system():
    global _rag_system
    if _rag_system is None:
        embed_config = EmbeddingConfig()
        embedding = EmbeddingModel(embed_config)

        vs_config = VectorStoreConfig(
            store_type=VectorStoreType.MEMORY,
            persist_directory=None,
        )
        vector_store = VectorStore(vs_config, embedding)

        retriever_config = RetrieverConfig(
            strategy=RetrievalStrategy.HYBRID,
            top_k=10,
            rerank_top_k=5,
        )
        retriever = AdaptiveRetriever(vector_store, embedding, retriever_config)

        _rag_system = {
            "embedding": embedding,
            "vector_store": vector_store,
            "retriever": retriever,
        }
    return _rag_system


def rag_query(
    query: str,
    collection: str = "default",
    n_results: int = 5,
    min_score: float = 0.5,
    filter_metadata: dict | None = None,
) -> RAGResult:
    rag = _get_rag_system()
    retriever = rag["retriever"]

    result = retriever.retrieve(
        query,
        top_k=n_results * 2,
        filter_metadata=filter_metadata,
    )

    chunks = []
    for doc, score in zip(result.documents, result.scores):
        if score < min_score:
            continue
        metadata = doc.get("metadata", {})
        chunks.append(RAGChunk(
            content=doc.get("document", ""),
            source=metadata.get("source", doc.get("id", "unknown")),
            score=float(score),
            chunk_id=doc.get("id", ""),
            metadata=metadata,
        ))

    from datetime import datetime, timezone
    return RAGResult(
        query=query,
        chunks=chunks,
        context=format_rag_context(chunks),
        collection=collection,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def format_rag_context(chunks: list[RAGChunk], max_chars: int = 4000) -> str:
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
    rag = _get_rag_system()
    vector_store = rag["vector_store"]
    embedding = rag["embedding"]

    meta = dict(metadata or {})
    meta["source"] = source
    meta["collection"] = collection

    import uuid
    doc_id = f"{collection}-{uuid.uuid4().hex[:12]}"

    vector_store.add_documents(
        documents=[text],
        metadata=[meta],
        ids=[doc_id],
    )

    return doc_id
