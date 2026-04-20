# -*- coding: utf-8 -*-
"""
Qdrant Repository - Qdrant 数据访问层

封装所有 Qdrant 数据库操作，提供清晰的数据访问接口
"""

from typing import List, Dict, Optional, Any
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct
import logging

logger = logging.getLogger(__name__)


class QdrantRepo:
    """
    Qdrant 数据访问层

    封装所有 Qdrant 操作，包括：
    - 按 by1 查询记录
    - 列出所有记录
    - 删除记录
    - 前缀匹配搜索
    """

    def __init__(
        self,
        client: QdrantClient,
        parent_collection: str,
        child_collection: str
    ):
        """
        初始化 Qdrant Repo

        Args:
            client: Qdrant 客户端
            parent_collection: 父集合名称
            child_collection: 子集合名称
        """
        self.client = client
        self.parent_collection = parent_collection
        self.child_collection = child_collection

    # ==================== 查询操作 ====================

    def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        """
        根据 by1 获取记录

        Args:
            by1: 基配品种编码

        Returns:
            记录字典，未找到返回 None
        """
        results = self.client.scroll(
            collection_name=self.parent_collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="productName",
                        match=MatchValue(value=by1)
                    )
                ]
            ),
            limit=10,
            with_payload=True
        )

        points, _ = results

        if not points:
            return None

        point = points[0]
        payload = point.payload

        # 兼容新旧数据模型
        edesc_list = payload.get("edesc_list", [])
        edesc_count = payload.get("edesc_count", len(edesc_list))

        # 如果没有 edesc_list 但有 EDesc（旧数据），则从 EDesc 解析
        if not edesc_list and payload.get("EDesc"):
            edesc_list = [e.strip() for e in payload["EDesc"].split(';') if e.strip()]
            edesc_count = len(edesc_list)

        return {
            "by1": by1,
            "parent_id": point.id,
            "productName": payload.get("productName", ""),
            "EDesc": payload.get("EDesc", "; ".join(edesc_list)),  # 兼容旧字段
            "edesc_list": edesc_list,
            "edesc_count": edesc_count,
            "metadata": payload.get("metadata", {})
        }

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        列出所有记录

        Args:
            limit: 最大返回数量

        Returns:
            记录列表
        """
        results = self.client.scroll(
            collection_name=self.parent_collection,
            limit=limit,
            with_payload=True
        )

        points, _ = results

        items = []
        for p in points:
            payload = p.payload
            edesc_list = payload.get("edesc_list", [])
            edesc_count = payload.get("edesc_count", len(edesc_list))

            # 兼容旧数据
            if not edesc_list and payload.get("EDesc"):
                edesc_list = [e.strip() for e in payload["EDesc"].split(';') if e.strip()]
                edesc_count = len(edesc_list)

            # 生成预览
            if edesc_list:
                edesc_preview = edesc_list[0][:100] + ("..." if len(edesc_list[0]) > 100 else "")
            else:
                edesc_preview = payload.get("EDesc", "")[:100] + "..."

            items.append({
                "by1": payload.get("productName", ""),
                "edesc_preview": edesc_preview,
                "edesc_count": edesc_count
            })

        return items

    def get_all_by1s(self, limit: int = 10000) -> List[str]:
        """
        获取所有 by1 列表

        Args:
            limit: 最大返回数量

        Returns:
            by1 列表
        """
        results = self.client.scroll(
            collection_name=self.parent_collection,
            limit=limit,
            with_payload=True
        )

        points, _ = results
        return [p.payload.get("productName", "") for p in points]

    # ==================== 写入操作 ====================

    def upsert_parent(
        self,
        parent_id: str,
        product_name: str,
        edesc_list: list,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        插入或更新父块

        Args:
            parent_id: 父块 ID
            product_name: 产品名称
            edesc_list: 标准化货描列表
            metadata: 元数据
        """
        parent_payload = {
            "productName": product_name,
            "edesc_list": edesc_list,
            "edesc_count": len(edesc_list),
            **(metadata or {})
        }

        self.client.upsert(
            collection_name=self.parent_collection,
            points=[PointStruct(
                id=parent_id,
                vector=[0.0] * 4,  # 4 维占位向量
                payload=parent_payload
            )]
        )

        logger.debug(f"Upserted parent: {parent_id} ({product_name})")

    def upsert_children(
        self,
        child_points: List[PointStruct]
    ) -> None:
        """
        批量插入子块

        Args:
            child_points: 子块点列表
        """
        if child_points:
            self.client.upsert(
                collection_name=self.child_collection,
                points=child_points
            )
            logger.debug(f"Upserted {len(child_points)} child points")

    # ==================== 删除操作 ====================

    def delete_by_parent_id(self, parent_id: str) -> None:
        """
        删除父块及子块

        Args:
            parent_id: 父块 ID
        """
        # 删除父块
        self.client.delete(
            collection_name=self.parent_collection,
            points_selector=[parent_id]
        )

        # 删除关联的子块
        self.client.delete(
            collection_name=self.child_collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="parent_id",
                        match=MatchValue(value=parent_id)
                    )
                ]
            )
        )

        logger.debug(f"Deleted parent and children: {parent_id}")

    # ==================== 前缀匹配 ====================

    def search_by_prefix(
        self,
        new_by1: str,
        all_by1s: List[str],
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        前缀匹配搜索

        Args:
            new_by1: 新的 by1
            all_by1s: 所有 by1 列表
            top_k: 返回数量

        Returns:
            匹配结果列表
        """
        results = []

        for by1 in all_by1s:
            if by1 == new_by1:
                continue

            score = self._calculate_prefix_similarity(new_by1, by1)
            if score > 0:
                results.append({
                    "by1": by1,
                    "score": score,
                    "prefix_match_len": int(score * max(len(new_by1), len(by1)))
                })

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _calculate_prefix_similarity(self, by1_a: str, by1_b: str) -> float:
        """
        计算两个 by1 的前缀相似度

        Args:
            by1_a: 第一个 by1
            by1_b: 第二个 by1

        Returns:
            相似度分数 (0-1)
        """
        a = by1_a.upper()
        b = by1_b.upper()

        min_len = min(len(a), len(b))
        prefix_len = 0

        for i in range(min_len):
            if a[i] == b[i]:
                prefix_len += 1
            else:
                break

        max_len = max(len(a), len(b))
        if max_len == 0:
            return 0.0

        return prefix_len / max_len

    # ==================== 导出操作 ====================

    def export_all(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """
        导出所有数据

        Args:
            limit: 最大导出数量

        Returns:
            数据列表
        """
        results = self.client.scroll(
            collection_name=self.parent_collection,
            limit=limit,
            with_payload=True
        )

        points, _ = results

        items = []
        for p in points:
            payload = p.payload
            edesc_list = payload.get("edesc_list", [])
            items.append({
                "by1": payload.get("productName", ""),
                "edesc_list": edesc_list,
                "edesc_count": payload.get("edesc_count", len(edesc_list)),
                "EDesc": "; ".join(edesc_list),
                "source_by1": payload.get("source_by1", ""),
                "source_score": payload.get("source_score", ""),
                "import_strategy": payload.get("import_strategy", ""),
                "parent_id": p.id
            })
        return items
