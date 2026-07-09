# -*- coding: utf-8 -*-
"""Repository helpers for storing and searching product descriptions in Qdrant."""

from typing import Any, Dict, List, Optional
import logging

import requests as http_req
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

logger = logging.getLogger(__name__)


class QdrantRepo:
    """Repository layer for parent/child Qdrant collections."""

    def __init__(self, client: QdrantClient, parent_collection: str, child_collection: str) -> None:
        self.client = client
        self.parent_collection = parent_collection
        self.child_collection = child_collection
        self._base_url = client._client.rest_uri

    def add_product_with_edesc_list(
        self,
        product_name: str,
        edesc_list: List[str],
        embedding_func: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Upsert a parent point and its child description points."""
        from config import EMBEDDING_DIM
        from utils.id_utils import generate_child_id, generate_parent_id

        parent_id = generate_parent_id(product_name)
        payload_metadata = metadata or {}

        self.client.upsert(
            collection_name=self.parent_collection,
            points=[
                PointStruct(
                    id=parent_id,
                    vector=[0.0] * EMBEDDING_DIM,
                    payload={
                        "productName": product_name,
                        "edesc_list": edesc_list,
                        "edesc_count": len(edesc_list),
                        "metadata": payload_metadata,
                        **payload_metadata,
                    },
                )
            ],
        )

        if edesc_list and embedding_func:
            embeddings = embedding_func(edesc_list)
            if len(embeddings) != len(edesc_list):
                raise ValueError(
                    f"Embedding count mismatch: expected {len(edesc_list)}, got {len(embeddings)}"
                )

            child_points: List[PointStruct] = []
            for idx, (text, embedding) in enumerate(zip(edesc_list, embeddings)):
                vector = list(embedding) if not isinstance(embedding, list) else embedding
                if len(vector) != EMBEDDING_DIM:
                    raise ValueError(
                        f"Embedding dim mismatch: expected {EMBEDDING_DIM}, got {len(vector)}"
                    )
                child_points.append(
                    PointStruct(
                        id=generate_child_id(parent_id, idx),
                        vector=vector,
                        payload={
                            "parent_id": parent_id,
                            "edesc_index": idx,
                            "edesc_text": text,
                            "productName": product_name,
                        },
                    )
                )

            if child_points:
                self.client.upsert(
                    collection_name=self.child_collection,
                    points=child_points,
                )

        logger.info("Added product %s with %s descriptions", product_name, len(edesc_list))
        return parent_id

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Search child points and hydrate unique parent results."""
        limit = top_k * 5
        child_results: List[Any] = []

        try:
            response = http_req.post(
                f"{self._base_url}/collections/{self.child_collection}/points/search",
                json={"vector": query_vector, "limit": limit, "with_payload": True},
                timeout=30,
            )
            if response.status_code == 200:
                raw_hits = response.json().get("result", [])
                child_results = [
                    type("Hit", (), {"score": hit["score"], "payload": hit.get("payload", {})})()
                    for hit in raw_hits
                ]
        except Exception:
            child_results = []

        if not child_results:
            try:
                search_response = self.client.query_points(
                    collection_name=self.child_collection,
                    query=query_vector,
                    limit=limit,
                    with_payload=True,
                )
                child_results = search_response.points
            except Exception as exc:
                logger.error("Vector search failed: %s", exc)
                return []

        if not child_results:
            return []

        if score_threshold is not None:
            child_results = [result for result in child_results if result.score >= score_threshold]
            if not child_results:
                return []

        parent_scores: Dict[str, Dict[str, Any]] = {}
        for hit in child_results:
            parent_id = hit.payload.get("parent_id")
            if not parent_id:
                continue
            if parent_id not in parent_scores:
                parent_scores[parent_id] = {
                    "score": hit.score,
                    "matched_edescs": [hit.payload.get("edesc_text", "")],
                }
            else:
                if hit.score > parent_scores[parent_id]["score"]:
                    parent_scores[parent_id]["score"] = hit.score
                parent_scores[parent_id]["matched_edescs"].append(
                    hit.payload.get("edesc_text", "")
                )

        sorted_parents = sorted(
            parent_scores.items(),
            key=lambda item: item[1]["score"],
            reverse=True,
        )[:top_k]

        parent_ids = [parent_id for parent_id, _ in sorted_parents]
        parent_map: Dict[str, Any] = {}
        try:
            response = http_req.post(
                f"{self._base_url}/collections/{self.parent_collection}/points",
                json={"ids": parent_ids, "with_payload": True},
                timeout=15,
            )
            if response.status_code == 200:
                for point in response.json().get("result", []):
                    parent_map[point["id"]] = type(
                        "ParentPoint",
                        (),
                        {"payload": point.get("payload", {})},
                    )()
        except Exception:
            parent_map = {}

        if not parent_map:
            for hit in child_results:
                parent_id = hit.payload.get("parent_id")
                product_name = hit.payload.get("productName", "")
                if parent_id and parent_id not in parent_map and product_name:
                    parent_map[parent_id] = type(
                        "ParentPoint",
                        (),
                        {
                            "payload": {
                                "productName": product_name,
                                "edesc_list": [],
                                "edesc_count": 0,
                                "metadata": {},
                            }
                        },
                    )()

        results: List[Dict[str, Any]] = []
        for parent_id, info in sorted_parents:
            if parent_id not in parent_map:
                continue
            parent = parent_map[parent_id]
            results.append(
                {
                    "productName": parent.payload.get("productName", ""),
                    "edesc_list": parent.payload.get("edesc_list", []),
                    "edesc_count": parent.payload.get("edesc_count", 0),
                    "parent_id": parent_id,
                    "score": info["score"],
                    "matched_edescs": info["matched_edescs"][:3],
                    "metadata": parent.payload.get("metadata", {}),
                }
            )
        return results

    def delete_by_parent_id(self, parent_id: str) -> None:
        """Delete a parent point and all linked child points."""
        self.client.delete(
            collection_name=self.parent_collection,
            points_selector=[parent_id],
        )
        self.client.delete(
            collection_name=self.child_collection,
            points_selector=Filter(
                must=[
                    FieldCondition(key="parent_id", match=MatchValue(value=parent_id))
                ]
            ),
        )
        logger.debug("Deleted parent and children: %s", parent_id)

    def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        """Load a single product by its by1 code."""
        points, _ = self.client.scroll(
            collection_name=self.parent_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="productName", match=MatchValue(value=by1))]
            ),
            limit=10,
            with_payload=True,
        )
        if not points:
            return None

        point = points[0]
        payload = point.payload
        edesc_list = payload.get("edesc_list", [])
        return {
            "by1": by1,
            "parent_id": point.id,
            "productName": payload.get("productName", ""),
            "edesc_list": edesc_list,
            "edesc_count": payload.get("edesc_count", len(edesc_list)),
            "metadata": payload.get("metadata", {}),
        }

    def get_all_by1s(self, limit: int = 10000) -> List[str]:
        """Return all product by1 codes from the parent collection."""
        points, _ = self.client.scroll(
            collection_name=self.parent_collection,
            limit=limit,
            with_payload=True,
        )
        return [point.payload.get("productName", "") for point in points]
