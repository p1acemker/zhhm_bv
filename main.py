# -*- coding: utf-8 -*-
"""
主入口 - Qdrant 父子分段检索系统
整合所有操作：建库、导入、检索
"""

from config import *
from embedding_client import EmbeddingClient
from qdrant_store import QdrantVectorStore
from data_processor import DataCleaner, EDescStandardizer
from typing import List, Dict, Optional
import pandas as pd


class ProductSearchEngine:
    """产品检索引擎"""

    def __init__(self):
        """初始化检索引擎"""
        print("=" * 50)
        print("初始化产品检索引擎")
        print("=" * 50)

        # 1. 初始化 Embedding 客户端
        print("\n[1/2] 检查 Embedding 服务...")
        self.embedding_client = EmbeddingClient()
        if self.embedding_client.health_check():
            print(f"  [OK] Embedding 服务正常 ({EMBEDDING_MODEL}, {EMBEDDING_DIM}维)")
        else:
            raise ConnectionError(f"无法连接 Embedding 服务: {EMBEDDING_API_URL}")

        # 2. 初始化 Qdrant 存储
        print("\n[2/2] 连接 Qdrant...")
        self.store = QdrantVectorStore()
        self.store.init_collections()
        print(f"  [OK] Qdrant 连接成功 ({QDRANT_URL})")
        print(f"  [OK] 父集合: {PARENT_COLLECTION}")
        print(f"  [OK] 子集合: {CHILD_COLLECTION}")

        print("\n" + "=" * 50)
        print("检索引擎初始化完成!")
        print("=" * 50)

    # ==================== 建库操作 ====================

    def clear_all(self):
        """清空所有数据"""
        self.store.clear_collections()

    def rebuild_collections(self):
        """重建集合（删除后重新创建）"""
        self.store.delete_collections()
        self.store.init_collections()

    # ==================== 导入操作 ====================

    def import_from_csv(
        self, csv_file: str, clean_first: bool = True, standardize_first: bool = True
    ):
        """
        从 CSV 导入数据
        重构后的导入逻辑：
        - 相同 by1 对应一个父块
        - 每条货描作为独立子块存储（逐条存储）
        - 检索时按 parent_id 去重

        Args:
            csv_file: CSV 文件路径
            clean_first: 是否先清洗数据
            standardize_first: 是否先标准化数据
        """
        df = pd.read_csv(csv_file)
        # 数据处理
        if clean_first:
            print("清洗数据...")
            cleaner = DataCleaner()
            df = cleaner.clean_csv(csv_file)
            print(f"  清洗后: {len(df)} 行")

        if standardize_first and "EDesc_Standardized" not in df.columns:
            print("标准化 EDesc...")
            standardizer = EDescStandardizer()
            df = standardizer.standardize_csv(
                csv_file
                if not clean_first
                else csv_file.replace(".csv", "_cleaned.csv")
            )
            print(f"  标准化后: {len(df)} 行")
        # 按 by1 分组，收集货描列表（不合并）
        grouped = df.groupby("by1")["EDesc_Standardized"].apply(list).reset_index()
        grouped.columns = ["by1", "edesc_list"]
        print(f"\n开始导入 {len(grouped)} 个产品...")
        total_edesc_count = sum(len(lst) for lst in grouped["edesc_list"])
        print(f"共 {total_edesc_count} 条货描")
        success_count = 0

        for idx, row in grouped.iterrows():
            by1 = row["by1"]
            edesc_list = row["edesc_list"]

            try:
                # 使用新方法：每条货描独立存储
                self.store.add_product_with_edesc_list(
                    product_name=by1,
                    edesc_list=edesc_list,
                    embedding_func=self.embedding_client.encode,
                    metadata={"by1": by1, "edesc_count": len(edesc_list)},
                )
                success_count += 1

                if (idx + 1) % 10 == 0:
                    print(f"  进度: {idx + 1}/{len(grouped)}")

            except Exception as e:
                print(f"  [ERROR] by1={by1}: {e}")

        print(f"\n[OK] 导入完成: {success_count}/{len(grouped)} 个产品")

        # 显示统计
        stats = self.store.get_stats()
        print(f"\n集合统计:")
        print(f"  父块数量: {stats['parent_collection']['points_count']}")
        print(f"  子块数量: {stats['child_collection']['points_count']}")

    # ==================== 检索操作 ====================

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> List[Dict]:
        """
        检索产品

        Args:
            query: 查询文本
            top_k: 返回结果数量
            score_threshold: 相似度阈值

        Returns:
            搜索结果列表
        """
        query_vector = self.embedding_client.encode(query)
        results = self.store.search(
            query_vector, top_k=top_k, score_threshold=score_threshold
        )
        return results

    # ==================== 统计操作 ====================

    def get_stats(self) -> Dict:
        """获取系统统计信息"""
        return self.store.get_stats()


# ==================== 命令行接口 ====================

if __name__ == "__main__":
    import sys

    engine = ProductSearchEngine()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "import" and len(sys.argv) > 2:
            csv_file = sys.argv[2]
            engine.import_from_csv(csv_file)

        elif command == "clear":
            engine.clear_all()

        elif command == "rebuild":
            engine.rebuild_collections()

        elif command == "stats":
            stats = engine.get_stats()
            print(f"父块数量: {stats['parent_collection']['points_count']}")
            print(f"子块数量: {stats['child_collection']['points_count']}")

        elif command == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            results = engine.search(query)
            print(f"\n查询: {query}")
            for i, r in enumerate(results, 1):
                print(f"\n[{i}] by1: {r['productName']}")
                print(f"    相似度: {r['score']:.4f}")
                # 兼容新旧数据模型
                if "matched_edescs" in r:
                    print(f"    匹配货描: {r['matched_edescs'][0][:80]}...")
                    print(f"    货描总数: {r.get('edesc_count', 'N/A')}")
                else:
                    print(f"    匹配片段: {r.get('matched_chunks', [''])[0][:80]}...")
                    if "EDesc" in r:
                        print(f"    货描预览: {r['EDesc'][:80]}...")

        else:
            print("用法:")
            print("  python main.py import <csv_file>  # 导入数据")
            print("  python main.py search <query>    # 检索")
            print("  python main.py clear            # 清空数据")
            print("  python main.py rebuild          # 重建集合")
            print("  python main.py stats            # 统计信息")
    else:
        print("用法:")
        print("  python main.py import <csv_file>  # 导入数据")
        print("  python main.py search <query>    # 检索")
        print("  python main.py clear            # 清空数据")
        print("  python main.py rebuild          # 重建集合")
        print("  python main.py stats            # 统计信息")
