"""
One-time bootstrap script for the local RAG knowledge base.

Run this once after installing dependencies:
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install -r requirements.txt
    python setup_rag.py
"""

import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
from pathlib import Path


def main() -> None:
    print("=" * 60)
    print("  Local RAG Knowledge Base — Setup")
    print("=" * 60)

    # ── Import config (sets HF cache env vars as a side-effect) ───────────
    from config import (
        COLLECTION_NAME,
        EMBEDDING_MODEL_NAME,
        KNOWLEDGE_BASE_DIR,
        MODELS_CACHE_DIR,
        VECTOR_STORE_DIR,
    )

    # ── 1. Create directories ──────────────────────────────────────────────
    for d in [VECTOR_STORE_DIR, MODELS_CACHE_DIR, KNOWLEDGE_BASE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory ready: {d}")

    # ── 2. Download / verify embedding model ──────────────────────────────
    print(f"\n[..] Loading embedding model: {EMBEDDING_MODEL_NAME}")
    print("     (First run downloads ~130 MB — may take a few minutes)")
    try:
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(MODELS_CACHE_DIR)
        os.environ["HF_HOME"] = str(MODELS_CACHE_DIR)

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        test_vector = model.encode(["测试 test"], normalize_embeddings=True)
        dim = len(test_vector[0])
        print(f"[OK] Model loaded. Embedding dimension: {dim}")
        del model
    except Exception as exc:
        print(f"[ERROR] Failed to load embedding model: {exc}")
        print("        Check your internet connection or set HTTPS_PROXY.")
        sys.exit(1)

    # ── 3. Initialize ChromaDB collection ─────────────────────────────────
    print(f"\n[..] Initializing ChromaDB collection: {COLLECTION_NAME}")
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[OK] Collection ready. Current document chunks: {collection.count()}")
    except Exception as exc:
        print(f"[ERROR] Failed to initialize ChromaDB: {exc}")
        sys.exit(1)

    # ── 4. Done ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print(f"  1. Place your documents (PDF/TXT/MD/DOCX) in:")
    print(f"     {KNOWLEDGE_BASE_DIR}")
    print(f"  2. Open Claude Code in this directory.")
    print(f"     The MCP server 'local-rag-kb' will connect automatically.")
    print(f"  3. Ask Claude to ingest your documents:")
    print(f"     'Please ingest all documents in the knowledge_base folder.'")
    print()


if __name__ == "__main__":
    main()
