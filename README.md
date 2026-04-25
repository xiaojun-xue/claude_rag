# Local RAG Knowledge Base — MCP Server

A local retrieval-augmented generation (RAG) knowledge base exposed as an **MCP (Model Context Protocol) server**. Supports both stdio and HTTP SSE transports, enabling Claude Desktop and other MCP clients to search PDF manuals, DOCX guides, and source code (C/C++, Python, JS, Go, Rust, etc.) stored on your local machine — **no API key required, all models run locally**.

---

## Features

- **Dual-collection architecture** — documents (`kb_text`) and source code (`kb_code`) use separate embedding models optimized for each domain
- **12 MCP tools** — ingest, search, list, delete, grep, and context-expand operations
- **Hybrid search for code** — vector search + BM25 with Reciprocal Rank Fusion (RRF)
- **Language-aware chunking** — C/C++ (brace state machine), Python (AST), Markdown (headings), INI (sections), header files (struct/enum/macro extraction)
- **Function name injection** — C/C++ chunks carry `/* File: foo.c | Func: bar */` prefix for better retrieval
- **Bilingual** — Chinese + English queries supported
- **HTTP SSE transport** — serve over LAN so multiple machines can share one knowledge base

---

## Architecture

```
Documents / Source Code
        │
        ▼
  document_loader.py          # PDF (pdfplumber), DOCX, TXT, MD, code files
        │
        ▼
    chunker.py                # Language-aware splitting
        │
   ┌────┴────┐
   ▼         ▼
kb_text    kb_code            # ChromaDB collections (cosine, HNSW)
   │         │
bge-base  st-codesearch       # Local embedding models (768-dim each)
   │         │
   └────┬────┘
        ▼
  rag_engine.py               # Search, BM25+RRF, normalization
        │
  server_tools.py             # MCP tool definitions + dispatch
        │
   ┌────┴────┐
   ▼         ▼
server.py  server_http.py     # stdio / HTTP SSE transports
```

---

## Embedding Models

| Collection | Model | Dim | Size | Domain |
|-----------|-------|-----|------|--------|
| `kb_text` | `BAAI/bge-base-zh-v1.5` | 768 | ~400 MB | CN+EN documents |
| `kb_code` | `flax-sentence-embeddings/st-codesearch-distilroberta-base` | 768 | ~330 MB | Source code (6 languages) |

Models are downloaded automatically on first run and cached in `models_cache/`.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `ingest_document` | Index a single file (PDF, TXT, MD, DOCX, C, H, PY, …) |
| `ingest_directory` | Recursively index all supported files in a directory |
| `search_knowledge_base` | Semantic search across both collections |
| `search_code` | Hybrid vector + BM25 search in code collection |
| `search_docs` | Semantic search in document collection only |
| `search_symbol` | Exact substring match for function names / macros |
| `grep_code` | Regex search on raw disk files (guaranteed recall) |
| `get_file` | Retrieve all chunks of a file in order |
| `get_chunk_context` | Expand ±N chunks around a search result |
| `list_documents` | List all indexed documents |
| `list_code_files` | List indexed source files, filterable by extension |
| `delete_document` | Remove a document and all its chunks |

---

## Installation

```bash
# 1. Clone
git clone https://github.com/<your-username>/<repo>.git
cd <repo>

# 2. Install CPU-only PyTorch first (avoids downloading 2 GB CUDA build)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3. Install remaining dependencies
pip install -r requirements.txt

# 4. Optional: BM25 hybrid search and better PDF parsing
pip install rank-bm25 pdfplumber
```

---

## Quick Start

### 1. Add your files

Place documents and source code under `knowledge_base/`:

```
knowledge_base/
├── manual.pdf
├── guide.docx
└── src/
    ├── main.c
    └── utils.h
```

### 2. Index everything

```bash
python reingest_fast.py knowledge_base/
```

### 3. Start the server

**stdio** (for Claude Desktop on the same machine):
```bash
python server.py
```

**HTTP SSE** (for LAN access):
```bash
python server_http.py              # listens on 0.0.0.0:8765
python server_http.py --port 9000  # custom port
```

Graceful shutdown (prevents HNSW index corruption):
```bash
curl -X POST http://localhost:8765/shutdown
```

---

## Claude Desktop / MCP Client Configuration

Copy the example and fill in your paths:

**stdio (local)**:
```bash
cp .mcp.json.example .mcp.json
# edit .mcp.json — set your Python path and project directory
```

**HTTP SSE (remote)**:
```bash
cp .mcp.remote.json.example .mcp.remote.json
# edit .mcp.remote.json — set the server IP
```

---

## Chunking Strategy

| File Type | Strategy | Chunk Prefix |
|-----------|----------|-------------|
| PDF / DOCX / TXT | Paragraph + sentence-boundary sliding window | — |
| Markdown | Split on `#`/`##`/`###` headings | `# File: x.md \| ## Section` |
| INI / CFG | Split on `[section]` boundaries | `# File: x.ini \| [section]` |
| `.h` / `.hpp` | Extract struct/enum/macros/declarations | `// File: x.h \| typedef struct Foo` |
| `.c` / `.cpp` | Brace-depth state machine + comment lookback | `/* File: x.c \| Func: bar */` |
| Python | AST top-level `def`/`class` extraction | `# File: x.py \| def foo (L10-25)` |
| Other code | Blank-line separated logical blocks | `# File: x.sh` |

---

## Retrieval Strategy

```
Known symbol name     →  search_symbol  (exact $contains, fastest)
Code semantic query   →  search_code    (vector + BM25 RRF)
Document query        →  search_docs    (bge-base vector)
Mixed / unsure        →  search_knowledge_base  (cross-collection, normalized)
Result truncated      →  get_chunk_context  (expand ±window)
Vector missed it      →  grep_code      (disk regex, guaranteed recall)
```

---

## Project Structure

```
├── config.py              # All constants: paths, models, chunk sizes
├── document_loader.py     # PDF/DOCX/TXT/MD/code loaders
├── chunker.py             # Language-aware chunking
├── bm25_engine.py         # BM25 index + tokenizer for code
├── rag_engine.py          # Core: ingest, search, BM25+RRF, normalization
├── server_tools.py        # MCP tool definitions and dispatch
├── server.py              # stdio MCP transport
├── server_http.py         # HTTP SSE MCP transport
├── reingest_fast.py       # Fast single-process re-indexer
├── setup_rag.py           # First-time setup helper
├── tests/                 # pytest test suite
├── .mcp.json.example      # stdio config template
└── .mcp.remote.json.example  # SSE config template
```

---

## Requirements

- Python 3.10+
- ~800 MB disk for embedding models (downloaded on first run)
- RAM: ~2 GB with both models loaded

---

## License

MIT
