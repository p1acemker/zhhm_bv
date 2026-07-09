# -*- coding: utf-8 -*-
"""
Import strategy - 批量导入时的候选选择策略

仅保留 most_references（引用最多）策略。
"""

from dataclasses import dataclass
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """候选品种数据结构。"""

    by1: str
    score: float
    prefix_match_len: int
    edesc_count: int
    edesc: str = ""
    edesc_length: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "by1": self.by1,
            "score": round(self.score, 4),
            "prefix_match_len": self.prefix_match_len,
            "edesc_count": self.edesc_count,
        }


def prefix_similarity(left: str, right: str) -> float:
    """Return common-prefix similarity normalized by the longer string."""
    a = left.upper()
    b = right.upper()
    prefix_len = 0
    for index in range(min(len(a), len(b))):
        if a[index] != b[index]:
            break
        prefix_len += 1
    max_len = max(len(a), len(b))
    return prefix_len / max_len if max_len else 0.0


def rank_prefix_matches(
    new_by1: str, existing_by1s: List[str], top_k: int = 10
) -> List[Dict[str, Any]]:
    """Rank existing product codes by common-prefix similarity."""
    matches: List[Dict[str, Any]] = []
    for by1 in existing_by1s:
        if by1 == new_by1:
            continue
        score = prefix_similarity(new_by1, by1)
        if score > 0:
            matches.append(
                {
                    "by1": by1,
                    "score": score,
                    "prefix_match_len": int(score * max(len(new_by1), len(by1))),
                }
            )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:top_k]


def select_best(candidates: List[Candidate]) -> Candidate:
    """选择引用数最多的候选。

    Args:
        candidates: 候选列表。

    Returns:
        选中的候选。

    Raises:
        ValueError: 候选列表为空。
    """
    if not candidates:
        raise ValueError("候选列表不能为空")
    selected = max(candidates, key=lambda c: c.edesc_count)
    logger.debug(f"Selected: {selected.by1} (count={selected.edesc_count})")
    return selected
