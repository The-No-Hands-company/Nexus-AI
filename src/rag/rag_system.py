from __future__ import annotations

import copy
import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any


def _tokenize(text: str) -> list[str]:
    return [tok for tok in (text or "").lower().split() if tok]


def _hash_to_unit_interval(value: str) -> float:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / float(0xFFFFFFFF)


class _EmbeddingModel:
    """Deterministic lightweight embedding used for tests and local fallback."""

    dimension = 16

    def embed_batch(self, inputs: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in inputs:
            base = str(text or "")
            row: list[float] = []
            for idx in range(self.dimension):
                unit = _hash_to_unit_interval(f"{base}::{idx}")
                row.append(round((unit * 2.0) - 1.0, 6))
            vectors.append(row)
        return vectors


@dataclass
class _Doc:
    id: str
    document: str
    metadata: dict[str, Any]
    created_at: float


class _VectorStore:
    def __init__(self, parent: "RAGSystem") -> None:
        self._parent = parent

    def get_all_documents(self) -> list[dict[str, Any]]:
        return [
            {"id": doc.id, "document": doc.document, "metadata": dict(doc.metadata)}
            for doc in self._parent._docs
        ]

    def add_documents(self, documents: list[str], metadata: list[dict[str, Any]], ids: list[str]) -> None:
        for idx, text in enumerate(documents):
            meta = dict(metadata[idx] if idx < len(metadata) else {})
            doc_id = ids[idx] if idx < len(ids) else f"doc-{uuid.uuid4().hex[:10]}"
            self._parent._docs.append(_Doc(id=doc_id, document=str(text or ""), metadata=meta, created_at=time.time()))

    def delete(self, ids: list[str]) -> None:
        id_set = set(ids or [])
        self._parent._docs = [doc for doc in self._parent._docs if doc.id not in id_set]

    def persist(self) -> None:
        return None


class RAGSystem:
    def __init__(self) -> None:
        self._docs: list[_Doc] = []
        self._snapshots: dict[str, list[_Doc]] = {}
        self._embedding_model = _EmbeddingModel()
        self.vector_store = _VectorStore(self)
        self._queries = 0

    @property
    def embedding_model(self) -> _EmbeddingModel:
        return self._embedding_model

    def ingest(self, text: str, metadata: dict[str, Any] | None = None, doc_id_prefix: str | None = None) -> int:
        body = str(text or "").strip()
        if not body:
            return 0

        meta = dict(metadata or {})
        if bool(meta.get("incremental")) and meta.get("source"):
            source = str(meta.get("source"))
            self._docs = [doc for doc in self._docs if str(doc.metadata.get("source", "")) != source]

        doc_id = f"{doc_id_prefix or 'doc'}-{uuid.uuid4().hex[:10]}"
        self._docs.append(_Doc(id=doc_id, document=body, metadata=meta, created_at=time.time()))
        return 1

    def _passes_filter(self, metadata: dict[str, Any], filt: dict[str, Any] | None) -> bool:
        if not filt:
            return True
        for key, expected in filt.items():
            actual = metadata.get(key)
            if isinstance(expected, dict):
                if "$eq" in expected and actual != expected.get("$eq"):
                    return False
                if "$contains" in expected:
                    needle = expected.get("$contains")
                    if isinstance(actual, list):
                        if needle not in actual:
                            return False
                    elif isinstance(actual, str):
                        if str(needle) not in actual:
                            return False
                    else:
                        return False
            else:
                if actual != expected:
                    return False
        return True

    def query(
        self,
        question: str,
        top_k: int | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._queries += 1
        q = str(question or "").strip()
        tokens = _tokenize(q)
        ranked: list[dict[str, Any]] = []

        for doc in self._docs:
            if not self._passes_filter(doc.metadata, filter_metadata):
                continue
            text_lower = doc.document.lower()
            overlap = sum(1 for token in tokens if token in text_lower)
            lexical = (overlap / max(1, len(tokens))) if tokens else 0.0
            recency_boost = min(0.1, max(0.0, 1.0 / (1.0 + math.log1p(max(1.0, time.time() - doc.created_at)))))
            score = round(min(1.0, 0.45 + (lexical * 0.5) + recency_boost), 4)
            if lexical > 0 or not tokens:
                ranked.append(
                    {
                        "id": doc.id,
                        "document": doc.document,
                        "metadata": dict(doc.metadata),
                        "score": score,
                    }
                )

        ranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        limit = max(1, int(top_k or 5))
        return ranked[:limit]

    def stats(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "documents": len(self._docs),
            "queries": self._queries,
            "snapshots": len(self._snapshots),
        }

    def create_snapshot(self, label: str | None = None) -> dict[str, Any]:
        snapshot_id = (label or f"snap-{int(time.time())}").strip()
        self._snapshots[snapshot_id] = copy.deepcopy(self._docs)
        return {"snapshot_id": snapshot_id, "count": len(self._snapshots[snapshot_id])}

    def rollback_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        if snapshot_id not in self._snapshots:
            raise KeyError(snapshot_id)
        self._docs = copy.deepcopy(self._snapshots[snapshot_id])
        return {"rolled_back_to": snapshot_id, "count": len(self._docs)}
