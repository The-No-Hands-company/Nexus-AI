"""
src/rag/incremental_index.py — Incremental vector index updates

Implements an incremental document upsert pipeline that avoids re-embedding
unchanged documents on every ingest call. Tracks document content hashes to
detect changes; only embeds and upserts documents whose content has changed.

Also provides:
  - Batch upsert with configurable batch size
  - Stale document detection (documents removed from source that remain in index)
  - Index health metrics

Environment variables:
    RAG_INCREMENTAL_BATCH_SIZE — documents per embedding batch (default: 32)
    RAG_HASH_ALGORITHM         — hash algorithm for content change detection (default: sha256)
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nexus.rag.incremental_index")

_BATCH_SIZE = int(os.getenv("RAG_INCREMENTAL_BATCH_SIZE", "32"))
_HASH_ALG = os.getenv("RAG_HASH_ALGORITHM", "sha256").strip()


# ── Content hashing ───────────────────────────────────────────────────────────

def _content_hash(text: str, metadata: dict | None = None) -> str:
    """Compute a stable content hash for a document."""
    content = text + (str(sorted((metadata or {}).items())) if metadata else "")
    h = hashlib.new(_HASH_ALG)
    h.update(content.encode("utf-8", errors="replace"))
    return h.hexdigest()[:32]


# ── Hash registry (persisted to DB) ──────────────────────────────────────────

def _load_hash_registry(collection: str) -> dict[str, str]:
    """Load the {doc_id: content_hash} registry for a collection."""
    try:
        from src.db import load_pref  # type: ignore
        return load_pref(f"rag:hashes:{collection}") or {}
    except Exception:
        return {}


def _save_hash_registry(collection: str, registry: dict[str, str]) -> None:
    try:
        from src.db import save_pref  # type: ignore
        save_pref(f"rag:hashes:{collection}", registry)
    except Exception:
        pass


# ── Incremental upsert ────────────────────────────────────────────────────────

@dataclass
class IngestStats:
    total: int = 0
    upserted: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: int = 0
    duration_s: float = 0.0
    collection: str = ""


def incremental_upsert(
    documents: list[dict],
    collection: str,
    vector_store=None,
    embedding_fn=None,
    delete_stale: bool = False,
) -> IngestStats:
    """Upsert documents into a vector collection, skipping unchanged content.

    documents: list of {"id": str, "content": str, "metadata": dict}
    collection: collection/namespace name
    vector_store: vector store instance with add_documents/delete methods
    embedding_fn: callable(texts: list[str]) -> list[list[float]]
    delete_stale: if True, remove documents in index not present in *documents*

    Returns IngestStats with counts of upserted/skipped/deleted.
    """
    import time as _time
    start = _time.time()
    stats = IngestStats(total=len(documents), collection=collection)

    registry = _load_hash_registry(collection)
    incoming_ids = {doc["id"] for doc in documents}

    # Determine which documents need re-embedding
    to_upsert = []
    for doc in documents:
        doc_id = doc.get("id", "")
        content = doc.get("content", "")
        metadata = doc.get("metadata", {})
        new_hash = _content_hash(content, metadata)
        existing_hash = registry.get(doc_id)
        if existing_hash != new_hash:
            to_upsert.append((doc_id, content, metadata, new_hash))
        else:
            stats.skipped += 1

    logger.info("Incremental upsert: %d to embed, %d unchanged (collection=%s)",
                len(to_upsert), stats.skipped, collection)

    # Delete stale documents
    if delete_stale:
        stale_ids = [k for k in registry if k not in incoming_ids]
        for stale_id in stale_ids:
            try:
                if vector_store and hasattr(vector_store, "delete"):
                    vector_store.delete(ids=[stale_id])
                registry.pop(stale_id, None)
                stats.deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete stale doc %s: %s", stale_id, exc)

    # Embed and upsert in batches
    for i in range(0, len(to_upsert), _BATCH_SIZE):
        batch = to_upsert[i: i + _BATCH_SIZE]
        batch_ids = [b[0] for b in batch]
        batch_texts = [b[1] for b in batch]
        batch_metas = [b[2] for b in batch]
        batch_hashes = [b[3] for b in batch]

        try:
            if embedding_fn:
                embeddings = embedding_fn(batch_texts)
            else:
                embeddings = None

            if vector_store:
                if hasattr(vector_store, "upsert"):
                    vector_store.upsert(
                        ids=batch_ids, texts=batch_texts,
                        metadatas=batch_metas, embeddings=embeddings,
                    )
                elif hasattr(vector_store, "add_documents"):
                    docs_to_add = [
                        {"id": bid, "content": text, "metadata": meta,
                         "embedding": emb if embeddings else None}
                        for bid, text, meta, emb in zip(
                            batch_ids, batch_texts, batch_metas,
                            embeddings if embeddings else [None] * len(batch_ids)
                        )
                    ]
                    vector_store.add_documents(docs_to_add)

            # Update registry with new hashes
            for doc_id, h in zip(batch_ids, batch_hashes):
                registry[doc_id] = h

            stats.upserted += len(batch)
        except Exception as exc:
            logger.error("Batch upsert failed (batch %d): %s", i // _BATCH_SIZE, exc)
            stats.errors += len(batch)

    _save_hash_registry(collection, registry)
    stats.duration_s = round(_time.time() - start, 2)
    logger.info(
        "Incremental upsert complete: upserted=%d skipped=%d deleted=%d errors=%d (%.1fs)",
        stats.upserted, stats.skipped, stats.deleted, stats.errors, stats.duration_s,
    )
    return stats


def detect_stale_documents(documents: list[dict], collection: str) -> list[str]:
    """Return doc IDs that are in the index but not in *documents* (stale)."""
    registry = _load_hash_registry(collection)
    incoming_ids = {doc["id"] for doc in documents}
    return [k for k in registry if k not in incoming_ids]


def get_index_stats(collection: str) -> dict:
    """Return stats about the current index state for a collection."""
    registry = _load_hash_registry(collection)
    return {
        "collection": collection,
        "indexed_documents": len(registry),
        "last_updated": max(
            (datetime.fromisoformat(h[:19]) for h in [] if h),
            default=None
        ),
    }


def invalidate_document(doc_id: str, collection: str) -> bool:
    """Remove a document from the hash registry, forcing re-embed on next upsert."""
    registry = _load_hash_registry(collection)
    if doc_id in registry:
        registry.pop(doc_id)
        _save_hash_registry(collection, registry)
        return True
    return False


def clear_hash_registry(collection: str) -> int:
    """Clear all hashes for a collection, forcing full re-embed on next upsert."""
    registry = _load_hash_registry(collection)
    count = len(registry)
    _save_hash_registry(collection, {})
    return count
