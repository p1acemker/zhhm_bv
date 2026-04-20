# -*- coding: utf-8 -*-
"""
Qdrant 向量库操作模块
- 建库：创建父/子集合
- 增：添加产品和货描
- 删：删除产品
- 改：更新产品
- 查：向量检索（按 parent_id 去重）

数据模型：
- 父块：存储 by1 和货描列表
- 子块：每条独立货描的 embedding
"""

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, PayloadSchemaType
)
from typing import List, Dict, Optional
import logging

# 使用 utils 模块中的 ID 生成函数
from utils.id_utils import generate_parent_id, generate_child_id

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """
    Qdrant 父子向量存储

    - Parent Collection: 存储 by1 和货描列表
    - Child Collection: 存储每条独立货描的 embedding
    - 检索时通过子块召回父块，按 parent_id 去重
    """

    def __init__(
        self,
        url: str = None,
        embedding_dim: int = None,
        parent_collection: str = None,
        child_collection: str = None
    ):
        """初始化 Qdrant 向量存储"""
        from config import QDRANT_URL, EMBEDDING_DIM, PARENT_COLLECTION, CHILD_COLLECTION

        self.client = QdrantClient(url=url or QDRANT_URL, timeout=60, check_compatibility=False)
        self.embedding_dim = embedding_dim or EMBEDDING_DIM
        self.parent_collection = parent_collection or PARENT_COLLECTION
        self.child_collection = child_collection or CHILD_COLLECTION

    # ==================== 建库 ====================

    def init_collections(self):
        """
        初始化/创建父集合和子集合
        """
        # 父集合 - 存储完整信息，使用小向量作为占位
        if not self.client.collection_exists(self.parent_collection):
            self.client.create_collection(
                collection_name=self.parent_collection,
                vectors_config=VectorParams(
                    size=4,  # 占位向量
                    distance=Distance.COSINE
                )
            )
            logger.info(f"Created parent collection: {self.parent_collection}")

        # 子集合 - 存储嵌入向量
        if not self.client.collection_exists(self.child_collection):
            self.client.create_collection(
                collection_name=self.child_collection,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
            # 为 parent_id 创建索引，加速关联查询
            self.client.create_payload_index(
                collection_name=self.child_collection,
                field_name="parent_id",
                field_schema=PayloadSchemaType.KEYWORD
            )
            # 为 productName 创建索引，加速按 by1 查询
            self.client.create_payload_index(
                collection_name=self.child_collection,
                field_name="productName",
                field_schema=PayloadSchemaType.KEYWORD
            )
            logger.info(f"Created child collection: {self.child_collection}")

    def clear_collections(self):
        """清空所有数据"""
        for collection in [self.parent_collection, self.child_collection]:
            self.client.delete(
                collection_name=collection,
                points_selector=Filter()
            )
        logger.info("Cleared all collection data")

    def delete_collections(self):
        """删除集合"""
        if self.client.collection_exists(self.parent_collection):
            self.client.delete_collection(self.parent_collection)
            logger.info(f"Deleted parent collection: {self.parent_collection}")
        if self.client.collection_exists(self.child_collection):
            self.client.delete_collection(self.child_collection)
            logger.info(f"Deleted child collection: {self.child_collection}")

    # ==================== 增 - 添加数据 ====================

    def add_product(
        self,
        product_name: str,
        edesc: str,
        embedding_func,
        metadata: Optional[Dict] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ) -> str:
        """
        添加产品（兼容旧接口，内部调用 add_product_with_edesc_list）

        Args:
            product_name: 产品名称/by1
            edesc: 产品描述（单条或分号分隔的多条）
            embedding_func: 嵌入函数
            metadata: 额外元数据
            chunk_size: 每段字符数（已废弃，保留兼容）
            chunk_overlap: 段间重叠字符数（已废弃，保留兼容）

        Returns:
            parent_id: 父块 ID
        """
        # 按分号分割货描
        edesc_list = [e.strip() for e in edesc.split(';') if e.strip()]
        return self.add_product_with_edesc_list(product_name, edesc_list, embedding_func, metadata)

    def add_product_with_edesc_list(
        self,
        product_name: str,
        edesc_list: List[str],
        embedding_func,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        添加产品，每条货描作为独立子块

        Args:
            product_name: 产品名称/by1
            edesc_list: 货描列表（每条货描独立存储）
            embedding_func: 嵌入函数
            metadata: 额外元数据

        Returns:
            parent_id: 父块 ID
        """
        # 生成父块 ID（基于 product_name，不基于 edesc，保证相同 by1 生成相同 ID）
        parent_id = generate_parent_id(product_name)

        # 1. 插入或更新父块
        # 先检查是否已存在
        existing_parent = None
        try:
            existing = self.client.retrieve(
                collection_name=self.parent_collection,
                ids=[parent_id],
                with_payload=True
            )
            if existing:
                existing_parent = existing[0]
        except Exception:
            pass

        # 合并已有货描和新货描
        if existing_parent:
            existing_edesc_list = existing_parent.payload.get("edesc_list", [])
            # 合并去重
            all_edesc = list(set(existing_edesc_list + edesc_list))
            edesc_count = len(all_edesc)
            # 合并 metadata
            new_metadata = dict(existing_parent.payload.get("metadata", {}))
            new_metadata.update(metadata or {})
        else:
            all_edesc = edesc_list
            edesc_count = len(edesc_list)
            new_metadata = metadata or {}

        parent_payload = {
            "productName": product_name,
            "edesc_list": all_edesc,
            "edesc_count": edesc_count,
            "metadata": new_metadata
        }

        self.client.upsert(
            collection_name=self.parent_collection,
            points=[PointStruct(
                id=parent_id,
                vector=[0.0] * 4,
                payload=parent_payload
            )]
        )

        # 2. 为每条货描生成子块 embedding（批量调用，提高效率）
        if embedding_func and edesc_list:
            child_points = []

            # 获取已有子块数量，用于确定起始索引
            existing_child_count = 0
            if existing_parent:
                # 查询已有子块数量
                existing_children = self.client.scroll(
                    collection_name=self.child_collection,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="parent_id", match=MatchValue(value=parent_id))]
                    ),
                    limit=10000,
                    with_payload=False
                )
                existing_child_count = len(existing_children[0]) if existing_children[0] else 0

            # 批量获取所有 embedding（一次 API 调用）
            logger.debug(f"Batch encoding {len(edesc_list)} edescs for {product_name}")
            embeddings = embedding_func(edesc_list)  # 批量调用

            # 校验返回数量
            if len(embeddings) != len(edesc_list):
                raise ValueError(
                    f"Embedding count mismatch: expected {len(edesc_list)}, got {len(embeddings)}"
                )

            for idx, (edesc_text, embedding) in enumerate(zip(edesc_list, embeddings)):
                # 校验 embedding 维度
                if len(embedding) != self.embedding_dim:
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {self.embedding_dim}, "
                        f"got {len(embedding)} for edesc {idx}"
                    )

                child_id = generate_child_id(parent_id, existing_child_count + idx)

                child_points.append(PointStruct(
                    id=child_id,
                    vector=embedding,
                    payload={
                        "parent_id": parent_id,
                        "edesc_index": existing_child_count + idx,
                        "edesc_text": edesc_text,
                        "productName": product_name
                    }
                ))

            # 批量插入子块
            if child_points:
                self.client.upsert(
                    collection_name=self.child_collection,
                    points=child_points
                )
                logger.debug(f"Added {len(child_points)} child edesc blocks for {product_name}")

        logger.info(f"Added product: {product_name} (parent_id={parent_id}, edesc_count={edesc_count})")
        return parent_id

    # ==================== 删 - 删除数据 ====================

    def delete_by_parent_id(self, parent_id: str):
        """删除父块及其所有子块"""
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

    # ==================== 查 - 向量检索 ====================

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        score_threshold: float = None
    ) -> List[Dict]:
        """
        向量检索：通过子块召回父块，按 parent_id 去重

        Args:
            query_vector: 查询向量
            top_k: 返回多少个不同的 by1
            score_threshold: 相似度阈值

        Returns:
            包含 productName 的结果列表（每个 by1 只出现一次）
        """
        # 1. 在子集合中搜索，多取一些用于去重
        search_result = self.client.query_points(
            collection_name=self.child_collection,
            query=query_vector,
            limit=top_k * 5,  # 多取一些用于去重
            with_payload=True
        )

        child_results = search_result.points
        if not child_results:
            return []

        # 过滤阈值
        if score_threshold:
            child_results = [r for r in child_results if r.score >= score_threshold]
            if not child_results:
                return []

        # 2. 按 parent_id 分组，取最高分（去重）
        parent_scores = {}
        for hit in child_results:
            parent_id = hit.payload.get("parent_id")
            if not parent_id:
                continue

            if parent_id not in parent_scores:
                parent_scores[parent_id] = {
                    "score": hit.score,
                    "matched_edescs": [hit.payload.get("edesc_text", "")]
                }
            else:
                # 保留最高分
                if hit.score > parent_scores[parent_id]["score"]:
                    parent_scores[parent_id]["score"] = hit.score
                # 收集所有匹配的货描
                parent_scores[parent_id]["matched_edescs"].append(hit.payload.get("edesc_text", ""))

        # 3. 按分数排序，取 top_k 个不同的 by1
        sorted_parents = sorted(
            parent_scores.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )[:top_k]

        # 4. 召回父块信息
        results = []
        parent_ids = [pid for pid, _ in sorted_parents]
        parent_points = self.client.retrieve(
            collection_name=self.parent_collection,
            ids=parent_ids,
            with_payload=True
        )

        parent_map = {p.id: p for p in parent_points}

        for parent_id, info in sorted_parents:
            if parent_id in parent_map:
                parent = parent_map[parent_id]
                results.append({
                    "productName": parent.payload.get("productName", ""),
                    "edesc_list": parent.payload.get("edesc_list", []),
                    "edesc_count": parent.payload.get("edesc_count", 0),
                    "parent_id": parent_id,
                    "score": info["score"],
                    "matched_edescs": info["matched_edescs"][:3],  # 最多显示3条匹配的货描
                    "metadata": parent.payload.get("metadata", {})
                })

        return results

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict:
        """获取集合统计信息"""
        parent_info = self.client.get_collection(self.parent_collection)
        child_info = self.client.get_collection(self.child_collection)

        return {
            "parent_collection": {
                "name": self.parent_collection,
                "points_count": parent_info.points_count
            },
            "child_collection": {
                "name": self.child_collection,
                "points_count": child_info.points_count
            }
        }
