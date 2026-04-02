# -*- coding: utf-8 -*-
"""
Strategy tests - 导入策略测试
"""

import pytest
from strategy.import_strategy import (
    Candidate,
    MostReferencesStrategy,
    HighestScoreStrategy,
    CombinedStrategy,
    get_strategy,
    list_strategies
)


def create_candidate(by1, score, prefix_len, count):
    """创建测试候选"""
    return Candidate(
        by1=by1,
        score=score,
        prefix_match_len=prefix_len,
        edesc_count=count,
        edesc="Test description",
        edesc_length=20
    )


class TestCandidate:
    """候选数据类测试"""

    def test_candidate_creation(self):
        """测试候选创建"""
        c = Candidate(
            by1="D71X4",
            score=0.8,
            prefix_match_len=5,
            edesc_count=10
        )
        assert c.by1 == "D71X4"
        assert c.score == 0.8
        assert c.prefix_match_len == 5
        assert c.edesc_count == 10

    def test_candidate_to_dict(self):
        """测试候选转字典"""
        c = create_candidate("D71X4", 0.8, 5, 10)
        d = c.to_dict()
        assert d["by1"] == "D71X4"
        assert d["score"] == 0.8
        assert "edesc" not in d  # edesc 不应该在字典中


class TestMostReferencesStrategy:
    """引用数最多策略测试"""

    def test_select_highest_count(self):
        """测试选择引用数最多的"""
        strategy = MostReferencesStrategy()
        candidates = [
            create_candidate("A", 0.9, 5, 5),
            create_candidate("B", 0.7, 4, 10),  # 引用数最多
            create_candidate("C", 0.8, 4, 3),
        ]
        selected = strategy.select(candidates)
        assert selected.by1 == "B"

    def test_select_with_tie(self):
        """测试引用数相同时（选择第一个）"""
        strategy = MostReferencesStrategy()
        candidates = [
            create_candidate("A", 0.9, 5, 10),
            create_candidate("B", 0.7, 4, 10),
        ]
        selected = strategy.select(candidates)
        assert selected.by1 == "A"

    def test_empty_candidates(self):
        """测试空候选列表"""
        strategy = MostReferencesStrategy()
        with pytest.raises(ValueError):
            strategy.select([])

    def test_strategy_name(self):
        """测试策略名称"""
        strategy = MostReferencesStrategy()
        assert strategy.name == "most_references"


class TestHighestScoreStrategy:
    """最高匹配度策略测试"""

    def test_select_highest_score(self):
        """测试选择匹配度最高的"""
        strategy = HighestScoreStrategy()
        candidates = [
            create_candidate("A", 0.9, 5, 5),  # 匹配度最高
            create_candidate("B", 0.7, 4, 10),
            create_candidate("C", 0.8, 4, 3),
        ]
        selected = strategy.select(candidates)
        assert selected.by1 == "A"

    def test_strategy_name(self):
        """测试策略名称"""
        strategy = HighestScoreStrategy()
        assert strategy.name == "highest_score"


class TestCombinedStrategy:
    """综合评分策略测试"""

    def test_combined_scoring(self):
        """测试综合评分

        combined_score = score * 0.4 + (count / max_count) * 0.6

        候选 A: score=0.9, count=5, max_count=10
            combined = 0.9 * 0.4 + (5/10) * 0.6 = 0.36 + 0.3 = 0.66

        候选 B: score=0.7, count=10, max_count=10
            combined = 0.7 * 0.4 + (10/10) * 0.6 = 0.28 + 0.6 = 0.88

        候选 C: score=0.8, count=3, max_count=10
            combined = 0.8 * 0.4 + (3/10) * 0.6 = 0.32 + 0.18 = 0.50

        应该选择 B
        """
        strategy = CombinedStrategy()
        candidates = [
            create_candidate("A", 0.9, 5, 5),
            create_candidate("B", 0.7, 4, 10),  # 综合得分最高
            create_candidate("C", 0.8, 4, 3),
        ]
        selected = strategy.select(candidates)
        assert selected.by1 == "B"

    def test_combined_with_equal_scores(self):
        """测试相同匹配度时的选择"""
        strategy = CombinedStrategy()
        candidates = [
            create_candidate("A", 0.8, 4, 5),
            create_candidate("B", 0.8, 4, 10),  # 引用数更高
        ]
        selected = strategy.select(candidates)
        assert selected.by1 == "B"

    def test_strategy_name(self):
        """测试策略名称"""
        strategy = CombinedStrategy()
        assert strategy.name == "combined"


class TestGetStrategy:
    """策略工厂函数测试"""

    def test_get_most_references(self):
        """测试获取 most_references 策略"""
        strategy = get_strategy("most_references")
        assert isinstance(strategy, MostReferencesStrategy)

    def test_get_highest_score(self):
        """测试获取 highest_score 策略"""
        strategy = get_strategy("highest_score")
        assert isinstance(strategy, HighestScoreStrategy)

    def test_get_combined(self):
        """测试获取 combined 策略"""
        strategy = get_strategy("combined")
        assert isinstance(strategy, CombinedStrategy)

    def test_get_invalid_strategy(self):
        """测试获取无效策略"""
        with pytest.raises(ValueError):
            get_strategy("invalid")


class TestListStrategies:
    """策略列表测试"""

    def test_list_strategies(self):
        """测试列出所有策略"""
        strategies = list_strategies()
        assert len(strategies) == 3
        names = [s["name"] for s in strategies]
        assert "most_references" in names
        assert "highest_score" in names
        assert "combined" in names
