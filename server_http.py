"""
HTTP SSE MCP server — 供局域网其他用户访问。

启动方式：
    python server_http.py              # 默认监听 0.0.0.0:8765
    python server_http.py --port 9000  # 自定义端口
    python server_http.py --host 127.0.0.1  # 仅本机

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

import argparse
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

from config import SERVER_NAME, SERVER_VERSION
from rag_engine import RAGEngine
from server_tools import TOOLS, dispatch

# ── MCP Server ─────────────────────────────────────────────────────────────

server = Server(SERVER_NAME)

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
    logger.info("Tool called: %s  args=%s", name, arguments)
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

def build_app() -> Starlette:
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        logger.info("New SSE connection from %s", request.client)
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
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

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse_transport.handle_post_message),
            Route("/health", endpoint=lambda r: Response("ok"), methods=["GET"]),
            Route("/shutdown", endpoint=handle_shutdown, methods=["POST"]),
        ]
    )


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    import signal

    parser = argparse.ArgumentParser(description="RAG Knowledge Base MCP HTTP Server")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0 = all interfaces)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Port to listen on (default: 8765)")
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
