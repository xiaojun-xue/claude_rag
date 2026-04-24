"""BM25 keyword index over kb_code, used for hybrid search with RRF."""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric; preserves C/Python identifiers and underscores."""
    return re.findall(r"[a-z0-9_]+", text.lower())


class BM25Index:
    """
    In-memory BM25 index over all kb_code chunks.
    Built once on first search_code() call; invalidated when new code is ingested.
    """

    def __init__(self, code_collection) -> None:
        from rank_bm25 import BM25Okapi

        result = code_collection.get(include=["documents", "metadatas"])
        self._docs: list[str] = result["documents"]
        self._metas: list[dict[str, Any]] = result["metadatas"]

        if not self._docs:
            logger.warning("BM25Index: code collection is empty.")
            self._index = None
            return

        tokenized = [_tokenize(d) for d in self._docs]
        self._index = BM25Okapi(tokenized)
        logger.info("BM25 index built: %d code chunks.", len(self._docs))

    def search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        """Return top_k chunks ranked by BM25 score."""
        if self._index is None or not self._docs:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._index.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [
            {
                **self._metas[i],
                "content": self._docs[i],
                "bm25_score": float(s),
                "bm25_rank": r,
            }
            for r, (i, s) in enumerate(ranked[:top_k])
        ]
