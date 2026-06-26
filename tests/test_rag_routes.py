"""Tests for src/routes/rag.py.

Covers RAG ingestion, query, citations, confidence, snapshots,
and Knowledge Graph endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.routes.rag import _build_rag_citations, _rag_retrieval_confidence


# ── _rag_retrieval_confidence ───────────────────────────────────────────


def test_rag_confidence_empty():
    assert _rag_retrieval_confidence([]) == 0.0


def test_rag_confidence_single():
    results = [{"score": 0.8}]
    assert _rag_retrieval_confidence(results) == 0.8


def test_rag_confidence_multiple_average():
    results = [{"score": 1.0}, {"score": 0.0}]
    assert _rag_retrieval_confidence(results) == 0.5


def test_rag_confidence_clamps_low():
    results = [{"score": -0.5}]
    assert _rag_retrieval_confidence(results) == 0.0


def test_rag_confidence_clamps_high():
    results = [{"score": 1.5}]
    assert _rag_retrieval_confidence(results) == 1.0


def test_rag_confidence_missing_score_defaults_zero():
    results = [{"no_score": True}]
    assert _rag_retrieval_confidence(results) == 0.0


def test_rag_confidence_mixed():
    results = [{"score": 0.9}, {"score": "invalid"}, {"score": 0.7}]
    val = _rag_retrieval_confidence(results)
    assert 0.5 <= val <= 0.9


# ── _build_rag_citations ────────────────────────────────────────────────


def test_build_citations_empty():
    assert _build_rag_citations([]) == []


def test_build_citations_single():
    results = [{"id": "doc1", "score": 0.95, "metadata": {"source_url": "https://example.com"}}]
    citations = _build_rag_citations(results)
    assert len(citations) == 1
    assert citations[0]["rank"] == 1
    assert citations[0]["source"] == "https://example.com"
    assert citations[0]["score"] == 0.95
    assert citations[0]["id"] == "doc1"


def test_build_citations_fallback_source():
    results = [{"id": "doc1", "score": 0.5, "metadata": {"source": "manual.pdf"}}]
    citations = _build_rag_citations(results)
    assert citations[0]["source"] == "manual.pdf"


def test_build_citations_no_metadata():
    results = [{"id": "doc1", "score": 0.5}]
    citations = _build_rag_citations(results)
    assert citations[0]["source"] == "document-1"


def test_build_citations_multiple():
    results = [
        {"id": "a", "score": 0.9, "metadata": {"source_url": "https://a.com"}},
        {"id": "b", "score": 0.8, "metadata": {"source_url": "https://b.com"}},
    ]
    citations = _build_rag_citations(results)
    assert len(citations) == 2
    assert citations[0]["rank"] == 1
    assert citations[1]["rank"] == 2


def test_build_citations_chunk_ref():
    results = [{"id": "d", "score": 0.7, "metadata": {"chunk_index": 3}}]
    assert _build_rag_citations(results)[0]["chunk_ref"] == 3


# ── RAG endpoints ───────────────────────────────────────────────────────


def test_rag_ingest_missing_text(client):
    resp = client.post("/rag/ingest", json={})
    assert resp.status_code == 400
    assert "text or path" in resp.json()["error"]


def test_rag_ingest_success(client):
    mock_rag = MagicMock()
    mock_rag.ingest.return_value = 5
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        resp = client.post("/rag/ingest", json={"text": "hello world"})
    assert resp.status_code == 200
    assert resp.json()["ingested_chunks"] == 5


def test_rag_ingest_incremental(client):
    mock_rag = MagicMock()
    mock_rag.ingest.return_value = 3
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        resp = client.post("/rag/ingest", json={"text": "data", "incremental": True})
    assert resp.status_code == 200
    _, kwargs = mock_rag.ingest.call_args
    assert kwargs["metadata"].get("incremental") is True


def test_rag_query_missing_query(client):
    resp = client.post("/rag/query", json={})
    assert resp.status_code == 400


def test_rag_query_success(client):
    mock_rag = MagicMock()
    mock_rag.query.return_value = [{"id": "d1", "score": 0.9, "document": "text"}]
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        with patch("src.routes.rag.call_llm_with_fallback", return_value=({"content": "answer"}, "mock")):
            resp = client.post("/rag/query", json={"query": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test"
    assert data["retrieval_confidence"] == 0.9


def test_rag_status(client):
    mock_rag = MagicMock()
    mock_rag.stats.return_value = {"chunks": 100}
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        resp = client.get("/rag/status")
    assert resp.status_code == 200
    assert resp.json()["chunks"] == 100


def test_rag_documents(client):
    mock_rag = MagicMock()
    mock_doc = {"id": "doc1", "document": "some content here", "metadata": {"source": "test.txt"}}
    mock_rag.vector_store.get_all_documents.return_value = [mock_doc]
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        resp = client.get("/rag/documents")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_rag_delete_document(client):
    mock_rag = MagicMock()
    with patch("src.routes.rag.get_rag_system", return_value=mock_rag):
        resp = client.delete("/rag/documents/doc1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_rag.vector_store.delete.assert_called_once_with(["doc1"])


# ── Knowledge Graph endpoints ───────────────────────────────────────────


def test_kg_store_missing_name(client):
    resp = client.post("/kg/store", json={})
    assert resp.status_code == 422


def test_kg_store_success(client):
    with patch("src.routes.rag._kg_store", return_value="new-id"):
        resp = client.post("/kg/store", json={"name": "test entity"})
    assert resp.status_code == 200
    assert resp.json()["id"] == "new-id"


def test_kg_query_missing_q(client):
    resp = client.get("/kg/query")
    assert resp.status_code == 422


def test_kg_query_success(client):
    with patch("src.routes.rag._kg_query", return_value=[{"name": "test"}]):
        resp = client.get("/kg/query", params={"q": "test"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_kg_entities(client):
    with patch("src.routes.rag._kg_list", return_value=[{"name": "e1"}]):
        resp = client.get("/kg/entities")
    assert resp.status_code == 200


def test_kg_entity_get_found(client):
    with patch("src.routes.rag._kg_get", return_value={"name": "e1"}):
        resp = client.get("/kg/entities/e1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "e1"


def test_kg_entity_get_not_found(client):
    with patch("src.routes.rag._kg_get", return_value=None):
        resp = client.get("/kg/entities/nonexistent")
    assert resp.status_code == 404


def test_kg_entity_delete_found(client):
    with patch("src.routes.rag._kg_delete", return_value=True):
        resp = client.delete("/kg/entities/e1")
    assert resp.status_code == 200


def test_kg_entity_delete_not_found(client):
    with patch("src.routes.rag._kg_delete", return_value=False):
        resp = client.delete("/kg/entities/nonexistent")
    assert resp.status_code == 404


def test_kg_graph(client):
    with patch("src.routes.rag._kg_graph", return_value={"nodes": [], "edges": []}):
        resp = client.get("/kg/graph")
    assert resp.status_code == 200


def test_kg_merge_missing_params(client):
    resp = client.post("/kg/merge", json={"primary": "a"})
    assert resp.status_code == 422


def test_kg_merge_success(client):
    with patch("src.routes.rag._kg_merge", return_value={"merged": True}):
        resp = client.post("/kg/merge", json={"primary": "a", "duplicate": "b"})
    assert resp.status_code == 200


def test_kg_hybrid_search_missing_q(client):
    resp = client.get("/kg/hybrid-search")
    assert resp.status_code == 422


def test_kg_hybrid_search_success(client):
    with patch("src.routes.rag._kg_hybrid_search", return_value=[{"name": "r1"}]):
        resp = client.get("/kg/hybrid-search", params={"q": "test"})
    assert resp.status_code == 200
