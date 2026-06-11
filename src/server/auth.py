"""
SSE / REST API 鉴权中间件（多密钥 / 分角色方案）。

纯 ASGI 中间件（非 Starlette BaseHTTPMiddleware）——这样才能正确覆盖通过
`Mount` 挂载的 MCP 子应用（`/messages/`）和 SSE 长连接（`/sse`），
BaseHTTPMiddleware 会缓冲响应、破坏流式传输。

两种角色，每个角色可配多把密钥（逗号分隔，便于按人发放/单独吊销）：
  • admin    —— 全部权限：所有 MCP 工具（含写操作）、/shutdown、Web UI / REST。
  • readonly —— Web UI / REST 只读端点，以及全部「只读」MCP 工具（语义搜索 +
                精确检索/读取，共 9 个）；仅写操作（ingest_document /
                ingest_directory / delete_document）与 /shutdown 被拒绝。

凭据来源（受保护路径）：
  • 请求头 `x-api-key: <key>`，或
  • 查询参数 `?api_key=<key>`（用于无法自定义请求头的客户端）

公开路径（始终放行）：/health、/ui、/assets/*、/static/*
受保护路径：/sse、/messages/、/api/*、/shutdown

为什么分两层：path 级中间件无法区分同一个 `/messages/` 上的具体 MCP 工具
（所有 tools/call 都走这一个端点）。因此本中间件只负责：
  (1) 把密钥解析成角色；(2) 按 path 对 REST / /shutdown 做角色门禁；
  (3) 把角色写进 scope["auth_role"]，交给 serve.py 在 /sse 连接时绑定到会话，
      再由工具分发层用 is_tool_allowed() 做工具级门禁。

Stdio 模式不经过 HTTP 层，因此完全不受影响（默认即 admin）。
"""

from __future__ import annotations

import secrets
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# ── 角色 ──────────────────────────────────────────────────────────────────
ROLE_ADMIN = "admin"
ROLE_READONLY = "readonly"

# readonly 角色在 MCP 上允许调用的「只读」工具（允许清单，deny-by-default：
# 未列出的工具——包括未来新增的——对 readonly 一律拒绝）。
READONLY_TOOLS = frozenset({
    # 语义搜索（3）
    "search_knowledge_base",   # 全库语义搜索（文档+代码）
    "search_code",             # 仅搜代码，BM25+向量混合
    "search_docs",             # 仅搜文档
    # 精确检索 / 读取（6）
    "search_symbol",           # 精确匹配函数名/宏/结构体
    "grep_code",               # 磁盘源文件正则全文搜索
    "get_file",                # 按文件名获取完整内容
    "get_chunk_context",       # 展开某 chunk 的上下文
    "list_documents",          # 列出所有已索引文档
    "list_code_files",         # 列出已索引代码文件
})

# 仅管理员可调用的写操作（参考用；readonly 因不在 READONLY_TOOLS 中而被拒绝）
ADMIN_ONLY_TOOLS = frozenset({"ingest_document", "ingest_directory", "delete_document"})

# 受保护路径前缀：命中其一即需要校验
PROTECTED_PREFIXES = ("/sse", "/messages/", "/api/", "/shutdown")

# 仅管理员可访问的路径
ADMIN_ONLY_PREFIXES = ("/shutdown",)

# 公开路径：始终放行（优先级高于受保护前缀）
PUBLIC_EXACT = ("/health", "/ui")
PUBLIC_PREFIXES = ("/assets/", "/static/")


def is_protected(path: str) -> bool:
    """判断路径是否需要鉴权。公开路径优先放行；其余按受保护前缀匹配。"""
    if path in PUBLIC_EXACT:
        return False
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return False
    return any(path == p or path.startswith(p) for p in PROTECTED_PREFIXES)


def requires_admin(path: str) -> bool:
    """该路径是否仅限管理员（如 /shutdown）。"""
    return any(path == p or path.startswith(p) for p in ADMIN_ONLY_PREFIXES)


def extract_api_key(scope: Scope) -> str | None:
    """从 ASGI scope 提取 API key：先查 `x-api-key` 头，再回退 `api_key` 查询参数。"""
    for name, value in scope.get("headers", []):
        if name == b"x-api-key":
            try:
                return value.decode("latin-1")
            except Exception:
                return None

    qs = scope.get("query_string", b"")
    if qs:
        params = parse_qs(qs.decode("latin-1"))
        values = params.get("api_key")
        if values:
            return values[0]

    return None


def _matches_any(provided: str, keys) -> bool:
    """与一组密钥逐个做常量时间比较，命中任意一把即 True。空 key 跳过（fail closed）。"""
    matched = False
    for k in keys:
        if k and secrets.compare_digest(provided, k):
            matched = True  # 不提前 break：尽量保持比较次数一致，减小时序差异
    return matched


def resolve_role(provided: str | None, admin_keys, readonly_keys) -> str | None:
    """把客户端密钥解析成角色；不匹配任何已配置密钥返回 None。

    每个角色都可配多把 key（可迭代）。admin 优先级高于 readonly（同值按 admin）。
    空的服务端密钥永不匹配（fail closed）。使用常量时间比较防时序侧信道。
    """
    if not provided:
        return None
    if _matches_any(provided, admin_keys):
        return ROLE_ADMIN
    if _matches_any(provided, readonly_keys):
        return ROLE_READONLY
    return None


def is_tool_allowed(role: str | None, tool_name: str) -> bool:
    """工具级门禁：admin 放行全部；readonly 仅放行 READONLY_TOOLS；其余角色拒绝。"""
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_READONLY:
        return tool_name in READONLY_TOOLS
    return False


class AuthMiddleware:
    """纯 ASGI 中间件：解析角色、对 REST / /shutdown 做 path 级门禁。

    admin_keys / readonly_keys 为可迭代的密钥集合，每个角色支持多把 key。
    """

    def __init__(self, app: ASGIApp, admin_keys=(), readonly_keys=()) -> None:
        self.app = app
        self.admin_keys = tuple(k for k in admin_keys if k)
        self.readonly_keys = tuple(k for k in readonly_keys if k)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 非 HTTP 流量（lifespan / websocket 握手）直接放行
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not is_protected(path):
            await self.app(scope, receive, send)
            return

        provided = extract_api_key(scope)
        role = resolve_role(provided, self.admin_keys, self.readonly_keys)

        if role is None:
            await self._reject(scope, receive, send, 401,
                               "missing or invalid api key")
            return

        if requires_admin(path) and role != ROLE_ADMIN:
            await self._reject(scope, receive, send, 403,
                               "admin privileges required")
            return

        # 把角色写进 scope，供 serve.py 在 /sse 连接时绑定到会话
        scope["auth_role"] = role
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send, status, detail):
        response = JSONResponse(
            {"error": "unauthorized" if status == 401 else "forbidden", "detail": detail},
            status_code=status,
            headers={"WWW-Authenticate": "ApiKey"} if status == 401 else None,
        )
        await response(scope, receive, send)
