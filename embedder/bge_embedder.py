# -*- coding: utf-8 -*-
"""BGE-M3 embedding client."""

import logging
from typing import List, Optional, cast

import requests

from .base import BaseEmbedder, EmbeddingInput, EmbeddingOutput

logger = logging.getLogger(__name__)


class BGEEmbedder(BaseEmbedder):
    """Embedding client backed by the remote BGE-M3 API."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        timeout: int = 30,
    ) -> None:
        from config import EMBEDDING_API_URL, EMBEDDING_DIM, EMBEDDING_MODEL

        self.api_url = api_url or EMBEDDING_API_URL
        self.model = model or EMBEDDING_MODEL
        self.embedding_dim = embedding_dim or EMBEDDING_DIM
        self.timeout = timeout
        self.headers = {
            "User-Agent": "yaak",
            "Accept": "*/*",
            "Content-Type": "application/json",
        }

        logger.debug(
            "BGEEmbedder init: %s, model=%s, dim=%s",
            self.api_url,
            self.model,
            self.embedding_dim,
        )

    def encode(self, texts: EmbeddingInput, batch_size: int = 32) -> EmbeddingOutput:
        """Encode one text or a batch of texts into embedding vectors."""
        single = isinstance(texts, str)
        normalized_texts = [texts] if single else texts
        normalized_texts = [t if t and str(t).strip() else "" for t in normalized_texts]

        all_embeddings: List[List[float]] = []
        for i in range(0, len(normalized_texts), batch_size):
            batch = normalized_texts[i : i + batch_size]
            all_embeddings.extend(self._call_api(batch))

        return all_embeddings[0] if single else all_embeddings

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Call the embedding API and return one vector per input text."""
        payload = {"model": self.model, "input": texts}
        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            if "data" in result:
                return [item["embedding"] for item in result["data"]]
            if "embeddings" in result:
                return result["embeddings"]
            raise ValueError(f"Unknown API response format: {result.keys()}")
        except requests.exceptions.Timeout:
            logger.error("Embedding API timeout: %s", self.api_url)
            raise
        except requests.exceptions.RequestException as exc:
            logger.error("Embedding API error: %s", exc)
            raise

    def health_check(self) -> bool:
        """Return True when the remote embedding service returns one vector."""
        try:
            result = cast(List[float], self.encode("test"))
            return len(result) == self.embedding_dim
        except Exception as exc:
            logger.warning("Embedder health check failed: %s", exc)
            return False
