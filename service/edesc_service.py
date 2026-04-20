# -*- coding: utf-8 -*-
"""
EDesc Service - 货描维护业务逻辑层

核心业务逻辑：
- 查询操作：get, list, search
- 增删改操作：add, update, delete
- 智能导入：preview, import, batch-import
"""

from typing import List, Dict, Optional, Any
import logging
import json
import os

from embedder.base import BaseEmbedder
from repo.qdrant_repo import QdrantRepo
from qdrant_store import QdrantVectorStore
from strategy.import_strategy import get_strategy, Candidate
from utils.id_utils import generate_parent_id, generate_child_id
from qdrant_client.models import PointStruct
import re

logger = logging.getLogger(__name__)


def _standardize(edesc: str) -> str:
    """调用 7 段标准化，返回标准化后的字符串"""
    from scripts.edesc_standardizer import standardize_edesc

    result = standardize_edesc(edesc)
    return result["standardized"]


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
    result = result.replace("\u2018", '"').replace(
        "\u2019", '"'
    )  # 单引号 → 双引号(英寸)
    result = result.replace("''", '"')  # 两个单引号 → 英寸

    # 3. 去除开头/结尾的尺寸前缀: "4\"", "2 1/2\"", "6\""
    result = re.sub(r'^[\d./\s"]+\s*', "", result)
    result = re.sub(r'\s*[\d./]+\s*"\s*$', "", result)

    # 4. 统一空白字符
    result = re.sub(r"\s+", " ", result).strip()

    # 5. 统一逗号格式
    result = re.sub(r"\s*,\s*", ", ", result)

    # 6. 展开常见缩写（长缩写优先匹配）
    abbreviations = {
        "BFV": "Butterfly Valve",
        "B/FLY VALVE": "Butterfly Valve",
        "B/FLY": "Butterfly",
        "GRVD": "Grooved",
        "THD": "Threaded",
        "THEREADED": "Threaded",
        "THEARED": "Threaded",
        "DUCTIL": "Ductile",
        "W/": "With ",
        "C/W": "Complete With ",
        "BVL": "Butterfly Valve",
        "OP": "Operator",
        "GRV": "Grooved",
        "FR": "Fire Riser",
    }
    for abbr, full in sorted(abbreviations.items(), key=lambda x: -len(x[0])):
        result = re.sub(
            r"\b" + re.escape(abbr) + r"\b", full, result, flags=re.IGNORECASE
        )

    # 再次清理多余空格
    result = re.sub(r"\s+", " ", result).strip()

    return result


