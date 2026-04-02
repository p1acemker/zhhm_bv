# -*- coding: utf-8 -*-
"""
演示脚本 - 导入与搜索演示

此脚本演示货描维护系统的核心功能：
1. 智能导入新品种
2. 向量搜索
3. 前缀匹配搜索

使用 fake embedding 可以在没有真实 embedding 服务的情况下运行
"""

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeEmbedder:
    """Fake Embedder - 用于演示，不需要真实 embedding 服务"""

    def __init__(self, dim=1024):
        self.dim = dim

    def encode(self, texts, batch_size=32):
        """生成随机向量（仅用于演示）"""
        import hashlib
        import random

        single = isinstance(texts, str)
        texts = [texts] if single else texts

        results = []
        for text in texts:
            # 使用文本哈希作为种子，保证相同文本生成相同向量
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
            random.seed(seed)
            results.append([random.random() for _ in range(self.dim)])

        return results[0] if single else results

    def get_dimension(self):
        return self.dim

    def health_check(self):
        return True


class FakeQdrantClient:
    """Fake Qdrant Client - 用于演示，使用内存存储"""

    def __init__(self):
        self.parents = {}
        self.children = {}
        self._collection_exists = {"products_parent": True, "products_child": True}

    def collection_exists(self, name):
        return self._collection_exists.get(name, False)

    def create_collection(self, collection_name, vectors_config):
        self._collection_exists[collection_name] = True
        print(f"  [Demo] Created collection: {collection_name}")

    def create_payload_index(self, collection_name, field_name, field_schema):
        pass

    def upsert(self, collection_name, points):
        for point in points:
            if collection_name == "products_parent":
                self.parents[point.id] = point
            else:
                self.children[point.id] = point

    def scroll(self, collection_name, limit=100, with_payload=True, scroll_filter=None):
        if collection_name == "products_parent":
            points = list(self.parents.values())
            # 简单过滤
            if scroll_filter and hasattr(scroll_filter, 'must'):
                for cond in scroll_filter.must:
                    if hasattr(cond, 'match'):
                        value = cond.match.value
                        field = cond.key
                        points = [p for p in points if p.payload.get(field) == value]
            return (points[:limit], None)
        return ([], None)

    def delete(self, collection_name, points_selector):
        if isinstance(points_selector, list):
            for pid in points_selector:
                if collection_name == "products_parent":
                    self.parents.pop(pid, None)
                else:
                    self.children.pop(pid, None)

    def retrieve(self, collection_name, ids, with_payload=True):
        if collection_name == "products_parent":
            return [self.parents.get(pid) for pid in ids if pid in self.parents]
        return []

    def query_points(self, collection_name, query, limit=10, with_payload=True):
        """模拟向量搜索"""
        from qdrant_client.models import ScoredPoint

        # 简单模拟：返回所有点，分数随机
        points = list(self.children.values())[:limit]
        results = []
        for i, p in enumerate(points):
            results.append(ScoredPoint(
                id=p.id,
                version=1,
                score=0.9 - i * 0.1,
                payload=p.payload
            ))
        from qdrant_client.models import QueryResponse
        return QueryResponse(points=results)

    def get_collection(self, collection_name):
        class CollectionInfo:
            points_count = len(self.parents) if collection_name == "products_parent" else len(self.children)
        return CollectionInfo()


def run_demo():
    """运行演示"""
    print("=" * 60)
    print("货描维护系统 - 导入与搜索演示")
    print("=" * 60)

    # 使用 fake 组件
    from qdrant_client.models import PointStruct

    print("\n[1] 初始化组件 (使用 Fake Embedding)...")

    fake_client = FakeQdrantClient()
    fake_embedder = FakeEmbedder(dim=1024)

    # 创建测试数据
    print("\n[2] 创建测试数据...")

    test_data = [
        {"by1": "D71X4", "edesc": "Wafer Butterfly Valve, EPDM Seat, DI Body, Gear Operator"},
        {"by1": "D71X5", "edesc": "Lug Butterfly Valve, NBR Seat, DI Body, Lever Operator"},
        {"by1": "D71X6", "edesc": "Wafer Butterfly Valve, EPDM Seat, SS Body, Gear Operator"},
        {"by1": "XD371X208", "edesc": "Wafer Butterfly Valve, EPDM Seat, DI Body, Gear Operator, Fire Safe"},
        {"by1": "XD371X209", "edesc": "Lug Butterfly Valve, EPDM Seat, DI Body, Gear Operator"},
    ]

    for item in test_data:
        parent_id = f"parent_{item['by1']}"
        fake_client.upsert("products_parent", [
            PointStruct(
                id=parent_id,
                vector=[0.0] * 4,
                payload={
                    "productName": item["by1"],
                    "EDesc": item["edesc"],
                    "edesc_count": 1
                }
            )
        ])
        print(f"  添加: {item['by1']}")

    # 演示前缀匹配
    print("\n[3] 演示前缀匹配搜索...")
    print("  搜索: D71X")

    # 获取所有 by1
    all_by1s = [p.payload["productName"] for p in fake_client.parents.values()]

    def calculate_prefix_similarity(a, b):
        a, b = a.upper(), b.upper()
        min_len = min(len(a), len(b))
        prefix_len = 0
        for i in range(min_len):
            if a[i] == b[i]:
                prefix_len += 1
            else:
                break
        return prefix_len / max(len(a), len(b)) if max(len(a), len(b)) > 0 else 0

    results = []
    for by1 in all_by1s:
        score = calculate_prefix_similarity("D71X", by1)
        if score > 0:
            results.append({"by1": by1, "score": score})

    results.sort(key=lambda x: x["score"], reverse=True)

    for r in results[:5]:
        print(f"  - {r['by1']}: {r['score']:.2%}")

    # 演示导入策略
    print("\n[4] 演示导入策略...")

    from strategy.import_strategy import get_strategy, Candidate

    # 创建候选
    candidates = [
        Candidate(by1="D71X4", score=0.8, prefix_match_len=4, edesc_count=5),
        Candidate(by1="D71X5", score=0.8, prefix_match_len=4, edesc_count=10),
        Candidate(by1="D71X6", score=0.6, prefix_match_len=3, edesc_count=2),
    ]

    for strategy_name in ["most_references", "highest_score", "combined"]:
        strategy = get_strategy(strategy_name)
        selected = strategy.select(candidates)
        print(f"  策略 '{strategy_name}': 选择了 {selected.by1}")
        print(f"    - 描述: {strategy.description}")

    # 演示文本工具
    print("\n[5] 演示文本工具...")

    from utils.text_utils import split_edesc_list, is_edesc_duplicate, count_edesc_items

    edesc = "Desc A; Desc B; Desc C"
    print(f"  原始货描: {edesc}")
    print(f"  分割结果: {split_edesc_list(edesc)}")
    print(f"  条目数量: {count_edesc_items(edesc)}")

    print(f"  'Desc B' 是否重复: {is_edesc_duplicate('Desc B', edesc)}")
    print(f"  'Desc D' 是否重复: {is_edesc_duplicate('Desc D', edesc)}")

    # 完成
    print("\n" + "=" * 60)
    print("演示完成!")
    print("=" * 60)

    print("\n提示:")
    print("  - 使用真实服务: python api.py")
    print("  - 使用 CLI: python edesc_maintenance.py --help")
    print("  - 运行测试: python -m pytest tests/ -v")


if __name__ == "__main__":
    run_demo()
