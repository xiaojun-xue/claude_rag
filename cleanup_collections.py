"""One-time script: delete stale collections before re-indexing."""
import sys
sys.path.insert(0, '.')
import chromadb

client = chromadb.PersistentClient(path='d:/workplace/claude_rag/vector_store')
before = [c.name for c in client.list_collections()]
print('Collections before:', before)

for name in ['knowledge_base', 'kb_text', 'kb_code']:
    try:
        client.delete_collection(name)
        print(f'Deleted: {name}')
    except Exception as e:
        print(f'Skip {name}: {e}')

after = [c.name for c in client.list_collections()]
print('Collections after:', after)
