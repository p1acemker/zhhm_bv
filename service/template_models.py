"""Typed records shared by description-template builders and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AttributeEvidence:
    """One explicitly observed or validated attribute value."""

    value: str | None
    source: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class DescriptionViews:
    """Lossless raw, structural, and full description representations."""

    raw_description: str
    normalized_description: str
    structural_description: str
    full_description: str
    attributes: dict[str, AttributeEvidence]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation for index builders."""
        return asdict(self)
