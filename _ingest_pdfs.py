"""Ingest individual PDF/doc files one-by-one through MCP (avoids timeout)."""
import sys, os, asyncio, json
from pathlib import Path
sys.path.insert(0, 'd:/workplace/claude_rag')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mcp import ClientSession
from mcp.client.sse import sse_client

KB = Path("d:/workplace/claude_rag/knowledge_base")
FILES = sorted(f for f in KB.iterdir() if f.suffix.lower() in {'.pdf', '.txt', '.md', '.docx'})

async def main():
    async with sse_client("http://localhost:8765/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for f in FILES:
                result = await session.call_tool("ingest_document", {"file_path": str(f)})
                data = json.loads(result.content[0].text)
                print(f"{data['status']:7s} {data.get('chunks_added',0):4d} chunks  {f.name}")

asyncio.run(main())
