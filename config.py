"""
Central configuration for the local RAG knowledge base.
All modules import from here; nothing hardcodes paths or model names elsewhere.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
VECTOR_STORE_DIR = BASE_DIR / "vector_store"
MODELS_CACHE_DIR = BASE_DIR / "models_cache"
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"

# ── Embedding models ───────────────────────────────────────────────────────
# Text model: bilingual CN+EN, ~400 MB, 768-dim
EMBEDDING_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
# Code model: trained on CodeSearchNet, 768-dim, ~330MB, works with transformers 5.x
# jina-embeddings-v2-base-code requires transformers 4.x (incompatible with 5.x)
CODE_EMBEDDING_MODEL_NAME = "flax-sentence-embeddings/st-codesearch-distilroberta-base"

# ── ChromaDB collections ───────────────────────────────────────────────────
COLLECTION_NAME = "knowledge_base"   # legacy (kept for reference)
TEXT_COLLECTION_NAME = "kb_text"     # PDF/DOCX/TXT/MD/INI/YAML/JSON
CODE_COLLECTION_NAME = "kb_code"     # C/C++/Python/JS/Go/Rust/Shell

# ── Chunking ───────────────────────────────────────────────────────────────
CHUNK_SIZE = 512        # characters — text documents
CHUNK_OVERLAP = 64      # character overlap between adjacent chunks
MIN_CHUNK_LENGTH = 30   # discard chunks shorter than this
CODE_CHUNK_SIZE = 1500  # larger chunks for code (functions can be long)

# ── Search ─────────────────────────────────────────────────────────────────
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
BM25_TOP_K = 20   # candidate pool for BM25 before RRF merging

# ── File type routing (without leading dot) ────────────────────────────────
TEXT_FILE_TYPES = {
    "pdf", "txt", "docx",
    "md",
    "yaml", "yml", "json", "toml",
    "ini", "cfg",
    "html", "css",
}

CODE_FILE_TYPES = {
    "c", "h", "cpp", "cc", "cxx", "hpp", "hh",
    "py", "pyw",
    "js", "ts", "jsx", "tsx",
    "java", "kt", "go", "rs",
    "sh", "bat", "ps1",
    "cmake", "mk", "makefile",
}

# ── File support ───────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    # Documents
    ".pdf", ".txt", ".md", ".docx",
    # C / C++
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    # Python
    ".py", ".pyw",
    # Web / Script
    ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    # Java / Kotlin / Go / Rust
    ".java", ".kt", ".go", ".rs",
    # Shell / Config
    ".sh", ".bat", ".ps1", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    # Other
    ".cmake", ".mk", ".makefile",
}

# Code files that need special chunking (split on function/class boundaries)
CODE_EXTENSIONS = {
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".go", ".rs", ".sh", ".bat", ".ps1",
}

# ── MCP server identity ────────────────────────────────────────────────────
SERVER_NAME = "local-rag-kb"
SERVER_VERSION = "2.0.0"

# ── HuggingFace cache (set early so imports pick it up) ───────────────────
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODELS_CACHE_DIR))
os.environ.setdefault("HF_HOME", str(MODELS_CACHE_DIR))
