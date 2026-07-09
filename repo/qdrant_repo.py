# -*- coding: utf-8 -*-
"""
Qdrant Repository - 数据访问层

封装核心 Qdrant 操作：
- add_product_with_edesc_list: 原子性写入父块 + 子块
- search: 向量检索
- search_by_prefix: by1 前缀匹配（batch_import 依赖）
- delete_by_parent_id: 删除父块及子块（add_edesc 去重时依赖）
"""

from typing import List, Dict, Optional, Any
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct
import logging
import requests as http_req

logger = logging.getLogger(__name__)


class QdrantRepo:
    """Qdrant 数据访问层。"""

    def __init__(self, client: QdrantClient, parent_collection: str, child_collection: str):
        """初始化。

        Args:
            client: Qdrant 客户端。
            parent_collection: 父集合名称。
            child_collection: 子集合名称。
        """
        self.client = client
        self.parent_collection = parent_collection
        self.child_collection = child_collection
        self._base_url = client._client.rest_uri

    # ==================== 写入 ====================

    def add_product_with_edesc_list(
        self,
        product_name: str,
        edesc_list: List[str],
        embedding_func,
        metadata: Optional[Dict] = None,
    ) -> str:
        """原子性写入父块 + 子块 embedding。

        Args:
            product_name: by1 品种编码。
            edesc_list: 标准化货描列表。
            embedding_func: 编码函数。
            metadata: 可选元数据。

        Returns:
            parent_id。
        """
        from utils.id_utils import generate_parent_id, generate_child_id
        from config import EMBEDDING_DIM

        parent_id = generate_parent_id(product_name)

        # 插入/更新父块
        self.client.upsert(
            collection_name=self.parent_collection,
            points=[
                PointStruct(
                    id=parent_id,
                    vector=[0.0] * 4,
                    payload={
                        "productName": product_name,
                        "edesc_list": edesc_list,
                        "edesc_count": len(edesc_list),
                        **(metadata or {}),
                    },
                )
            ],
        )

        # 每条 edesc 独立编码为子块
        if edesc_list and embedding_func:
            embeddings = embedding_func(edesc_list)
            if len(embeddings) != len(edesc_list):
                raise ValueError(
                    f"Embedding count mismatch: expected {len(edesc_list)}, got {len(embeddings)}"
                )

            child_points = []
            for idx, (text, emb) in enumerate(zip(edesc_list, embeddings)):
                vec = list(emb) if not isinstance(emb, list) else emb
                if len(vec) != EMBEDDING_DIM:
                    raise ValueError(
                        f"Embedding dim mismatch: expected {EMBEDDING_DIM}, got {len(vec)}"
                    )
                child_id = generate_child_id(parent_id, idx)
                child_points.append(
                    PointStruct(
                        id=child_id,
                        vector=vec,
                        payload={
                            "parent_id": parent_id,
                            "edesc_index": idx,
                            "edesc_text": text,
                            "productName": product_name,
                        },
                    )
                )

            if child_points:
                self.client.upsert(
                    collection_name=self.child_collection, points=child_points
                )

        logger.info(
            f"Added product: {product_name} (parent_id={parent_id}, edesc_count={len(edesc_list)})"
        )
        return parent_id

    # ==================== 检索 ====================

    def search(
        self, query_vector: List[float], top_k: int = 10, score_threshold: float = None
    ) -> List[Dict]:
        """向量检索：通过子块召回父块，按 parent_id 去重。

        Args:
            query_vector: 查询向量。
            top_k: 返回多少个不同的 by1。
            score_threshold: 相似度阈值。

        Returns:
            匹配结果列表。
        """
        limit = top_k * 5

        # 优先 REST API（避免 SDK 502）
        child_results = []
        try:
            resp = http_req.post(
                f"{self._base_url}/collections/{self.child_collection}/points/search",
                json={"vector": query_vector, "limit": limit, "with_payload": True},
                timeout=30,
            )
            if resp.status_code == 200:
                raw_hits = resp.json().get("result", [])
                child_results = [
                    type("Hit", (), {"score": h["score"], "payload": h.get("payload", {})})()
                    for h in raw_hits
                ]
        except Exception:
            pass

        # Fallback: SDK
        if not child_results:
            try:
                search_response = self.client.query_points(
                    collection_name=self.child_collection,
                    query=query_vector,
                    limit=limit,
                    with_payload=True,
                )
                child_results = search_response.points
            except Exception as e:
                logger.error(f"Search failed: {e}")
                return []

        if not child_results:
            return []

        # 过滤阈值
        if score_threshold:
            child_results = [r for r in child_results if r.score >= score_threshold]
            if not child_results:
                return []

        # 按 parent_id 分组，取最高分
        parent_scores: Dict[str, Dict] = {}
        for hit in child_results:
            parent_id = hit.payload.get("parent_id")
            if not parent_id:
                continue
            if parent_id not in parent_scores:
                parent_scores[parent_id] = {
                    "score": hit.score,
                    "matched_edescs": [hit.payload.get("edesc_text", "")],
                }
            else:
                if hit.score > parent_scores[parent_id]["score"]:
                    parent_scores[parent_id]["score"] = hit.score
                parent_scores[parent_id]["matched_edescs"].append(
                    hit.payload.get("edesc_text", "")
                )

        sorted_parents = sorted(
            parent_scores.items(), key=lambda x: x[1]["score"], reverse=True
        )[:top_k]

        # 召回父块信息
        parent_ids = [pid for pid, _ in sorted_parents]
        parent_map: Dict[str, Any] = {}
        try:
            resp = http_req.post(
                f"{self._base_url}/collections/{self.parent_collection}/points",
                json={"ids": parent_ids, "with_payload": True},
                timeout=15,
            )
            if resp.status_code == 200:
                for pt in resp.json().get("result", []):
                    parent_map[pt["id"]] = type(
                        "P", (), {"payload": pt.get("payload", {})}
                    )()
        except Exception:
            pass

        # Fallback: 从 child payload 获取 productName
        if not parent_map:
            for hit in child_results:
                pid = hit.payload.get("parent_id")
                name = hit.payload.get("productName", "")
                if pid and pid not in parent_map and name:
                    parent_map[pid] = type(
                        "P",
                        (),
                        {
                            "payload": {
                                "productName": name,
                                "edesc_list": [],
                                "edesc_count": 0,
                            }
                        },
                    )()

        results = []
        for parent_id, info in sorted_parents:
            if parent_id in parent_map:
                parent = parent_map[parent_id]
                results.append(
                    {
                        "productName": parent.payload.get("productName", ""),
                        "edesc_list": parent.payload.get("edesc_list", []),
                        "edesc_count": parent.payload.get("edesc_count", 0),
                        "parent_id": parent_id,
                        "score": info["score"],
                        "matched_edescs": info["matched_edescs"][:3],
                        "metadata": parent.payload.get("metadata", {}),
                    }
                )
        return results

    # ==================== 删除 ====================

    def delete_by_parent_id(self, parent_id: str) -> None:
        """删除父块及其所有子块。"""
        self.client.delete(
            collection_name=self.parent_collection, points_selector=[parent_id]
        )
        self.client.delete(
            collection_name=self.child_collection,
            points_selector=Filter(
                must=[
                    FieldCondition(key="parent_id", match=MatchValue(value=parent_id))
                ]
            ),
        )
        logger.debug(f"Deleted parent and children: {parent_id}")

    # ==================== 前缀匹配（batch_import 依赖）====================

    # ==================== 辅助查询（batch_import / add_edesc 依赖）====================

    def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        """根据 by1 获取记录。"""
        results = self.client.scroll(
            collection_name=self.parent_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="productName", match=MatchValue(value=by1))]
            ),
            limit=10,
            with_payload=True,
        )
        points, _ = results
        if not points:
            return None
        point = points[0]
        payload = point.payload
        edesc_list = payload.get("edesc_list", [])
        return {
            "by1": by1,
            "parent_id": point.id,
            "productName": payload.get("productName", ""),
            "edesc_list": edesc_list,
            "edesc_count": payload.get("edesc_count", len(edesc_list)),
            "metadata": payload.get("metadata", {}),
        }

    def get_all_by1s(self, limit: int = 10000) -> List[str]:
        """获取所有 by1 列表。"""
        results = self.client.scroll(
            collection_name=self.parent_collection,
            limit=limit,
            with_payload=True,
        )
        points, _ = results
        return [p.payload.get("productName", "") for p in points]
