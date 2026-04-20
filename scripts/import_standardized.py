# -*- coding: utf-8 -*-
"""导入标准化数据到 Qdrant"""
import csv, os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType
from config import QDRANT_URL, EMBEDDING_DIM
from embedder.bge_embedder import BGEEmbedder
from utils.id_utils import generate_parent_id, generate_child_id
from collections import defaultdict

logging.disable(logging.WARNING)
for logger_name in ['httpx', 'config', 'urllib3', 'filelock']:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

print("导入标准化数据到 Qdrant")

# 读取标准化后的数据
CSV_PATH = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_standardized.csv'
with open(CSV_PATH, 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

print(f"标准化数据: {len(rows)} 条")

# 按 by1 分组, 合并 edesc
by1_edescs = defaultdict(list)
for r in rows:
    by1_edescs[r['by1']].append(r['standardized'])

# 去重
for by1 in list(by1_edescs.keys()):
    by1_edescs[by1] = list(set(by1_edescs[by1]))

print(f"唯一 by1: {len(by1_edescs)}, 总 edesc 条数: {sum(len(v) for v in by1_edescs.values())}")

# 连接 Qdrant
client = QdrantClient(url=QDRANT_URL, check_compatibility=False)

print("Qdrant 连接成功")

# 创建集合
STD_PARENT = 'products_standardized'
STD_CHILD = 'products_std_child'

for coll_name in [STD_PARENT, STD_CHILD]:
    if not client.collection_exists(coll_name):
        dim = 4 if coll_name == STD_PARENT else EMBEDDING_DIM
        client.create_collection(
            collection_name=coll_name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
        )
        print(f"Created: {coll_name} (dim={dim})")
    else:
        print(f"已存在: {coll_name}")

# child 集合创建索引
try:
    client.create_payload_index(
        collection_name=STD_CHILD,
        field_name='parent_id',
        field_schema=PayloadSchemaType.KEYWORD
    )
except Exception:
    pass

# 初始化 embedder
embedder = BGEEmbedder()
print("Embedder 初始化完成")

# 导入数据
success = 0
by1_list = sorted(by1_edescs.keys())
total = len(by1_list)

print(f"开始导入 {total} 个 by1 ...")

for i, by1 in enumerate(by1_list):
    edesc_list = by1_edescs[by1]
    parent_id = generate_parent_id(by1)

    # 批量编码
    try:
        embeddings = embedder.encode(edesc_list)
        if len(embeddings) != len(edesc_list):
            print(f"  [{by1}] embedding 数量不匹配: {len(embeddings)} vs {len(edesc_list)}")
            continue
    except Exception as e:
        print(f"  [{by1}] 编码失败: {e}")
        continue

    # 插入 parent
    client.upsert(
        collection_name=STD_PARENT,
        points=[PointStruct(
            id=parent_id,
            vector=[0.0] * 4,
            payload={
                'productName': by1,
                'edesc_list': edesc_list,
                'edesc_count': len(edesc_list),
                'metadata': {'standardized': True}
            }
        )]
    )

    # 插入 child embeddings
    child_points = []
    for idx in range(min(len(edesc_list), len(embeddings))):
        emb = embeddings[idx]
        if isinstance(emb, list):
            vec = emb
        else:
            vec = list(emb)
        if len(vec) != EMBEDDING_DIM:
            continue
        child_id = generate_child_id(parent_id, idx)
        child_points.append(PointStruct(
            id=child_id,
            vector=vec,
            payload={
                'parent_id': parent_id,
                'edesc_index': idx,
                'edesc_text': edesc_list[idx],
                'productName': by1
            }
        ))

    if child_points:
        client.upsert(collection_name=STD_CHILD, points=child_points)

    success += 1
    if (i + 1) % 20 == 0 or (i + 1) % 100 == 0:
        print(f"  [{i+1}/{total}] {by1}: {len(edesc_list)} edescs, {len(child_points)} vectors")

print(f"\n导入完成! {success} products imported")
print(f"Parent: {STD_PARENT}")
print(f"Child: {STD_CHILD}")
