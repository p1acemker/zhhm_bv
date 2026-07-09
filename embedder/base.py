# -*- coding: utf-8 -*-
"""Embedding client interface."""

from abc import ABC, abstractmethod
from typing import List, Union

Embedding = List[float]
EmbeddingInput = Union[str, List[str]]
EmbeddingOutput = Union[Embedding, List[Embedding]]


class BaseEmbedder(ABC):
    """Abstract interface implemented by embedding clients."""

    @abstractmethod
    def encode(self, texts: EmbeddingInput, batch_size: int = 32) -> EmbeddingOutput:
        """Encode one text or a batch of texts into embedding vectors."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return whether the embedding service is reachable and well-formed."""
