# -*- coding: utf-8 -*-
"""
Service tests - 业务逻辑层测试

使用 Mock 来隔离外部依赖
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from service.edesc_service import EDescService
from strategy.import_strategy import Candidate


class TestEDescService:
    """业务逻辑层测试"""

    @pytest.fixture
    def mock_store(self):
        """Mock 向量存储"""
        store = Mock()
        store.get_stats.return_value = {
            "parent_collection": {"name": "parents", "points_count": 10},
            "child_collection": {"name": "children", "points_count": 50}
        }
        return store

    @pytest.fixture
    def mock_embedder(self):
        """Mock Embedder"""
        embedder = Mock()
        embedder.encode.return_value = [0.1] * 1024
        embedder.get_dimension.return_value = 1024
        return embedder

    @pytest.fixture
    def mock_repo(self):
        """Mock 数据访问层"""
        repo = Mock()
        return repo

    @pytest.fixture
    def service(self, mock_store, mock_embedder, mock_repo):
        """创建 Service 实例"""
        return EDescService(
            store=mock_store,
            embedder=mock_embedder,
            repo=mock_repo,
            chunk_size=500,
            chunk_overlap=50
        )

    # ==================== 查询操作测试 ====================

    def test_get_by1_found(self, service, mock_repo):
        """测试查询 by1 - 找到"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Test description",
            "edesc_count": 1
        }

        result = service.get_by1("D71X4")

        assert result is not None
        assert result["by1"] == "D71X4"
        mock_repo.get_by_by1.assert_called_once_with("D71X4")

    def test_get_by1_not_found(self, service, mock_repo):
        """测试查询 by1 - 未找到"""
        mock_repo.get_by_by1.return_value = None

        result = service.get_by1("NOTEXIST")

        assert result is None

    def test_list_by1(self, service, mock_repo):
        """测试列出 by1"""
        mock_repo.list_all.return_value = [
            {"by1": "D71X4", "edesc_preview": "...", "edesc_count": 1},
            {"by1": "D71X5", "edesc_preview": "...", "edesc_count": 2},
        ]

        result = service.list_by1(limit=100)

        assert len(result) == 2
        mock_repo.list_all.assert_called_once_with(limit=100)

    def test_search_by_edesc(self, service, mock_store, mock_embedder):
        """测试根据货描搜索"""
        mock_store.search.return_value = [
            {"productName": "D71X4", "score": 0.9}
        ]

        result = service.search_by_edesc("test query", top_k=10)

        assert len(result) == 1
        mock_embedder.encode.assert_called_once_with("test query")
        mock_store.search.assert_called_once()

    # ==================== 添加操作测试 ====================

    def test_add_edesc_new_by1(self, service, mock_repo):
        """测试添加新 by1"""
        mock_repo.get_by_by1.return_value = None

        result = service.add_edesc("NEW001", "New description")

        assert result["success"] is True
        assert result["action"] == "created"
        assert "parent_id" in result

    def test_add_edesc_existing_append(self, service, mock_repo):
        """测试添加到已存在的 by1（追加）"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "parent_id": "test-id",
            "EDesc": "Existing desc",
            "edesc_count": 1,
            "metadata": {}
        }

        result = service.add_edesc("D71X4", "New desc")

        assert result["success"] is True
        assert result["action"] == "appended"

    def test_add_edesc_duplicate(self, service, mock_repo):
        """测试添加重复货描"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "parent_id": "test-id",
            "EDesc": "Test desc",
            "edesc_count": 1,
            "metadata": {}
        }

        result = service.add_edesc("D71X4", "Test desc")

        assert result["success"] is False
        assert result["is_duplicate"] is True

    # ==================== 删除操作测试 ====================

    def test_delete_by1_success(self, service, mock_repo):
        """测试删除 by1 - 成功"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "parent_id": "test-id",
            "EDesc": "Test desc",
            "edesc_count": 1
        }

        result = service.delete_by1("D71X4")

        assert result["success"] is True
        mock_repo.delete_by_parent_id.assert_called_once_with("test-id")

    def test_delete_by1_not_found(self, service, mock_repo):
        """测试删除 by1 - 未找到"""
        mock_repo.get_by_by1.return_value = None

        result = service.delete_by1("NOTEXIST")

        assert result["success"] is False

    # ==================== 智能导入测试 ====================

    def test_preview_import_not_exists(self, service, mock_repo):
        """测试预览导入 - 不存在"""
        # Mock 新 by1 不存在
        mock_repo.get_by_by1.return_value = None
        mock_repo.get_all_by1s.return_value = ["D71X4", "D71X5"]
        mock_repo.search_by_prefix.return_value = [
            {"by1": "D71X4", "score": 0.8, "prefix_match_len": 5}
        ]

        # Mock search_by_prefix 方法返回结果（需要 mock service 层的 search_by_prefix）
        service.search_by_prefix = Mock(return_value=[
            {"by1": "D71X4", "score": 0.8, "prefix_match_len": 5, "edesc_count": 5}
        ])

        # Mock 获取候选详情
        mock_repo.get_by_by1.side_effect = [
            None,  # preview_import 中检查新 by1
            {"by1": "D71X4", "EDesc": "Test description", "edesc_count": 5},  # 获取候选详情
        ]

        result = service.preview_import("D71X", top_k=5)

        assert result["exists"] is False

    def test_preview_import_exists(self, service, mock_repo):
        """测试预览导入 - 已存在"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Test",
            "edesc_count": 5
        }

        result = service.preview_import("D71X4")

        assert result["exists"] is True

    def test_import_by1_success(self, service, mock_repo):
        """测试智能导入 - 成功"""
        # Mock search_by_prefix 返回结果
        service.search_by_prefix = Mock(return_value=[
            {"by1": "D71X4", "score": 0.8, "prefix_match_len": 5, "edesc_count": 5}
        ])

        # Mock 获取候选详情 - 第一次检查新 by1 不存在，第二次返回候选详情
        mock_repo.get_by_by1.side_effect = [
            None,  # import_by1 中检查新 by1 不存在
            {"by1": "D71X4", "EDesc": "Test desc", "edesc_count": 5, "metadata": {}},  # 获取候选详情
            None,  # add_edesc 中检查不存在
        ]

        result = service.import_by1("D71X", strategy="most_references")

        assert result["success"] is True
        assert "selected_source" in result

    def test_import_by1_already_exists(self, service, mock_repo):
        """测试智能导入 - 已存在"""
        mock_repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Test",
            "edesc_count": 5
        }

        result = service.import_by1("D71X4")

        assert result["success"] is False
        assert "已存在" in result["message"]

    # ==================== 批量操作测试 ====================

    def test_batch_import(self, service):
        """测试批量导入"""
        # Mock import_by1 方法
        service.import_by1 = Mock(side_effect=[
            {"success": True, "by1": "A"},
            {"success": False, "by1": "B", "message": "Already exists"},
            {"success": True, "by1": "C"},
        ])

        result = service.batch_import(["A", "B", "C"], strategy="most_references")

        assert result["total"] == 3
        assert result["success_count"] == 2
        assert result["fail_count"] == 1

    def test_batch_add_edesc(self, service):
        """测试批量添加"""
        service.add_edesc = Mock(side_effect=[
            {"success": True},
            {"success": False, "is_duplicate": True},
            {"success": True},
        ])

        data_list = [
            {"by1": "A", "edesc": "Desc A"},
            {"by1": "B", "edesc": "Desc B"},
            {"by1": "C", "edesc": "Desc C"},
        ]

        result = service.batch_add_edesc(data_list)

        assert result["total"] == 3
        assert result["success_count"] == 2
        assert result["fail_count"] == 1


