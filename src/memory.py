"""Nexus AI Memory - Phase 1 Super Intelligence Layer."""
import os, time, threading, json, hashlib
from pathlib import Path
from typing import List, Dict
from .db import (add_memory_entry, load_memory_entries,
                  delete_all_memory as _db_delete_all,
                  prune_memory_by_age as _db_prune_by_age)

MEMORY_IN_CONTEXT  = 5
COLLECTION_NAME    = "nexus_memory"
MEMORY_MAX_AGE_DAYS = int(os.getenv("MEMORY_MAX_AGE_DAYS", "30"))
MEMORY_MIN_KEEP     = int(os.getenv("MEMORY_MIN_KEEP", "5"))
_MEMORY_META_PATH = Path(os.getenv("MEMORY_META_PATH", "/tmp/nexus_memory_meta.json"))
_EMBED_TIMEOUT_S = float(os.getenv("MEMORY_EMBED_TIMEOUT_S", "2.0"))


def _memory_key(summary: str, ts: float) -> str:
    base = f"{summary}|{int(ts)}"
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _load_meta() -> dict:
    try:
        if _MEMORY_META_PATH.exists():
            return json.loads(_MEMORY_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"entries": {}, "episodic": []}


def _save_meta(meta: dict) -> None:
    try:
        _MEMORY_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MEMORY_META_PATH.write_text(json.dumps(meta), encoding="utf-8")
    except Exception:
        pass


def _register_memory_metadata(
    summary: str,
    tags: List[str],
    ts: float,
    persona: str = "",
    session_id: str = "",
    task_id: str = "",
    source: str = "conversation",
) -> str:
    key = _memory_key(summary, ts)
    meta = _load_meta()
    entries = meta.setdefault("entries", {})
    entries[key] = {
        "key": key,
        "summary": summary,
        "tags": tags,
        "created_at": ts,
        "persona": persona,
        "session_id": session_id,
        "task_id": task_id,
        "source": source,
        "importance": float(entries.get(key, {}).get("importance", 0.65)),
        "access_count": int(entries.get(key, {}).get("access_count", 0)),
    }
    episodic = meta.setdefault("episodic", [])
    episodic.append(
        {
            "id": key,
            "event_type": "memory_created",
            "created_at": ts,
            "summary": summary,
            "session_id": session_id,
            "task_id": task_id,
            "source": source,
        }
    )
    meta["episodic"] = episodic[-2000:]
    _save_meta(meta)
    return key


def _touch_memory(summary: str, ts: float) -> None:
    key = _memory_key(summary, ts)
    meta = _load_meta()
    entry = meta.get("entries", {}).get(key)
    if not entry:
        return
    access = int(entry.get("access_count", 0)) + 1
    entry["access_count"] = access
    # Small boost on access, capped.
    entry["importance"] = min(1.0, float(entry.get("importance", 0.65)) + 0.03)
    _save_meta(meta)


def _importance_with_decay(base_importance: float, created_at: float) -> float:
    age_days = max(0.0, (time.time() - float(created_at or 0)) / 86400.0)
    decay = max(0.45, 1.0 - age_days * 0.01)
    return round(max(0.0, min(1.0, base_importance * decay)), 4)


def _get_embed(text: str) -> List[float] | None:
    """Generate embedding vector. Tries Ollama first, then Groq."""
    import requests
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    try:
        resp = requests.post(
            f"{ollama_url}/embeddings",
            json={"model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"), "prompt": text},
            timeout=_EMBED_TIMEOUT_S,
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
            timeout=_EMBED_TIMEOUT_S,
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


