"""Full-label BGE/Qdrant candidate retrieval for low-evidence searches."""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any, Optional

from qdrant_client import QdrantClient

from scripts.edesc_standardizer import standardize_edesc_for_by1


logger = logging.getLogger(__name__)


class CandidateRetriever:
    """Retrieve and aggregate a broad child-description candidate pool."""

    def __init__(
        self,
        client: QdrantClient,
        embedder: Any,
        child_collection: str,
        child_limit: int = 100,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.child_collection = child_collection
        self.child_limit = max(50, int(child_limit))

    @classmethod
    def from_config(cls) -> "CandidateRetriever":
        """Create a retriever using the configured full recommendation index."""
        from config import (
            QDRANT_URL,
            RECOMMENDATION_CHILD_COLLECTION,
            RECOMMENDATION_VECTOR_CANDIDATES,
        )
        from embedder import BGEEmbedder

        client = QdrantClient(url=QDRANT_URL, timeout=60, check_compatibility=False)
        return cls(
            client=client,
            embedder=BGEEmbedder(timeout=30),
            child_collection=RECOMMENDATION_CHILD_COLLECTION,
            child_limit=RECOMMENDATION_VECTOR_CANDIDATES,
        )

    def retrieve(
        self,
        query: str,
        form_code: str = "",
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        """Return distinct by1 candidates ranked from the configured child pool."""
        semantic_query = standardize_edesc_for_by1(query)
        if not semantic_query:
            return []
        try:
            vector = self.embedder.encode(semantic_query)
            response = self.client.query_points(
                collection_name=self.child_collection,
                query=vector,
                limit=self.child_limit,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.warning("Recommendation vector retrieval failed: %s", exc)
            return []

        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "scores": [],
                "support": 0,
                "form_match": False,
                "matched_descriptions": [],
            }
        )
        normalized_form = str(form_code).upper().replace(" ", "")
        for hit in response.points:
            payload = hit.payload or {}
            by1 = str(payload.get("by1") or payload.get("productName") or "")
            if not by1:
                continue
            item = grouped[by1]
            item["scores"].append(float(hit.score))
            item["support"] += int(payload.get("support", 1))
            item["form_match"] = item["form_match"] or bool(
                normalized_form and payload.get("form_code") == normalized_form
            )
            if len(item["matched_descriptions"]) < 3:
                item["matched_descriptions"].append(
                    payload.get("example") or payload.get("description") or ""
                )

        candidates = []
        for by1, item in grouped.items():
            scores = sorted(item["scores"], reverse=True)
            top_scores = scores[:3]
            vector_score = scores[0]
            mean_score = sum(top_scores) / len(top_scores)
            rank_score = 0.85 * vector_score + 0.15 * mean_score
            if item["form_match"]:
                rank_score += 0.03
            candidates.append(
                {
                    "by1": by1,
                    "productName": by1,
                    "score": round(rank_score, 4),
                    "vector_score": round(vector_score, 4),
                    "support": item["support"],
                    "form_match": item["form_match"],
                    "matched_descriptions": item["matched_descriptions"],
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[: max(1, min(int(top_k), 50))]
