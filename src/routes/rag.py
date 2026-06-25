"""RAG and Knowledge Graph routes.

Extracted from src/api/routes.py for maintainability.
Covers: RAG ingestion, querying, snapshots, citation, incremental index,
and Knowledge Graph CRUD, query, merge, import, hybrid search.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="", tags=["rag"])

from ._helpers import (
    _api_error,
    require_admin,
)
from ..agent import call_llm_with_fallback
from ..api.state import get_rag_system
from ..knowledge_graph import (
    kg_store as _kg_store,
    kg_query as _kg_query,
    kg_list_entities as _kg_list,
    kg_get as _kg_get,
    kg_delete as _kg_delete,
    kg_graph as _kg_graph,
    kg_merge as _kg_merge,
    kg_import_ontology as _kg_import,
    kg_hybrid_search as _kg_hybrid_search,
)


# ── RAG endpoints ─────────────────────────────────────────────────────────
@router.post("/rag/ingest")
async def rag_ingest(request: Request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    path = (data.get("path") or "").strip()
    metadata = data.get("metadata", {}) or {}
    prefix = data.get("doc_id_prefix")
    incremental = bool(data.get("incremental", False))

    if not text and not path:
        return JSONResponse({"error": "text or path is required"}, status_code=400)

    if path:
        try:
            full_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return JSONResponse({"error": f"Failed to read path {path}: {e}"}, status_code=400)

    try:
        if incremental:
            metadata = {**metadata, "incremental": True}
        count = get_rag_system().ingest(text, metadata=metadata, doc_id_prefix=prefix)
        return {"ingested_chunks": count, "status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _rag_retrieval_confidence(results: list[dict]) -> float:
    if not results:
        return 0.0
    scores = []
    for r in results:
        try:
            score = float(r.get("score", 0.0))
        except Exception:
            score = 0.0
        scores.append(max(0.0, min(1.0, score)))
    return round(sum(scores) / max(len(scores), 1), 4)


def _build_rag_citations(results: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for idx, item in enumerate(results, start=1):
        meta = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        source = meta.get("source_url") or meta.get("source") or f"document-{idx}"
        chunk_ref = meta.get("chunk_index", meta.get("section", idx - 1))
        citations.append(
            {
                "rank": idx,
                "source": source,
                "chunk_ref": chunk_ref,
                "score": float(item.get("score", 0.0) or 0.0),
                "id": item.get("id", ""),
            }
        )
    return citations


def _rag_answer_with_critic(query: str, results: list[dict]) -> dict:
    from ..rag.critic import CriticAgent

    if not results:
        return {
            "answer": "No relevant documents were found for this query.",
            "model_confidence": 0.0,
            "retrieval_confidence": 0.0,
            "calibrated_confidence": 0.0,
            "critique": None,
        }

    context = "\n\n".join(
        f"[{i + 1}] {r.get('document', '')}"
        for i, r in enumerate(results[:5])
    )

    prompt = (
        "Answer the question using only the provided retrieval context. "
        "Cite sources inline as [1], [2], etc. If uncertain, explicitly say so.\n\n"
        f"Question: {query}\n\nContext:\n{context}"
    )

    answer_text = ""
    model_conf = 0.55
    try:
        llm_resp, _provider = call_llm_with_fallback(
            [{"role": "user", "content": prompt}],
            "rag_query",
        )
        answer_text = (llm_resp.get("content") if isinstance(llm_resp, dict) else str(llm_resp) or "").strip()
    except Exception:
        answer_text = " ".join(str(r.get("document", "")).strip() for r in results[:3])[:1200]

    retrieval_conf = _rag_retrieval_confidence(results)
    critic = CriticAgent()
    critique = critic.critique(query, answer_text, results)
    model_conf = round(max(0.0, min(1.0, float(critique.overall_score))), 4)
    calibrated = round((0.45 * retrieval_conf) + (0.55 * model_conf), 4)

    return {
        "answer": answer_text,
        "model_confidence": model_conf,
        "retrieval_confidence": retrieval_conf,
        "calibrated_confidence": calibrated,
        "critique": critique.to_dict(),
    }


@router.post("/rag/query")
async def rag_query(request: Request):
    data = await request.json()
    query = (data.get("query") or "").strip()
    top_k = data.get("top_k")
    filter_metadata = data.get("filter_metadata")
    include_answer = bool(data.get("include_answer", True))

    if not query:
        return JSONResponse({"error": "query field is required"}, status_code=400)

    try:
        results = get_rag_system().query(query, top_k=top_k, filter_metadata=filter_metadata)
        payload: dict = {
            "query": query,
            "results": results,
            "citations": _build_rag_citations(results),
            "retrieval_confidence": _rag_retrieval_confidence(results),
        }
        if include_answer:
            payload.update(_rag_answer_with_critic(query, results))
        return payload
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/rag/status")
def rag_status():
    try:
        return get_rag_system().stats()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/rag/documents")
def rag_documents(limit: int = 200, q: str = ""):
    """List ingested RAG corpus documents (with optional text search)."""
    try:
        rag = get_rag_system()
        docs = rag.vector_store.get_all_documents()
        query = (q or "").strip().lower()
        if query:
            docs = [
                d for d in docs
                if query in str(d.get("document", "")).lower()
                or query in str((d.get("metadata") or {}).get("source", "")).lower()
                or query in str((d.get("metadata") or {}).get("title", "")).lower()
            ]
        safe_limit = max(1, min(int(limit), 1000))
        docs = docs[:safe_limit]
        return {
            "count": len(docs),
            "items": [
                {
                    "id": str(item.get("id", "")),
                    "preview": str(item.get("document", ""))[:240],
                    "metadata": item.get("metadata") or {},
                }
                for item in docs
            ],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/rag/documents/{doc_id}")
def rag_delete_document(doc_id: str):
    """Delete a single document from the RAG corpus by id."""
    try:
        rag = get_rag_system()
        rag.vector_store.delete([doc_id])
        rag.vector_store.persist()
        return {"ok": True, "deleted": doc_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/rag/snapshots")
async def rag_snapshot_create(request: Request):
    data = await request.json() if request else {}
    label = (data.get("label") or "").strip() or None
    try:
        return get_rag_system().create_snapshot(label=label)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/rag/snapshots/{snapshot_id}/rollback")
def rag_snapshot_rollback(snapshot_id: str):
    try:
        return get_rag_system().rollback_snapshot(snapshot_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Knowledge Graph endpoints ─────────────────────────────────────────────

@router.post("/kg/store")
async def kg_store_endpoint(request: Request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return _api_error("name is required", "validation_error", 422)
    eid = _kg_store(
        name,
        entity_type=data.get("entity_type", "concept"),
        facts=data.get("facts", {}),
        relations=data.get("relations", []),
    )
    return {"id": eid, "name": name, "ok": True}


@router.get("/kg/query")
def kg_query_endpoint(q: str = "", limit: int = 10):
    if not q:
        return _api_error("q is required", "validation_error", 422)
    results = _kg_query(q, limit=limit)
    return {"results": results, "count": len(results)}


@router.get("/kg/entities")
def kg_entities_endpoint(entity_type: str = "", limit: int = 100):
    results = _kg_list(entity_type=entity_type or None, limit=limit)
    return {"entities": results, "count": len(results)}


@router.get("/kg/entities/{name}")
def kg_entity_get_endpoint(name: str):
    entity = _kg_get(name)
    if entity is None:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return entity


@router.delete("/kg/entities/{name}")
def kg_entity_delete_endpoint(name: str):
    deleted = _kg_delete(name)
    if not deleted:
        return _api_error(f"Entity not found: {name}", "not_found", 404)
    return {"deleted": name, "ok": True}


@router.get("/kg/graph")
def kg_graph_endpoint(limit: int = 500):
    return _kg_graph(limit=limit)


@router.post("/kg/merge")
async def kg_merge_endpoint(request: Request):
    data = await request.json()
    primary = (data.get("primary") or "").strip()
    duplicate = (data.get("duplicate") or "").strip()
    if not primary or not duplicate:
        return _api_error("primary and duplicate are required", "validation_error", 422)
    result = _kg_merge(primary, duplicate)
    if not result.get("merged"):
        return _api_error("merge failed", "merge_error", 400)
    return result


@router.post("/kg/import")
async def kg_import_endpoint(request: Request):
    data = await request.json()
    content = str(data.get("content", "") or "")
    if not content.strip():
        return _api_error("content is required", "validation_error", 422)
    fmt = str(data.get("format", "auto") or "auto")
    limit = int(data.get("limit", 2000) or 2000)
    return _kg_import(content, fmt=fmt, limit=limit)


@router.get("/kg/hybrid-search")
def kg_hybrid_search_endpoint(q: str = "", limit: int = 10):
    if not q.strip():
        return _api_error("q is required", "validation_error", 422)
    kg_results = _kg_hybrid_search(q.strip(), limit=limit)
    return {"kg": kg_results, "semantic": []}


# ── 26.8 Data & Knowledge: citation, incremental index ───────────────────

@router.post("/rag/cite")
async def api_rag_cite(request: Request):
    body = await request.json()
    response_text = str(body.get("response", "")).strip()
    chunks = body.get("chunks", [])
    if not response_text:
        return _api_error("response is required", status_code=400)
    try:
        from ..rag.citation import attribute_response
        result = attribute_response(
            response=response_text, chunks=chunks,
            method=str(body.get("method", "auto")),
            min_confidence=float(body.get("min_confidence", 0.1)),
        )
        return {
            "inline_text": result.inline_text,
            "footnotes": result.footnotes,
            "sources": result.sources,
            "method": result.method,
        }
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/rag/index/{collection}/stats")
async def api_rag_index_stats(request: Request, collection: str):
    try:
        from ..rag.incremental_index import get_index_stats
        return get_index_stats(collection)
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/rag/index/{collection}/invalidate/{doc_id}")
async def api_rag_invalidate_doc(request: Request, collection: str, doc_id: str):
    require_admin(request)
    try:
        from ..rag.incremental_index import invalidate_document
        ok = invalidate_document(doc_id, collection)
        return {"invalidated": ok, "doc_id": doc_id, "collection": collection}
    except Exception as exc:
        return _api_error(str(exc))
