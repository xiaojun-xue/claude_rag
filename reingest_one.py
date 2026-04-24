"""Ingest a single file. Called per-file by reingest_batch.py to avoid memory segfault."""
import sys, os
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

file_path = sys.argv[1]
from rag_engine import RAGEngine
engine = RAGEngine()
result = engine.ingest_document(file_path)
coll = result.get('collection', '?')
print(f"{result['status']}|{result['chunks_added']}|{coll}|{result.get('message','')}")