def add_memory(
    summary: str,
    tags: List[str] | None = None,
    persona: str = "",
    session_id: str = "",
    task_id: str = "",
    source: str = "conversation",
    index_semantic: bool = True,
) -> None:
    tags = tags or []
    ts = time.time()
    add_memory_entry(summary, tags, ts)
    _register_memory_metadata(
        summary=summary,
        tags=tags,
        ts=ts,
        persona=persona,
        session_id=session_id,
        task_id=task_id,
        source=source,
    )
    emb = _get_embed(summary) if index_semantic else None
    if emb:
        coll = _get_collection()
        if coll:
            try:
                memory_id = _memory_key(summary, ts)
                coll.add(
                    embeddings=[emb],
                    documents=[summary],
                    metadatas=[{
                        "tags": ",".join(tags),
                        "ts": ts,
                        "persona": persona,
                        "session_id": session_id,
                        "task_id": task_id,
                        "source": source,
                        "importance": 0.65,
                        "access_count": 0,
                    }],
                    ids=[memory_id],
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
    _save_meta({"entries": {}, "episodic": []})
    try:
        coll = _get_collection()
        if coll:
            coll.delete(where={})
    except Exception:
        pass


def get_all() -> List[Dict]:
    entries = load_memory_entries(50)
    meta = _load_meta().get("entries", {})
    enriched: List[Dict] = []
    for entry in entries:
        key = _memory_key(str(entry.get("summary", "")), float(entry.get("created_at", 0)))
        m = meta.get(key, {})
        importance = _importance_with_decay(float(m.get("importance", 0.65)), float(entry.get("created_at", 0)))
        enriched.append(
            {
                **entry,
                "importance": importance,
                "access_count": int(m.get("access_count", 0)),
                "provenance": {
                    "session_id": m.get("session_id", ""),
                    "task_id": m.get("task_id", ""),
                    "source": m.get("source", ""),
                },
            }
        )
    return enriched


def get_semantic_memory(query: str, limit: int = 5) -> List[Dict]:
    """Return memory entries relevant to *query* using vector search, falling back to recency."""
    return get_semantic_memory_filtered(query, limit)


def get_semantic_memory_filtered(
    query: str,
    limit: int = 5,
    date_from: float | None = None,
    date_to: float | None = None,
    tags: List[str] | None = None,
    persona: str | None = None,
) -> List[Dict]:
    """Filtered semantic memory search.

    Supports optional date range (unix timestamps), tags (substring match),
    and persona filter.  Falls back to recency-ordered SQLite when Chroma is
    unavailable.
    """
    # Build Chroma where-clause if any filter is active
    where: dict | None = None
    conditions: list[dict] = []
    if date_from is not None:
        conditions.append({"ts": {"$gte": date_from}})
    if date_to is not None:
        conditions.append({"ts": {"$lte": date_to}})
    if persona:
        conditions.append({"persona": {"$eq": persona}})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    if query:
        emb = _get_embed(query)
        if emb:
            coll = _get_collection()
            if coll:
                try:
                    kwargs: dict = {
                        "query_embeddings": [emb],
                        "n_results": limit * 3,   # over-fetch to allow tag post-filter
                        "include": ["documents", "metadatas"],
                    }
                    if where:
                        kwargs["where"] = where
                    results = coll.query(**kwargs)
                    docs  = results.get("documents", [[]])[0]
                    metas = results.get("metadatas", [{}])[0]
                    entries = [
                        {
                            "summary":    doc,
                            "tags":       meta.get("tags", "").split(","),
                            "created_at": meta.get("ts", 0),
                            "persona":    meta.get("persona", ""),
                            "importance": _importance_with_decay(float(meta.get("importance", 0.65)), float(meta.get("ts", 0))),
                            "provenance": {
                                "session_id": meta.get("session_id", ""),
                                "task_id": meta.get("task_id", ""),
                                "source": meta.get("source", ""),
                            },
                        }
                        for doc, meta in zip(docs, metas)
                    ]
                    for e in entries:
                        _touch_memory(e.get("summary", ""), float(e.get("created_at", 0)))
                    # Post-filter by tags (substring match against comma-joined tag string)
                    if tags:
                        entries = [
                            e for e in entries
                            if any(t.lower() in e["tags"] for t in tags)
                        ]
                    entries.sort(key=lambda item: float(item.get("importance", 0.0)), reverse=True)
                    return entries[:limit]
                except Exception:
                    pass

    # SQLite fallback with in-process filtering
    all_entries = load_memory_entries(200)
    filtered = all_entries
    if date_from is not None:
        filtered = [e for e in filtered if e.get("created_at", 0) >= date_from]
    if date_to is not None:
        filtered = [e for e in filtered if e.get("created_at", 0) <= date_to]
    if tags:
        filtered = [
            e for e in filtered
            if any(t.lower() in [tag.lower() for tag in e.get("tags", [])] for t in tags)
        ]
    if persona:
        filtered = [e for e in filtered if e.get("persona", "") == persona]
    meta_entries = _load_meta().get("entries", {})
    enriched = []
    for e in filtered:
        key = _memory_key(str(e.get("summary", "")), float(e.get("created_at", 0)))
        m = meta_entries.get(key, {})
        importance = _importance_with_decay(float(m.get("importance", 0.65)), float(e.get("created_at", 0)))
        _touch_memory(str(e.get("summary", "")), float(e.get("created_at", 0)))
        enriched.append(
            {
                **e,
                "importance": importance,
                "access_count": int(m.get("access_count", 0)),
                "provenance": {
                    "session_id": m.get("session_id", ""),
                    "task_id": m.get("task_id", ""),
                    "source": m.get("source", ""),
                },
            }
        )
    enriched.sort(key=lambda item: float(item.get("importance", 0.0)), reverse=True)
    return enriched[:limit]


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


def get_episodic_timeline(limit: int = 100) -> List[Dict]:
    meta = _load_meta()
    events = list(meta.get("episodic", []))
    events.sort(key=lambda event: float(event.get("created_at", 0)), reverse=True)
    return events[: max(1, min(int(limit), 1000))]


def export_memory_bundle(limit: int = 1000) -> Dict:
    return {
        "version": 1,
        "exported_at": time.time(),
        "entries": get_all()[: max(1, min(int(limit), 5000))],
        "episodic": get_episodic_timeline(limit=limit),
    }


def import_memory_bundle(bundle: Dict, source: str = "import") -> Dict:
    rows = bundle.get("entries", []) if isinstance(bundle, dict) else []
    imported = 0
    for row in rows:
        summary = str(row.get("summary", "")).strip()
        if not summary:
            continue
        add_memory(
            summary,
            tags=list(row.get("tags", []) or []),
            persona=str(row.get("persona", "") or ""),
            session_id=str(row.get("provenance", {}).get("session_id", "") or ""),
            task_id=str(row.get("provenance", {}).get("task_id", "") or ""),
            source=source,
            index_semantic=False,
        )
        imported += 1
    return {"imported": imported}
