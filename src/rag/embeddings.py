"""
VersaAI Embedding System — multi-backend embedding generation.

Supports (in priority order):
1. Ollama /api/embed – zero extra deps, uses running Ollama server
2. sentence-transformers – local HuggingFace models (optional)
3. Hash-based fallback – deterministic pseudo-embeddings for testing only

Usage:
    >>> from versaai.rag.embeddings import EmbeddingModel, EmbeddingConfig
    >>> model = EmbeddingModel()                    # auto-detect best backend
    >>> vec = model.embed_text("Hello, world!")     # → np.ndarray (dim,)
    >>> batch = model.embed_texts(["a", "b", "c"]) # → np.ndarray (3, dim)
    >>> sim = model.similarity(vec, batch[0])       # → float in [-1, 1]
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_MULTILINGUAL_ST_MODEL = "intfloat/multilingual-e5-base"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding system."""

    # Backend selection: "ollama" | "sentence-transformers" | "auto"
    backend: str = "auto"

    # Ollama settings
    ollama_base_url: str = ""  # empty → from settings
    ollama_model: str = "nomic-embed-text"

    # sentence-transformers settings
    st_model_name: str = _DEFAULT_ST_MODEL
    multilingual_preferred: bool = False
    device: str = "cpu"

    # Shared settings
    normalize_embeddings: bool = True
    batch_size: int = 64
    max_seq_length: Optional[int] = None
    cache_dir: Optional[Path] = None
    show_progress: bool = False

    # LRU cache for repeated texts (0 = disabled)
    cache_size: int = 4096

    def __post_init__(self):
        # Environment overrides keep runtime config simple and deployment-friendly.
        backend_env = (os.getenv("RAG_EMBED_BACKEND") or "").strip().lower()
        if backend_env:
            self.backend = backend_env

        st_model_env = (os.getenv("RAG_EMBED_ST_MODEL") or "").strip()
        if st_model_env:
            self.st_model_name = st_model_env

        multilingual_env = (os.getenv("RAG_EMBED_MULTILINGUAL") or "").strip().lower()
        if multilingual_env in {"1", "true", "yes", "on"}:
            self.multilingual_preferred = True

        if self.multilingual_preferred and self.st_model_name == _DEFAULT_ST_MODEL:
            self.st_model_name = _DEFAULT_MULTILINGUAL_ST_MODEL


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


class _OllamaEmbeddingBackend:
    """Embed via Ollama /api/embed (batch-capable)."""

    def __init__(self, base_url: str, model: str, timeout: int = 120):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self.dimension: Optional[int] = None

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Embed one or more texts in a single API call."""
        payload = {"model": self.model, "input": texts}
        r = self._client.post("/api/embed", json=payload)
        r.raise_for_status()
        data = r.json()
        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise RuntimeError(f"Ollama returned no embeddings for model {self.model}")
        arr = np.asarray(embeddings, dtype=np.float32)
        if self.dimension is None:
            self.dimension = arr.shape[1]
        return arr

    def probe_dimension(self) -> int:
        """Embed a single token to discover the embedding dimension."""
        arr = self.embed_batch(["test"])
        self.dimension = arr.shape[1]
        return self.dimension

    def close(self):
        self._client.close()


class _SentenceTransformerBackend:
    """Embed via local sentence-transformers model."""

    def __init__(self, config: EmbeddingConfig):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            config.st_model_name,
            device=config.device,
            cache_folder=str(config.cache_dir) if config.cache_dir else None,
        )
        if config.max_seq_length:
            self.model.max_seq_length = config.max_seq_length
        self.dimension: int = self.model.get_sentence_embedding_dimension()
        self._normalize = config.normalize_embeddings
        self._batch_size = config.batch_size
        self._show = config.show_progress

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return self.model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=self._show,
            normalize_embeddings=self._normalize,
            convert_to_numpy=True,
        )

    def close(self):
        pass


class _HashEmbeddingBackend:
    """
    Deterministic hash-based pseudo-embeddings.

    NOT suitable for production — provides zero semantic similarity.
    Useful only for integration testing when no model server is available.
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(
                int.from_bytes(digest[:8], byteorder="little")
            )
            vec = rng.standard_normal(self.dimension).astype(np.float32)
            out[i] = vec / (np.linalg.norm(vec) + 1e-10)
        return out

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Unified EmbeddingModel
# ---------------------------------------------------------------------------