class TestEDescServiceDeduplication:
    """货描去重逻辑测试"""

    @pytest.fixture
    def service(self):
        """创建带有 Mock 依赖的 Service"""
        return EDescService(
            store=Mock(),
            embedder=Mock(encode=lambda x: [0.1] * 1024, get_dimension=lambda: 1024),
            repo=Mock(),
            chunk_size=500,
            chunk_overlap=50
        )

    def test_dedup_exact_match(self, service):
        """测试精确匹配去重"""
        service.repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Desc A; Desc B; Desc C",
            "edesc_count": 3,
            "parent_id": "test-id",
            "metadata": {}
        }

        result = service.add_edesc("D71X4", "Desc B")

        assert result["is_duplicate"] is True

    def test_dedup_with_spaces(self, service):
        """测试带空格的去重"""
        service.repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Desc A;Desc B;Desc C",  # 无空格
            "edesc_count": 3,
            "parent_id": "test-id",
            "metadata": {}
        }

        # 带空格的输入也应该被识别为重复
        result = service.add_edesc("D71X4", "Desc B")

        assert result["is_duplicate"] is True

    def test_no_dedup_different_content(self, service):
        """测试不同内容不触发去重"""
        service.repo.get_by_by1.return_value = {
            "by1": "D71X4",
            "EDesc": "Desc A; Desc B",
            "edesc_count": 2,
            "parent_id": "test-id",
            "metadata": {}
        }

        result = service.add_edesc("D71X4", "Desc C")

        assert result["success"] is True
        assert result["action"] == "appended"
