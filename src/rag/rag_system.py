"""
VersaAI RAG System — unified facade for document ingestion, retrieval, and Q&A.

This is the primary public interface for the RAG subsystem.  It wires together:
- DocumentChunker  → splits raw text into overlapping chunks
- EmbeddingModel   → embeds chunks and queries (Ollama / sentence-transformers)
- VectorStore      → stores and searches embeddings (ChromaDB / FAISS / memory)

Usage:
    >>> from rag.rag_system import RAGSystem
    >>> rag = RAGSystem()                               # auto-configures
    >>> rag.ingest("VersaAI documentation goes here...", metadata={"source": "docs"})
    >>> results = rag.query("How does the agent system work?", top_k=5)
    >>> for r in results:
    ...     print(r["score"], r["document"][:80])
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .chunker import DocumentChunker, ChunkerConfig
from .embeddings import EmbeddingModel, EmbeddingConfig
from .vector_store import VectorStore, VectorStoreConfig, VectorStoreType

logger = logging.getLogger(__name__)


class RAGSystem:
    """
    End-to-end Retrieval-Augmented Generation system.

    Lifecycle:
        1. ``ingest(text)``   — chunk → embed → store
        2. ``query(question)`` — embed question → search store → return docs

    The system is lazily initialized: the embedding model and vector store
    are created on first use to avoid startup cost when RAG is not needed.
    """

    def __init__(
        self,
        embedding_config: Optional[EmbeddingConfig] = None,
        vector_store_config: Optional[VectorStoreConfig] = None,
        chunker_config: Optional[ChunkerConfig] = None,
    ):
        self._emb_cfg = embedding_config
        self._vs_cfg = vector_store_config
        self._chunk_cfg = chunker_config

        self._embedding_model: Optional[EmbeddingModel] = None
        self._vector_store: Optional[VectorStore] = None
        self._chunker: Optional[DocumentChunker] = None

        self._total_ingested: int = 0
        self._total_queries: int = 0

    # ------------------------------------------------------------------
    # Lazy component init
    # ------------------------------------------------------------------

    @property
    def embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            cfg = self._emb_cfg or EmbeddingConfig()
            self._embedding_model = EmbeddingModel(cfg)
            logger.info("RAGSystem: embedding model ready (%s)", self._embedding_model.backend_name)
        return self._embedding_model

    @property
    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            if self._vs_cfg:
                cfg = self._vs_cfg
            else:
                # Build config with defaults
                cfg = VectorStoreConfig(
                    store_type=VectorStoreType.MEMORY,  # default to memory
                    persist_directory=Path("./rag_data").expanduser(),
                    embedding_dimension=self.embedding_model.dimension,
                    collection_name="nexus_documents",
                )
            try:
                self._vector_store = VectorStore(cfg, embedding_model=self.embedding_model)
            except (ImportError, Exception) as exc:
                if cfg.store_type != VectorStoreType.MEMORY:
                    logger.warning(
                        "RAGSystem: %s backend failed (%s), falling back to in-memory",
                        cfg.store_type.value, exc,
                    )
                    cfg = VectorStoreConfig(
                        store_type=VectorStoreType.MEMORY,
                        embedding_dimension=self.embedding_model.dimension,
                        collection_name="versaai_documents",
                    )
                    self._vector_store = VectorStore(cfg, embedding_model=self.embedding_model)
                else:
                    raise
            logger.info("RAGSystem: vector store ready (%s)", self._vector_store)
        return self._vector_store

    @property
    def chunker(self) -> DocumentChunker:
        if self._chunker is None:
            self._chunker = DocumentChunker(self._chunk_cfg or ChunkerConfig())
        return self._chunker

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id_prefix: Optional[str] = None,
    ) -> int:
        """
        Ingest a document: chunk → embed → store.

        Args:
            text: Raw document text.
            metadata: Optional metadata dict propagated to every chunk.
            doc_id_prefix: Optional prefix for chunk IDs.

        Returns:
            Number of chunks stored.
        """
        t0 = time.perf_counter()
        chunks = self.chunker.split(text, metadata=metadata)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        metas = [c.metadata for c in chunks]

        prefix = doc_id_prefix or f"doc{self._total_ingested}"
        ids = [f"{prefix}_chunk_{i}" for i in range(len(texts))]

        self.vector_store.add_documents(documents=texts, metadata=metas, ids=ids)
        self._total_ingested += len(texts)

        elapsed = time.perf_counter() - t0
        logger.info(
            "Ingested %d chunks in %.2fs (total: %d)",
            len(texts), elapsed, self._total_ingested,
        )
        return len(texts)

    def ingest_documents(
        self,
        documents: List[Dict[str, Any]],
        text_key: str = "text",
    ) -> int:
        """Ingest a list of document dicts; each is chunked and stored."""
        total = 0
        for i, doc in enumerate(documents):
            text = doc.get(text_key, "")
            meta = {k: v for k, v in doc.items() if k != text_key}
            total += self.ingest(text, metadata=meta, doc_id_prefix=f"batch{i}")
        return total

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: Optional[int] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most relevant chunks for a question.

        Returns:
            List of dicts with keys: id, document, score, metadata
        """
        if top_k is None:
            try:
                k = settings.rag.top_k
            except Exception:
                k = 5
        else:
            k = top_k
        t0 = time.perf_counter()

        results = self.vector_store.search(question, k=k, filter_metadata=filter_metadata)
        self._total_queries += 1

        elapsed = time.perf_counter() - t0
        logger.info(
            "Query returned %d results in %.3fs (q=%d total)",
            len(results), elapsed, self._total_queries,
        )
        return results

    # ------------------------------------------------------------------
    # Corpus access
    # ------------------------------------------------------------------

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Return every stored document (for BM25 / sparse retrieval)."""
        return self.vector_store.get_all_documents()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        return {
            "total_ingested": self._total_ingested,
            "total_queries": self._total_queries,
            "store_count": self.vector_store.count() if self._vector_store else 0,
            "embedding_backend": (
                self._embedding_model.backend_name if self._embedding_model else "not initialized"
            ),
            "vector_store": repr(self._vector_store) if self._vector_store else "not initialized",
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        if self._embedding_model:
            self._embedding_model.close()
            self._embedding_model = None
        self._vector_store = None

    def __repr__(self) -> str:
        return (
            f"RAGSystem(ingested={self._total_ingested}, "
            f"queries={self._total_queries})"
        )
