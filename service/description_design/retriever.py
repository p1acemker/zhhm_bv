"""Qdrant-backed template retrieval with deterministic conflict handling."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from qdrant_client.models import FieldCondition, Filter, MatchValue


logger = logging.getLogger(__name__)


class TemplateRetriever:
    """Retrieve compatible valve-description templates from Qdrant."""

    def __init__(
        self,
        client: Any,
        embedder: Any,
        collection: str,
        *,
        reranker: Any = None,
        candidate_limit: int = 100,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection = collection
        self.reranker = reranker
        self.candidate_limit = max(20, min(int(candidate_limit), 100))

    def retrieve(
        self,
        query: str,
        query_design: Mapping[str, Any],
        *,
        by1: str = "",
        form_code: str = "",
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Return compatible templates ordered by fields, context, and semantics."""
        vector = self.embedder.encode(query)
        return self.retrieve_with_vector(
            vector,
            query,
            query_design,
            by1=by1,
            form_code=form_code,
            top_k=top_k,
        )

    def retrieve_with_vector(
        self,
        vector: list[float],
        query: str,
        query_design: Mapping[str, Any],
        *,
        by1: str = "",
        form_code: str = "",
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve templates using a caller-provided query vector."""
        if query_design.get("product_role") != "valve":
            return []
        family = query_design.get("valve_family")
        if not family:
            return []
        query_filter = Filter(
            must=[
                FieldCondition(key="product_role", match=MatchValue(value="valve")),
                FieldCondition(key="valve_family", match=MatchValue(value=family)),
            ]
        )
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=self.candidate_limit,
            with_payload=True,
            with_vectors=False,
        )
        explicit = {
            field: item.get("value")
            for field, item in query_design.get("attributes", {}).items()
            if field != "size" and item.get("source") == "query" and item.get("value")
        }
        candidates = []
        normalized_by1 = str(by1).strip().upper()
        normalized_form = str(form_code).strip().upper()
        for point in response.points:
            payload = dict(point.payload or {})
            attributes = payload.get("attributes") or {}
            if self._has_conflict(explicit, attributes):
                continue
            comparable = [field for field in explicit if field in attributes]
            matches = sum(attributes[field] == explicit[field] for field in comparable)
            expected_fields = list(explicit)
            field_match_ratio = matches / len(expected_fields) if expected_fields else 0.0
            by1_match = bool(normalized_by1 and normalized_by1 in payload.get("supported_by1", []))
            form_match = bool(normalized_form and normalized_form in payload.get("form_codes", []))
            candidates.append(
                {
                    **payload,
                    "vector_score": float(point.score),
                    "score": float(point.score),
                    "field_match_ratio": round(field_match_ratio, 4),
                    "matched_field_count": matches,
                    "by1_match": by1_match,
                    "form_match": form_match,
                    "by1_form_match": by1_match and form_match,
                    "matched_descriptions": [payload.get("standardized_description", "")],
                    "reranker_used": False,
                }
            )
        candidates.sort(key=self._sort_key, reverse=True)
        if self.reranker is not None and candidates:
            head = candidates[:20]
            try:
                reranked = self.reranker.rerank(query, normalized_form, head)
                candidates = reranked + candidates[20:]
            except Exception as exc:
                logger.warning("Template reranking failed: %s", exc)
            candidates.sort(key=self._sort_key, reverse=True)
        limit = max(1, min(int(top_k), self.candidate_limit))
        return [self._public_candidate(item) for item in candidates[:limit]]

    @staticmethod
    def _has_conflict(
        explicit: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> bool:
        return any(
            field in candidate and candidate[field] != value
            for field, value in explicit.items()
        )

    @staticmethod
    def _sort_key(item: Mapping[str, Any]) -> tuple[float, int, int, int, float, int]:
        return (
            float(item.get("field_match_ratio", 0.0)),
            int(bool(item.get("by1_form_match"))),
            int(bool(item.get("form_match"))),
            int(bool(item.get("by1_match"))),
            float(item.get("score", item.get("vector_score", 0.0))),
            int(item.get("support", 0)),
        )

    @staticmethod
    def _public_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "template_id": item.get("template_id"),
            "standardized_description": item.get("standardized_description"),
            "score": round(float(item.get("score", 0.0)), 4),
            "vector_score": round(float(item.get("vector_score", 0.0)), 4),
            "field_match_ratio": item.get("field_match_ratio", 0.0),
            "by1": sorted({str(value) for value in item.get("supported_by1", []) if value}),
            "form_codes": sorted({str(value) for value in item.get("form_codes", []) if value}),
            "by1_match": bool(item.get("by1_match")),
            "form_match": bool(item.get("form_match")),
            "by1_form_match": bool(item.get("by1_form_match")),
            "support": int(item.get("support", 0)),
            "reranker_used": bool(item.get("reranker_used")),
            "_attributes": dict(item.get("attributes") or {}),
        }
