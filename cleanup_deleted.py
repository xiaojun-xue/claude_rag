"""
清理向量库中已被删除文件的索引。
扫描所有 chunk 的 source_path，若文件不存在则删除该文档的全部 chunks。

用法：
    python cleanup_deleted.py           # 预览（dry-run，不实际删除）
    python cleanup_deleted.py --delete  # 执行删除
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import argparse
import chromadb
from config import COLLECTION_NAME, VECTOR_STORE_DIR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--delete', action='store_true',
                        help='实际执行删除（不加此参数则仅预览）')
    args = parser.parse_args()

    dry_run = not args.delete

    # 连接向量库
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    total_chunks = collection.count()
    print(f"向量库中共有 {total_chunks} 个 chunks，开始扫描...\n")

    # 获取所有 metadata（不取 embeddings，节省内存）
    # 分批获取，每批 2000 条，避免内存溢出
    BATCH = 2000
    offset = 0
    doc_map: dict[str, dict] = {}  # doc_name -> {source_path, ids: []}

    while True:
        result = collection.get(
            limit=BATCH,
            offset=offset,
            include=["metadatas"]
        )
        ids = result["ids"]
        metas = result["metadatas"]
        if not ids:
            break

        for chunk_id, meta in zip(ids, metas):
            doc_name = meta.get("doc_name", "")
            source_path = meta.get("source_path", "")
            if doc_name not in doc_map:
                doc_map[doc_name] = {"source_path": source_path, "ids": []}
            doc_map[doc_name]["ids"].append(chunk_id)

        offset += len(ids)
        if len(ids) < BATCH:
            break

    print(f"共发现 {len(doc_map)} 个文档\n")

    # 检查哪些文件已不存在
    missing = []
    existing = []
    for doc_name, info in sorted(doc_map.items()):
        path = info["source_path"]
        if path and not Path(path).exists():
            missing.append((doc_name, path, len(info["ids"])))
        else:
            existing.append(doc_name)

    if not missing:
        print("✓ 所有文档对应的源文件均存在，无需清理。")
        return

    print(f"发现 {len(missing)} 个文档的源文件已被删除：\n")
    total_orphan_chunks = 0
    for doc_name, path, chunk_count in missing:
        print(f"  [待删除] {doc_name}  ({chunk_count} chunks)")
        print(f"           路径: {path}")
        total_orphan_chunks += chunk_count

    print(f"\n合计：{len(missing)} 个文档，{total_orphan_chunks} 个 orphan chunks")

    if dry_run:
        print("\n[预览模式] 未实际删除。加 --delete 参数执行删除：")
        print("  python cleanup_deleted.py --delete")
        return

    # 执行删除
    print("\n开始删除...")
    deleted_docs = 0
    deleted_chunks = 0

    for doc_name, path, chunk_count in missing:
        ids_to_delete = doc_map[doc_name]["ids"]
        # 分批删除（ChromaDB 单次删除上限约 5000）
        BATCH_DEL = 500
        for i in range(0, len(ids_to_delete), BATCH_DEL):
            collection.delete(ids=ids_to_delete[i:i+BATCH_DEL])
        deleted_docs += 1
        deleted_chunks += chunk_count
        print(f"  [已删除] {doc_name} ({chunk_count} chunks)")

    print(f"\n完成！共删除 {deleted_docs} 个文档，{deleted_chunks} 个 chunks。")
    print(f"向量库剩余 chunks：{collection.count()}")


if __name__ == "__main__":
    main()
