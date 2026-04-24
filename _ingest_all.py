"""Ingest all documents (PDFs + src) through the running MCP server."""
import sys, os, asyncio, json
sys.path.insert(0, 'd:/workplace/claude_rag')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mcp import ClientSession
from mcp.client.sse import sse_client

DIRS = [
    "d:/workplace/claude_rag/knowledge_base",  # PDFs + readmes at root
    "d:/workplace/claude_rag/knowledge_base/src",  # C/H source code
]

async def ingest_dir(session, dir_path):
    print(f"\nIngesting: {dir_path}")
    result = await session.call_tool("ingest_directory", {"dir_path": dir_path})
    data = json.loads(result.content[0].text)
    print(f"  Files: {data['total_files']}, Chunks: {data['total_chunks']}, Errors: {len(data['errors'])}")
    if data['errors']:
        for e in data['errors'][:5]:
            print(f"  ERR: {e['file']}: {e['error']}")
    return data

async def main():
    async with sse_client("http://localhost:8765/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to MCP server")

            for d in DIRS:
                await ingest_dir(session, d)

            # Final count
            result = await session.call_tool("list_documents", {})
            docs = json.loads(result.content[0].text)
            print(f"\nTotal documents indexed: {len(docs)}")
            for doc in docs:
                print(f"  {doc['doc_name']:40s} {doc['chunk_count']:4d} chunks  [{doc['file_type']}]")

asyncio.run(main())
