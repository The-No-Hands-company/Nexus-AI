"""Nexus AI Memory - Phase 1 Super Intelligence Layer."""
import os, time, threading
from typing import List, Dict
from .db import (add_memory_entry, load_memory_entries,
                  delete_all_memory as _db_delete_all,
                  prune_memory_by_age as _db_prune_by_age)

MEMORY_IN_CONTEXT  = 5
COLLECTION_NAME    = "nexus_memory"
MEMORY_MAX_AGE_DAYS = int(os.getenv("MEMORY_MAX_AGE_DAYS", "30"))
MEMORY_MIN_KEEP     = int(os.getenv("MEMORY_MIN_KEEP", "5"))


def _get_embed(text: str) -> List[float] | None:
    """Generate embedding vector. Tries Ollama first, then Groq."""
    import requests
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    try:
        resp = requests.post(
            f"{ollama_url}/embeddings",
            json={"model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"), "prompt": text},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()["embedding"]
    except Exception:
        pass
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/embeddings",
            headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}",
                     "Content-Type": "application/json"},
            json={"model": "llma3-8b-8192", "input": text},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()["data"][0]["embedding"]
    except Exception:
        pass
    return None


_chroma_lock = threading.Lock()
_chroma_client = None

def _get_chroma():
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    try:
        import chromadb
        with _chroma_lock:
            if _chroma_client is None:
                _chroma_client = chromadb.PersistentClient(path="/tmp/nexus_chroma")
        return _chroma_client
    except ImportError:
        return None

def _get_collection():
    cl = _get_chroma()
    if cl is None:
        return None
    try:
        return cl.get_or_create_collection(name=COLLECTION_NAME)
    except Exception:
        return None


def add_memory(summary: str, tags: List[str] | None = None) -> None:
    tags = tags or []
    add_memory_entry(summary, tags, time.time())
    emb = _get_embed(summary)
    if emb:
        coll = _get_collection()
        if coll:
            try:
                coll.add(
                    embeddings=[emb],
                    documents=[summary],
                    metadatas=[{"tags": ",".join(tags), "ts": time.time()}],
                    ids=[f"mem_{int(time.time() * 1000)}"],
                )
            except Exception:
                pass


def get_memory_context(max_entries: int = MEMORY_IN_CONTEXT) -> str:
    emb_system = _get_embed(
        "Nexus AI agent capabilities, tools, architecture, and user preferences"
    )
    if emb_system:
        coll = _get_collection()
        if coll:
            try:
                results = coll.query(
                    query_embeddings=[emb_system],
                    n_results=max_entries,
                    include=["documents", "metadatas"],
                )
                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [{}])[0]
                if docs:
                    lines = ["[MEMORY - semantically relevant past context]"]
                    for doc, meta in zip(docs, metas):
                        ts = time.strftime("%Y-%m-%d",
                                          time.localtime(meta.get("ts", 0)))
                        lines.append(f"  - {ts}: {doc}")
                    lines.append("")
                    return "\n".join(lines)
            except Exception:
                pass
    entries = load_memory_entries(max_entries)
    if not entries:
        return ""
    entries = list(reversed(entries))
    lines = ["[MEMORY - recent conversation summaries to give you context]"]
    for m in entries:
        ts = time.strftime("%Y-%m-%d", time.localtime(m["created_at"]))
        lines.append(f"  - {ts}: {m['summary']}")
    lines.append("")
    return "\n".join(lines)


def summarize_history(history: List[Dict], call_llm_fn) -> str:
    if not history:
        return ""
    transcript = [
        m["content"][:300]
        for m in history
        if m.get("role") == "user" and isinstance(m.get("content"), str)
        and not m["content"].startswith(("Tool result:", "Continue", "[MEMORY"))
    ]
    if not transcript:
        return ""
    prompt = (
        "Summarize this conversation in ONE sentence (max 20 words), "
        "focusing on what was built or accomplished:\n\n"
        + "\n".join(f"- {t}" for t in transcript[-6:])
    )
    try:
        action, _ = call_llm_fn([{"role": "user", "content": prompt}])
        return action.get("content", "").strip()[:200]
    except Exception:
        return transcript[0][:100] if transcript else ""


def delete_all() -> None:
    _db_delete_all()
    try:
        coll = _get_collection()
        if coll:
            coll.delete(where={})
    except Exception:
        pass


def get_all() -> List[Dict]:
    return load_memory_entries(50)


def get_semantic_memory(query: str, limit: int = 5) -> List[Dict]:
    """Return memory entries relevant to *query* using vector search, falling back to recency."""
    if query:
        emb = _get_embed(query)
        if emb:
            coll = _get_collection()
            if coll:
                try:
                    results = coll.query(
                        query_embeddings=[emb],
                        n_results=limit,
                        include=["documents", "metadatas"],
                    )
                    docs = results.get("documents", [[]])[0]
                    metas = results.get("metadatas", [{}])[0]
                    return [
                        {"summary": doc, "tags": meta.get("tags", "").split(","),
                         "created_at": meta.get("ts", 0)}
                        for doc, meta in zip(docs, metas)
                    ]
                except Exception:
                    pass
    return load_memory_entries(limit)


def prune_old_memories(max_age_days: int | None = None, min_keep: int | None = None) -> int:
    """Delete memory entries older than *max_age_days* days.

    Always preserves at least *min_keep* most-recent entries (defaults to
    MEMORY_MIN_KEEP env var or 5).

    Returns the count of deleted SQLite rows; Chroma entries are pruned
    best-effort by re-syncing from SQLite.
    """
    age_days = max_age_days if max_age_days is not None else MEMORY_MAX_AGE_DAYS
    keep     = min_keep     if min_keep     is not None else MEMORY_MIN_KEEP
    cutoff   = time.time() - age_days * 86400
    deleted  = _db_prune_by_age(cutoff, keep)

    # Best-effort Chroma prune: drop collection in a background thread so we
    # never block the caller if Chroma is slow or unavailable.
    if deleted:
        def _drop_chroma():
            try:
                cl = _get_chroma()
                if cl is not None:
                    cl.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
        t = threading.Thread(target=_drop_chroma, daemon=True)
        t.start()
        t.join(timeout=2.0)   # give Chroma at most 2 s; silently abandon otherwise

    return deleted


def add_semantic_memory(summary: str, tags: List[str] | None = None) -> None:
    """Alias for add_memory — stores entry in both sqlite and chroma."""
    add_memory(summary, tags)
