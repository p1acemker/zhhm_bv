# -*- coding: utf-8 -*-
"""
高并发批量搜索测试脚本

测试步骤：
1. 确保 API 服务已启动: python api.py
2. 运行此脚本: python test_batch_search.py
"""

import requests
import time
import json
from typing import List, Dict


class BatchSearchTester:
    """批量搜索测试器"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.search_url = f"{base_url}/edesc/search"
        self.batch_url = f"{base_url}/edesc/batch-search"

    def test_single_search(self, query: str, top_k: int = 5) -> Dict:
        """测试单个搜索"""
        start = time.time()
        resp = requests.post(
            self.search_url,
            json={"query": query, "top_k": top_k}
        )
        elapsed = time.time() - start

        return {
            "query": query,
            "elapsed": elapsed,
            "status_code": resp.status_code,
            "data": resp.json() if resp.status_code == 200 else None
        }

    def test_batch_search(self, queries: List[str], top_k: int = 5, max_concurrent: int = 10) -> Dict:
        """测试批量搜索"""
        start = time.time()
        resp = requests.post(
            self.batch_url,
            json={
                "queries": queries,
                "top_k": top_k,
                "max_concurrent": max_concurrent
            }
        )
        elapsed = time.time() - start

        return {
            "total_queries": len(queries),
            "elapsed": elapsed,
            "status_code": resp.status_code,
            "data": resp.json() if resp.status_code == 200 else None
        }

    def compare_performance(self, queries: List[str], top_k: int = 5):
        """对比单个搜索 vs 批量搜索性能"""

        print("=" * 60)
        print("性能对比测试")
        print("=" * 60)
        print(f"查询数量: {len(queries)}")
        print(f"Top-K: {top_k}")
        print()

        # 1. 逐个搜索
        print("[1] 逐个搜索（串行）...")
        start = time.time()
        serial_results = []
        for query in queries:
            result = self.test_single_search(query, top_k)
            serial_results.append(result)
        serial_elapsed = time.time() - start
        print(f"    总耗时: {serial_elapsed:.3f}s")
        print(f"    平均每个: {serial_elapsed/len(queries):.3f}s")
        print(f"    QPS: {len(queries)/serial_elapsed:.2f}")

        print()

        # 2. 批量搜索
        print("[2] 批量搜索（并行）...")
        batch_result = self.test_batch_search(queries, top_k)

        if batch_result["status_code"] == 200:
            data = batch_result["data"]
            batch_elapsed = data.get("elapsed_seconds", batch_result["elapsed"])
            print(f"    总耗时: {batch_elapsed:.3f}s")
            print(f"    QPS: {data.get('queries_per_second', 0):.2f}")
        else:
            print(f"    失败: {batch_result['status_code']}")
            batch_elapsed = batch_result["elapsed"]

        print()

        # 3. 对比结果
        print("=" * 60)
        print("性能对比结果")
        print("=" * 60)
        print(f"{'方式':<15} {'耗时':<12} {'QPS':<12} {'加速比':<10}")
        print("-" * 50)
        print(f"{'串行搜索':<15} {serial_elapsed:<12.3f} {len(queries)/serial_elapsed:<12.2f} {'1.00x':<10}")

        if batch_result["status_code"] == 200:
            speedup = serial_elapsed / batch_elapsed if batch_elapsed > 0 else 0
            print(f"{'批量搜索':<15} {batch_elapsed:<12.3f} {len(queries)/batch_elapsed:<12.2f} {f'{speedup:.2f}x':<10}")
            print()
            print(f"✓ 批量搜索提速 {speedup:.2f} 倍")
        else:
            print(f"{'批量搜索':<15} {'失败':<12} {'-':<12} {'-':<10}")

        return {
            "serial_elapsed": serial_elapsed,
            "batch_elapsed": batch_elapsed if batch_result["status_code"] == 200 else None,
            "speedup": serial_elapsed / batch_elapsed if batch_result["status_code"] == 200 and batch_elapsed > 0 else 0
        }


def main():
    """主测试函数"""

    # 测试查询列表
    test_queries = [
        "Butterfly Valve",
        "Gate Valve",
        "Check Valve",
        "Ball Valve",
        "Globe Valve",
        "Diaphragm Valve",
        "Plug Valve",
        "Needle Valve",
        "Pinch Valve",
        "Safety Valve",
        "Pressure Relief Valve",
        "Control Valve",
        "Solenoid Valve",
        "Angle Valve",
        "Float Valve"
    ]

    tester = BatchSearchTester()

    # 检查服务是否可用
    print("检查 API 服务...")
    try:
        resp = requests.get(f"{tester.base_url}/health", timeout=5)
        if resp.status_code == 200:
            print("✓ API 服务正常")
            print()
        else:
            print("✗ API 服务异常")
            return
    except Exception as e:
        print(f"✗ 无法连接 API 服务: {e}")
        print()
        print("请先启动 API 服务:")
        print("  python api.py")
        return

    # 运行性能对比测试
    tester.compare_performance(test_queries, top_k=5)

    print()
    print("=" * 60)
    print("测试完成")
    print("=" * 60)
    print()
    print("API 文档: http://localhost:8000/docs")
    print()
    print("批量搜索示例:")
    print("""
curl -X POST "http://localhost:8000/edesc/batch-search" \\
  -H "Content-Type: application/json" \\
  -d '{
    "queries": ["Butterfly Valve", "Gate Valve"],
    "top_k": 5,
    "max_concurrent": 10
  }'
""")


if __name__ == "__main__":
    main()
