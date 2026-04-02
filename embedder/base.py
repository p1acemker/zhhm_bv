# -*- coding: utf-8 -*-
"""
Embedder base interface - Embedding 接口抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Union


class BaseEmbedder(ABC):
    """
    Embedding 接口抽象基类

    所有 Embedder 实现必须继承此类并实现以下方法：
    - encode: 将文本编码为向量
    - get_dimension: 获取向量维度
    - health_check: 检查服务是否可用
    """

    @abstractmethod
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
            - 如果输入是单个文本，返回单个向量 List[float]
            - 如果输入是文本列表，返回向量列表 List[List[float]]
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """
        获取向量维度

        Returns:
            向量维度
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        检查 Embedding 服务是否可用

        Returns:
            True 如果服务正常，False 否则
        """
        pass

    def validate_dimension(self, embedding: List[float]) -> bool:
        """
        校验向量维度是否正确

        Args:
            embedding: 向量

        Returns:
            True 如果维度正确
        """
        expected_dim = self.get_dimension()
        actual_dim = len(embedding)
        if actual_dim != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected_dim}, got {actual_dim}"
            )
        return True