class EDescService:
    """
    货描维护业务逻辑层

    职责：
    - 封装所有业务逻辑
    - 协调 Store、Embedder、Repo 组件
    - 提供统一的业务接口
    """

    def __init__(
        self,
        store: QdrantVectorStore,
        embedder: BaseEmbedder,
        repo: QdrantRepo,
    ):
        """
        初始化 Service

        Args:
            store: 向量存储
            embedder: Embedder
            repo: 数据访问层
        """
        self.store = store
        self.embedder = embedder
        self.repo = repo
        self._reranker = None
        self._spec_rules = None

        logger.info("EDescService initialized")

    def _get_reranker(self):
        """延迟初始化精排器"""
        if self._reranker is None:
            from scripts.reranker import By1Reranker

            self._reranker = By1Reranker()
            logger.info("By1Reranker initialized")
        return self._reranker

    def _get_spec_rules(self) -> dict:
        """延迟加载客户规格规则表"""
        if self._spec_rules is None:
            rule_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "by1_customer_spec_rules.json",
            )
            if os.path.exists(rule_path):
                with open(rule_path, "r", encoding="utf-8") as f:
                    self._spec_rules = json.load(f)
                logger.info(f"Loaded spec rules: {len(self._spec_rules)} by1 entries")
            else:
                logger.warning(f"Spec rules not found: {rule_path}")
                self._spec_rules = {}
        return self._spec_rules

    # ==================== 查询操作 ====================

    def get_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        """
        查询指定 by1 的货描

        Args:
            by1: 基配品种编码

        Returns:
            货描信息，未找到返回 None
        """
        logger.debug(f"Getting by1: {by1}")
        return self.repo.get_by_by1(by1)

    def list_by1(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        列出所有 by1

        Args:
            limit: 最大返回数量

        Returns:
            by1 列表
        """
        logger.debug(f"Listing by1, limit={limit}")
        return self.repo.list_all(limit=limit)

    def search_by_edesc_raw(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = None,
        customer: str = None,
    ) -> List[Dict[str, Any]]:
        """
        根据货描文本搜索匹配的 by1（仅向量召回，不精排）

        Args:
            query: 货描查询文本
            top_k: 返回结果数量
            score_threshold: 相似度阈值（可选）
            customer: 客户简称（可选），匹配时附带该客户对应规格

        Returns:
            匹配结果列表（按向量相似度排序），每条包含 matched_specs 字段
        """
        query_vector = self.embedder.encode(query)
        logger.debug(f"Raw searching by edesc: {query[:50]}...")
        vec_results = self.store.search(
            query_vector, top_k=top_k, score_threshold=score_threshold
        )

        # 如果提供了 customer，按规则表匹配规格
        if customer:
            rules = self._get_spec_rules()
            for r in vec_results:
                by1 = r.get("productName", "")
                # productName 本身即为规则表 key（品种去首位后的编码）
                by1_key = by1
                cust_specs = rules.get(by1_key, {}).get(customer)
                r["matched_specs"] = cust_specs  # 匹配到返回列表，未匹配返回 None
        else:
            for r in vec_results:
                r["matched_specs"] = None

        return vec_results

    def search_by_edesc(
        self, query: str, top_k: int = 10, score_threshold: float = None
    ) -> List[Dict[str, Any]]:
        """
        根据货描文本搜索匹配的 by1（两阶段：向量召回 + 精排）

        Args:
            query: 货描查询文本
            top_k: 返回结果数量
            score_threshold: 相似度阈值（可选）

        Returns:
            匹配结果列表（按精排分排序）
        """
        # 阶段1: 向量召回 — 多取候选供精排筛选
        std_query = _standardize(query)
        logger.debug(f"Searching by edesc: {std_query[:50]}...")
        query_vector = self.embedder.encode(std_query)
        recall_k = max(top_k * 3, 20)
        vec_results = self.store.search(
            query_vector, top_k=recall_k, score_threshold=score_threshold
        )

        if not vec_results:
            return []

        # 阶段2: 精排
        candidates = [r["productName"] for r in vec_results]
        vec_scores = {r["productName"]: r["score"] for r in vec_results}

        reranker = self._get_reranker()
        reranked = reranker.rerank(
            edesc=query,
            candidates=candidates,
            top_k=top_k,
            vec_scores=vec_scores,
        )

        # 阶段3: 合并精排结果与原始数据
        result_map = {r["productName"]: r for r in vec_results}
        output = []
        for item in reranked:
            by1 = item["by1"]
            if by1 not in result_map:
                continue
            entry = result_map[by1].copy()
            entry["rerank_score"] = item["score"]
            entry["rule_score"] = item["rule_score"]
            entry["vec_score"] = item["vec_score"]
            entry["rank"] = item["rank"]
            output.append(entry)

        return output

    def search_by_prefix(self, by1: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        根据 by1 前缀匹配搜索相似的品种

        Args:
            by1: 基配品种编码
            top_k: 返回结果数量

        Returns:
            相似 by1 列表
        """
        logger.debug(f"Searching by prefix: {by1}")

        # 获取所有 by1
        all_by1s = self.repo.get_all_by1s()

        if not all_by1s:
            return []

        # 前缀匹配
        results = self.repo.search_by_prefix(by1, all_by1s, top_k=top_k)

        # 补充货描引用数信息
        for r in results:
            detail = self.repo.get_by_by1(r["by1"])
            if detail:
                r["edesc_count"] = detail.get("edesc_count", 0)

        return results

    # ==================== 增删改操作 ====================

    def add_edesc(
        self, by1: str, edesc: str, metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        添加货描（自动标准化 + 去重）

        逻辑：
        1. 标准化 edesc
        2. 如果 by1 已存在：
           - 检查标准化后的 edesc 是否重复
           - 重复则不添加
           - 不重复则追加到 edesc_list
        3. 如果 by1 不存在：
           - 创建新记录

        Args:
            by1: 基配品种编码
            edesc: 货物描述
            metadata: 可选元数据

        Returns:
            操作结果
        """
        logger.info(f"Adding edesc for by1={by1}")

        # 标准化 edesc
        original = edesc.strip()
        std_edesc = _standardize(original)

        # 检查是否已存在
        existing = self.repo.get_by_by1(by1)

        if existing:
            # by1 已存在，检查标准化后的 edesc 是否重复
            existing_list = existing.get("edesc_list", [])

            if std_edesc in existing_list:
                logger.info(f"Duplicate edesc for by1={by1}, skipping")
                return {
                    "success": False,
                    "message": f"by1={by1} 的货描已存在，无需重复添加",
                    "is_duplicate": True,
                    "existing_edesc_count": len(existing_list),
                }

            # 不重复，追加到 edesc_list
            new_edesc_list = existing_list + [std_edesc]
            new_count = len(new_edesc_list)

            # 删除旧记录
            self.repo.delete_by_parent_id(existing["parent_id"])

            # 合并 metadata
            new_metadata = existing.get("metadata", {})
            new_metadata["by1"] = by1
            new_metadata["edesc_count"] = new_count
            if metadata:
                new_metadata.update(metadata)

            # 重建
            parent_id = self._add_product_with_embedding(
                product_name=by1, edesc_list=new_edesc_list, metadata=new_metadata
            )

            logger.info(f"Appended edesc for by1={by1}")
            return {
                "success": True,
                "message": f"成功为 by1={by1} 追加货描",
                "action": "appended",
                "parent_id": parent_id,
                "original": original,
                "standardized": std_edesc,
                "old_edesc_count": len(existing_list),
                "new_edesc_count": new_count,
            }

        else:
            # by1 不存在，创建新记录
            parent_id = self._add_product_with_embedding(
                product_name=by1,
                edesc_list=[std_edesc],
                metadata=metadata or {"by1": by1, "edesc_count": 1},
            )

            logger.info(f"Created new by1={by1}")
            return {
                "success": True,
                "message": f"成功添加新 by1={by1}",
                "action": "created",
                "parent_id": parent_id,
                "original": original,
                "standardized": std_edesc,
            }

    def update_edesc(
        self,
        by1: str,
        new_edesc: str,
        append: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        更新 by1 的货描

        Args:
            by1: 基配品种编码
            new_edesc: 新的货物描述
            append: 是否追加模式
            metadata: 可选元数据

        Returns:
            操作结果
        """
        logger.info(f"Updating edesc for by1={by1}, append={append}")

        existing = self.repo.get_by_by1(by1)
        if not existing:
            return {
                "success": False,
                "message": f"by1={by1} 不存在，请使用 add_edesc 添加",
            }

        # 标准化
        original = new_edesc.strip()
        std_edesc = _standardize(original)

        # 确定最终 edesc_list
        existing_list = existing.get("edesc_list", [])
        if append:
            final_list = existing_list + [std_edesc]
        else:
            final_list = [std_edesc]

        # 删除旧记录
        self.repo.delete_by_parent_id(existing["parent_id"])

        # 重建
        new_metadata = metadata or existing.get("metadata", {})
        new_metadata["edesc_count"] = len(final_list)

        parent_id = self._add_product_with_embedding(
            product_name=by1, edesc_list=final_list, metadata=new_metadata
        )

        logger.info(f"Updated edesc for by1={by1}")
        return {
            "success": True,
            "message": f"成功更新 by1={by1}",
            "parent_id": parent_id,
            "original": original,
            "standardized": std_edesc,
            "old_edesc_count": len(existing_list),
            "new_edesc_count": len(final_list),
        }

    def delete_by1(self, by1: str) -> Dict[str, Any]:
        """
        删除 by1 及其货描

        Args:
            by1: 基配品种编码

        Returns:
            操作结果
        """
        logger.info(f"Deleting by1={by1}")

        existing = self.repo.get_by_by1(by1)
        if not existing:
            return {"success": False, "message": f"by1={by1} 不存在"}

        self.repo.delete_by_parent_id(existing["parent_id"])

        logger.info(f"Deleted by1={by1}")
        edesc_list = existing.get("edesc_list", [])
        preview = edesc_list[0][:100] + "..." if edesc_list else ""
        return {
            "success": True,
            "message": f"成功删除 by1={by1}",
            "deleted_edesc_preview": preview,
        }

    # ==================== 智能导入 ====================

    def preview_import(self, new_by1: str, top_k: int = 5) -> Dict[str, Any]:
        """
        预览导入候选（不实际导入）

        Args:
            new_by1: 新的 by1
            top_k: 搜索数量

        Returns:
            候选列表
        """
        logger.info(f"Previewing import for by1={new_by1}")

        # 检查是否已存在
        existing = self.repo.get_by_by1(new_by1)
        if existing:
            return {
                "exists": True,
                "message": f"by1={new_by1} 已存在",
                "existing_data": existing,
            }

        # 搜索相似品种
        similar_results = self.search_by_prefix(new_by1, top_k=top_k)

        if not similar_results:
            return {
                "exists": False,
                "candidates": [],
                "message": f"未找到与 {new_by1} 前缀匹配的品种",
            }

        # 获取详细信息
        candidates = []
        for result in similar_results:
            by1 = result["by1"]
            detail = self.repo.get_by_by1(by1)
            if detail:
                edesc_list = detail.get("edesc_list", [])
                preview = edesc_list[0][:150] + "..." if edesc_list else ""
                candidates.append(
                    {
                        "by1": by1,
                        "score": round(result["score"], 4),
                        "prefix_match_len": result["prefix_match_len"],
                        "edesc_count": detail["edesc_count"],
                        "edesc_preview": preview,
                    }
                )

        # 推荐（引用数最多的）
        recommended = (
            max(candidates, key=lambda x: x["edesc_count"]) if candidates else None
        )

        return {
            "exists": False,
            "new_by1": new_by1,
            "recommended": recommended,
            "candidates": candidates,
            "total_found": len(candidates),
        }

    def import_by1(
        self, new_by1: str, strategy: str = "most_references", top_k: int = 5
    ) -> Dict[str, Any]:
        """
        智能导入新 by1

        Args:
            new_by1: 新的 by1
            strategy: 选择策略
            top_k: 搜索数量

        Returns:
            导入结果
        """
        logger.info(f"Importing by1={new_by1} with strategy={strategy}")

        # 检查是否已存在
        existing = self.repo.get_by_by1(new_by1)
        if existing:
            return {
                "success": False,
                "message": f"by1={new_by1} 已存在",
                "existing_data": existing,
            }

        # 搜索相似品种
        similar_results = self.search_by_prefix(new_by1, top_k=top_k)

        if not similar_results:
            return {"success": False, "message": f"未找到与 {new_by1} 前缀匹配的品种"}

        # 获取详细信息
        candidates = []
        for result in similar_results:
            by1 = result["by1"]
            detail = self.repo.get_by_by1(by1)
            if detail:
                edesc_list = detail.get("edesc_list", [])
                edesc_text = "; ".join(edesc_list)
                candidates.append(
                    Candidate(
                        by1=by1,
                        score=result["score"],
                        prefix_match_len=result["prefix_match_len"],
                        edesc_count=detail["edesc_count"],
                        edesc=edesc_text,
                        edesc_length=len(edesc_text),
                    )
                )

        if not candidates:
            return {"success": False, "message": "无法获取相似品种的详细信息"}

        # 使用策略选择
        strategy_instance = get_strategy(strategy)
        selected = strategy_instance.select(candidates)

        # 导入新 by1（直接使用源 by1 的 edesc_list，已是标准化数据）
        source_detail = self.repo.get_by_by1(selected.by1)
        source_edesc_list = source_detail.get("edesc_list", []) if source_detail else []

        parent_id = self._add_product_with_embedding(
            product_name=new_by1,
            edesc_list=source_edesc_list,
            metadata={
                "by1": new_by1,
                "edesc_count": selected.edesc_count,
                "source_by1": selected.by1,
                "source_score": round(selected.score, 4),
                "prefix_match_len": selected.prefix_match_len,
                "import_strategy": strategy,
            },
        )

        logger.info(f"Imported by1={new_by1} from source={selected.by1}")

        return {
            "success": True,
            "message": f"成功为 {new_by1} 导入货描",
            "new_by1": new_by1,
            "selected_source": {
                "by1": selected.by1,
                "score": round(selected.score, 4),
                "prefix_match_len": selected.prefix_match_len,
                "edesc_count": selected.edesc_count,
            },
            "all_candidates": [c.to_dict() for c in candidates],
            "imported_edesc_preview": "; ".join(source_edesc_list[:2])[:200] + "...",
            "parent_id": parent_id,
        }

    def batch_import(
        self, by1_list: List[str], strategy: str = "most_references"
    ) -> Dict[str, Any]:
        """
        批量智能导入

        Args:
            by1_list: by1 列表
            strategy: 选择策略

        Returns:
            批量导入结果
        """
        logger.info(f"Batch importing {len(by1_list)} by1s")

        results = []
        success_count = 0

        for by1 in by1_list:
            result = self.import_by1(by1, strategy=strategy)
            results.append({"by1": by1, **result})
            if result["success"]:
                success_count += 1

        return {
            "total": len(by1_list),
            "success_count": success_count,
            "fail_count": len(by1_list) - success_count,
            "details": results,
        }

    # ==================== 内部方法 ====================

    def _add_product_with_embedding(
        self, product_name: str, edesc_list: list, metadata: Optional[Dict] = None
    ) -> str:
        """
        添加产品及其嵌入向量（标准化数据模型）

        每条 edesc 独立编码，存为独立子块。

        Args:
            product_name: 产品名称
            edesc_list: 标准化货描列表
            metadata: 元数据

        Returns:
            parent_id
        """
        parent_id = generate_parent_id(product_name)

        # 插入父块
        self.repo.upsert_parent(
            parent_id=parent_id,
            product_name=product_name,
            edesc_list=edesc_list,
            metadata=metadata,
        )

        # 每条 edesc 独立编码为子块
        if edesc_list:
            embeddings = self.embedder.encode(edesc_list)
            child_points = []
            for idx, (text, emb) in enumerate(zip(edesc_list, embeddings)):
                child_id = generate_child_id(parent_id, idx)
                vec = list(emb) if not isinstance(emb, list) else emb
                child_points.append(
                    PointStruct(
                        id=child_id,
                        vector=vec,
                        payload={
                            "parent_id": parent_id,
                            "edesc_index": idx,
                            "edesc_text": text,
                            "productName": product_name,
                        },
                    )
                )
            self.repo.upsert_children(child_points)

        return parent_id

    # ==================== 统计与导出 ====================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.store.get_stats()

    def export_all(self) -> List[Dict[str, Any]]:
        """导出所有数据"""
        return self.repo.export_all()

    def batch_add_edesc(self, data_list: List[Dict]) -> Dict[str, Any]:
        """
        批量添加货描

        Args:
            data_list: 数据列表，每项包含 {by1, edesc, metadata可选}

        Returns:
            批量操作结果
        """
        success_count = 0
        fail_count = 0
        details = []

        for item in data_list:
            by1 = item.get("by1")
            edesc = item.get("edesc")
            metadata = item.get("metadata")

            if not by1 or not edesc:
                fail_count += 1
                details.append(
                    {"by1": by1, "success": False, "reason": "缺少by1或edesc"}
                )
                continue

            result = self.add_edesc(by1, edesc, metadata)
            if result["success"]:
                success_count += 1
            else:
                fail_count += 1
            details.append({"by1": by1, **result})

        return {
            "total": len(data_list),
            "success_count": success_count,
            "fail_count": fail_count,
            "details": details,
        }
