# -*- coding: utf-8 -*-
"""
EDesc service orchestration.

This module standardizes incoming descriptions, delegates vector operations
to the repository, and owns the user-facing service result contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
import json
import logging
import os

from strategy.import_strategy import Candidate, rank_prefix_matches, select_best

if TYPE_CHECKING:
    from embedder.base import BaseEmbedder
    from qdrant_store import QdrantVectorStore
    from repo.qdrant_repo import QdrantRepo

logger = logging.getLogger(__name__)


def _standardize(edesc: str) -> str:
    """Return the standardized description text for a raw description."""
    from scripts.edesc_standardizer import standardize_edesc

    result = standardize_edesc(edesc)
    return result["standardized"]


class EDescService:
    """Service layer for eDesc search, add, and import workflows."""

    def __init__(
        self,
        store: QdrantVectorStore,
        embedder: BaseEmbedder,
        repo: QdrantRepo,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.repo = repo
        self._spec_rules: Optional[Dict[str, Dict[str, List[str]]]] = None
        logger.info("EDescService initialized")

    def _get_spec_rules(self) -> Dict[str, Dict[str, List[str]]]:
        """Load customer spec rules lazily."""
        if self._spec_rules is None:
            rule_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "by1_customer_spec_rules.json",
            )
            if os.path.exists(rule_path):
                with open(rule_path, "r", encoding="utf-8") as handle:
                    self._spec_rules = json.load(handle)
                logger.info("Loaded spec rules: %s by1 entries", len(self._spec_rules))
            else:
                self._spec_rules = {}
        return self._spec_rules

    def search_by_edesc_raw(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        customer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search products by a raw description string."""
        standardized_query = _standardize(query)
        logger.debug("Searching standardized description: %s", standardized_query[:50])
        query_vector = self.embedder.encode(standardized_query)
        results = self.repo.search(
            query_vector,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        rules = self._get_spec_rules() if customer else {}
        for result in results:
            if customer:
                by1_key = result.get("productName", "")
                result["matched_specs"] = rules.get(by1_key, {}).get(customer)
            else:
                result["matched_specs"] = None

        return results

    def add_edesc(
        self,
        by1: str,
        edesc: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a standardized description to an existing or new product."""
        logger.info("Adding description for by1=%s", by1)
        original = edesc.strip()
        standardized = _standardize(original)

        existing = self.repo.get_by_by1(by1)
        if existing:
            existing_list = existing.get("edesc_list", [])
            if standardized in existing_list:
                logger.info("Description already exists for by1=%s", by1)
                return {
                    "success": False,
                    "message": f"Description already exists for by1={by1}",
                    "is_duplicate": True,
                    "existing_edesc_count": len(existing_list),
                }

            new_edesc_list = existing_list + [standardized]
            new_metadata = dict(existing.get("metadata", {}))
            new_metadata["by1"] = by1
            new_metadata["edesc_count"] = len(new_edesc_list)
            if metadata:
                new_metadata.update(metadata)

            self.repo.delete_by_parent_id(existing["parent_id"])
            parent_id = self._add_product_with_embedding(
                product_name=by1,
                edesc_list=new_edesc_list,
                metadata=new_metadata,
            )
            return {
                "success": True,
                "message": f"Appended description for by1={by1}",
                "action": "appended",
                "parent_id": parent_id,
                "original": original,
                "standardized": standardized,
                "old_edesc_count": len(existing_list),
                "new_edesc_count": len(new_edesc_list),
            }

        create_metadata = {"by1": by1, "edesc_count": 1}
        if metadata:
            create_metadata.update(metadata)
        parent_id = self._add_product_with_embedding(
            product_name=by1,
            edesc_list=[standardized],
            metadata=create_metadata,
        )
        return {
            "success": True,
            "message": f"Created product by1={by1}",
            "action": "created",
            "parent_id": parent_id,
            "original": original,
            "standardized": standardized,
        }

    def batch_import(
        self,
        by1_list: List[str],
        strategy: str = "most_references",
    ) -> Dict[str, Any]:
        """Import multiple missing products by reusing ranked prefix candidates."""
        logger.info("Batch importing %s by1 values with strategy=%s", len(by1_list), strategy)
        details: List[Dict[str, Any]] = []
        success_count = 0

        for by1 in by1_list:
            item_result = self._import_single(by1)
            details.append({"by1": by1, **item_result})
            if item_result["success"]:
                success_count += 1

        return {
            "total": len(by1_list),
            "success_count": success_count,
            "fail_count": len(by1_list) - success_count,
            "details": details,
        }

    def _import_single(self, new_by1: str) -> Dict[str, Any]:
        """Import a single product by copying descriptions from the best prefix match."""
        existing = self.repo.get_by_by1(new_by1)
        if existing:
            return {
                "success": False,
                "message": f"by1={new_by1} already exists",
                "existing_data": existing,
            }

        all_by1s = self.repo.get_all_by1s()
        similar = rank_prefix_matches(new_by1, all_by1s, top_k=5)
        if not similar:
            return {
                "success": False,
                "message": f"No prefix candidates found for {new_by1}",
            }

        candidates: List[Candidate] = []
        for item in similar:
            detail = self.repo.get_by_by1(item["by1"])
            if detail:
                candidates.append(
                    Candidate(
                        by1=item["by1"],
                        score=item["score"],
                        prefix_match_len=item["prefix_match_len"],
                        edesc_count=detail["edesc_count"],
                        edesc="; ".join(detail.get("edesc_list", [])),
                    )
                )

        if not candidates:
            return {
                "success": False,
                "message": "No candidate details could be loaded",
            }

        selected = select_best(candidates)
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
            },
        )

        logger.info("Imported by1=%s from source=%s", new_by1, selected.by1)
        return {
            "success": True,
            "message": f"Imported {new_by1} from {selected.by1}",
            "new_by1": new_by1,
            "selected_source": {
                "by1": selected.by1,
                "score": round(selected.score, 4),
                "prefix_match_len": selected.prefix_match_len,
                "edesc_count": selected.edesc_count,
            },
            "parent_id": parent_id,
        }

    def _add_product_with_embedding(
        self,
        product_name: str,
        edesc_list: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Delegate product creation to the repository using the embedder."""
        return self.repo.add_product_with_edesc_list(
            product_name=product_name,
            edesc_list=edesc_list,
            embedding_func=self.embedder.encode,
            metadata=metadata,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return service-level collection stats."""
        return self.store.get_stats()
