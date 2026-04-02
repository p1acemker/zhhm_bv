# -*- coding: utf-8 -*-
"""
Import strategy - 导入策略模块

提供三种策略用于从候选品种中选择最标准的货描：
1. most_references: 选择引用数最多的（更可靠）
2. highest_score: 选择前缀匹配度最高的
3. combined: 综合匹配度和引用次数
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """候选品种数据结构"""
    by1: str                          # 品种编码
    score: float                      # 前缀匹配分数 (0-1)
    prefix_match_len: int             # 前缀匹配长度
    edesc_count: int                  # 货描引用次数
    edesc: str = ""                   # 货描内容
    edesc_length: int = 0             # 货描长度

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "by1": self.by1,
            "score": round(self.score, 4),
            "prefix_match_len": self.prefix_match_len,
            "edesc_count": self.edesc_count,
        }


class BaseImportStrategy(ABC):
    """
    导入策略抽象基类

    所有策略必须实现 select 方法
    """

    @abstractmethod
    def select(self, candidates: List[Candidate]) -> Candidate:
        """
        从候选中选择最佳匹配

        Args:
            candidates: 候选列表

        Returns:
            选中的候选
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass

    @property
    def description(self) -> str:
        """策略描述"""
        return ""


class MostReferencesStrategy(BaseImportStrategy):
    """
    选择引用数最多的策略

    打分公式：edesc_count 越大越好

    适用场景：希望选择被引用最多、最标准的货描
    """

    @property
    def name(self) -> str:
        return "most_references"

    @property
    def description(self) -> str:
        return "选择货描引用次数最多的候选"

    def select(self, candidates: List[Candidate]) -> Candidate:
        if not candidates:
            raise ValueError("候选列表不能为空")

        selected = max(candidates, key=lambda c: c.edesc_count)
        logger.debug(f"MostReferencesStrategy selected: {selected.by1} (count={selected.edesc_count})")
        return selected


class HighestScoreStrategy(BaseImportStrategy):
    """
    选择匹配度最高的策略

    打分公式：score 越大越好

    适用场景：希望选择编码最相似的品种
    """

    @property
    def name(self) -> str:
        return "highest_score"

    @property
    def description(self) -> str:
        return "选择前缀匹配度最高的候选"

    def select(self, candidates: List[Candidate]) -> Candidate:
        if not candidates:
            raise ValueError("候选列表不能为空")

        selected = max(candidates, key=lambda c: c.score)
        logger.debug(f"HighestScoreStrategy selected: {selected.by1} (score={selected.score})")
        return selected


class CombinedStrategy(BaseImportStrategy):
    """
    综合评分策略

    打分公式：combined_score = score * 0.4 + (edesc_count / max_count) * 0.6

    权重说明：
    - score * 0.4: 编码相似度占 40%
    - (count / max_count) * 0.6: 标准化引用数占 60%

    适用场景：综合考虑编码相似度和货描可靠性
    """

    @property
    def name(self) -> str:
        return "combined"

    @property
    def description(self) -> str:
        return "综合评分: 匹配度*0.4 + 标准化引用数*0.6"

    def select(self, candidates: List[Candidate]) -> Candidate:
        if not candidates:
            raise ValueError("候选列表不能为空")

        # 计算最大引用数用于标准化
        max_count = max(c.edesc_count for c in candidates)
        if max_count == 0:
            max_count = 1  # 避免除零

        # 计算综合得分
        def combined_score(c: Candidate) -> float:
            normalized_count = c.edesc_count / max_count
            return c.score * 0.4 + normalized_count * 0.6

        selected = max(candidates, key=combined_score)
        logger.debug(
            f"CombinedStrategy selected: {selected.by1} "
            f"(score={selected.score}, count={selected.edesc_count}, combined={combined_score(selected):.4f})"
        )
        return selected


def get_strategy(name: str) -> BaseImportStrategy:
    """
    根据名称获取策略实例

    Args:
        name: 策略名称 (most_references, highest_score, combined)

    Returns:
        策略实例

    Raises:
        ValueError: 如果策略名称无效
    """
    strategies = {
        "most_references": MostReferencesStrategy(),
        "highest_score": HighestScoreStrategy(),
        "combined": CombinedStrategy(),
    }

    if name not in strategies:
        available = ", ".join(strategies.keys())
        raise ValueError(f"无效的策略 '{name}'，可用策略: {available}")

    return strategies[name]


def list_strategies() -> List[Dict[str, str]]:
    """
    列出所有可用策略

    Returns:
        策略列表，每项包含 name 和 description
    """
    return [
        {"name": s.name, "description": s.description}
        for s in [MostReferencesStrategy(), HighestScoreStrategy(), CombinedStrategy()]
    ]
