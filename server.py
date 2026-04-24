"""
MCP server entry point for the local RAG knowledge base.

Claude Code spawns this process and communicates via stdio JSON-RPC.
IMPORTANT: stdout is reserved for MCP protocol frames — never print() here.
           All logging goes to stderr.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

# Force UTF-8 on Windows console before anything else
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Logging to stderr only
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from config import SERVER_NAME, SERVER_VERSION
from rag_engine import RAGEngine
from server_tools import TOOLS, dispatch

# ── Server setup ───────────────────────────────────────────────────────────

server = Server(SERVER_NAME)

_engine: RAGEngine | None = None


def get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


# ── Tool definitions & dispatch ────────────────────────────────────────────

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


# ── Entry point ────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("%s v%s starting…", SERVER_NAME, SERVER_VERSION)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    # Windows asyncio: use SelectorEventLoop to avoid ProactorEventLoop issues
    # with some stdin/stdout pipe configurations.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