class EmbeddingModel:
    """
    Production embedding interface with auto-backend selection.

    Tries backends in order: Ollama → sentence-transformers → hash fallback.
    Includes an in-memory LRU cache for repeated queries.
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig()
        self._backend: Any = None
        self.dimension: int = 0
        self._backend_name: str = "none"
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_order: List[str] = []
        self._initialize()

    # ----- init helpers ---------------------------------------------------

    def _initialize(self):
        backend = self.config.backend.lower()
        if backend == "auto":
            self._try_auto()
        elif backend == "ollama":
            self._init_ollama()
        elif backend in ("sentence-transformers", "st"):
            self._init_st()
        elif backend in ("hash", "test"):
            self._init_hash()
        else:
            raise ValueError(f"Unknown embedding backend: {backend}")
        logger.info(
            "EmbeddingModel ready: backend=%s  dim=%d", self._backend_name, self.dimension
        )

    def _try_auto(self):
        """Auto-detect the best available backend."""
        if self.config.multilingual_preferred:
            # Cross-lingual mode prioritizes multilingual sentence-transformers models.
            try:
                self._init_st()
                return
            except Exception as exc:
                logger.debug("multilingual sentence-transformers unavailable: %s", exc)

            try:
                self._init_ollama()
                return
            except Exception as exc:
                logger.debug("Ollama embedding unavailable: %s", exc)
        else:
            # 1. Try Ollama (preferred — zero extra Python deps)
            try:
                self._init_ollama()
                return
            except Exception as exc:
                logger.debug("Ollama embedding unavailable: %s", exc)

            # 2. Try sentence-transformers
            try:
                self._init_st()
                return
            except Exception as exc:
                logger.debug("sentence-transformers unavailable: %s", exc)

        # 3. Hash fallback (always available)
        logger.warning(
            "No embedding backend available — using hash fallback (no semantic similarity)"
        )
        self._init_hash()

    def _init_ollama(self):
        base_url = self.config.ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        timeout = 120  # default timeout
        backend = _OllamaEmbeddingBackend(base_url, self.config.ollama_model, timeout)
        dim = backend.probe_dimension()
        self._backend = backend
        self._backend_name = f"ollama/{self.config.ollama_model}"
        self.dimension = dim

    def _init_st(self):
        backend = _SentenceTransformerBackend(self.config)
        self._backend = backend
        self._backend_name = f"st/{self.config.st_model_name}"
        self.dimension = backend.dimension

    def _init_hash(self):
        backend = _HashEmbeddingBackend(dimension=384)
        self._backend = backend
        self._backend_name = "hash"
        self.dimension = backend.dimension

    # ----- public API -----------------------------------------------------

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Embed a batch of texts.

        Returns:
            np.ndarray of shape (len(texts), self.dimension)
        """
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        cache = self._cache
        max_cache = self.config.cache_size

        # Split into cached hits and uncached misses
        results: List[Optional[np.ndarray]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, t in enumerate(texts):
            if max_cache and t in cache:
                results[i] = cache[t]
            else:
                uncached_indices.append(i)
                uncached_texts.append(t)

        # Batch-embed uncached texts
        if uncached_texts:
            batch_size = self.config.batch_size
            all_embeddings: List[np.ndarray] = []
            for start in range(0, len(uncached_texts), batch_size):
                chunk = uncached_texts[start : start + batch_size]
                emb = self._backend.embed_batch(chunk)
                if self.config.normalize_embeddings and self._backend_name.startswith("ollama"):
                    norms = np.linalg.norm(emb, axis=1, keepdims=True)
                    emb = emb / (norms + 1e-10)
                all_embeddings.append(emb)

            merged = np.vstack(all_embeddings) if len(all_embeddings) > 1 else all_embeddings[0]

            for j, idx in enumerate(uncached_indices):
                vec = merged[j]
                results[idx] = vec
                if max_cache:
                    self._cache_put(uncached_texts[j], vec)

        return np.vstack(results)  # type: ignore[arg-type]

    def embed_text(self, text: str) -> np.ndarray:
        """Embed a single text string."""
        return self.embed_texts([text])[0]

    def embed_documents(
        self,
        documents: List[Dict[str, Any]],
        text_key: str = "text",
    ) -> List[Dict[str, Any]]:
        """Embed documents in-place, adding an ``embedding`` field."""
        texts = [doc.get(text_key, "") for doc in documents]
        embeddings = self.embed_texts(texts)
        for doc, emb in zip(documents, embeddings):
            doc["embedding"] = emb.tolist()
        return documents

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two embedding vectors."""
        a_f = np.asarray(a, dtype=np.float32).flatten()
        b_f = np.asarray(b, dtype=np.float32).flatten()
        dot = float(np.dot(a_f, b_f))
        denom = float(np.linalg.norm(a_f) * np.linalg.norm(b_f))
        return dot / denom if denom > 1e-10 else 0.0

    def get_dimension(self) -> int:
        """Return the embedding dimensionality."""
        return self.dimension

    @property
    def backend_name(self) -> str:
        return self._backend_name

    # ----- cache helpers --------------------------------------------------

    def _cache_put(self, key: str, value: np.ndarray):
        cache = self._cache
        order = self._cache_order
        if key in cache:
            order.remove(key)
        elif len(cache) >= self.config.cache_size:
            evict_key = order.pop(0)
            del cache[evict_key]
        cache[key] = value
        order.append(key)

    def clear_cache(self):
        """Flush the embedding cache."""
        self._cache.clear()
        self._cache_order.clear()

    # ----- lifecycle ------------------------------------------------------

    def close(self):
        if self._backend:
            self._backend.close()
            self._backend = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"EmbeddingModel(backend={self._backend_name!r}, dim={self.dimension})"
