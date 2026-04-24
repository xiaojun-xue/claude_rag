"""
Batch re-indexer: spawns a fresh Python process per file to avoid segfaults.
Usage: python reingest_batch.py [dir_path]
"""
import sys, os, subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PYTHON = r"C:/Users/Administrator/AppData/Local/Python/pythoncore-3.14-64/python.exe"
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("d:/workplace/claude_rag/knowledge_base")
SCRIPT = Path(__file__).parent / "reingest_one.py"

EXTENSIONS = {
    ".pdf", ".docx",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh",
    ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".kt", ".go", ".rs", ".sh", ".bat", ".ps1",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".cmake", ".mk", ".makefile", ".txt", ".md",
}

files = sorted(f for ext in EXTENSIONS for f in ROOT.rglob(f"*{ext}"))
print(f"Found {len(files)} files under {ROOT}\n")

ok = err = 0
total_chunks = 0
by_collection: dict[str, int] = {}

for i, f in enumerate(files, 1):
    r = subprocess.run(
        [PYTHON, str(SCRIPT), str(f)],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    line = r.stdout.strip()
    if r.returncode != 0 or not line:
        print(f"[{i:3d}/{len(files)}] ERR  {f.name}  exit={r.returncode}")
        if r.stderr:
            last = [l for l in r.stderr.splitlines() if l.strip()]
            if last:
                print(f"        {last[-1][:120]}")
        err += 1
    else:
        parts = line.split("|", 3)
        status = parts[0]
        chunks = int(parts[1]) if len(parts) > 1 else 0
        coll = parts[2] if len(parts) > 2 else "?"
        total_chunks += chunks
        by_collection[coll] = by_collection.get(coll, 0) + chunks
        print(f"[{i:3d}/{len(files)}] {status:7s} {chunks:4d} chunks  [{coll}]  {f.name}")
        if status == "success":
            ok += 1
        else:
            err += 1

print(f"\nDone: {ok} OK, {err} errors, {total_chunks} total chunks")
for coll, n in sorted(by_collection.items()):
    print(f"  {coll}: {n} chunks")
