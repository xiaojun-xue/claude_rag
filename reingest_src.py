"""
Re-index all source code files in knowledge_base/src with the new code-aware chunker.
Run this directly (not through MCP) while the server is stopped.
"""
import sys, os
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from rag_engine import RAGEngine

engine = RAGEngine()
result = engine.ingest_directory("d:/workplace/claude_rag/knowledge_base/src")

print(f"\nTotal files: {result['total_files']}")
print(f"Total chunks: {result['total_chunks']}")
print(f"Errors: {len(result['errors'])}")

for item in result['processed']:
    print(f"  OK  {item['chunks']:3d} chunks  {item['file']}")

if result['errors']:
    print("\nErrors:")
    for e in result['errors']:
        print(f"  ERR {e['file']}: {e['error']}")
