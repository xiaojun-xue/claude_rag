"""
Shared MCP tool definitions and dispatch logic.
Both server.py (stdio) and server_http.py (SSE) import from here.
"""

from __future__ import annotations

from mcp import types

from config import DEFAULT_TOP_K

# ── Tool definitions ───────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    # ── Document tools ─────────────────────────────────────────────────────
    types.Tool(
        name="ingest_document",
        description=(
            "Parse and index a single file (PDF, TXT, MD, DOCX, C, H, PY, …) "
            "into the local knowledge base. Re-ingesting is safe and idempotent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file (on the server machine).",
                }
            },
            "required": ["file_path"],
        },
    ),
    types.Tool(
        name="ingest_directory",
        description=(
            "Recursively index all supported files found in a directory "
            "(PDF, TXT, MD, DOCX, C/C++, Python, JS, Go, Rust, …)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "Absolute path to the directory on the server machine.",
                }
            },
            "required": ["dir_path"],
        },
    ),
    types.Tool(
        name="search_knowledge_base",
        description=(
            "Semantic (vector) search over all indexed content. "
            "Best for natural-language queries about concepts, APIs, or behavior. "
            "Supports both Chinese and English."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="list_documents",
        description="List all documents indexed in the knowledge base.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="delete_document",
        description="Remove a document and all its chunks from the knowledge base.",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_name": {
                    "type": "string",
                    "description": "doc_name as returned by list_documents.",
                }
            },
            "required": ["doc_name"],
        },
    ),
    types.Tool(
        name="grep_code",
        description=(
            "Search source files on disk by exact keyword or regex pattern. "
            "Unlike semantic search, this guarantees finding every occurrence of a "
            "function name, macro, struct, or any string in the source code. "
            "Use this when semantic search misses results or you need exact matches. "
            "Returns matching lines with file path and line number."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Keyword or regex pattern to search for (e.g. 'ss_mpi_ao_', 'ot_aio_attr_t').",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in. Defaults to knowledge_base/src.",
                },
                "file_glob": {
                    "type": "string",
                    "description": "File pattern filter, e.g. '*.c', '*.h', '*.c,*.h'. Default: all supported code files.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum lines to return (default 50).",
                    "default": 50,
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default false).",
                    "default": False,
                },
            },
            "required": ["pattern"],
        },
    ),
    # ── Code-specific tools ────────────────────────────────────────────────
    types.Tool(
        name="get_file",
        description=(
            "Retrieve the full indexed content of a specific source file by name. "
            "Returns all chunks in order. Use this when you know which file you need "
            "(e.g. 'sample_comm_vi.c', 'sample_comm_isp'). "
            "Supports partial/substring name matching."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doc_name": {
                    "type": "string",
                    "description": (
                        "File name or doc_name (with or without extension, "
                        "with or without subdirectory path). "
                        "Examples: 'sample_comm_vi', 'common/sample_comm_vi.c'"
                    ),
                }
            },
            "required": ["doc_name"],
        },
    ),
    types.Tool(
        name="search_symbol",
        description=(
            "Exact keyword search inside indexed code. "
            "Use this to find a specific function name, struct, macro, or API call. "
            "Unlike semantic search, this does exact substring matching. "
            "Example: search_symbol('HI_MPI_ISP_Init') finds every chunk that "
            "contains that exact string."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Exact function name, struct name, macro, or keyword to find.",
                },
                "file_type": {
                    "type": "string",
                    "description": "Optional: filter by file extension, e.g. 'c', 'h', 'py'.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max results to return (default 10).",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="list_code_files",
        description=(
            "List indexed source code files, optionally filtered by file type. "
            "Useful to discover what code is available before searching. "
            "If no file_type given, returns all non-document files (code/config)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_type": {
                    "type": "string",
                    "description": "Optional file extension filter, e.g. 'c', 'h', 'py', 'ini'.",
                }
            },
        },
    ),
    types.Tool(
        name="search_code",
        description=(
            "Semantic search restricted to the code collection (kb_code) using a "
            "code-specialized embedding model (jina-embeddings-v2-base-code). "
            "Use this when you want to find C/C++/Python/Go/Rust/Shell code by "
            "describing what it does — e.g. 'initialize ISP pipeline', "
            "'open audio output device', 'encode H264 frame'. "
            "More accurate than search_knowledge_base for code queries."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What the code should do (English or Chinese)."},
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 20).",
                    "default": 5, "minimum": 1, "maximum": 20,
                },
                "use_bm25": {
                    "type": "boolean",
                    "description": "Enable BM25 hybrid search with RRF merging (default true). Set false for pure vector search.",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="search_docs",
        description=(
            "Semantic search restricted to the document collection (kb_text) using a "
            "bilingual text embedding model (bge-small-zh-v1.5). "
            "Use this when you want to find information in PDF manuals, "
            "DOCX guides, TXT readmes, or INI config documentation — "
            "e.g. 'ISP pipeline 初始化流程', 'AWB calibration steps', "
            "'sensor 配置参数说明'. Does NOT search source code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in documents."},
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 20).",
                    "default": 5, "minimum": 1, "maximum": 20,
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_chunk_context",
        description=(
            "Expand context around a specific chunk. Given a doc_name and chunk_index "
            "(from search results), returns the surrounding chunks (±window) from "
            "the same file. Use this when a search result is truncated and you need "
            "to see more of the surrounding code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doc_name": {
                    "type": "string",
                    "description": "doc_name from the search result.",
                },
                "chunk_index": {
                    "type": "integer",
                    "description": "chunk_index from the search result.",
                },
                "window": {
                    "type": "integer",
                    "description": "Number of chunks before and after to include (default 2).",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["doc_name", "chunk_index"],
        },
    ),
]


# ── Dispatch ───────────────────────────────────────────────────────────────

async def dispatch(name: str, args: dict, engine) -> object:
    if name == "ingest_document":
        return engine.ingest_document(args["file_path"])

    if name == "ingest_directory":
        return engine.ingest_directory(args["dir_path"])

    if name == "search_knowledge_base":
        top_k = int(args.get("top_k", DEFAULT_TOP_K))
        return engine.search(args["query"], top_k=top_k)

    if name == "list_documents":
        return engine.list_documents()

    if name == "delete_document":
        return engine.delete_document(args["doc_name"])

    if name == "get_file":
        return engine.get_file(args["doc_name"])

    if name == "search_symbol":
        return engine.search_symbol(
            args["symbol"],
            file_type=args.get("file_type"),
            top_k=int(args.get("top_k", 10)),
        )

    if name == "list_code_files":
        return engine.list_code_files(file_type=args.get("file_type"))

    if name == "get_chunk_context":
        return engine.get_chunk_context(
            args["doc_name"],
            int(args["chunk_index"]),
            window=int(args.get("window", 2)),
        )

    if name == "grep_code":
        return engine.grep_code(
            pattern=args["pattern"],
            directory=args.get("directory"),
            file_glob=args.get("file_glob", "*.c,*.h,*.cpp,*.py,*.js,*.ts,*.go,*.rs,*.sh"),
            max_results=int(args.get("max_results", 50)),
            ignore_case=bool(args.get("ignore_case", False)),
        )

    if name == "search_code":
        top_k = int(args.get("top_k", DEFAULT_TOP_K))
        use_bm25 = bool(args.get("use_bm25", True))
        return engine.search_code(args["query"], top_k=top_k, use_bm25=use_bm25)

    if name == "search_docs":
        top_k = int(args.get("top_k", DEFAULT_TOP_K))
        return engine.search_docs(args["query"], top_k=top_k)

    return {"error": f"Unknown tool: '{name}'"}
