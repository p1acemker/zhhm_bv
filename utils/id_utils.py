# -*- coding: utf-8 -*-
"""
ID utilities - ID生成工具函数
- 生成稳定的父块ID
- 生成子块ID
"""

import uuid
from typing import Optional


def generate_parent_id(product_name: str, edesc: Optional[str] = None) -> str:
    """
    生成稳定的 UUID 作为 parent_id

    使用 uuid5 基于产品名称生成，保证相同产品名称生成相同的 ID

    Args:
        product_name: 产品名称/by1
        edesc: 货描（可选，用于增加唯一性）

    Returns:
        UUID 字符串
    """
    # 使用产品名称作为唯一标识符的基础
    if edesc:
        unique_str = f"{product_name}_{edesc[:50]}"
    else:
        unique_str = product_name

    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))


def generate_child_id(parent_id: str, chunk_index: int) -> str:
    """
    为子块生成稳定的 UUID

    Args:
        parent_id: 父块 ID
        chunk_index: 子块索引

    Returns:
        UUID 字符串
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{parent_id}_chunk_{chunk_index}"))
