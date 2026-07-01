"""Tests for src/document_pipeline.py — parsing, chunking, embedding, search, RAG."""

from __future__ import annotations

from src.document_pipeline import (
    DocStore,
    _parse_text,
    _parse_markdown,
    _parse_html,
    _parse_csv,
    _parse_json,
    _parse_xml,
    _parse_pdf_fallback,
    _detect_type,
    build_rag_context,
    chunk_document,
    ingest_document,
    parse_document,
)


class TestTypeDetection:
    """Document type detection from filenames."""

    def test_pdf_detection(self):
        assert _detect_type("report.pdf") == "pdf"

    def test_docx_detection(self):
        assert _detect_type("doc.docx") == "docx"

    def test_markdown_detection(self):
        assert _detect_type("README.md") == "markdown"

    def test_html_detection(self):
        assert _detect_type("page.html") == "html"
        assert _detect_type("page.htm") == "html"

    def test_txt_detection(self):
        assert _detect_type("notes.txt") == "text"

    def test_unknown_extension_defaults_to_text(self):
        assert _detect_type("data.bin") == "text"


class TestTextParsing:
    """Plain text and structured format parsers."""

    def test_parse_text_basic(self):
        segments = _parse_text("Hello world.\n\nSecond paragraph.")
        assert len(segments) == 2
        assert segments[0]["text"] == "Hello world."
        assert segments[1]["text"] == "Second paragraph."

    def test_parse_text_single_paragraph(self):
        segments = _parse_text("Just one paragraph.")
        assert len(segments) == 1

    def test_parse_text_empty(self):
        segments = _parse_text("")
        assert len(segments) == 0

    def test_parse_markdown_headings(self):
        md = "# Title\nContent here.\n\n## Section\nMore content."
        segments = _parse_markdown(md, "test.md")
        assert len(segments) >= 2
        # Should have sections separated by headings
        sections = [s["metadata"]["section"] for s in segments]
        assert "Title" in sections or "top" in str(sections)

    def test_parse_html_strips_tags(self):
        html = "<html><body><p>Hello <b>World</b></p></body></html>"
        segments = _parse_html(html)
        assert len(segments) >= 1
        text = " ".join(s["text"] for s in segments)
        assert "Hello" in text
        assert "World" in text
        assert "<b>" not in text

    def test_parse_csv_preserves_header(self):
        csv = "name,age,city\nAlice,30,NYC\nBob,25,LA"
        segments = _parse_csv(csv, "data.csv")
        assert len(segments) == 1
        assert "name,age,city" in segments[0]["text"]
        assert "Alice" in segments[0]["text"]

    def test_parse_json_formats(self):
        json_str = '{"key": "value", "list": [1, 2, 3]}'
        segments = _parse_json(json_str)
        assert len(segments) == 1
        assert "key" in segments[0]["text"]
        assert "value" in segments[0]["text"]

    def test_parse_xml_strips_tags(self):
        xml = "<root><item>Data</item></root>"
        segments = _parse_xml(xml)
        text = segments[0]["text"]
        assert "Data" in text
        assert "<root>" not in text

    def test_parse_pdf_fallback_joins_hyphenated(self):
        pdf_text = "This is a bro-\nken word at line end.\n\nNew paragraph."
        segments = _parse_pdf_fallback(pdf_text, "test.pdf")
        assert len(segments) >= 1
        full_text = " ".join(s["text"] for s in segments)
        assert "broken" in full_text

    def test_parse_document_routes_to_correct_parser(self):
        segments = parse_document("# Hello\nWorld", file_type="markdown", filename="doc.md")
        assert len(segments) >= 1


