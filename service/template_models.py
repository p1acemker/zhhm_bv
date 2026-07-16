"""Typed records shared by description-template builders and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


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


@dataclass(frozen=True)
class TemplateMember:
    """One historical description assigned to a by1 template cluster."""

    point_id: str
    by1: str
    views: DescriptionViews
    structural_vector: np.ndarray
    form_code: str
    spec: str
    parsed_size: str
    support: int


@dataclass(frozen=True)
class TemplateCluster:
    """A deterministic, by1-scoped cluster of historical descriptions."""

    template_id: str
    by1: str
    cluster_id: int
    member_ids: tuple[str, ...]
    representative_point_id: str
    structural_signature: str
    cohesion: float
    outlier_count: int
    template_status: str = "clustered"
