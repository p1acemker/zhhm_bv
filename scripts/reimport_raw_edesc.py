# -*- coding: utf-8 -*-
"""从 edesc_by1_filtered.csv 重新导入原始 EDesc 到 Qdrant（用 requests 绕过代理问题）"""
import csv, os, sys, logging, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as req
import numpy as np
from config import QDRANT_URL, EMBEDDING_DIM
from embedder.bge_embedder import BGEEmbedder
from utils.id_utils import generate_parent_id, generate_child_id
from collections import defaultdict

logging.disable(logging.WARNING)

BASE = QDRANT_URL.rstrip('/')
CSV_PATH = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_filtered.csv'
STD_PARENT = 'products_standardized'
STD_CHILD = 'products_std_child'

def api_get(path):
    return req.get(f'{BASE}{path}', timeout=30).json()

def api_put(path, data):
    return req.put(f'{BASE}{path}', json=data, timeout=60).json()

def api_delete(path):
    return req.delete(f'{BASE}{path}', timeout=60).json()

def api_post(path, data):
    return req.post(f'{BASE}{path}', json=data, timeout=120).json()

print("=== 重新导入原始 EDesc 到 Qdrant ===")

# 1. 读取数据
with open(CSV_PATH, 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
print(f"读取 {len(rows)} 条记录")

by1_edescs = defaultdict(list)
for r in rows:
    by1_edescs[r['by1']].append(r['EDesc'])

for by1 in list(by1_edescs.keys()):
    by1_edescs[by1] = list(dict.fromkeys(by1_edescs[by1]))

print(f"唯一 by1: {len(by1_edescs)}, 总 edesc: {sum(len(v) for v in by1_edescs.values())}")

# 2. 删除旧集合
for coll in [STD_PARENT, STD_CHILD]:
    r = api_delete(f'/collections/{coll}')
    print(f"删除 {coll}: {r.get('status', r)}")
    time.sleep(2)

# 3. 创建新集合
api_put('/collections/products_standardized', {
    "vectors": {"size": 4, "distance": "Cosine"}
})
print(f"已创建: {STD_PARENT} (dim=4)")

api_put('/collections/products_std_child', {
    "vectors": {"size": EMBEDDING_DIM, "distance": "Cosine"}
})
print(f"已创建: {STD_CHILD} (dim={EMBEDDING_DIM})")

time.sleep(2)

# 4. child 创建索引
try:
    api_put(f'/collections/{STD_CHILD}/index', {
        "field_name": "parent_id", "field_schema": "keyword"
    })
except Exception:
    pass

# 5. 初始化 embedder
embedder = BGEEmbedder()
print("Embedder 初始化完成")

# 6. 导入数据
success = 0
fail = 0
by1_list = sorted(by1_edescs.keys())
total = len(by1_list)
print(f"开始导入 {total} 个 by1 ...")

for i, by1 in enumerate(by1_list):
    edesc_list = by1_edescs[by1]
    parent_id = generate_parent_id(by1)

    try:
        embeddings = embedder.encode(edesc_list)
        if len(embeddings) != len(edesc_list):
            print(f"  [{by1}] embedding 数量不匹配")
            fail += 1
            continue
    except Exception as e:
        print(f"  [{by1}] 编码失败: {e}")
        fail += 1
        continue

    # 插入 parent
    api_put(f'/collections/{STD_PARENT}/points', {
        "points": [{
            "id": parent_id,
            "vector": [0.0, 0.0, 0.0, 0.0],
            "payload": {
                "productName": by1,
                "edesc_list": edesc_list,
                "edesc_count": len(edesc_list),
                "metadata": {"standardized": False}
            }
        }]
    })

    # 插入 child
    child_points = []
    for idx in range(len(edesc_list)):
        vec = list(embeddings[idx]) if not isinstance(embeddings[idx], list) else embeddings[idx]
        if len(vec) != EMBEDDING_DIM:
            continue
        child_id = generate_child_id(parent_id, idx)
        child_points.append({
            "id": child_id,
            "vector": vec,
            "payload": {
                "parent_id": parent_id,
                "edesc_index": idx,
                "edesc_text": edesc_list[idx],
                "productName": by1
            }
        })

    if child_points:
        # 分批上传，每批最多100个
        for batch_start in range(0, len(child_points), 100):
            batch = child_points[batch_start:batch_start + 100]
            api_put(f'/collections/{STD_CHILD}/points', {"points": batch})

    success += 1
    if (i + 1) % 10 == 0:
        print(f"  [{i+1}/{total}] {by1}: {len(edesc_list)} edescs, {len(child_points)} vectors")

print(f"\n导入完成! 成功: {success}, 失败: {fail}")
print(f"Parent: {STD_PARENT}")
print(f"Child: {STD_CHILD}")

# 验证
for coll in [STD_PARENT, STD_CHILD]:
    info = api_get(f'/collections/{coll}')
    cnt = info.get('result', {}).get('points_count', '?')
    print(f"  {coll}: {cnt} points")
