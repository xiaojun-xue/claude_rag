"""
Integration tests — use the real embedding model and ChromaDB.
Marked @pytest.mark.slow; excluded from the default test run.

Run with:
    pytest tests/test_integration.py -m slow -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from rag_engine import RAGEngine


@pytest.mark.slow
class TestFullPipeline:
    """End-to-end tests with real model loading."""

    @pytest.fixture(scope="class")
    def engine(self, tmp_path_factory):
        vs = tmp_path_factory.mktemp("vector_store")
        return RAGEngine({"VECTOR_STORE_DIR": vs})

    def test_chinese_text_retrieval(self, engine, tmp_path):
        doc = tmp_path / "quantum.txt"
        doc.write_text(
            "量子计算是计算机科学的前沿领域，利用量子力学现象进行信息处理。" * 20,
            encoding="utf-8",
        )
        result = engine.ingest_document(str(doc))
        assert result["status"] == "success"
        assert result["chunks_added"] > 0

        hits = engine.search("量子计算")
        assert len(hits) > 0
        assert hits[0]["doc_name"] == "quantum"
        assert hits[0]["score"] > 0.5

    def test_english_text_retrieval(self, engine, tmp_path):
        doc = tmp_path / "ml.txt"
        doc.write_text(
            "Machine learning is a branch of artificial intelligence. " * 20,
            encoding="utf-8",
        )
        engine.ingest_document(str(doc))
        hits = engine.search("artificial intelligence machine learning")
        assert len(hits) > 0
        assert hits[0]["score"] > 0.5

    def test_source_attribution(self, engine, tmp_path):
        doc = tmp_path / "attribution_test.txt"
        doc.write_text("Unique rare phrase xyzzy42 for source testing. " * 10,
                       encoding="utf-8")
        engine.ingest_document(str(doc))
        hits = engine.search("xyzzy42")
        assert hits[0]["doc_name"] == "attribution_test"
        assert "attribution_test" in hits[0]["source_path"]

    def test_idempotent_reingestion(self, engine, tmp_path):
        doc = tmp_path / "idempotent.txt"
        doc.write_text("Idempotency test content. " * 20, encoding="utf-8")
        r1 = engine.ingest_document(str(doc))
        r2 = engine.ingest_document(str(doc))
        assert r1["chunks_added"] == r2["chunks_added"]

    def test_delete_removes_from_search(self, engine, tmp_path):
        doc = tmp_path / "to_delete.txt"
        doc.write_text("This document will be deleted. " * 20, encoding="utf-8")
        engine.ingest_document(str(doc))

        engine.delete_document("to_delete")
        hits = engine.search("document will be deleted")
        for h in hits:
            assert h["doc_name"] != "to_delete"
