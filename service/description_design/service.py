"""Application service combining dictionary rules, rendering, and Qdrant templates."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from .dictionary import BusinessDictionary
from .engine import DescriptionDesignEngine


logger = logging.getLogger(__name__)


def _is_active(value: object) -> bool:
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


class DescriptionDesignService:
    """Generate a deterministic design and attach compatible Qdrant templates."""

    def __init__(
        self,
        engine: DescriptionDesignEngine,
        *,
        mature_rules: Mapping[tuple[str, str], Mapping[str, Mapping[str, Any]]] | None = None,
        retriever: Any = None,
        dictionary_version: str = "bootstrap",
    ) -> None:
        self.engine = engine
        self.mature_rules = dict(mature_rules or {})
        self.retriever = retriever
        self.dictionary_version = dictionary_version

    @classmethod
    def from_dictionary_path(
        cls,
        path: str | Path,
        *,
        retriever: Any = None,
    ) -> "DescriptionDesignService":
        """Load dictionary terms and mature rules from compiled JSON."""
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        dictionary = BusinessDictionary.from_compiled_json(path)
        rules: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for row in payload.get("sheets", {}).get("品种形式规则", []):
            if not _is_active(row.get("active", True)):
                continue
            by1 = str(row.get("by1") or "").strip().upper()
            form_code = str(row.get("form_code") or "").strip().upper()
            field = str(row.get("field") or "").strip()
            value = str(row.get("value") or "").strip()
            confidence = float(row.get("confidence") or 0.0)
            if not by1 or not field or not value or confidence < 0.99:
                continue
            rules.setdefault((by1, form_code), {})[field] = {
                "value": value,
                "source": "mature_rule",
                "confidence": confidence,
            }
        return cls(
            DescriptionDesignEngine(dictionary),
            mature_rules=rules,
            retriever=retriever,
            dictionary_version=str(payload.get("version") or "unknown"),
        )

    @classmethod
    def from_config(cls) -> "DescriptionDesignService":
        """Build the runtime service from local dictionary and Qdrant configuration."""
        from config import (
            EDESC_DICTIONARY_JSON_PATH,
            EDESC_TEMPLATE_ALIAS,
            EDESC_TEMPLATE_CANDIDATES,
            QDRANT_URL,
        )
        from embedder import BGEEmbedder
        from qdrant_client import QdrantClient
        from service.candidate_reranker import CandidateReranker, RerankerClient

        dictionary_path = Path(EDESC_DICTIONARY_JSON_PATH)
        reranker_client = RerankerClient.from_config()
        retriever = None
        try:
            from .retriever import TemplateRetriever

            retriever = TemplateRetriever(
                QdrantClient(url=QDRANT_URL, timeout=60, check_compatibility=False),
                BGEEmbedder(timeout=30),
                EDESC_TEMPLATE_ALIAS,
                reranker=CandidateReranker(reranker_client) if reranker_client else None,
                candidate_limit=EDESC_TEMPLATE_CANDIDATES,
            )
        except Exception as exc:
            logger.warning("Template retriever initialization failed: %s", exc)
        if dictionary_path.exists():
            return cls.from_dictionary_path(dictionary_path, retriever=retriever)
        logger.warning("Description dictionary is missing: %s", dictionary_path)
        return cls(DescriptionDesignEngine(), retriever=retriever)

    def design(
        self,
        query: str,
        *,
        by1_candidates: list[Mapping[str, Any]] | None = None,
        form_code: str = "",
    ) -> dict[str, Any]:
        """Return one design with rule evidence and up to three template alternatives."""
        by1 = ""
        if by1_candidates:
            by1 = str(by1_candidates[0].get("by1") or by1_candidates[0].get("productName") or "")
        inferred = dict(self.mature_rules.get((by1.upper(), ""), {}))
        inferred.update(self.mature_rules.get((by1.upper(), form_code.upper()), {}))
        result = self.engine.design(
            query,
            by1=by1,
            form_code=form_code,
            inferred=inferred,
        )
        result["dictionary_version"] = self.dictionary_version
        if self.retriever is not None and result.get("product_role") == "valve":
            try:
                alternatives = self.retriever.retrieve(
                    query,
                    result,
                    by1=by1,
                    form_code=form_code,
                    top_k=3,
                )
                explicit_values = {
                    field: item.get("value")
                    for field, item in result.get("attributes", {}).items()
                    if item.get("value")
                }
                for candidate in alternatives:
                    values = dict(candidate.pop("_attributes", {}) or {})
                    values.update(explicit_values)
                    candidate["standardized_description"] = self.engine.render_from_values(
                        result["valve_family"], values
                    )
                result["alternatives"] = alternatives
            except Exception as exc:
                logger.warning("Template retrieval failed: %s", exc)
                result["warnings"].append("template_retrieval_unavailable")
        return result
