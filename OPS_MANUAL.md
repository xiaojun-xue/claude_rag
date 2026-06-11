# RAG 知识库运维手册

> **适用版本**: local-rag-kb v2.0.0  
> **最后更新**: 2026-06-06  
> **面向对象**: 运维人员 / 知识库管理员

---

## 目录

1. [系统概览](#1-系统概览)
2. [启停操作](#2-启停操作)
3. [客户端接入（.mcp.json 配置）](#3-客户端接入mcpjson-配置)
4. [知识库内容管理](#4-知识库内容管理)
5. [鉴权与角色权限](#5-鉴权与角色权限)
6. [健康检查与监控](#6-健康检查与监控)
7. [故障排查](#7-故障排查)
8. [附录：关键路径速查](#8-附录关键路径速查)

---

## 1. 系统概览

```
┌──────────────────────────────────────────────────┐
│                  claude_rag                        │
│                                                    │
│  knowledge_base/  ──▶  rag_engine  ──▶  vector_store/ │
│  (文档+源码)           (ChromaDB)      (持久化索引)  │
│                                                    │
│  HTTP 层:  starlette + uvicorn                     │
│  传输方式:  stdio (本机) / SSE (局域网)              │
│  鉴权:      API-Key 多角色（admin / readonly）      │
└──────────────────────────────────────────────────┘
```

### 核心组件

| 组件 | 路径 | 说明 |
|------|------|------|
| 配置文件 | `claude_rag.toml` | 总控配置（gitignored） |
| 知识库素材 | `knowledge_base/` | 原始文档与源码（gitignored） |
| 向量存储 | `vector_store/` | ChromaDB 持久化数据（gitignored） |
| 模型缓存 | `models_cache/` | 本地 Embedding 模型（gitignored） |
| HTTP 服务 | `src/server/serve.py` | SSE 传输入口 |
| stdio 服务 | `src/server/stdio.py` | 本机标准输入输出 |
| 重建索引 | `src/scripts/reingest_fast.py` | 全量重建索引脚本 |
| 清理集合 | `src/scripts/cleanup_collections.py` | 删除 ChromaDB 集合 |

### 端口与地址

| 项目 | 默认值 | 环境变量覆盖 |
|------|--------|-------------|
| 监听地址 | `0.0.0.0` | `SERVER_HOST` |
| 监听端口 | `8765` | `SERVER_PORT` 或 `--port` |

---

## 2. 启停操作

### 2.1 启动 HTTP SSE 服务（推荐）

```bash
python src/server/serve.py

# 自定义端口
python src/server/serve.py --port 9000
```

启动成功标志：
```
INFO:     Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit)
```

### 2.2 启动 stdio 服务（本机 Claude Desktop）

```bash
python src/server/stdio.py
```

stdio 模式不经过 HTTP 层，无鉴权，默认拥有 admin 权限。

### 2.3 优雅关闭

```bash
# 通过 shutdown 端点（admin 权限）
curl -X POST http://localhost:8765/shutdown \
  -H "x-api-key: <admin_key>"

# 或 Ctrl+C 在终端直接中断
```

> ⚠️ **重要**：请始终使用优雅关闭（shutdown 端点或 Ctrl+C），避免直接 kill，否则可能损坏 ChromaDB 的 HNSW 索引。

### 2.4 通过 systemd 自启（Linux）

```ini
# /etc/systemd/system/claude-rag.service
[Unit]
Description=Local RAG Knowledge Base
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/opt/claude_rag
ExecStart=/usr/bin/python3 src/server/serve.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 3. 客户端接入（.mcp.json 配置）

### 3.1 本机 stdio 模式

复制模板，填入实际路径：

```bash
cp .mcp.json.example .mcp.json
```

编辑 `.mcp.json`：

```json
{
  "mcpServers": {
    "local-rag-kb": {
      "type": "stdio",
      "command": "python",
      "args": ["D:/path/to/claude_rag/src/server/stdio.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"
      }
    }
  }
}
```

- `command` — Python 解释器路径，Windows 可用 `py` 或完整路径
- `args` — 指向 `src/server/stdio.py` 的绝对路径
- stdio 模式无需 API Key（本地信任边界）

### 3.2 局域网 SSE 模式（带鉴权）

复制模板：

```bash
cp .mcp.remote.json.example .mcp.remote.json
```

**无鉴权（仅内网可信环境）：**

```json
{
  "mcpServers": {
    "local-rag-kb": {
      "type": "sse",
      "url": "http://192.168.81.105:8765/sse"
    }
  }
}
```

**带 API-Key 鉴权（推荐）：**

```json
{
  "mcpServers": {
    "local-rag-kb": {
      "type": "sse",
      "url": "http://192.168.1.100:8765/sse",
      "headers": {
        "x-api-key": "your_readonly_or_admin_key_here"
      }
    }
  }
}
```

也可通过 URL 参数传 Key（适用于无法自定义请求头的客户端）：
```
http://192.168.1.100:8765/sse?api_key=your_key_here
```

---

## 4. 知识库内容管理

### 4.1 目录结构约定

```
knowledge_base/
├── 01.manuals/          # 按类别分目录（可选）
│   ├── manual_a.pdf
│   └── guide_b.docx
├── 02.source/
│   ├── main.c
│   └── utils.h
└── 03.notes/
    └── meeting.md
```

支持的文件类型：
- **文档**: `.pdf` `.txt` `.md` `.docx` `.html` `.css`
- **代码**: `.c` `.h` `.cpp` `.py` `.js` `.ts` `.go` `.rs` `.java` `.sh` 等
- **配置**: `.yaml` `.yml` `.json` `.toml` `.ini` `.cfg`

### 4.2 添加文件（增量索引）

**方法一：MCP 工具（推荐，在线增量）**

通过 MCP 客户端调用：
```
ingest_document   → 摄入单个文件
ingest_directory  → 摄入整个目录
```

示例（通过 curl 直接调用 API，admin 权限）：
```bash
# 添加单个文件
curl -X POST http://localhost:8765/api/ingest \
  -H "x-api-key: <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"path": "knowledge_base/new_doc.pdf"}'

# 添加整个目录
curl -X POST http://localhost:8765/api/ingest \
  -H "x-api-key: <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"path": "knowledge_base/new_project/"}'
```

**方法二：放入目录后全量重建**

```bash
# 1. 将新文件放入 knowledge_base/
cp new_doc.pdf knowledge_base/

# 2. 全量重建索引
python src/scripts/reingest_fast.py knowledge_base/

# 3. 重启服务（如已运行）
curl -X POST http://localhost:8765/shutdown -H "x-api-key: <admin_key>"
python src/server/serve.py
```

### 4.3 删除文件

**方法一：MCP 工具**
```
delete_document  → 按文件名删除文档及其所有 chunks
```

**方法二：手动清理后重建**

```bash
# 1. 从 knowledge_base/ 中删除原始文件
rm knowledge_base/old_doc.pdf

# 2. 扫描并清理失效索引
python src/scripts/cleanup_deleted.py --delete

# 3. 或者直接全量重建（更彻底）
python src/scripts/cleanup_collections.py
python src/scripts/reingest_fast.py knowledge_base/
```

### 4.4 查看已索引内容

通过 MCP 工具：
```
list_documents  → 列出所有已索引文档（文件路径、chunk 数）
list_code_files → 列出已索引代码文件，可按扩展名过滤
```

命令行快速检查：
```bash
python -c "
import chromadb
from src.core.config import VECTOR_STORE_DIR, TEXT_COLLECTION_NAME, CODE_COLLECTION_NAME
client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
for name in [TEXT_COLLECTION_NAME, CODE_COLLECTION_NAME]:
    col = client.get_collection(name)
    print(f'{name}: {col.count()} chunks')
"
```

### 4.5 重建索引流程

```bash
# 1. 关闭服务
curl -X POST http://localhost:8765/shutdown -H "x-api-key: <admin_key>"

# 2. 清理旧索引
python src/scripts/cleanup_collections.py

# 3. 重建
python src/scripts/reingest_fast.py knowledge_base/

# 4. 重启
python src/server/serve.py
```

---

## 5. 鉴权与角色权限

### 5.1 两种角色

| 角色 | 能力范围 | 适用场景 |
|------|---------|---------|
| **admin** | 全部 MCP 工具 + `/shutdown` 端点 + Web UI 完整功能 | 知识库管理员 |
| **readonly** | 仅 9 个只读 MCP 工具 + Web UI 只读 | 普通开发者/查询用户 |

### 5.2 受保护路径

| 路径 | admin | readonly | 无 Key |
|------|:-----:|:--------:|:------:|
| `/health` | ✅ | ✅ | ✅ |
| `/ui` | ✅ | ✅ | ✅ |
| `/assets/*` `/static/*` | ✅ | ✅ | ✅ |
| `/sse` | ✅ | ✅ | ❌ |
| `/messages/` | ✅ | ✅* | ❌ |
| `/api/*` | ✅ | ✅* | ❌ |
| `/shutdown` | ✅ | ❌ | ❌ |

> \* readonly 用户在 `/messages/` 和 `/api/*` 上仅能调用只读工具，写操作被拒绝。

### 5.3 MCP 工具权限明细

#### 管理员专属（3 个写操作）

| 工具 | 功能 |
|------|------|
| `ingest_document` | 摄入单个文件（PDF/TXT/MD/DOCX/代码） |
| `ingest_directory` | 递归摄入整个目录 |
| `delete_document` | 删除文档及其全部 chunks |

#### 全员可调用（9 个只读操作）

| 工具 | 功能 | 搜索方式 |
|------|------|---------|
| `search_knowledge_base` | 全库语义搜索（文档+代码） | 向量 |
| `search_code` | 仅搜索代码集合 | BM25+向量混合 (RRF) |
| `search_docs` | 仅搜索文档集合 | 向量 |
| `search_symbol` | 精确匹配函数名/宏/结构体 | 字符串 contains |
| `grep_code` | 磁盘源文件正则全文搜索 | 正则表达式 |
| `get_file` | 按文件名获取完整内容 | — |
| `get_chunk_context` | 展开某 chunk 的 ±N 上下文 | — |
| `list_documents` | 列出所有已索引文档 | — |
| `list_code_files` | 列出已索引代码文件(可按扩展名过滤) | — |

### 5.4 多密钥管理

每个角色支持逗号分隔的多把 key（便于按人发放、单独吊销）：

```toml
[auth]
enabled = true
admin_api_key    = "key_for_alice,key_for_bob"
readonly_api_key = "key_team_a,key_team_b,key_guest"
```

**密钥操作指南**：

```bash
# 生成新密钥
openssl rand -hex 32

# 吊销某把密钥：从 claude_rag.toml 中删除对应 key，重启服务
curl -X POST http://localhost:8765/shutdown -H "x-api-key: <admin_key>"
python src/server/serve.py

# 添加新密钥：在对应角色的字段后面追加，逗号分隔，重启生效
```

### 5.5 凭据传递方式

```
# 方式一：请求头（推荐）
x-api-key: <your_key>

# 方式二：URL 查询参数（兼容无法自定义请求头的客户端）
?api_key=<your_key>
```

---

## 6. 健康检查与监控

### 6.1 健康检查

```bash
curl http://localhost:8765/health
# 返回: ok
```

该端点无需认证，可用于负载均衡器或监控系统的存活检测。

### 6.2 查看已索引统计

```bash
python -c "
from src.core.rag_engine import RAGEngine
rag = RAGEngine()
text_count = rag.text_collection.count()
code_count = rag.code_collection.count()
print(f'kbb_text: {text_count} chunks')
print(f'kbb_code: {code_count} chunks')
print(f'total:     {text_count + code_count} chunks')
"
```

### 6.3 检查向量存储磁盘占用

```bash
du -sh vector_store/
```

---

## 7. 故障排查

### 7.1 服务无法启动

```bash
# 检查端口是否被占用
netstat -ano | findstr 8765

# 检查依赖是否完整
python -c "import chromadb, sentence_transformers, starlette, uvicorn; print('OK')"

# 检查配置文件语法
python -c "
try:
    import tomllib
except ImportError:
    import tomli as tomllib
with open('claude_rag.toml', 'rb') as f:
    print(tomllib.load(f))
"
```

### 7.2 模型下载失败

```bash
# 模型首次使用需要联网下载 (~800MB)，确保 HF_HUB_OFFLINE=0
export HF_HUB_OFFLINE=0

# 如果代理已配置但仍失败，直接测试
python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-base-zh-v1.5', cache_folder='./models_cache')
print('Text model OK')
m = SentenceTransformer('flax-sentence-embeddings/st-codesearch-distilroberta-base', cache_folder='./models_cache')
print('Code model OK')
"
```

### 7.3 向量存储损坏

```bash
# 症状：启动报 HNSW index 相关错误
# 解决方案：清理后重建

python src/scripts/cleanup_collections.py
python src/scripts/reingest_fast.py knowledge_base/
```

### 7.4 CUDA 不可用

如果 CUDA 报错或不支持 GPU 架构，可在 `claude_rag.toml` 中强制使用 CPU：

```toml
[embedding]
device = "cpu"
```

### 7.5 Auth 401/403 错误

```bash
# 测试 key 是否有效
curl -v http://localhost:8765/health \
  -H "x-api-key: your_key"

# 正常应返回 200（/health 始终放行）
# 测试受保护路径
curl -v http://localhost:8765/sse \
  -H "x-api-key: your_key"
# 401 → key 无效或缺失
# 403 → readonly key 尝试访问 /shutdown
```

---

## 8. 附录：关键路径速查

### 配置文件

| 文件 | 用途 | 入 Git |
|------|------|:------:|
| `claude_rag.toml` | 主配置文件 | ❌ |
| `claude_rag.toml.example` | 配置模板 | ✅ |
| `.mcp.json` | stdio 客户端配置 | ❌ |
| `.mcp.json.example` | stdio 配置模板 | ✅ |
| `.mcp.remote.json` | SSE 客户端配置 | ❌ |
| `.mcp.remote.json.example` | SSE 配置模板 | ✅ |

### 数据目录

| 目录 | 用途 | 入 Git |
|------|------|:------:|
| `knowledge_base/` | 原始文档与源码 | ❌ |
| `vector_store/` | ChromaDB 持久化索引 | ❌ |
| `models_cache/` | 本地 Embedding 模型 (~800MB) | ❌ |

### 环境变量速查

| 变量 | 对应配置 | 说明 |
|------|---------|------|
| `SERVER_HOST` | `[server] host` | 绑定地址 |
| `SERVER_PORT` | `[server] port` | 监听端口 |
| `AUTH_ENABLED` | `[auth] enabled` | 是否启用鉴权 |
| `AUTH_ADMIN_API_KEY` | `[auth] admin_api_key` | 管理员密钥 |
| `AUTH_READONLY_API_KEY` | `[auth] readonly_api_key` | 只读密钥 |
| `LLM_MODEL` | `[llm] model` | LLM 模型名 |
| `LLM_MAX_TOKENS` | `[llm] max_tokens` | LLM 最大 token 数 |
| `USE_RERANKING` | `[reranking] enabled` | 是否启用重排序 |
| `HF_HUB_OFFLINE` | — | 设 `0` 允许下载模型，设 `1` 离线 |

---

> 📝 本手册随 local-rag-kb 项目维护更新。如有新增工具或配置项，请同步更新本文档。
