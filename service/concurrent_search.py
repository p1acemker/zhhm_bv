# -*- coding: utf-8 -*-
"""
高并发搜索服务

支持批量查询、并行处理
"""

import asyncio
from typing import List, Dict, Optional
import logging
from datetime import datetime

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

logger = logging.getLogger(__name__)


class ConcurrentSearchService:
    """
    高并发搜索服务

    特性：
    - 批量查询：一次请求处理多个查询
    - 并行 embedding：并行获取多个查询的向量
    - 连接复用：复用 Qdrant 连接
    """

    def __init__(
        self,
        qdrant_url: str,
        parent_collection: str,
        child_collection: str,
        async_embedder
    ):
        """
        初始化高并发搜索服务

        Args:
            qdrant_url: Qdrant 服务地址
            parent_collection: 父集合名称
            child_collection: 子集合名称
            async_embedder: 异步 Embedder 实例
        """
        self.client = QdrantClient(url=qdrant_url)
        self.parent_collection = parent_collection
        self.child_collection = child_collection
        self.embedder = async_embedder

        logger.info(f"ConcurrentSearchService initialized: {qdrant_url}")

    async def search_single(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = None
    ) -> List[Dict]:
        """
        单个查询（异步）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            score_threshold: 相似度阈值

        Returns:
            搜索结果列表
        """
        # 1. 异步获取 embedding
        query_vector = await self.embedder.encode(query)

        # 2. 在子集合中搜索
        search_result = self.client.query_points(
            collection_name=self.child_collection,
            query=query_vector,
            limit=top_k * 5,
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

        # 3. 按 parent_id 去重
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
                if hit.score > parent_scores[parent_id]["score"]:
                    parent_scores[parent_id]["score"] = hit.score
                parent_scores[parent_id]["matched_edescs"].append(
                    hit.payload.get("edesc_text", "")
                )

        # 4. 排序取 top_k
        sorted_parents = sorted(
            parent_scores.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )[:top_k]

        # 5. 召回父块
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
                    "matched_edescs": info["matched_edescs"][:3],
                    "metadata": parent.payload.get("metadata", {})
                })

        return results

    async def search_batch(
        self,
        queries: List[str],
        top_k: int = 10,
        score_threshold: float = None,
        max_concurrent: int = 10
    ) -> List[Dict]:
        """
        批量查询（高并发）

        Args:
            queries: 查询文本列表
            top_k: 每个查询返回结果数量
            score_threshold: 相似度阈值
            max_concurrent: 最大并发数

        Returns:
            每个查询的结果列表
        """
        start_time = datetime.now()
        logger.info(f"Batch search started: {len(queries)} queries")

        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)

        async def search_with_limit(query: str):
            async with semaphore:
                try:
                    return await self.search_single(query, top_k, score_threshold)
                except Exception as e:
                    logger.error(f"Search failed for query '{query[:50]}...': {e}")
                    return []

        # 并行执行所有查询
        tasks = [search_with_limit(query) for query in queries]
        results = await asyncio.gather(*tasks)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Batch search completed: {len(queries)} queries in {elapsed:.2f}s")

        return results

    async def search_batch_optimized(
        self,
        queries: List[str],
        top_k: int = 10,
        score_threshold: float = None
    ) -> List[Dict]:
        """
        优化的批量查询

        先批量获取所有 embedding，再批量查询 Qdrant

        Args:
            queries: 查询文本列表
            top_k: 每个查询返回结果数量
            score_threshold: 相似度阈值

        Returns:
            每个查询的结果列表
        """
        start_time = datetime.now()
        logger.info(f"Optimized batch search started: {len(queries)} queries")

        # 1. 批量获取所有 embedding（并行）
        query_vectors = await self.embedder.encode(queries, batch_size=32)
        logger.debug(f"Got {len(query_vectors)} embeddings")

        # 2. 对每个向量进行搜索
        results = []
        for i, query_vector in enumerate(query_vectors):
            try:
                search_result = self.client.query_points(
                    collection_name=self.child_collection,
                    query=query_vector,
                    limit=top_k * 5,
                    with_payload=True
                )

                child_results = search_result.points
                if score_threshold:
                    child_results = [r for r in child_results if r.score >= score_threshold]

                # 去重
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
                        if hit.score > parent_scores[parent_id]["score"]:
                            parent_scores[parent_id]["score"] = hit.score
                        parent_scores[parent_id]["matched_edescs"].append(
                            hit.payload.get("edesc_text", "")
                        )

                sorted_parents = sorted(
                    parent_scores.items(),
                    key=lambda x: x[1]["score"],
                    reverse=True
                )[:top_k]

                # 召回父块
                query_results = []
                if sorted_parents:
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
                            query_results.append({
                                "productName": parent.payload.get("productName", ""),
                                "edesc_list": parent.payload.get("edesc_list", []),
                                "edesc_count": parent.payload.get("edesc_count", 0),
                                "parent_id": parent_id,
                                "score": info["score"],
                                "matched_edescs": info["matched_edescs"][:3],
                                "metadata": parent.payload.get("metadata", {})
                            })

                results.append(query_results)

            except Exception as e:
                logger.error(f"Search failed for query {i}: {e}")
                results.append([])

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Optimized batch search completed: {len(queries)} queries in {elapsed:.2f}s")

        return results

    def get_stats(self) -> Dict:
        """获取统计信息"""
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
