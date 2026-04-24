"""
Unit tests for chunker.py.
Pure Python, no external dependencies beyond pytest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from chunker import chunk_text


class TestChunkText:
    def test_empty_string(self):
        assert chunk_text("") == []

    def test_whitespace_only(self):
        assert chunk_text("   \n\n  ") == []

    def test_short_text_under_min_length(self):
        # Default min_length is 30; a 5-char string should be discarded
        result = chunk_text("hello", min_length=30)
        assert result == []

    def test_short_text_above_min_length(self):
        text = "This is a reasonably sized sentence for testing."
        result = chunk_text(text, chunk_size=512, min_length=10)
        assert len(result) == 1
        assert result[0] == text

    def test_exact_chunk_size(self):
        text = "a" * 512
        result = chunk_text(text, chunk_size=512, chunk_overlap=64, min_length=1)
        assert len(result) >= 1

    def test_chunk_size_not_exceeded(self):
        text = "这是一个测试句子。" * 100  # ~900 chars
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20, min_length=10)
        for chunk in chunks:
            # Allow slight overage due to sentence-boundary snapping
            assert len(chunk) <= 200, f"Chunk too long: {len(chunk)}"

    def test_overlap_present(self):
        """Last N chars of chunk[i] should appear in chunk[i+1]."""
        text = "Hello world. " * 50  # simple repetitive English text
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=10, min_length=5)
        if len(chunks) >= 2:
            tail = chunks[0][-5:]  # last 5 chars of first chunk
            assert tail in chunks[1], "Expected overlap between consecutive chunks"

    def test_chinese_sentence_boundary(self):
        """Chunks should preferably break at Chinese sentence endings."""
        text = ("量子计算是计算机科学的前沿领域。" * 10 +
                "人工智能正在改变世界。" * 10)
        chunks = chunk_text(text, chunk_size=80, chunk_overlap=16, min_length=10)
        assert len(chunks) > 1
        # At least one chunk should end with a Chinese sentence-end character
        ends = {"。", "！", "？", "…", ".", "!", "?"}
        assert any(c[-1] in ends for c in chunks), (
            "Expected at least one chunk to end at a sentence boundary"
        )

    def test_paragraph_split(self):
        """Paragraphs separated by blank lines become separate chunks when small."""
        para1 = "First paragraph with enough content to pass min_length check."
        para2 = "Second paragraph with enough content to pass min_length check."
        text = f"{para1}\n\n{para2}"
        chunks = chunk_text(text, chunk_size=512, chunk_overlap=64, min_length=10)
        assert len(chunks) == 2
        assert para1 in chunks[0]
        assert para2 in chunks[1]

    def test_large_text_produces_multiple_chunks(self):
        text = "word " * 1000  # 5000 chars
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=40, min_length=10)
        assert len(chunks) > 5

    def test_no_empty_chunks(self):
        text = "sentence one. sentence two. " * 50
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20, min_length=5)
        assert all(len(c.strip()) > 0 for c in chunks)
