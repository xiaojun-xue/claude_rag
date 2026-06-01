"""
Central configuration for the local RAG knowledge base.
All modules import from here; nothing hardcodes paths or model names elsewhere.

Priority for every setting: env var  >  claude_rag.toml  >  built-in default
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.parent.resolve()  # project root
VECTOR_STORE_DIR = BASE_DIR / "vector_store"
MODELS_CACHE_DIR = BASE_DIR / "models_cache"
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"

# ── TOML config loader ─────────────────────────────────────────────────────

def _load_toml() -> dict:
    try:
        import tomllib          # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return {}
    path = BASE_DIR / "claude_rag.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)

_TOML = _load_toml()


def _get(env_var: str, section: str, key: str, default: str) -> str:
    v = os.getenv(env_var)
    if v is not None:
        return v
    return str(_TOML.get(section, {}).get(key, default))


def _get_int(env_var: str, section: str, key: str, default: int) -> int:
    v = os.getenv(env_var)
    if v is not None:
        return int(v)
    return int(_TOML.get(section, {}).get(key, default))


def _get_bool(env_var: str, section: str, key: str, default: bool) -> bool:
    v = os.getenv(env_var)
    if v is not None:
        return v.lower() == "true"
    return bool(_TOML.get(section, {}).get(key, default))


# ── Embedding models ───────────────────────────────────────────────────────
# Text model: bilingual CN+EN, ~400 MB, 768-dim
EMBEDDING_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
# Code model: trained on CodeSearchNet, 768-dim, ~330MB, works with transformers 5.x
CODE_EMBEDDING_MODEL_NAME = "flax-sentence-embeddings/st-codesearch-distilroberta-base"

# Device: "auto" (default) | "cpu" | "cuda" | "cuda:0" | …
# No env-var override — only server admin can change via claude_rag.toml.
EMBEDDING_DEVICE = str(_TOML.get("embedding", {}).get("device", "auto"))

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

# ── HTTP server ────────────────────────────────────────────────────────────
SERVER_HOST = _get    ("SERVER_HOST", "server", "host", "0.0.0.0")
SERVER_PORT = _get_int("SERVER_PORT", "server", "port", 8765)

# ── LLM Synthesis ──────────────────────────────────────────────────────────
# SYNTHESIS_BACKEND: deepseek | qianwen | ollama | claude | openai | custom
# No env-var override — only server admin can change via claude_rag.toml.
SYNTHESIS_BACKEND = str(_TOML.get("llm", {}).get("backend", ""))
LLM_API_KEY       = str(_TOML.get("llm", {}).get("api_key", ""))
LLM_BASE_URL      = str(_TOML.get("llm", {}).get("base_url", ""))
LLM_MODEL         = _get    ("LLM_MODEL",          "llm", "model",      "")
LLM_MAX_TOKENS    = _get_int("LLM_MAX_TOKENS",     "llm", "max_tokens", 1024)

# ── Reranking ──────────────────────────────────────────────────────────────
USE_RERANKING  = _get_bool("USE_RERANKING",  "reranking", "enabled", True)
RERANKER_MODEL = _get     ("RERANKER_MODEL", "reranking", "model",
                            "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
RERANK_FETCH_K = _get_int ("RERANK_FETCH_K", "reranking", "fetch_k", 20)
RERANK_FINAL_K = _get_int ("RERANK_FINAL_K", "reranking", "final_k", 5)

# ── HuggingFace cache (set early so imports pick it up) ───────────────────
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODELS_CACHE_DIR))
os.environ.setdefault("HF_HOME", str(MODELS_CACHE_DIR))
# Default to offline mode — model validation/download must not block startup.
# Set HF_HUB_OFFLINE=0 in the environment to allow network access for first-time download.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
