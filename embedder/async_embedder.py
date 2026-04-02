# -*- coding: utf-8 -*-
"""
Async Embedder - 异步 Embedding 客户端

支持高并发的异步 embedding 调用
"""

import aiohttp
import asyncio
from typing import Union, List
import logging

logger = logging.getLogger(__name__)


class AsyncBGEEmbedder:
    """
    异步 BGE-M3 Embedder

    使用 aiohttp 进行异步 HTTP 请求，支持高并发
    """

    def __init__(
        self,
        api_url: str = None,
        model: str = None,
        embedding_dim: int = None,
        timeout: int = 60,
        max_connections: int = 100
    ):
        """
        初始化异步 Embedder

        Args:
            api_url: Embedding 服务地址
            model: 模型名称
            embedding_dim: 向量维度
            timeout: 请求超时时间(秒)
            max_connections: 最大连接数
        """
        from config import EMBEDDING_API_URL, EMBEDDING_MODEL, EMBEDDING_DIM

        self.api_url = api_url or EMBEDDING_API_URL
        self.model = model or EMBEDDING_MODEL
        self.embedding_dim = embedding_dim or EMBEDDING_DIM
        self.timeout = aiohttp.ClientTimeout(total=timeout)

        # 连接池配置
        self.connector = aiohttp.TCPConnector(
            limit=max_connections,
            limit_per_host=max_connections,
            enable_cleanup_closed=True
        )

        self._session: aiohttp.ClientSession = None

        self.headers = {
            "User-Agent": "yaak-async",
            "Accept": "*/*",
            "Content-Type": "application/json"
        }

        logger.debug(f"AsyncBGEEmbedder initialized: {self.api_url}, dim={self.embedding_dim}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=self.timeout,
                headers=self.headers
            )
        return self._session

    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32
    ) -> Union[List[float], List[List[float]]]:
        """
        异步将文本编码为向量

        Args:
            texts: 单个文本或文本列表
            batch_size: 批处理大小

        Returns:
            向量或向量列表
        """
        single = isinstance(texts, str)
        texts = [texts] if single else texts

        # 过滤空文本
        texts = [t if t and str(t).strip() else "" for t in texts]

        # 分批处理
        all_embeddings = []
        tasks = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            tasks.append(self._call_api(batch))

        # 并行执行所有批次
        batch_results = await asyncio.gather(*tasks)

        for batch_embeddings in batch_results:
            all_embeddings.extend(batch_embeddings)

        result = all_embeddings[0] if single else all_embeddings

        # 校验维度
        if single:
            self._validate_dimension(result)
        else:
            for emb in result:
                self._validate_dimension(emb)

        return result

    async def _call_api(self, texts: List[str]) -> List[List[float]]:
        """异步调用 Embedding API"""
        payload = {
            "model": self.model,
            "input": texts
        }

        session = await self._get_session()

        try:
            async with session.post(self.api_url, json=payload) as response:
                response.raise_for_status()
                result = await response.json()

                # 解析响应
                if "data" in result:
                    embeddings = [item["embedding"] for item in result["data"]]
                elif "embeddings" in result:
                    embeddings = result["embeddings"]
                else:
                    raise ValueError(f"未知 API 响应格式: {result.keys()}")

                return embeddings

        except asyncio.TimeoutError:
            logger.error(f"Embedding API timeout: {self.api_url}")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Embedding API error: {e}")
            raise

    def _validate_dimension(self, embedding: List[float]):
        """校验向量维度"""
        if len(embedding) != self.embedding_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.embedding_dim}, "
                f"got {len(embedding)}"
            )

    def get_dimension(self) -> int:
        """获取向量维度"""
        return self.embedding_dim

    async def health_check(self) -> bool:
        """异步检查 Embedding 服务是否可用"""
        try:
            test_result = await self.encode("test")
            return len(test_result) == self.embedding_dim
        except Exception as e:
            logger.warning(f"Embedder health check failed: {e}")
            return False

    async def encode_batch_concurrent(
        self,
        texts_list: List[List[str]],
        batch_size: int = 32
    ) -> List[List[List[float]]]:
        """
        并行编码多个文本列表

        用于高并发场景，同时处理多个查询

        Args:
            texts_list: 多个文本列表
            batch_size: 每个请求的批处理大小

        Returns:
            每个文本列表对应的向量列表
        """
        tasks = [self.encode(texts, batch_size) for texts in texts_list]
        results = await asyncio.gather(*tasks)
        return results
