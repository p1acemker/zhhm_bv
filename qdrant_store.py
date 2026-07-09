# -*- coding: utf-8 -*-
"""Qdrant connection and collection lifecycle helpers."""

import logging
from typing import Any, Dict, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Manage Qdrant connectivity and collection initialization."""

    def __init__(
        self,
        url: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        parent_collection: Optional[str] = None,
        child_collection: Optional[str] = None,
    ) -> None:
        from config import CHILD_COLLECTION, EMBEDDING_DIM, PARENT_COLLECTION, QDRANT_URL

        self.client = QdrantClient(
            url=url or QDRANT_URL,
            timeout=60,
            check_compatibility=False,
        )
        self.embedding_dim = embedding_dim or EMBEDDING_DIM
        self.parent_collection = parent_collection or PARENT_COLLECTION
        self.child_collection = child_collection or CHILD_COLLECTION

    def init_collections(self) -> None:
        """Create the parent and child collections when they are missing."""
        if not self.client.collection_exists(self.parent_collection):
            self.client.create_collection(
                collection_name=self.parent_collection,
                vectors_config=VectorParams(size=4, distance=Distance.COSINE),
            )
            logger.info("Created parent collection: %s", self.parent_collection)

        if not self.client.collection_exists(self.child_collection):
            self.client.create_collection(
                collection_name=self.child_collection,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
            self.client.create_payload_index(
                collection_name=self.child_collection,
                field_name="parent_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            self.client.create_payload_index(
                collection_name=self.child_collection,
                field_name="productName",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created child collection: %s", self.child_collection)

    def clear_collections(self) -> None:
        """Delete all points from both collections."""
        from qdrant_client.models import Filter

        for collection in [self.parent_collection, self.child_collection]:
            self.client.delete(collection_name=collection, points_selector=Filter())
        logger.info("Cleared all collection data")

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Return names and point counts for the configured collections."""
        parent_info = self.client.get_collection(self.parent_collection)
        child_info = self.client.get_collection(self.child_collection)
        return {
            "parent_collection": {
                "name": self.parent_collection,
                "points_count": parent_info.points_count,
            },
            "child_collection": {
                "name": self.child_collection,
                "points_count": child_info.points_count,
            },
        }
