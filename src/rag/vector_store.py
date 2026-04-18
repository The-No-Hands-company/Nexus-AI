"""
Production-grade Vector Store system with ChromaDB, FAISS, and in-memory backends.

Features:
- Multiple backend support (ChromaDB, FAISS, in-memory)
- Efficient similarity search with metadata filtering
- Batch add / delete / search
- Full corpus retrieval for BM25/sparse integration
- Persistence (auto for ChromaDB, manual for FAISS)
"""

from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import logging
import numpy as np

logger = logging.getLogger(__name__)


def _metadata_matches(metadata: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
    """Evaluate rich metadata filters against a metadata row."""
    if not filters:
        return True

    for key, expected in filters.items():
        actual = metadata.get(key)

        if isinstance(expected, dict):
            for op, value in expected.items():
                if op == "$eq" and actual != value:
                    return False
                if op == "$in":
                    if isinstance(actual, list):
                        if not any(item in value for item in actual):
                            return False
                    elif actual not in value:
                        return False
                if op == "$contains":
                    if isinstance(actual, list):
                        if value not in actual:
                            return False
                    elif isinstance(actual, str):
                        if str(value).lower() not in actual.lower():
                            return False
                    else:
                        return False
                if op == "$gte":
                    if actual is None or actual < value:
                        return False
                if op == "$lte":
                    if actual is None or actual > value:
                        return False
        else:
            if actual != expected:
                return False

    return True


class VectorStoreType(Enum):
    """Supported vector store backends."""
    CHROMADB = "chromadb"
    FAISS = "faiss"
    MEMORY = "memory"


@dataclass
class VectorStoreConfig:
    """Configuration for vector store."""
    store_type: VectorStoreType = VectorStoreType.CHROMADB
    persist_directory: Optional[Path] = None
    collection_name: str = "versaai_documents"
    embedding_dimension: int = 384
    distance_metric: str = "cosine"
    chroma_host: Optional[str] = None
    chroma_port: Optional[int] = None
    faiss_index_type: str = "Flat"
    faiss_nprobe: int = 10


class VectorStore:
    """
    Unified vector store interface supporting ChromaDB, FAISS, and in-memory.

    Provides add, search, delete, get_all_documents, persist, and count.
    Accepts an optional embedding_model for auto-embedding text queries.
    """

    def __init__(self, config: VectorStoreConfig, embedding_model=None):
        self.config = config
        self.embedding_model = embedding_model
        self.store = None
        self._document_count = 0
        self._initialize_store()

    # ------------------------------------------------------------------
    # Backend init
    # ------------------------------------------------------------------

    def _initialize_store(self):
        if self.config.store_type == VectorStoreType.CHROMADB:
            self._init_chromadb()
        elif self.config.store_type == VectorStoreType.FAISS:
            self._init_faiss()
        elif self.config.store_type == VectorStoreType.MEMORY:
            self._init_memory()
        else:
            raise ValueError(f"Unsupported store type: {self.config.store_type}")

    def _init_chromadb(self):
        try:
            import chromadb

            logger.info("Initializing ChromaDB vector store")

            if self.config.chroma_host and self.config.chroma_port:
                self.client = chromadb.HttpClient(
                    host=self.config.chroma_host,
                    port=self.config.chroma_port,
                )
            elif self.config.persist_directory:
                self.client = chromadb.PersistentClient(
                    path=str(self.config.persist_directory),
                )
            else:
                self.client = chromadb.Client()

            self.store = self.client.get_or_create_collection(
                name=self.config.collection_name,
                metadata={"hnsw:space": self.config.distance_metric},
            )
            self._document_count = self.store.count()
            logger.info("ChromaDB initialized with %d documents", self._document_count)

        except ImportError:
            raise ImportError("ChromaDB not installed. Install with: pip install chromadb")

    def _init_faiss(self):
        try:
            import faiss

            logger.info("Initializing FAISS vector store")

            dim = self.config.embedding_dimension
            if self.config.faiss_index_type == "Flat":
                if self.config.distance_metric == "cosine":
                    self.index = faiss.IndexFlatIP(dim)
                elif self.config.distance_metric == "l2":
                    self.index = faiss.IndexFlatL2(dim)
                else:
                    raise ValueError(f"Unsupported distance metric: {self.config.distance_metric}")
            elif self.config.faiss_index_type == "IVF":
                quantizer = faiss.IndexFlatL2(dim)
                self.index = faiss.IndexIVFFlat(quantizer, dim, 100)
                self.index.nprobe = self.config.faiss_nprobe
            else:
                raise ValueError(f"Unsupported FAISS index type: {self.config.faiss_index_type}")

            self.metadata_store: Dict[str, Dict[str, Any]] = {}
            self.id_to_idx: Dict[str, int] = {}

            if self.config.persist_directory:
                index_path = self.config.persist_directory / "faiss.index"
                metadata_path = self.config.persist_directory / "metadata.npy"
                if index_path.exists():
                    self.index = faiss.read_index(str(index_path))
                    if metadata_path.exists():
                        self.metadata_store = np.load(str(metadata_path), allow_pickle=True).item()
                    self._document_count = self.index.ntotal
                    logger.info("Loaded FAISS index with %d vectors", self._document_count)

            self.store = self.index

        except ImportError:
            raise ImportError("FAISS not installed. Install with: pip install faiss-cpu")

    def _init_memory(self):
        logger.info("Initializing in-memory vector store")
        self.store = {
            "embeddings": [],
            "documents": [],
            "metadata": [],
            "ids": [],
        }

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add_documents(
        self,
        documents: List[str],
        embeddings: Optional[List[np.ndarray]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Add documents (with optional pre-computed embeddings)."""
        if not documents:
            return []

        if embeddings is None:
            if self.embedding_model is None:
                raise ValueError("Either provide embeddings or set embedding_model")
            embeddings = list(self.embedding_model.embed_texts(documents))

        if ids is None:
            ids = [f"doc_{self._document_count + i}" for i in range(len(documents))]
        if metadata is None:
            metadata = [{} for _ in documents]

        if self.config.store_type == VectorStoreType.CHROMADB:
            self.store.add(
                documents=documents,
                embeddings=[emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings],
                metadatas=metadata,
                ids=ids,
            )
        elif self.config.store_type == VectorStoreType.FAISS:
            arr = np.array(embeddings).astype("float32")
            self.index.add(arr)
            for i, (doc_id, doc, meta) in enumerate(zip(ids, documents, metadata)):
                idx = self._document_count + i
                self.metadata_store[doc_id] = {"document": doc, "metadata": meta, "index": idx}
                self.id_to_idx[doc_id] = idx
        else:
            self.store["embeddings"].extend(embeddings)
            self.store["documents"].extend(documents)
            self.store["metadata"].extend(metadata)
            self.store["ids"].extend(ids)

        self._document_count += len(documents)
        logger.debug("Added %d documents (total: %d)", len(documents), self._document_count)
        return ids

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: Union[str, np.ndarray],
        k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Similarity search; returns list of {id, document, score, metadata}."""
        if isinstance(query, str):
            if self.embedding_model is None:
                raise ValueError("embedding_model required for text queries")
            query_embedding = self.embedding_model.embed_text(query)
        else:
            query_embedding = query

        if self.config.store_type == VectorStoreType.CHROMADB:
            where = filter_metadata if filter_metadata else None
            if where and any(isinstance(v, dict) for v in where.values()):
                where = None
            results = self.store.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=min(max(k * 5, k), max(self._document_count, 1)),
                where=where,
            )
            out = []
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                if not _metadata_matches(meta or {}, filter_metadata):
                    continue
                out.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "score": 1 - results["distances"][0][i],
                    "metadata": meta,
                })
            return out[:k]

        elif self.config.store_type == VectorStoreType.FAISS:
            qvec = query_embedding.reshape(1, -1).astype("float32")
            distances, indices = self.index.search(qvec, k)
            out = []
            idx_to_id = {info["index"]: did for did, info in self.metadata_store.items()}
            for dist, idx in zip(distances[0], indices[0]):
                if idx == -1:
                    continue
                doc_id = idx_to_id.get(int(idx))
                if not doc_id:
                    continue
                info = self.metadata_store[doc_id]
                if not _metadata_matches(info["metadata"], filter_metadata):
                    continue
                out.append({
                    "id": doc_id,
                    "document": info["document"],
                    "score": float(dist),
                    "metadata": info["metadata"],
                })
            return out

        else:
            embs = np.array(self.store["embeddings"])
            if len(embs) == 0:
                return []
            sims = np.dot(embs, query_embedding)
            top_idx = np.argsort(sims)[-k:][::-1]
            out = []
            for idx in top_idx:
                if not _metadata_matches(self.store["metadata"][idx], filter_metadata):
                    continue
                out.append({
                    "id": self.store["ids"][idx],
                    "document": self.store["documents"][idx],
                    "score": float(sims[idx]),
                    "metadata": self.store["metadata"][idx],
                })
            return out

    # ------------------------------------------------------------------
    # Full corpus access (for BM25 / sparse retrieval)
    # ------------------------------------------------------------------

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        Return every stored document with metadata.

        Needed by BM25/sparse retrieval for full-text access to the corpus.
        """
        if self.config.store_type == VectorStoreType.CHROMADB:
            if self._document_count == 0:
                return []
            result = self.store.get()
            return [
                {
                    "id": result["ids"][i],
                    "document": result["documents"][i] if result["documents"] else "",
                    "metadata": result["metadatas"][i] if result["metadatas"] else {},
                }
                for i in range(len(result["ids"]))
            ]
        elif self.config.store_type == VectorStoreType.FAISS:
            return [
                {"id": did, "document": info["document"], "metadata": info["metadata"]}
                for did, info in self.metadata_store.items()
            ]
        else:
            return [
                {
                    "id": self.store["ids"][i],
                    "document": self.store["documents"][i],
                    "metadata": self.store["metadata"][i],
                }
                for i in range(len(self.store["ids"]))
            ]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, ids: List[str]) -> None:
        if self.config.store_type == VectorStoreType.CHROMADB:
            self.store.delete(ids=ids)
        elif self.config.store_type == VectorStoreType.FAISS:
            for doc_id in ids:
                self.metadata_store.pop(doc_id, None)
                self.id_to_idx.pop(doc_id, None)
        else:
            for doc_id in ids:
                if doc_id in self.store["ids"]:
                    idx = self.store["ids"].index(doc_id)
                    for key in ("ids", "documents", "metadata", "embeddings"):
                        del self.store[key][idx]
        self._document_count = max(0, self._document_count - len(ids))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self) -> None:
        if not self.config.persist_directory:
            logger.warning("No persist_directory configured")
            return
        self.config.persist_directory.mkdir(parents=True, exist_ok=True)
        if self.config.store_type == VectorStoreType.FAISS:
            import faiss
            faiss.write_index(self.index, str(self.config.persist_directory / "faiss.index"))
            np.save(str(self.config.persist_directory / "metadata.npy"), self.metadata_store)
            logger.info("Persisted FAISS index to %s", self.config.persist_directory)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self._document_count

    def __repr__(self) -> str:
        return (
            f"VectorStore(type={self.config.store_type.value}, "
            f"collection={self.config.collection_name}, docs={self._document_count})"
        )
