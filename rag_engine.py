"""
Core RAG engine: dual embedding models + dual ChromaDB collections.

文件类型路由：
  CODE_FILE_TYPES → jina-embeddings-v2-base-code (768-dim) → kb_code
  TEXT_FILE_TYPES → bge-small-zh-v1.5 (512-dim)            → kb_text

Lazy-initializes models and collections on first use.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from chunker import chunk_document
from config import (
    BM25_TOP_K,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CODE_CHUNK_SIZE,
    CODE_COLLECTION_NAME,
    CODE_EMBEDDING_MODEL_NAME,
    CODE_FILE_TYPES,
    COLLECTION_NAME,
    DEFAULT_TOP_K,
    EMBEDDING_MODEL_NAME,
    KNOWLEDGE_BASE_DIR,
    MAX_TOP_K,
    MIN_CHUNK_LENGTH,
    MODELS_CACHE_DIR,
    SUPPORTED_EXTENSIONS,
    TEXT_COLLECTION_NAME,
    TEXT_FILE_TYPES,
    VECTOR_STORE_DIR,
)
from document_loader import load_document

try:
    from bm25_engine import BM25Index
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    Manages document ingestion and semantic retrieval with dual models.

    Config override keys (all optional):
        VECTOR_STORE_DIR, TEXT_COLLECTION_NAME, CODE_COLLECTION_NAME,
        EMBEDDING_MODEL_NAME, CODE_EMBEDDING_MODEL_NAME,
        CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK_LENGTH
    """

    def __init__(self, config_override: dict[str, Any] | None = None):
        cfg = config_override or {}
        self._vector_store_dir = Path(cfg.get("VECTOR_STORE_DIR", VECTOR_STORE_DIR))
        self._text_collection_name = cfg.get("TEXT_COLLECTION_NAME", TEXT_COLLECTION_NAME)
        self._code_collection_name = cfg.get("CODE_COLLECTION_NAME", CODE_COLLECTION_NAME)
        self._text_model_name = cfg.get("EMBEDDING_MODEL_NAME", EMBEDDING_MODEL_NAME)
        self._code_model_name = cfg.get("CODE_EMBEDDING_MODEL_NAME", CODE_EMBEDDING_MODEL_NAME)
        self._chunk_size = int(cfg.get("CHUNK_SIZE", CHUNK_SIZE))
        self._chunk_overlap = int(cfg.get("CHUNK_OVERLAP", CHUNK_OVERLAP))
        self._min_chunk_length = int(cfg.get("MIN_CHUNK_LENGTH", MIN_CHUNK_LENGTH))

        self._text_model = None
        self._code_model = None
        self._text_collection = None
        self._code_collection = None
        self._bm25_index: "BM25Index | None" = None
        self._chroma_client = None
        self._lock = threading.Lock()

    # ── Initialization ─────────────────────────────────────────────────────

    def _ensure_initialized(self) -> None:
        with self._lock:
            if self._text_model is None:
                self._load_text_model()
            if self._code_model is None:
                self._load_code_model()
            if self._text_collection is None or self._code_collection is None:
                self._open_collections()

    def _load_text_model(self) -> None:
        import os
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(MODELS_CACHE_DIR)
        os.environ["HF_HOME"] = str(MODELS_CACHE_DIR)
        from sentence_transformers import SentenceTransformer
        logger.info("Loading text model: %s", self._text_model_name)
        self._text_model = SentenceTransformer(self._text_model_name)
        logger.info("Text model loaded.")

    def _load_code_model(self) -> None:
        import os
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(MODELS_CACHE_DIR)
        os.environ["HF_HOME"] = str(MODELS_CACHE_DIR)
        from sentence_transformers import SentenceTransformer
        logger.info("Loading code model: %s", self._code_model_name)
        self._code_model = SentenceTransformer(self._code_model_name, trust_remote_code=True)
        logger.info("Code model loaded.")

    def _open_collections(self) -> None:
        import chromadb
        self._vector_store_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self._vector_store_dir))
        self._chroma_client = client
        self._text_collection = client.get_or_create_collection(
            name=self._text_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._code_collection = client.get_or_create_collection(
            name=self._code_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Collections opened — text: %d items, code: %d items",
            self._text_collection.count(),
            self._code_collection.count(),
        )

    # ── Routing helper ─────────────────────────────────────────────────────

    def _route(self, file_type: str) -> tuple:
        """Return (model, collection) based on file_type."""
        ft = file_type.lower().lstrip(".")
        if ft in CODE_FILE_TYPES:
            return self._code_model, self._code_collection
        return self._text_model, self._text_collection

    # ── Embedding ──────────────────────────────────────────────────────────

    def _embed(self, texts: list[str], model) -> list[list[float]]:
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=16,
        )
        return [v.tolist() for v in vectors]

    @staticmethod
    def _rrf_merge(
        vector_hits: list[dict],
        bm25_hits: list[dict],
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion of vector + BM25 results (standard RRF, k=60)."""
        scores: dict[str, float] = {}
        data: dict[str, dict] = {}
        for rank, hit in enumerate(vector_hits):
            key = f"{hit['doc_name']}::{hit['chunk_index']}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            data[key] = hit
        for rank, hit in enumerate(bm25_hits):
            key = f"{hit['doc_name']}::{hit['chunk_index']}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in data:
                data[key] = hit
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [{**data[k2], "score": round(s, 6)} for k2, s in ranked[:top_k]]

    @staticmethod
    def _normalize_scores(hits: list[dict]) -> list[dict]:
        """Min-max normalize scores within a result set to [0, 1]."""
        if len(hits) < 2:
            return hits
        lo = min(h["score"] for h in hits)
        hi = max(h["score"] for h in hits)
        span = hi - lo + 1e-9
        for h in hits:
            h["score"] = round((h["score"] - lo) / span, 4)
        return hits

    # ── Public API ─────────────────────────────────────────────────────────

    def ingest_document(self, file_path: str) -> dict:
        """
        Load, chunk, embed, and store one document into the appropriate collection.
        Re-ingestion is idempotent.
        """
        self._ensure_initialized()

        path = Path(file_path).resolve()
        doc_name = path.stem

        try:
            text, meta = load_document(path)
        except FileNotFoundError as exc:
            return {"status": "error", "doc_name": doc_name, "chunks_added": 0, "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "doc_name": doc_name, "chunks_added": 0, "message": str(exc)}

        file_type = meta.get("file_type", "")
        language = meta.get("language", file_type)

        chunk_size = CODE_CHUNK_SIZE if file_type in CODE_FILE_TYPES else self._chunk_size

        chunks = chunk_document(
            text,
            language=language,
            file_name=meta.get("file_name", path.name),
            chunk_size=chunk_size,
            chunk_overlap=self._chunk_overlap,
            min_length=self._min_chunk_length,
        )

        if not chunks:
            return {
                "status": "error",
                "doc_name": doc_name,
                "chunks_added": 0,
                "message": "Document produced no usable text chunks.",
            }

        model, collection = self._route(file_type)

        # Remove stale chunks (idempotent re-ingestion)
        self._delete_by_doc_name(doc_name)

        ids = [f"{doc_name}__chunk_{i:04d}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_name": doc_name,
                "source_path": meta["source_path"],
                "file_type": file_type,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "char_count": len(chunk),
            }
            for i, chunk in enumerate(chunks)
        ]

        logger.info("Embedding %d chunks for '%s' (%s)…", len(chunks), doc_name, file_type)
        embeddings = self._embed(chunks, model)

        batch_size = 500
        for start in range(0, len(chunks), batch_size):
            sl = slice(start, start + batch_size)
            collection.add(
                ids=ids[sl],
                documents=chunks[sl],
                embeddings=embeddings[sl],
                metadatas=metadatas[sl],
            )

        if file_type in CODE_FILE_TYPES and self._bm25_index is not None:
            self._bm25_index = None  # rebuild on next search_code() call

        logger.info("Ingested '%s': %d chunks → %s.", doc_name, len(chunks),
                    self._code_collection_name if file_type in CODE_FILE_TYPES
                    else self._text_collection_name)
        return {
            "status": "success",
            "doc_name": doc_name,
            "chunks_added": len(chunks),
            "collection": (CODE_COLLECTION_NAME if file_type in CODE_FILE_TYPES
                           else TEXT_COLLECTION_NAME),
            "message": f"Indexed {len(chunks)} chunks from '{path.name}'.",
        }

    def ingest_directory(self, dir_path: str) -> dict:
        """Index all supported files under dir_path (recursive)."""
        self._ensure_initialized()

        root = Path(dir_path).resolve()
        if not root.exists():
            return {
                "processed": [],
                "total_files": 0,
                "total_chunks": 0,
                "errors": [{"file": str(root), "error": "Directory not found."}],
            }

        files = sorted(
            f for ext in SUPPORTED_EXTENSIONS for f in root.rglob(f"*{ext}")
        )

        processed = []
        errors = []
        total_chunks = 0

        for f in files:
            result = self.ingest_document(str(f))
            if result["status"] == "success":
                total_chunks += result["chunks_added"]
                processed.append({
                    "file": str(f),
                    "status": "success",
                    "chunks": result["chunks_added"],
                    "collection": result.get("collection", ""),
                })
            else:
                errors.append({"file": str(f), "error": result["message"]})

        return {
            "processed": processed,
            "total_files": len(files),
            "total_chunks": total_chunks,
            "errors": errors,
        }

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        """
        Semantic search over both collections.
        Queries each with its own model, merges and re-ranks by score.
        """
        self._ensure_initialized()

        top_k = max(1, min(top_k, MAX_TOP_K))
        results = []

        for model, collection, coll_name in [
            (self._text_model, self._text_collection, TEXT_COLLECTION_NAME),
            (self._code_model, self._code_collection, CODE_COLLECTION_NAME),
        ]:
            n = min(top_k, collection.count())
            if n == 0:
                continue
            emb = self._embed([query], model)[0]
            raw = collection.query(
                query_embeddings=[emb],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
            coll_hits = [
                {
                    "content": doc,
                    "doc_name": meta.get("doc_name", ""),
                    "source_path": meta.get("source_path", ""),
                    "file_type": meta.get("file_type", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "total_chunks": meta.get("total_chunks", 1),
                    "score": round(1.0 - float(dist), 4),
                    "distance": round(float(dist), 4),
                    "collection": coll_name,
                }
                for doc, meta, dist in zip(
                    raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
                )
            ]
            results.extend(self._normalize_scores(coll_hits))

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_code(
        self, query: str, top_k: int = DEFAULT_TOP_K, use_bm25: bool = True
    ) -> list[dict]:
        """Search kb_code using vector search, optionally hybrid with BM25+RRF."""
        self._ensure_initialized()
        top_k = max(1, min(top_k, MAX_TOP_K))
        fetch_k = BM25_TOP_K if (use_bm25 and _BM25_AVAILABLE) else top_k
        n = min(fetch_k, self._code_collection.count())
        if n == 0:
            return []

        emb = self._embed([query], self._code_model)[0]
        raw = self._code_collection.query(
            query_embeddings=[emb],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        vector_hits = [
            {
                "content": doc,
                "doc_name": meta.get("doc_name", ""),
                "source_path": meta.get("source_path", ""),
                "file_type": meta.get("file_type", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "total_chunks": meta.get("total_chunks", 1),
                "score": round(1.0 - float(dist), 4),
                "collection": CODE_COLLECTION_NAME,
            }
            for doc, meta, dist in zip(
                raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
            )
        ]

        if not (use_bm25 and _BM25_AVAILABLE):
            return vector_hits[:top_k]

        if self._bm25_index is None:
            self._bm25_index = BM25Index(self._code_collection)

        bm25_hits = self._bm25_index.search(query, top_k=BM25_TOP_K)
        return self._rrf_merge(vector_hits, bm25_hits, top_k=top_k)

    def search_docs(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        """Search only the text collection (kb_text) using the text model."""
        self._ensure_initialized()
        top_k = max(1, min(top_k, MAX_TOP_K))
        n = min(top_k, self._text_collection.count())
        if n == 0:
            return []
        emb = self._embed([query], self._text_model)[0]
        raw = self._text_collection.query(
            query_embeddings=[emb],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {
                "content": doc,
                "doc_name": meta.get("doc_name", ""),
                "source_path": meta.get("source_path", ""),
                "file_type": meta.get("file_type", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "total_chunks": meta.get("total_chunks", 1),
                "score": round(1.0 - float(dist), 4),
                "collection": TEXT_COLLECTION_NAME,
            }
            for doc, meta, dist in zip(
                raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
            )
        ]

    def list_documents(self) -> list[dict]:
        """List unique documents across both collections."""
        self._ensure_initialized()
        seen: dict[str, dict] = {}

        for collection, coll_name in [
            (self._text_collection, TEXT_COLLECTION_NAME),
            (self._code_collection, CODE_COLLECTION_NAME),
        ]:
            if collection.count() == 0:
                continue
            result = collection.get(include=["metadatas"])
            for meta in result["metadatas"]:
                name = meta.get("doc_name", "")
                if name not in seen:
                    seen[name] = {
                        "doc_name": name,
                        "source_path": meta.get("source_path", ""),
                        "file_type": meta.get("file_type", ""),
                        "chunk_count": 1,
                        "collection": coll_name,
                    }
                else:
                    seen[name]["chunk_count"] += 1

        return sorted(seen.values(), key=lambda d: d["doc_name"])

    def delete_document(self, doc_name: str) -> dict:
        """Delete all chunks for doc_name from both collections."""
        self._ensure_initialized()

        total_deleted = 0
        for collection in (self._text_collection, self._code_collection):
            existing = collection.get(
                where={"doc_name": {"$eq": doc_name}}, include=[]
            )
            count = len(existing["ids"])
            if count:
                collection.delete(ids=existing["ids"])
                total_deleted += count

        if total_deleted == 0:
            return {
                "status": "not_found",
                "doc_name": doc_name,
                "chunks_deleted": 0,
                "message": f"Document '{doc_name}' not found in knowledge base.",
            }

        logger.info("Deleted '%s' (%d chunks).", doc_name, total_deleted)
        return {
            "status": "success",
            "doc_name": doc_name,
            "chunks_deleted": total_deleted,
            "message": f"Deleted {total_deleted} chunks for '{doc_name}'.",
        }

    def get_file(self, doc_name: str) -> list[dict]:
        """
        Return all chunks of a file in order.
        Searches both collections; supports partial/substring name matching.
        """
        self._ensure_initialized()

        for collection in (self._code_collection, self._text_collection):
            result = collection.get(
                where={"doc_name": {"$eq": doc_name}},
                include=["documents", "metadatas"],
            )
            if result["ids"]:
                return self._sort_chunks(result)

        # Substring fallback across both collections
        for collection in (self._code_collection, self._text_collection):
            all_docs = collection.get(include=["metadatas"])
            candidates = {
                m["doc_name"]
                for m in all_docs["metadatas"]
                if doc_name.lower() in m.get("doc_name", "").lower()
            }
            if candidates:
                matched = sorted(candidates)[0]
                result = collection.get(
                    where={"doc_name": {"$eq": matched}},
                    include=["documents", "metadatas"],
                )
                return self._sort_chunks(result)

        return []

    def _sort_chunks(self, result: dict) -> list[dict]:
        pairs = sorted(
            zip(result["documents"], result["metadatas"]),
            key=lambda x: x[1].get("chunk_index", 0),
        )
        return [
            {
                "chunk_index": m.get("chunk_index", 0),
                "total_chunks": m.get("total_chunks", 1),
                "content": doc,
                "doc_name": m.get("doc_name", ""),
                "source_path": m.get("source_path", ""),
                "file_type": m.get("file_type", ""),
            }
            for doc, m in pairs
        ]

    def search_symbol(
        self, symbol: str, file_type: str | None = None, top_k: int = 10
    ) -> list[dict]:
        """
        Exact keyword search inside indexed code (substring match).
        Searches kb_code by default; falls back to kb_text if no results.
        """
        self._ensure_initialized()

        where_doc = {"$contains": symbol}
        where_meta = {"file_type": {"$eq": file_type}} if file_type else None

        hits: list[dict] = []
        collections = [
            (self._code_collection, CODE_COLLECTION_NAME),
            (self._text_collection, TEXT_COLLECTION_NAME),
        ]

        for collection, coll_name in collections:
            kwargs: dict = {
                "where_document": where_doc,
                "include": ["documents", "metadatas"],
            }
            if where_meta:
                kwargs["where"] = where_meta
            try:
                result = collection.get(**kwargs)
            except Exception:
                result = collection.get(
                    where_document=where_doc, include=["documents", "metadatas"]
                )
            for doc, meta in zip(result["documents"], result["metadatas"]):
                hits.append({
                    "doc_name": meta.get("doc_name", ""),
                    "source_path": meta.get("source_path", ""),
                    "file_type": meta.get("file_type", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "content": doc,
                    "collection": coll_name,
                })

        hits.sort(key=lambda x: (x["doc_name"], x["chunk_index"]))
        return hits[:top_k]

    def list_code_files(self, file_type: str | None = None) -> list[dict]:
        """List indexed files from kb_code, optionally filtered by file_type."""
        self._ensure_initialized()

        if self._code_collection.count() == 0:
            return []

        result = self._code_collection.get(include=["metadatas"])
        seen: dict[str, dict] = {}
        for meta in result["metadatas"]:
            name = meta.get("doc_name", "")
            ft = meta.get("file_type", "")
            if file_type and ft != file_type.lower().lstrip("."):
                continue
            if name not in seen:
                seen[name] = {
                    "doc_name": name,
                    "source_path": meta.get("source_path", ""),
                    "file_type": ft,
                    "chunk_count": 1,
                }
            else:
                seen[name]["chunk_count"] += 1

        return sorted(seen.values(), key=lambda d: d["doc_name"])

    def get_chunk_context(
        self, doc_name: str, chunk_index: int, window: int = 2
    ) -> list[dict]:
        """Return chunks surrounding chunk_index (±window) from the same file."""
        self._ensure_initialized()

        lo = max(0, chunk_index - window)
        hi = chunk_index + window

        for collection in (self._code_collection, self._text_collection):
            result = collection.get(
                where={
                    "$and": [
                        {"doc_name": {"$eq": doc_name}},
                        {"chunk_index": {"$gte": lo}},
                        {"chunk_index": {"$lte": hi}},
                    ]
                },
                include=["documents", "metadatas"],
            )
            if result["ids"]:
                chunks = sorted(
                    zip(result["documents"], result["metadatas"]),
                    key=lambda x: x[1].get("chunk_index", 0),
                )
                return [
                    {
                        "chunk_index": m.get("chunk_index", 0),
                        "total_chunks": m.get("total_chunks", 1),
                        "content": doc,
                        "doc_name": m.get("doc_name", ""),
                        "is_target": m.get("chunk_index", 0) == chunk_index,
                    }
                    for doc, m in chunks
                ]

        return []

    def grep_code(
        self,
        pattern: str,
        directory: str | None = None,
        file_glob: str = "*.c,*.h,*.cpp,*.py,*.js,*.ts,*.go,*.rs,*.sh",
        max_results: int = 50,
        ignore_case: bool = False,
    ) -> dict:
        """Regex search on disk files (not indexed content)."""
        import re

        root = Path(directory) if directory else KNOWLEDGE_BASE_DIR
        if not root.exists():
            return {"error": f"Directory not found: {root}", "matches": []}

        globs = [g.strip() for g in file_glob.split(",") if g.strip()]
        files: list[Path] = []
        for g in globs:
            files.extend(root.rglob(g))
        files = sorted(set(files))

        flags = re.IGNORECASE if ignore_case else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            return {"error": f"Invalid regex: {e}", "matches": []}

        matches = []
        for fpath in files:
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for lineno, line in enumerate(lines, 1):
                if rx.search(line):
                    matches.append({
                        "file": str(fpath.relative_to(root)),
                        "line": lineno,
                        "text": line.rstrip(),
                    })
                    if len(matches) >= max_results:
                        return {
                            "pattern": pattern,
                            "matches": matches,
                            "truncated": True,
                            "total_shown": len(matches),
                        }

        return {
            "pattern": pattern,
            "matches": matches,
            "truncated": False,
            "total_shown": len(matches),
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _delete_by_doc_name(self, doc_name: str) -> None:
        """Delete all entries for doc_name from both collections."""
        for collection in (self._text_collection, self._code_collection):
            existing = collection.get(
                where={"doc_name": {"$eq": doc_name}}, include=[]
            )
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
