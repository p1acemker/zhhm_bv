# -*- coding: utf-8 -*-
"""
Embedding API 客户端
调用远程 bge-m3 embedding 服务
"""

import requests
from typing import Union, List
import json


class EmbeddingClient:
    """
    远程 Embedding API 客户端
    调用 http://10.0.12.12:9997/v1/embeddings
    """

    def __init__(
        self,
        api_url: str = None,
        model: str = None,
        embedding_dim: int = None,
        timeout: int = 30
    ):
        """
        初始化 Embedding 客户端

        Args:
            api_url: Embedding 服务地址
            model: 模型名称 (bge-m3)
            embedding_dim: 向量维度
            timeout: 请求超时时间(秒)
        """
        from config import EMBEDDING_API_URL, EMBEDDING_MODEL, EMBEDDING_DIM

        self.api_url = api_url or EMBEDDING_API_URL
        self.model = model or EMBEDDING_MODEL
        self.embedding_dim = embedding_dim or EMBEDDING_DIM
        self.timeout = timeout

        self.headers = {
            "User-Agent": "yaak",
            "Accept": "*/*",
            "Content-Type": "application/json"
        }

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32
    ) -> Union[List[float], List[List[float]]]:
        """
        将文本编码为向量

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
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = self._call_api(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings[0] if single else all_embeddings

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """调用 Embedding API"""
        payload = {
            "model": self.model,
            "input": texts
        }

        response = requests.post(
            self.api_url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()

        result = response.json()

        # 解析响应
        if "data" in result:
            embeddings = [item["embedding"] for item in result["data"]]
        elif "embeddings" in result:
            embeddings = result["embeddings"]
        else:
            raise ValueError(f"未知 API 响应格式: {result.keys()}")

        return embeddings

    def health_check(self) -> bool:
        """检查 Embedding 服务是否可用"""
        try:
            test_result = self.encode("test")
            return len(test_result) == self.embedding_dim
        except Exception:
            return False
