"""Local template retrieval with explicit attribute conflict filtering."""

from __future__ import annotations

import json
import logging
from math import log1p
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .template_models import DescriptionViews


logger = logging.getLogger(__name__)


def _unit(vector: Any) -> np.ndarray:
    values = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(values))
    return values / norm if norm else np.zeros_like(values)


def _value(attribute: Any) -> str:
    if isinstance(attribute, Mapping):
        attribute = attribute.get("value")
    return "" if attribute is None else str(attribute).strip().upper()


class By1TemplateRetriever:
    """Retrieve template candidates from the generated local JSON index."""

    def __init__(self, index_path: str | Path, embedder: Any) -> None:
        self.index_path = Path(index_path)
        self.embedder = embedder
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ValueError("Unsupported by1 template index version")
        self.version = str(payload.get("template_version", payload.get("version")))
        self.templates = list(payload.get("templates", []))
        if not self.templates:
            raise ValueError("by1 template index contains no templates")

    @classmethod
    def from_config(cls) -> "By1TemplateRetriever":
        from config import BY1_TEMPLATE_INDEX_PATH
        from embedder import BGEEmbedder

        return cls(BY1_TEMPLATE_INDEX_PATH, BGEEmbedder(timeout=30))

    def retrieve(
        self,
        query_views: DescriptionViews,
        form_code: str,
        top_k: int = 50,
    ) -> list[dict[str, object]]:
        """Return compatible template candidates or an empty fallback result."""
        try:
            query_vector = _unit(self.embedder.encode(query_views.structural_description))
            explicit = {
                field: evidence.value.strip().upper()
                for field, evidence in query_views.attributes.items()
                if evidence.value and field != "size"
            }
            normalized_form = str(form_code or "").strip().upper()
            candidates: list[dict[str, object]] = []
            for template in self.templates:
                attributes = template.get("attributes", {})
                if self._has_conflict(explicit, attributes):
                    continue
                vector = _unit(template.get("representative_vector", []))
                structural_score = float(np.clip(query_vector @ vector, -1.0, 1.0))
                comparable = [field for field in explicit if field in attributes]
                matches = sum(
                    _value(attributes[field]) == explicit[field]
                    for field in comparable
                )
                match_ratio = matches / len(explicit) if explicit else 0.0
                supported_forms = {
                    str(value).strip().upper()
                    for value in template.get("supported_form_codes", [])
                }
                form_match = bool(normalized_form and normalized_form in supported_forms)
                support = max(0, int(template.get("support", 0)))
                score = (
                    0.70 * structural_score
                    + 0.20 * match_ratio
                    + 0.05 * float(form_match)
                    + 0.05 * min(log1p(support) / 6.0, 1.0)
                )
                candidates.append(
                    {
                        "template_id": template.get("template_id"),
                        "by1": template.get("by1"),
                        "structural_score": round(structural_score, 4),
                        "score": round(score, 4),
                        "attribute_match_ratio": round(match_ratio, 4),
                        "form_match": form_match,
                        "support": support,
                        "representative_description": template.get(
                            "representative_description", ""
                        ),
                        "spec_profile": template.get("spec_profiles", []),
                        "evidence": {
                            "structural_description": query_views.structural_description,
                            "matched_attributes": comparable,
                        },
                    }
                )
            candidates.sort(
                key=lambda item: (
                    float(item["score"]),
                    int(bool(item["form_match"])),
                    int(item["support"]),
                    str(item["template_id"]),
                ),
                reverse=True,
            )
            return candidates[: max(1, min(int(top_k), 100))]
        except Exception as exc:
            logger.warning("By1 template retrieval failed: %s", exc)
            return []

    @staticmethod
    def _has_conflict(
        explicit: Mapping[str, str],
        candidate: Mapping[str, Any],
    ) -> bool:
        return any(
            field in candidate and _value(candidate[field]) != value
            for field, value in explicit.items()
        )
