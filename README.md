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
  src/core/document_loader.py   # PDF (pdfplumber), DOCX, TXT, MD, code files
        │
        ▼
  src/core/chunker.py           # Language-aware splitting
        │
   ┌────┴────┐
   ▼         ▼
kb_text    kb_code              # ChromaDB collections (cosine, HNSW)
   │         │
bge-base  st-codesearch         # Local embedding models (768-dim each)
   │         │
   └────┬────┘
        ▼
  src/core/rag_engine.py        # Search, BM25+RRF, normalization
        │
  src/server/tools.py           # MCP tool definitions + dispatch
        │
   ┌────┴────┐
   ▼         ▼
stdio.py   serve.py             # stdio / HTTP SSE transports
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

# 3. Install remaining Python dependencies
pip install -r requirements.txt

# 4. Build the Web UI (requires Node.js ≥ 18)
cd webui
npm install
npm run build
cd ..

# 5. Optional: BM25 hybrid search and better PDF parsing
pip install rank-bm25 pdfplumber
```

### Web UI (re)build

The Web UI is pre-built and committed in `src/server/static/`. If you modify the frontend source under `webui/`, rebuild with:

```bash
cd webui
npm install        # skip if already done
npm run build      # outputs to ../src/server/static/
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
python src/scripts/reingest_fast.py knowledge_base/
```

### 3. Start the server

**stdio** (for Claude Desktop on the same machine):
```bash
python src/server/stdio.py
```

**HTTP SSE** (for LAN access):
```bash
python src/server/serve.py              # listens on 0.0.0.0:8765
python src/server/serve.py --port 9000  # custom port
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
claude_rag/
│
├── src/                                  # 全部业务源码
│   ├── core/                             # 核心引擎（无 MCP 依赖，可独立测试）
│   │   ├── config.py                     # 全局常量：路径、模型名、chunk 参数、集合名
│   │   ├── document_loader.py            # 文件解析：PDF(pdfplumber)、DOCX、TXT、MD、代码文件
│   │   ├── chunker.py                    # 语言感知切片：C/C++ 花括号状态机、Python AST、
│   │   │                                 #   Markdown 标题、INI 节、滑窗
│   │   ├── bm25_engine.py                # BM25 关键词索引，对 kb_code 全量构建，
│   │   │                                 #   与向量检索 RRF 融合
│   │   └── rag_engine.py                 # 主引擎：文件入库、向量化、双集合检索、
│   │                                     #   BM25+RRF、分数归一化
│   │
│   ├── server/                           # MCP 服务器层（依赖 core，对外暴露工具）
│   │   ├── tools.py                      # 12 个 MCP 工具的 schema 定义 + dispatch 路由
│   │   ├── stdio.py                      # stdio 传输入口，供 Claude Desktop 本机启动
│   │   └── serve.py                      # HTTP SSE 传输入口，供局域网远程访问
│   │                                     #   （默认 0.0.0.0:8765）
│   │
│   └── scripts/                          # 运维脚本（手动执行，不参与服务启动）
│       ├── reingest_fast.py              # 全量重建索引，单进程加载模型后批量处理所有文件
│       ├── cleanup_collections.py        # 删除 ChromaDB 集合（重建前清空用）
│       ├── cleanup_deleted.py            # 扫描 source_path 已失效的 chunk 并删除
│       └── setup_rag.py                  # 首次安装引导：检查依赖、创建目录、预下载模型
│
├── tests/                                # pytest 测试套件
│   ├── test_chunker.py                   # chunker 单元测试（纯 Python，无外部依赖）
│   ├── test_document_loader.py           # document_loader 单元测试（含 PDF/DOCX 解析）
│   ├── test_rag_engine.py                # rag_engine 单元测试（mock embed，隔离模型）
│   └── test_integration.py              # 集成测试（真实 ChromaDB，tmp_path 隔离）
│
├── knowledge_base/                       # 知识库素材目录（gitignore，不入库）
├── vector_store/                         # ChromaDB 持久化数据（gitignore，不入库）
├── models_cache/                         # 本地模型缓存（gitignore，不入库）
│
├── .mcp.json.example                     # stdio 客户端配置模板
├── .mcp.remote.json.example              # SSE 客户端配置模板
├── requirements.txt                      # Python 依赖
└── README.md                             # 项目文档
```

### Common Commands

| Operation | Command |
|-----------|---------|
| Start LAN server | `python src/server/serve.py` |
| Start local server | `python src/server/stdio.py` |
| Re-index knowledge base | `python src/scripts/reingest_fast.py knowledge_base/` |
| Clear collections | `python src/scripts/cleanup_collections.py` |
| Remove stale index entries | `python src/scripts/cleanup_deleted.py --delete` |
| Run tests | `python -m pytest tests/ -v` |

---

## Requirements

- Python 3.10+
- ~800 MB disk for embedding models (downloaded on first run)
- RAM: ~2 GB with both models loaded

---

## License

MIT
