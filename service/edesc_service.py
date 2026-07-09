# -*- coding: utf-8 -*-
"""
EDesc Service - 核心业务逻辑层

桥接 api.py 与 qdrant_repo，支撑 3 个核心 API：
- search_by_edesc_raw: 向量检索
- add_edesc: 添加货描
- batch_import: 批量智能导入
"""

from typing import List, Dict, Optional, Any
import logging
import json
import os

from embedder.base import BaseEmbedder
from repo.qdrant_repo import QdrantRepo
from qdrant_store import QdrantVectorStore
from strategy.import_strategy import Candidate, rank_prefix_matches, select_best
from utils.id_utils import generate_parent_id, generate_child_id
from qdrant_client.models import PointStruct

logger = logging.getLogger(__name__)


def _standardize(edesc: str) -> str:
    """调用 7 段标准化，返回标准化后的字符串。

    Args:
        edesc: 原始货描文本。

    Returns:
        标准化后的字符串。
    """
    from scripts.edesc_standardizer import standardize_edesc

    result = standardize_edesc(edesc)
    return result["standardized"]


class EDescService:
    """货描维护业务逻辑层。"""

    def __init__(
        self,
        store: QdrantVectorStore,
        embedder: BaseEmbedder,
        repo: QdrantRepo,
    ):
        """初始化。

        Args:
            store: 向量存储。
            embedder: Embedder。
            repo: 数据访问层。
        """
        self.store = store
        self.embedder = embedder
        self.repo = repo
        self._spec_rules: Optional[dict] = None
        logger.info("EDescService initialized")

    def _get_spec_rules(self) -> dict:
        """延迟加载客户规格规则表。"""
        if self._spec_rules is None:
            rule_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "by1_customer_spec_rules.json",
            )
            if os.path.exists(rule_path):
                with open(rule_path, "r", encoding="utf-8") as f:
                    self._spec_rules = json.load(f)
                logger.info(f"Loaded spec rules: {len(self._spec_rules)} by1 entries")
            else:
                self._spec_rules = {}
        return self._spec_rules

    # ==================== 核心方法 ====================

    def search_by_edesc_raw(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = None,
        customer: str = None,
    ) -> List[Dict[str, Any]]:
        """根据货描文本搜索匹配的 by1（仅向量召回）。

        Args:
            query: 货描查询文本。
            top_k: 返回结果数量。
            score_threshold: 相似度阈值（可选）。
            customer: 客户简称（可选），匹配时附带该客户对应规格。

        Returns:
            匹配结果列表。
        """
        std_query = _standardize(query)
        logger.debug(f"Raw searching: {std_query[:50]}...")
        query_vector = self.embedder.encode(std_query)
        vec_results = self.repo.search(
            query_vector, top_k=top_k, score_threshold=score_threshold
        )

        if customer:
            rules = self._get_spec_rules()
            for r in vec_results:
                by1_key = r.get("productName", "")
                cust_specs = rules.get(by1_key, {}).get(customer)
                r["matched_specs"] = cust_specs
        else:
            for r in vec_results:
                r["matched_specs"] = None

        return vec_results

    def add_edesc(
        self, by1: str, edesc: str, metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """添加货描（自动标准化 + 去重）。

        Args:
            by1: 基配品种编码。
            edesc: 货物描述。
            metadata: 可选元数据。

        Returns:
            操作结果。
        """
        logger.info(f"Adding edesc for by1={by1}")
        original = edesc.strip()
        std_edesc = _standardize(original)

        existing = self.repo.get_by_by1(by1)

        if existing:
            existing_list = existing.get("edesc_list", [])
            if std_edesc in existing_list:
                logger.info(f"Duplicate edesc for by1={by1}, skipping")
                return {
                    "success": False,
                    "message": f"by1={by1} 的货描已存在，无需重复添加",
                    "is_duplicate": True,
                    "existing_edesc_count": len(existing_list),
                }

            new_edesc_list = existing_list + [std_edesc]
            new_metadata = existing.get("metadata", {})
            new_metadata["by1"] = by1
            new_metadata["edesc_count"] = len(new_edesc_list)
            if metadata:
                new_metadata.update(metadata)

            # 删除旧记录再重建
            self.repo.delete_by_parent_id(existing["parent_id"])
            parent_id = self._add_product_with_embedding(
                product_name=by1, edesc_list=new_edesc_list, metadata=new_metadata
            )
            return {
                "success": True,
                "message": f"成功为 by1={by1} 追加货描",
                "action": "appended",
                "parent_id": parent_id,
                "original": original,
                "standardized": std_edesc,
                "old_edesc_count": len(existing_list),
                "new_edesc_count": len(new_edesc_list),
            }
        else:
            parent_id = self._add_product_with_embedding(
                product_name=by1,
                edesc_list=[std_edesc],
                metadata=metadata or {"by1": by1, "edesc_count": 1},
            )
            return {
                "success": True,
                "message": f"成功添加新 by1={by1}",
                "action": "created",
                "parent_id": parent_id,
                "original": original,
                "standardized": std_edesc,
            }

    def batch_import(
        self, by1_list: List[str], strategy: str = "most_references"
    ) -> Dict[str, Any]:
        """批量智能导入。

        Args:
            by1_list: by1 列表。
            strategy: 选择策略（当前仅支持 most_references）。

        Returns:
            批量导入结果。
        """
        logger.info(f"Batch importing {len(by1_list)} by1s")
        results = []
        success_count = 0

        for by1 in by1_list:
            result = self._import_single(by1)
            results.append({"by1": by1, **result})
            if result["success"]:
                success_count += 1

        return {
            "total": len(by1_list),
            "success_count": success_count,
            "fail_count": len(by1_list) - success_count,
            "details": results,
        }

    # ==================== 内部方法 ====================

    def _import_single(self, new_by1: str) -> Dict[str, Any]:
        """导入单个 by1。"""
        existing = self.repo.get_by_by1(new_by1)
        if existing:
            return {
                "success": False,
                "message": f"by1={new_by1} 已存在",
                "existing_data": existing,
            }

        all_by1s = self.repo.get_all_by1s()
        similar = rank_prefix_matches(new_by1, all_by1s, top_k=5)
        if not similar:
            return {"success": False, "message": f"未找到与 {new_by1} 前缀匹配的品种"}

        candidates = []
        for r in similar:
            detail = self.repo.get_by_by1(r["by1"])
            if detail:
                candidates.append(
                    Candidate(
                        by1=r["by1"],
                        score=r["score"],
                        prefix_match_len=r["prefix_match_len"],
                        edesc_count=detail["edesc_count"],
                        edesc="; ".join(detail.get("edesc_list", [])),
                    )
                )

        if not candidates:
            return {"success": False, "message": "无法获取候选品种详情"}

        selected = select_best(candidates)
        source_detail = self.repo.get_by_by1(selected.by1)
        source_edesc_list = source_detail.get("edesc_list", []) if source_detail else []

        parent_id = self._add_product_with_embedding(
            product_name=new_by1,
            edesc_list=source_edesc_list,
            metadata={
                "by1": new_by1,
                "edesc_count": selected.edesc_count,
                "source_by1": selected.by1,
                "source_score": round(selected.score, 4),
                "prefix_match_len": selected.prefix_match_len,
            },
        )

        logger.info(f"Imported by1={new_by1} from source={selected.by1}")
        return {
            "success": True,
            "message": f"成功为 {new_by1} 导入货描",
            "new_by1": new_by1,
            "selected_source": {
                "by1": selected.by1,
                "score": round(selected.score, 4),
                "prefix_match_len": selected.prefix_match_len,
                "edesc_count": selected.edesc_count,
            },
            "parent_id": parent_id,
        }

    def _add_product_with_embedding(
        self, product_name: str, edesc_list: list, metadata: Optional[Dict] = None
    ) -> str:
        """添加产品及其嵌入向量。

        Args:
            product_name: 产品名称。
            edesc_list: 标准化货描列表。
            metadata: 元数据。

        Returns:
            parent_id。
        """
        return self.repo.add_product_with_edesc_list(
            product_name=product_name,
            edesc_list=edesc_list,
            embedding_func=self.embedder.encode,
            metadata=metadata,
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。"""
        return self.store.get_stats()
