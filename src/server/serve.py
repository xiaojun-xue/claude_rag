"""
HTTP SSE MCP server — 供局域网其他用户访问。

启动方式：
    python src/server/serve.py              # 默认监听 0.0.0.0:8765
    python src/server/serve.py --port 9000  # 自定义端口
    python src/server/serve.py --host 127.0.0.1  # 仅本机

远程客户端在 .mcp.json 中配置：
    {
      "mcpServers": {
        "local-rag-kb": {
          "type": "sse",
          "url": "http://192.168.80.248:8765/sse"
        }
      }
    }
"""

from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import argparse
from pathlib import Path
import asyncio
import logging
import os
import sys

# UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import json

import uvicorn
from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src.server.ui import UI_ROUTES

from contextvars import ContextVar

from src.core.config import (
    SERVER_NAME, SERVER_VERSION, SERVER_HOST, SERVER_PORT,
    AUTH_ENABLED, AUTH_ADMIN_API_KEYS, AUTH_READONLY_API_KEYS,
)
from src.core.rag_engine import RAGEngine
from src.server.tools import TOOLS, dispatch
from src.server.auth import AuthMiddleware, ROLE_ADMIN, is_tool_allowed

# 当前 SSE 会话的角色。stdio / 鉴权关闭时默认 admin（本地可信，无限制）。
# 在 handle_sse 中按 /sse 连接所用的密钥绑定，server.run() 派生的工具调用任务
# 通过 contextvar 继承到该值，从而实现按会话的工具级门禁。
_current_role: ContextVar[str] = ContextVar("current_role", default=ROLE_ADMIN)

# ── MCP Server ─────────────────────────────────────────────────────────────

server = Server(
    SERVER_NAME,
    instructions=(
        "这是一个关于海思 Hi3516CV610 芯片 SDK 代码样例和芯片文档知识的知识库，"
        "当需要基于海思 Hi3516CV610 芯片编写代码和查询芯片相关的内容可以使用该知识库。"
        "Hi3516CV610 通常会简称为 CV610 或泛指海思视觉芯片。\n\n"
        "主要工具：\n"
        "• search_knowledge_base / search_docs / search_code — 语义检索文档或代码\n"
        "• search_symbol — 按符号名精确检索（函数/类/宏）\n"
        "• grep_code — 正则全文搜索源文件\n"
        "• get_file / get_chunk_context — 读取完整文件或指定 chunk 的上下文\n"
        "• ingest_document / ingest_directory — 向知识库添加文件\n"
        "• list_documents / list_code_files — 列出已索引内容\n"
        "• delete_document — 从知识库删除文件\n"
        "检索建议：先用 search_knowledge_base 做宽泛语义检索，"
        "再用 grep_code 或 search_symbol 定位具体符号/行号。"
    ),
)

_engine: RAGEngine | None = None


def get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    role = _current_role.get()
    logger.info("Tool called: %s  role=%s  args=%s", name, role, arguments)

    # 工具级门禁：readonly 角色只能调用 list_documents / list_code_files
    if not is_tool_allowed(role, name):
        logger.warning("Tool '%s' denied for role '%s'", name, role)
        result = {
            "error": "forbidden",
            "detail": f"tool '{name}' requires admin privileges",
            "tool": name,
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            )
        ]

    try:
        result = await dispatch(name, arguments, get_engine())
    except Exception as exc:
        logger.exception("Unhandled error in tool '%s'", name)
        result = {"error": str(exc), "tool": name}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


# ── Starlette / SSE app ────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"


def build_app() -> Starlette:
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        # 鉴权关闭或 stdio 场景下 scope 无 auth_role → 默认 admin（无限制）
        role = request.scope.get("auth_role", ROLE_ADMIN)
        logger.info("New SSE connection from %s  role=%s", request.client, role)
        # 把角色绑定到本会话；server.run() 派生的工具调用任务会继承该 contextvar
        token = _current_role.set(role)
        try:
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0],
                    streams[1],
                    server.create_initialization_options(),
                )
        finally:
            _current_role.reset(token)
        return Response()

    async def handle_shutdown(request: Request) -> Response:
        logger.info("POST /shutdown — clean exit in 0.5s")
        if _engine is not None:
            try:
                _engine._chroma_client.clear_system_cache()
            except Exception:
                pass

        async def _do_exit():
            await asyncio.sleep(0.5)
            sys.exit(0)

        asyncio.create_task(_do_exit())
        return Response("shutting down", status_code=200)

    extra_routes = []
    if _STATIC_DIR.exists():
        extra_routes = UI_ROUTES + [
            Mount("/assets", app=StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets"),
            Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR)), name="static"),
        ]

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse_transport.handle_post_message),
            Route("/health", endpoint=lambda r: Response("ok"), methods=["GET"]),
            Route("/shutdown", endpoint=handle_shutdown, methods=["POST"]),
        ] + extra_routes
    )
    app.state.engine = get_engine()

    # ── API Key auth（多密钥 / 分角色）─────────────────────────────────────
    # 默认关闭（向后兼容）；AUTH_ENABLED=true 时用纯 ASGI 中间件包裹整个 app。
    # admin 全权；readonly 仅只读 REST + list_documents/list_code_files。
    if AUTH_ENABLED:
        if not AUTH_ADMIN_API_KEYS and not AUTH_READONLY_API_KEYS:
            logger.warning(
                "AUTH_ENABLED=true 但未配置任何密钥 —— 所有受保护路径将一律拒绝。"
                "请在 claude_rag.toml [auth] 或环境变量设置 admin_api_key / readonly_api_key。"
            )
        app = AuthMiddleware(
            app,
            admin_keys=AUTH_ADMIN_API_KEYS,
            readonly_keys=AUTH_READONLY_API_KEYS,
        )
        logger.info(
            "API key auth ENABLED — admin keys=%d readonly keys=%d "
            "(protected paths require 'x-api-key' header or '?api_key=')",
            len(AUTH_ADMIN_API_KEYS), len(AUTH_READONLY_API_KEYS),
        )
    else:
        logger.info("API key auth DISABLED (AUTH_ENABLED=false) — all endpoints open")

    return app


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    import signal

    parser = argparse.ArgumentParser(description="RAG Knowledge Base MCP HTTP Server")
    parser.add_argument("--host", default=SERVER_HOST,
                        help=f"Bind address (default: {SERVER_HOST})")
    parser.add_argument("--port", type=int, default=SERVER_PORT,
                        help=f"Port to listen on (default: {SERVER_PORT})")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    logger.info("%s v%s HTTP server starting on %s:%d", SERVER_NAME, SERVER_VERSION, args.host, args.port)
    logger.info("Remote clients connect via: http://<this-machine-ip>:%d/sse", args.port)

    def _shutdown(signum, frame):
        logger.info("Shutting down gracefully (signal %s)...", signum)
        if _engine is not None:
            try:
                _engine._chroma_client.clear_system_cache()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    try:
        signal.signal(signal.SIGINT, _shutdown)
    except (OSError, ValueError):
        pass

    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
