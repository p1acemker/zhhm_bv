# -*- coding: utf-8 -*-
"""
货描维护接口模块 - CLI 入口

重构说明：
- 此文件保留作为 CLI 兼容层
- 业务逻辑已迁移到 service/edesc_service.py
- EDescMaintenance 类现在只是 Service 的包装器
"""

from typing import List, Dict, Optional
import logging

# 配置日志
from config import LOG_LEVEL
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class EDescMaintenance:
    """
    货描维护接口 - 兼容层

    此类包装 EDescService，保持原有接口不变
    新代码应直接使用 service.EDescService
    """

    def __init__(self):
        """初始化维护接口"""
        logger.info("Initializing EDescMaintenance (compatibility layer)...")
        from qdrant_store import QdrantVectorStore
        from embedder import BGEEmbedder
        from repo import QdrantRepo
        from service import EDescService

        self.store = QdrantVectorStore()
        self.store.init_collections()
        self.embedding_client = BGEEmbedder()

        repo = QdrantRepo(
            client=self.store.client,
            parent_collection=self.store.parent_collection,
            child_collection=self.store.child_collection
        )

        self._service = EDescService(
            store=self.store,
            embedder=self.embedding_client,
            repo=repo,
        )

        logger.info("EDescMaintenance initialized")

    # ==================== 查询操作（委托给 Service）====================

    def get_edesc_by_by1(self, by1: str) -> Optional[Dict]:
        """根据by1查询对应的货物描述"""
        return self._service.get_by1(by1)

    def list_all_by1(self, limit: int = 100) -> List[Dict]:
        """列出所有基配品种by1及其货描摘要"""
        return self._service.list_by1(limit=limit)

    def search_by1_by_edesc(self, edesc_query: str, top_k: int = 10) -> List[Dict]:
        """根据货描文本搜索匹配的by1"""
        return self._service.search_by_edesc(edesc_query, top_k=top_k)

    # ==================== 添加操作 ====================

    def add_edesc_for_by1(
        self,
        by1: str,
        edesc: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """为基配品种by1添加货描"""
        return self._service.add_edesc(by1, edesc, metadata)

    # ==================== 更新操作 ====================

    def update_edesc_for_by1(
        self,
        by1: str,
        new_edesc: str,
        append: bool = False,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """更新基配品种by1的货描"""
        return self._service.update_edesc(by1, new_edesc, append, metadata)

    # ==================== 删除操作 ====================

    def delete_by1(self, by1: str) -> Dict:
        """删除基配品种by1及其货描"""
        return self._service.delete_by1(by1)

    # ==================== 前缀匹配搜索 ====================

    def search_by1_by_prefix(self, new_by1: str, top_k: int = 10) -> List[Dict]:
        """根据by1前缀匹配搜索相似的品种"""
        return self._service.search_by_prefix(new_by1, top_k=top_k)

    # ==================== 智能导入操作 ====================

    def import_new_by1_with_similar_edesc(
        self,
        new_by1: str,
        top_k: int = 5,
        strategy: str = "most_references"
    ) -> Dict:
        """为新研发的by1智能匹配并导入货描"""
        return self._service.import_by1(new_by1, strategy=strategy, top_k=top_k)

    def preview_similar_edesc(self, new_by1: str, top_k: int = 5) -> Dict:
        """预览相似品种的货描（不实际导入）"""
        return self._service.preview_import(new_by1, top_k=top_k)

    # ==================== 批量操作 ====================

    def batch_add_edesc(self, data_list: List[Dict]) -> Dict:
        """批量添加货描"""
        return self._service.batch_add_edesc(data_list)


# ==================== 命令行接口 ====================

def print_usage():
    print("""
货描维护接口 - 使用说明
========================

查询操作:
  python edesc_maintenance.py get <by1>              # 查询指定by1的货描
  python edesc_maintenance.py list [limit]           # 列出所有by1
  python edesc_maintenance.py search <货描文本>       # 根据货描搜索by1 (向量搜索)

智能导入操作 (前缀匹配):
  python edesc_maintenance.py preview <新by1>        # 预览前缀匹配的品种
  python edesc_maintenance.py import <新by1> [策略]  # 智能导入新by1
  python edesc_maintenance.py batch-import <by1> <by2> ...  # 批量智能导入

  匹配策略:
    most_references  - 从前缀匹配的候选中选择引用数最多的 (默认)
    highest_score    - 选择前缀匹配度最高的
    combined         - 综合匹配度和引用数

添加操作:
  python edesc_maintenance.py add <by1> <货描>       # 添加货描（自动去重追加）

  逻辑说明:
    - 如果by1已存在: 检查货描是否重复，重复则跳过，不重复则追加
    - 如果by1不存在: 创建新记录

更新操作:
  python edesc_maintenance.py update <by1> <新货描>  # 替换货描
  python edesc_maintenance.py update <by1> <货描> --append  # 追加货描

删除操作:
  python edesc_maintenance.py delete <by1>           # 删除by1及其货描

示例:
  # 智能导入新研发品种 (基于by1前缀匹配)
  python edesc_maintenance.py preview XD371X210
  python edesc_maintenance.py import XD371X210
  python edesc_maintenance.py import XD371X210 highest_score
  python edesc_maintenance.py batch-import XD371X210 XD371X209

  # 其他操作
  python edesc_maintenance.py get D71X4
  python edesc_maintenance.py search "Wafer Butterfly Valve"
""")


if __name__ == "__main__":
    import sys
    import json

    def print_json(data):
        print(json.dumps(data, ensure_ascii=False, indent=2))

    maintenance = EDescMaintenance()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "get" and len(sys.argv) > 2:
            # 查询by1的货描
            by1 = sys.argv[2]
            result = maintenance.get_edesc_by_by1(by1)
            if result:
                print(f"\n=== by1: {by1} ===")
                # 兼容新旧数据模型
                if 'edesc_list' in result and result['edesc_list']:
                    print(f"货描数量: {result.get('edesc_count', len(result['edesc_list']))}条")
                    for i, edesc in enumerate(result['edesc_list'][:5], 1):
                        print(f"  [{i}] {edesc[:100]}...")
                    if len(result['edesc_list']) > 5:
                        print(f"  ... 还有 {len(result['edesc_list']) - 5} 条")
                else:
                    print(f"货描: {result.get('EDesc', '')[:200]}...")
                    print(f"货描数量: {result.get('edesc_count', 0)}")
            else:
                print(f"未找到 by1={by1}")

        elif command == "list":
            # 列出所有by1
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
            results = maintenance.list_all_by1(limit=limit)
            print(f"\n共 {len(results)} 个基配品种:")
            for r in results:
                # 兼容新旧数据模型
                preview = r.get('edesc_preview', r.get('EDesc', ''))[:60]
                count = r.get('edesc_count', 0)
                print(f"  - {r['by1']}: {preview}... ({count}条)")

        elif command == "search" and len(sys.argv) > 2:
            # 根据货描搜索by1
            query = ' '.join(sys.argv[2:])
            results = maintenance.search_by1_by_edesc(query)
            print(f"\n查询: {query}")
            for i, r in enumerate(results, 1):
                print(f"\n[{i}] by1: {r['productName']}")
                print(f"    相似度: {r['score']:.4f}")
                # 兼容新旧数据模型
                if 'matched_edescs' in r:
                    matched = r['matched_edescs']
                    print(f"    匹配货描: {matched[0][:80] if matched else 'N/A'}...")
                    print(f"    货描总数: {r.get('edesc_count', 'N/A')}")
                else:
                    matched = r.get('matched_chunks', [''])
                    print(f"    匹配片段: {matched[0][:80] if matched else 'N/A'}...")

        elif command == "add" and len(sys.argv) > 3:
            # 添加新by1的货描
            by1 = sys.argv[2]
            edesc = sys.argv[3]
            result = maintenance.add_edesc_for_by1(by1, edesc)
            print_json(result)

        elif command == "update" and len(sys.argv) > 3:
            # 更新by1的货描
            by1 = sys.argv[2]
            edesc = sys.argv[3]
            append = "--append" in sys.argv
            result = maintenance.update_edesc_for_by1(by1, edesc, append=append)
            print_json(result)

        elif command == "delete" and len(sys.argv) > 2:
            # 删除by1
            by1 = sys.argv[2]
            result = maintenance.delete_by1(by1)
            print_json(result)

        elif command == "preview" and len(sys.argv) > 2:
            # 预览相似品种
            by1 = sys.argv[2]
            result = maintenance.preview_similar_edesc(by1)
            if result.get("exists"):
                print(f"\n{by1} 已存在")
                print_json(result)
            else:
                print(f"\n=== 与 {by1} 前缀匹配的品种 ===")
                print(f"共找到 {result['total_found']} 个候选\n")
                for i, c in enumerate(result["candidates"], 1):
                    marker = " [推荐]" if result.get("recommended") and c["by1"] == result["recommended"]["by1"] else ""
                    print(f"[{i}] {c['by1']}{marker}")
                    print(f"    前缀匹配: {c['prefix_match_len']}位 ({c['score']:.2%})")
                    print(f"    货描引用数: {c['edesc_count']}")
                    print(f"    货描预览: {c['edesc_preview']}")
                    print()

        elif command == "import" and len(sys.argv) > 2:
            # 智能导入新by1
            by1 = sys.argv[2]
            strategy = sys.argv[3] if len(sys.argv) > 3 else "most_references"

            print(f"\n=== 为 {by1} 智能匹配货描 (前缀匹配) ===")
            print(f"策略: {strategy}")
            print()

            result = maintenance.import_new_by1_with_similar_edesc(by1, strategy=strategy)

            if result["success"]:
                print(f"[成功] {result['message']}")
                print(f"\n匹配来源: {result['selected_source']['by1']}")
                print(f"  - 前缀匹配: {result['selected_source']['prefix_match_len']}位 ({result['selected_source']['score']:.2%})")
                print(f"  - 货描引用数: {result['selected_source']['edesc_count']}")
                print(f"\n所有候选:")
                for c in result["all_candidates"]:
                    print(f"  - {c['by1']}: 前缀{c['prefix_match_len']}位({c['score']:.2%}), 引用数={c['edesc_count']}")
                print(f"\n导入的货描预览:")
                print(f"  {result['imported_edesc_preview']}")
            else:
                print(f"[失败] {result['message']}")
                print_json(result)

        elif command == "batch-import" and len(sys.argv) > 2:
            # 批量智能导入
            by1_list = sys.argv[2:]
            strategy = "most_references"

            print(f"\n=== 批量智能导入 ===")
            print(f"品种数量: {len(by1_list)}")
            print(f"策略: {strategy}\n")

            results = []
            for by1 in by1_list:
                result = maintenance.import_new_by1_with_similar_edesc(by1, strategy=strategy)
                results.append({"by1": by1, **result})
                status = "成功" if result["success"] else "失败"
                source = result.get("selected_source", {}).get("by1", "N/A")
                print(f"  {by1}: {status} <- {source}")

            success_count = sum(1 for r in results if r["success"])
            print(f"\n完成: {success_count}/{len(by1_list)} 成功")

        else:
            print_usage()

    else:
        print_usage()
