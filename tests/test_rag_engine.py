"""
Unit tests for rag_engine.py.
Uses tmp_path for DB isolation and mocks _embed() to avoid loading the model.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from rag_engine import RAGEngine


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Return deterministic dummy embeddings (unit vectors)."""
    dim = 512
    result = []
    for i, t in enumerate(texts):
        vec = [0.0] * dim
        # Use text hash to make each embedding slightly different
        idx = hash(t) % dim
        vec[idx] = 1.0
        result.append(vec)
    return result


@pytest.fixture()
def engine(tmp_path):
    """RAGEngine wired to a temporary ChromaDB, with embedding mocked."""
    e = RAGEngine({"VECTOR_STORE_DIR": tmp_path / "vector_store"})
    # Manually initialise so we can patch _embed before any real model load
    e._ensure_initialized = lambda: None  # skip lazy init
    e._open_collection()  # connect to temp ChromaDB
    e._embed = _fake_embed  # replace embedding with mock
    return e


@pytest.fixture()
def sample_txt(tmp_path) -> Path:
    f = tmp_path / "sample.txt"
    f.write_text(
        "量子计算是计算机科学的前沿领域。" * 30,
        encoding="utf-8",
    )
    return f


# ── ingest_document ────────────────────────────────────────────────────────

class TestIngestDocument:
    def test_success(self, engine, sample_txt):
        result = engine.ingest_document(str(sample_txt))
        assert result["status"] == "success"
        assert result["chunks_added"] > 0
        assert result["doc_name"] == "sample"

    def test_idempotent(self, engine, sample_txt):
        r1 = engine.ingest_document(str(sample_txt))
        r2 = engine.ingest_document(str(sample_txt))
        assert r1["chunks_added"] == r2["chunks_added"], (
            "Re-ingesting should not double chunk count"
        )
        assert engine._collection.count() == r1["chunks_added"]

    def test_file_not_found(self, engine):
        result = engine.ingest_document("/nonexistent/missing.txt")
        assert result["status"] == "error"

    def test_returns_expected_keys(self, engine, sample_txt):
        result = engine.ingest_document(str(sample_txt))
        for key in ("status", "doc_name", "chunks_added", "message"):
            assert key in result


# ── ingest_directory ───────────────────────────────────────────────────────

class TestIngestDirectory:
    def test_multiple_files(self, engine, tmp_path):
        for i in range(3):
            f = tmp_path / f"doc{i}.txt"
            f.write_text("Some content. " * 20, encoding="utf-8")

        result = engine.ingest_directory(str(tmp_path))
        assert result["total_files"] == 3
        assert result["total_chunks"] > 0
        assert len(result["errors"]) == 0

    def test_nonexistent_dir(self, engine):
        result = engine.ingest_directory("/nonexistent/dir")
        assert result["total_files"] == 0
        assert len(result["errors"]) > 0


# ── list_documents ─────────────────────────────────────────────────────────

class TestListDocuments:
    def test_empty(self, engine):
        assert engine.list_documents() == []

    def test_after_ingest(self, engine, sample_txt):
        engine.ingest_document(str(sample_txt))
        docs = engine.list_documents()
        assert len(docs) == 1
        assert docs[0]["doc_name"] == "sample"
        assert docs[0]["chunk_count"] > 0

    def test_multiple_docs(self, engine, tmp_path):
        for name in ("alpha", "beta", "gamma"):
            f = tmp_path / f"{name}.txt"
            f.write_text("Content. " * 20, encoding="utf-8")
            engine.ingest_document(str(f))

        docs = engine.list_documents()
        names = [d["doc_name"] for d in docs]
        assert sorted(names) == names  # should be sorted alphabetically
        assert set(names) == {"alpha", "beta", "gamma"}


# ── delete_document ────────────────────────────────────────────────────────

class TestDeleteDocument:
    def test_delete_existing(self, engine, sample_txt):
        engine.ingest_document(str(sample_txt))
        result = engine.delete_document("sample")
        assert result["status"] == "success"
        assert result["chunks_deleted"] > 0
        assert engine.list_documents() == []

    def test_delete_nonexistent(self, engine):
        result = engine.delete_document("ghost_document")
        assert result["status"] == "not_found"
        assert result["chunks_deleted"] == 0


# ── search ─────────────────────────────────────────────────────────────────

class TestSearch:
    def test_returns_empty_on_empty_db(self, engine):
        assert engine.search("query") == []

    def test_returns_results_after_ingest(self, engine, sample_txt):
        engine.ingest_document(str(sample_txt))
        results = engine.search("量子计算")
        assert len(results) > 0

    def test_result_keys(self, engine, sample_txt):
        engine.ingest_document(str(sample_txt))
        results = engine.search("量子计算", top_k=1)
        r = results[0]
        for key in ("content", "doc_name", "source_path", "chunk_index",
                    "total_chunks", "score", "distance"):
            assert key in r

    def test_score_in_range(self, engine, sample_txt):
        engine.ingest_document(str(sample_txt))
        results = engine.search("量子计算")
        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    def test_top_k_respected(self, engine, tmp_path):
        for i in range(5):
            f = tmp_path / f"doc{i}.txt"
            f.write_text("Unique content number " + str(i) + ". " * 10,
                         encoding="utf-8")
            engine.ingest_document(str(f))

        results = engine.search("content", top_k=2)
        assert len(results) <= 2
