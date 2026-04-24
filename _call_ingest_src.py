"""Ingest knowledge_base/src via running MCP server (avoids HNSW segfault in fresh process)."""
import sys, os, asyncio
sys.path.insert(0, 'd:/workplace/claude_rag')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8765/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "ingest_directory",
                {"dir_path": "d:/workplace/claude_rag/knowledge_base/src"}
            )
            for c in result.content:
                print(c.text)

asyncio.run(main())
