"""Ingest source code files one-by-one through MCP (avoids timeout on bulk ingest)."""
import sys, os, asyncio, json
from pathlib import Path
sys.path.insert(0, 'd:/workplace/claude_rag')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mcp import ClientSession
from mcp.client.sse import sse_client

ROOT = Path("d:/workplace/claude_rag/knowledge_base/src")
EXTS = {
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".go", ".rs", ".sh", ".bat", ".ps1",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".cmake", ".mk", ".makefile", ".txt", ".md",
}
FILES = sorted(f for ext in EXTS for f in ROOT.rglob(f"*{ext}"))

async def main():
    async with sse_client("http://localhost:8765/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"Ingesting {len(FILES)} files from {ROOT}")
            ok = err = total_chunks = 0
            for i, f in enumerate(FILES, 1):
                result = await session.call_tool("ingest_document", {"file_path": str(f)})
                data = json.loads(result.content[0].text)
                chunks = data.get('chunks_added', 0)
                total_chunks += chunks
                if data['status'] == 'success':
                    ok += 1
                    print(f"[{i:3d}/{len(FILES)}] OK   {chunks:4d} chunks  {f.name}")
                else:
                    err += 1
                    print(f"[{i:3d}/{len(FILES)}] ERR  {f.name}: {data.get('message','')[:60]}")
            print(f"\nDone: {ok} OK, {err} errors, {total_chunks} total chunks")

asyncio.run(main())
