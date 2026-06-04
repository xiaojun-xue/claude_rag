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

# ── Auth (SSE / REST API 鉴权) ─────────────────────────────────────────────
# 默认关闭，向后兼容。可通过 claude_rag.toml 的 [auth] 节或环境变量覆盖。
# 启用后，受保护路径需携带 x-api-key 请求头（或 ?api_key= 查询参数）。
AUTH_ENABLED = _get_bool("AUTH_ENABLED", "auth", "enabled", False)

# 单密钥（旧字段，向后兼容）：等价于管理员密钥。也支持逗号分隔多把。
AUTH_API_KEY = _get("AUTH_API_KEY", "auth", "api_key", "")


def _split_keys(raw: str) -> list[str]:
    """把逗号分隔的密钥串解析成去重后的非空列表（保序）。"""
    out: list[str] = []
    for part in (raw or "").split(","):
        k = part.strip()
        if k and k not in out:
            out.append(k)
    return out


# 多密钥 / 分角色（每个角色都支持逗号分隔的多把 key，便于按人发放/单独吊销）：
#   • 管理员（admin）——全部权限（所有 MCP 工具含写操作、/shutdown、Web UI）。
#   • 只读（readonly）——Web UI / REST 只读端点 + 全部只读 MCP 工具
#     （语义搜索 + 精确检索/读取，共 9 个）；仅写操作（ingest_document /
#     ingest_directory / delete_document）与 /shutdown 被拒绝。
# admin 列表 = AUTH_ADMIN_API_KEY 优先，为空时回退旧的 AUTH_API_KEY。
AUTH_ADMIN_API_KEYS    = _split_keys(_get("AUTH_ADMIN_API_KEY", "auth", "admin_api_key", "")) \
                         or _split_keys(AUTH_API_KEY)
AUTH_READONLY_API_KEYS = _split_keys(_get("AUTH_READONLY_API_KEY", "auth", "readonly_api_key", ""))

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
