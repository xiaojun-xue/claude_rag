"""
Fast single-process re-indexer: loads both models once, then processes all files.
Usage: python reingest_fast.py [dir_path]
"""
import sys, os
from pathlib import Path

os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("d:/workplace/claude_rag/knowledge_base")

EXTENSIONS = {
    ".pdf", ".docx",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".go", ".rs", ".sh", ".bat", ".ps1",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".cmake", ".mk", ".makefile", ".txt", ".md",
}

print("Loading RAGEngine (both models)...", flush=True)
from rag_engine import RAGEngine
engine = RAGEngine()

# Trigger lazy init of both models upfront
_ = engine._text_collection
_ = engine._code_collection
_ = engine._text_model
_ = engine._code_model
print("Models loaded.\n", flush=True)

files = sorted(f for ext in EXTENSIONS for f in ROOT.rglob(f"*{ext}"))
print(f"Found {len(files)} files under {ROOT}\n", flush=True)

ok = err = 0
total_chunks = 0
by_collection: dict[str, int] = {}

for i, f in enumerate(files, 1):
    try:
        result = engine.ingest_document(str(f))
        coll = result.get('collection', '?')
        chunks = result.get('chunks_added', 0)
        status = result.get('status', '?')
        total_chunks += chunks
        by_collection[coll] = by_collection.get(coll, 0) + chunks
        print(f"[{i:3d}/{len(files)}] {status:7s} {chunks:4d} chunks  [{coll}]  {f.name}", flush=True)
        if status in ('success', 'skipped'):
            ok += 1
        else:
            err += 1
    except Exception as e:
        print(f"[{i:3d}/{len(files)}] ERR  {f.name}  {str(e)[:100]}", flush=True)
        err += 1

print(f"\nDone: {ok} OK, {err} errors, {total_chunks} total chunks")
for coll, n in sorted(by_collection.items()):
    print(f"  {coll}: {n} chunks")