class TestChunking:
    """Document chunking with overlap."""

    def test_chunk_short_text_no_split(self):
        chunks = chunk_document([{"text": "short text", "metadata": {}}], chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "short text"

    def test_chunk_long_text_splits(self):
        long_text = "word " * 200  # 200 words
        chunks = chunk_document([{"text": long_text, "metadata": {"source": "test"}}], chunk_size=50, chunk_overlap=10)
        assert len(chunks) > 1
        # Each chunk should not exceed chunk_size words (approximately)
        for c in chunks:
            assert len(c["text"].split()) <= 55  # Allow slight overflow from last word

    def test_chunk_preserves_metadata(self):
        chunks = chunk_document([{"text": "x " * 150, "metadata": {"source": "meta-test"}}], chunk_size=50)
        for c in chunks:
            assert c["metadata"]["source"] == "meta-test"


class TestDocStore:
    """In-memory document store with semantic search."""

    def test_add_and_search(self):
        store = DocStore()
        store.add([{"text": "Nexus AI is a sovereign platform.", "metadata": {"source": "readme"}, "chunk_id": "c1"}])
        results = store.search("sovereign platform")
        assert len(results) >= 1
        assert results[0]["metadata"]["source"] == "readme"

    def test_search_returns_scores(self):
        store = DocStore()
        store.add([{"text": "The quick brown fox jumps over the lazy dog.", "metadata": {}, "chunk_id": "c1"}])
        results = store.search("fox")
        assert results[0]["score"] is not None

    def test_search_empty_store(self):
        store = DocStore()
        assert store.search("anything") == []

    def test_stats_reflects_state(self):
        store = DocStore()
        assert store.stats()["total_documents"] == 0
        store.add([{"text": "doc1", "metadata": {"source": "a"}, "chunk_id": "c1"}])
        store.add([{"text": "doc2", "metadata": {"source": "b"}, "chunk_id": "c2"}])
        stats = store.stats()
        assert stats["total_documents"] == 2
        assert stats["unique_sources"] == 2

    def test_clear_removes_all(self):
        store = DocStore()
        store.add([{"text": "data", "metadata": {}, "chunk_id": "c1"}])
        assert store.clear() == 1
        assert store.stats()["total_documents"] == 0

    def test_remove_by_source(self):
        store = DocStore()
        store.add([{"text": "A", "metadata": {"source": "src1"}, "chunk_id": "c1"}])
        store.add([{"text": "B", "metadata": {"source": "src2"}, "chunk_id": "c2"}])
        removed = store.remove_by_source("src1")
        assert removed == 1
        assert store.stats()["total_documents"] == 1

    def test_search_with_metadata_filter(self):
        store = DocStore()
        store.add([{"text": "Python docs", "metadata": {"lang": "python"}, "chunk_id": "c1"}])
        store.add([{"text": "JavaScript docs", "metadata": {"lang": "javascript"}, "chunk_id": "c2"}])
        results = store.search("docs", filter_metadata={"lang": "python"})
        assert len(results) == 1
        assert results[0]["metadata"]["lang"] == "python"


class TestIngestionPipeline:
    """End-to-end ingestion pipeline."""

    def test_ingest_document_full_pipeline(self):
        store = DocStore()
        result = ingest_document(store, "Nexus AI is a self-hosted AI coding agent platform.", file_type="text", filename="about.txt")
        assert result["status"] == "ok"
        assert result["ingested_chunks"] >= 1
        assert result["char_count"] > 0
        assert store.stats()["total_documents"] >= 1

    def test_ingest_empty_text(self):
        store = DocStore()
        result = ingest_document(store, "", file_type="text")
        assert result["status"] == "empty"

    def test_build_rag_context_includes_relevant_docs(self):
        store = DocStore()
        ingest_document(store, "The Apollo program landed humans on the Moon in 1969.", file_type="text", filename="nasa.txt")
        ctx = build_rag_context(store, "moon landing")
        assert len(ctx) > 0
        assert "Apollo" in ctx

    def test_build_rag_context_empty_store(self):
        store = DocStore()
        ctx = build_rag_context(store, "anything")
        assert ctx == ""
