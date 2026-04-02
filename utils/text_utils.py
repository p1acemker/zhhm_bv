# -*- coding: utf-8 -*-
"""
Text utilities - 文本处理工具函数
- 分号分割货描列表
- 货描去重检查
- 文本清洗
- 搜索 query 标准化
"""

import re
from typing import List


def split_edesc_list(edesc: str) -> List[str]:
    """
    按分号分割货描列表

    Args:
        edesc: 货描字符串，多个货描用分号分隔

    Returns:
        货描列表，已去除首尾空格
    """
    if not edesc:
        return []

    return [e.strip() for e in edesc.split(';') if e.strip()]


def is_edesc_duplicate(new_edesc: str, existing_edesc: str) -> bool:
    """
    检查货描是否重复

    Args:
        new_edesc: 新货描
        existing_edesc: 已存在的货描字符串

    Returns:
        True 如果重复，False 如果不重复
    """
    if not existing_edesc or not new_edesc:
        return False

    # 标准化新货描
    new_edesc = new_edesc.strip()

    # 获取已有货描列表
    existing_list = split_edesc_list(existing_edesc)

    # 检查是否存在于列表中
    return new_edesc in existing_list


def clean_edesc_text(edesc: str) -> str:
    """
    清洗货描文本

    - 去除首尾空格
    - 去除多余的分号
    - 统一分号为 "; " 格式

    Args:
        edesc: 原始货描文本

    Returns:
        清洗后的货描文本
    """
    if not edesc:
        return ""

    # 分割并去除空项
    parts = split_edesc_list(edesc)

    # 重新组合
    return "; ".join(parts)


def count_edesc_items(edesc: str) -> int:
    """
    统计货描条目数量

    Args:
        edesc: 货描字符串

    Returns:
        货描条目数量
    """
    return len(split_edesc_list(edesc))


def normalize_query(query: str) -> str:
    """
    标准化搜索 query

    处理步骤:
    1. 去除转义反斜杠
    2. 统一引号: 中文引号/智能引号 → 英寸符号 "
    3. 去除尺寸前缀: 开头的 4", 2 1/2", 6'' 等
    4. 统一空白字符: 多空格→单空格, 去除首尾空格
    5. 统一逗号格式: 去除逗号前后多余空格
    6. 展开常见缩写: BFV→Butterfly Valve, DI→Ductile Iron 等

    Args:
        query: 原始搜索文本

    Returns:
        标准化后的搜索文本
    """
    if not query:
        return ""

    # 1. 去除转义反斜杠
    result = query.replace("\\", "")

    # 2. 统一引号 → "
    result = result.replace("\u201c", '"').replace("\u201d", '"')  # 中文左右引号
    result = result.replace("\u2018", '"').replace("\u2019", '"')  # 单引号 → 双引号(英寸)
    result = result.replace("''", '"')  # 两个单引号 → 英寸

    # 3. 去除开头/结尾的尺寸前缀: "4\"", "2 1/2\"", "6\""
    result = re.sub(r'^[\d./\s"]+\s*', '', result)
    result = re.sub(r'\s*[\d./]+\s*"\s*$', '', result)

    # 4. 统一空白字符
    result = re.sub(r'\s+', ' ', result).strip()

    # 5. 统一逗号格式
    result = re.sub(r'\s*,\s*', ', ', result)

    # 6. 展开常见缩写（长缩写优先匹配）
    abbreviations = {
        'BFV': 'Butterfly Valve',
        'B/FLY VALVE': 'Butterfly Valve',
        'B/FLY': 'Butterfly',
        'GRVD': 'Grooved',
        'THD': 'Threaded',
        'THEREADED': 'Threaded',
        'THEARED': 'Threaded',
        'DUCTIL': 'Ductile',
        'W/': 'With ',
        'C/W': 'Complete With ',
        'BVL': 'Butterfly Valve',
        'OP': 'Operator',
        'GRV': 'Grooved',
        'FR': 'Fire Riser',
    }
    for abbr, full in sorted(abbreviations.items(), key=lambda x: -len(x[0])):
        result = re.sub(r'\b' + re.escape(abbr) + r'\b', full, result, flags=re.IGNORECASE)

    # 再次清理多余空格
    result = re.sub(r'\s+', ' ', result).strip()

    return result
