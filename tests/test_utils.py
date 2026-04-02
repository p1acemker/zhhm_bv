# -*- coding: utf-8 -*-
"""
Utils tests - 工具函数测试
"""

import pytest
from utils.text_utils import split_edesc_list, is_edesc_duplicate, clean_edesc_text, count_edesc_items
from utils.id_utils import generate_parent_id, generate_child_id


class TestTextUtils:
    """文本工具函数测试"""

    def test_split_edesc_list_single(self):
        """测试单个货描分割"""
        result = split_edesc_list("Test description")
        assert result == ["Test description"]

    def test_split_edesc_list_multiple(self):
        """测试多个货描分割"""
        result = split_edesc_list("Desc1; Desc2; Desc3")
        assert result == ["Desc1", "Desc2", "Desc3"]

    def test_split_edesc_list_with_spaces(self):
        """测试带空格的分割"""
        result = split_edesc_list("  Desc1  ;  Desc2  ")
        assert result == ["Desc1", "Desc2"]

    def test_split_edesc_list_empty(self):
        """测试空字符串"""
        assert split_edesc_list("") == []
        assert split_edesc_list(None) == []

    def test_split_edesc_list_semicolons_only(self):
        """测试只有分号"""
        result = split_edesc_list(";;")
        assert result == []

    def test_is_edesc_duplicate_found(self):
        """测试重复检测 - 找到"""
        existing = "Desc1; Desc2; Desc3"
        assert is_edesc_duplicate("Desc2", existing) is True

    def test_is_edesc_duplicate_not_found(self):
        """测试重复检测 - 未找到"""
        existing = "Desc1; Desc2"
        assert is_edesc_duplicate("Desc3", existing) is False

    def test_is_edesc_duplicate_empty(self):
        """测试重复检测 - 空字符串"""
        assert is_edesc_duplicate("Test", "") is False
        assert is_edesc_duplicate("", "Test") is False

    def test_clean_edesc_text(self):
        """测试清洗货描文本"""
        result = clean_edesc_text("  Desc1  ;  Desc2  ")
        assert result == "Desc1; Desc2"

    def test_clean_edesc_text_empty(self):
        """测试清洗空文本"""
        assert clean_edesc_text("") == ""
        assert clean_edesc_text(None) == ""

    def test_count_edesc_items(self):
        """测试统计货描条目数"""
        assert count_edesc_items("Desc1; Desc2; Desc3") == 3
        assert count_edesc_items("Single") == 1
        assert count_edesc_items("") == 0


class TestIdUtils:
    """ID 生成工具函数测试"""

    def test_generate_parent_id_stable(self):
        """测试父块 ID 生成稳定性"""
        id1 = generate_parent_id("D71X4", "Test description")
        id2 = generate_parent_id("D71X4", "Test description")
        assert id1 == id2

    def test_generate_parent_id_different(self):
        """测试父块 ID 生成差异性"""
        id1 = generate_parent_id("D71X4", "Desc1")
        id2 = generate_parent_id("D71X5", "Desc2")
        assert id1 != id2

    def test_generate_parent_id_without_edesc(self):
        """测试不带货描的父块 ID 生成"""
        id1 = generate_parent_id("D71X4")
        id2 = generate_parent_id("D71X4")
        assert id1 == id2

    def test_generate_child_id_stable(self):
        """测试子块 ID 生成稳定性"""
        parent_id = "test-parent-id"
        id1 = generate_child_id(parent_id, 0)
        id2 = generate_child_id(parent_id, 0)
        assert id1 == id2

    def test_generate_child_id_different_index(self):
        """测试不同索引的子块 ID"""
        parent_id = "test-parent-id"
        id1 = generate_child_id(parent_id, 0)
        id2 = generate_child_id(parent_id, 1)
        assert id1 != id2

    def test_generate_parent_id_format(self):
        """测试父块 ID 格式"""
        parent_id = generate_parent_id("D71X4", "Test")
        # UUID 格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert len(parent_id) == 36
        assert parent_id.count("-") == 4
