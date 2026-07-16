"""Historical by1 recommendation and form-code specification inference."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional

from scripts.edesc_standardizer import standardize_description_views

from .spec_rules import infer_size


SEP_RE = re.compile(r"\s*\[SEP\]\s*", re.IGNORECASE)


def normalize_text(value: object) -> str:
    """Normalize descriptions and customer names for index lookup."""
    if value is None:
        return ""
    text = str(value).upper().replace("BUNA-N", "NBR")
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_code(value: object) -> str:
    """Normalize compact by1, form, and specification codes."""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).upper())


def customer_fingerprint(value: str) -> str:
    """Return the non-plaintext customer key used by the index."""
    normalized = normalize_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def parse_recommendation_context(
    query: str,
    customer: str = "",
    form_code: str = "",
) -> tuple[str, str, str]:
    """Read explicit fields or ``customer[SEP]description[SEP]form_code``."""
    raw_query = str(query).strip()
    parsed_customer = ""
    parsed_form = ""
    if "[SEP]" in raw_query.upper():
        parts = SEP_RE.split(raw_query, maxsplit=2)
        parsed_customer = parts[0].strip() if parts else ""
        raw_query = parts[1].strip() if len(parts) > 1 else ""
        parsed_form = parts[2].strip() if len(parts) > 2 else ""
    resolved_customer = str(customer).strip() or parsed_customer
    resolved_form = str(form_code).strip() or parsed_form
    if not raw_query:
        raise ValueError("query must contain a product description")
    return raw_query, resolved_customer, resolved_form


class RecommendationService:
    """Serve deterministic historical recommendations from a generated index."""

    def __init__(
        self,
        index_path: str | Path,
        retriever: Any = None,
        reranker: Any = None,
        template_retriever: Any = None,
    ) -> None:
        self.index_path = Path(index_path)
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ValueError("Unsupported recommendation index version")
        self.source: Mapping[str, Any] = payload.get("source", {})
        self.criteria: Mapping[str, Any] = payload.get("criteria", {})
        self.form_prefix_rules: Mapping[str, Mapping[str, Any]] = payload.get(
            "form_prefix_rules", {}
        )
        self.retriever = retriever
        self.reranker = reranker
        self.template_retriever = template_retriever
        self._by1_maps: dict[str, defaultdict[tuple[str, ...], Counter[str]]] = {}
        self._spec_maps: dict[str, defaultdict[tuple[str, ...], Counter[str]]] = {}
        for item in payload.get("records", []):
            record = {
                "description": normalize_text(item.get("description", "")),
                "example": str(item.get("example", "")),
                "form_code": normalize_code(item.get("form_code", "")),
                "by1": normalize_code(item.get("by1", "")),
                "spec": normalize_code(item.get("spec", "")),
                "count": int(item.get("count", 1)),
                "customers": {
                    str(customer): int(count)
                    for customer, count in item.get("customers", [])
                    if customer
                },
            }
            if not record["description"] or not record["by1"]:
                continue
            self._add_maps(record)

    def _add_maps(self, record: Mapping[str, Any]) -> None:
        """Populate exact lookup maps with row-count support weights."""
        description = record["description"]
        form_code = record["form_code"]
        by1 = record["by1"]
        spec = record["spec"]
        count = int(record["count"])
        by1_maps = self._by1_maps.setdefault("by1", defaultdict(Counter))
        spec_maps = self._spec_maps.setdefault("spec", defaultdict(Counter))
        keys = [
            ((description, form_code), count),
            ((description,), count),
        ]
        for key, weight in keys:
            by1_maps[key][by1] += weight
            spec_maps[key][spec] += weight
        for customer, customer_count in record["customers"].items():
            by1_maps[(description, form_code, customer)][by1] += customer_count
            by1_maps[(description, customer)][by1] += customer_count
            spec_maps[(description, form_code, customer)][spec] += customer_count
            spec_maps[(description, customer)][spec] += customer_count

    def recommend(
        self,
        query: str,
        form_code: str = "",
        customer: str = "",
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Recommend by1 candidates and infer a specification."""
        raw_query, raw_customer, raw_form = parse_recommendation_context(
            query, customer, form_code
        )
        description = normalize_text(raw_query)
        normalized_form = normalize_code(raw_form)
        customer_key = customer_fingerprint(raw_customer)
        limit = max(1, min(int(top_k), 20))
        views = standardize_description_views(raw_query)

        by1_counts, by1_level = self._select_by1_counts(
            description, normalized_form, customer_key
        )
        by1_candidates = self._rank_candidates(by1_counts, limit)
        template_candidates: list[dict[str, Any]] = []
        if not by1_candidates and self.template_retriever is not None:
            template_candidates = self.template_retriever.retrieve(
                views,
                form_code=normalized_form,
                top_k=50,
            )
            by1_candidates = self._aggregate_template_candidates(
                template_candidates, limit
            )
            if by1_candidates:
                by1_level = "template_retrieval"
        if not by1_candidates and self.retriever is not None:
            by1_candidates = self.retriever.retrieve(
                raw_query,
                form_code=normalized_form,
                top_k=limit,
            )
            if by1_candidates:
                by1_level = "vector_full_index"
                if self.reranker is not None:
                    reranked = self.reranker.rerank(
                        raw_query,
                        normalized_form,
                        by1_candidates,
                    )
                    by1_candidates = reranked
                    if any(item.get("reranker_used") for item in reranked):
                        by1_level = "vector_reranked"

        spec_result = self._infer_specification(
            raw_query,
            description,
            normalized_form,
            customer_key,
            template_candidates,
        )
        return {
            "query": raw_query,
            "customer": raw_customer,
            "form_code": raw_form,
            "by1_candidates": by1_candidates,
            "by1_match_level": by1_level,
            "template_candidates": template_candidates,
            "template_match_level": (
                "template_retrieval" if template_candidates else "none"
            ),
            "inferred_spec": spec_result["inferred_spec"],
            "spec_confidence": spec_result["confidence"],
            "spec_confidence_score": spec_result["confidence_score"],
            "spec_match_level": spec_result["match_level"],
            "spec_alternatives": spec_result["alternatives"],
            "evidence": {
                "description": description,
                "form_code": normalized_form,
                "by1_support": sum(by1_counts.values())
                or sum(int(item.get("support", 0)) for item in by1_candidates),
                "by1_candidate_count": len(by1_candidates),
                "template_evidence": [
                    {
                        "template_id": item.get("template_id"),
                        "by1": item.get("by1"),
                        "score": item.get("score"),
                        "form_match": item.get("form_match"),
                    }
                    for item in template_candidates[:10]
                ],
                "spec_evidence": spec_result["evidence"],
                "source_rows": self.source.get("indexed_rows"),
                "index_date_max": self.source.get("date_max"),
            },
        }

    def _select_by1_counts(
        self,
        description: str,
        form_code: str,
        customer: str,
    ) -> tuple[Counter[str], str]:
        maps = self._by1_maps["by1"]
        if customer and form_code:
            counts = maps.get((description, form_code, customer))
            if counts:
                return counts, "description_form_customer"
        if form_code:
            counts = maps.get((description, form_code))
            if counts:
                return counts, "description_form_code"
        if customer:
            counts = maps.get((description, customer))
            if counts:
                return counts, "description_customer"
        counts = maps.get((description,))
        if counts:
            return counts, "description"
        return Counter(), "none"

    def _infer_specification(
        self,
        raw_query: str,
        description: str,
        form_code: str,
        customer: str,
        template_candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        maps = self._spec_maps["spec"]
        exact: Optional[tuple[Counter[str], str]] = None
        if customer and form_code and maps.get((description, form_code, customer)):
            exact = maps[(description, form_code, customer)], "description_form_customer"
        elif form_code and maps.get((description, form_code)):
            exact = maps[(description, form_code)], "description_form_code"

        if exact is not None:
            return self._spec_result_from_counts(exact[0], exact[1], raw_query)

        rule = self._rule_specification(raw_query, form_code)
        if rule is not None:
            return rule

        if customer and maps.get((description, customer)):
            return self._spec_result_from_counts(
                maps[(description, customer)], "description_customer", raw_query
            )
        if maps.get((description,)):
            return self._spec_result_from_counts(
                maps[(description,)], "description", raw_query
            )
        template_result = self._infer_spec_from_templates(
            raw_query,
            form_code,
            template_candidates or [],
        )
        if template_result is not None:
            return template_result
        return {
            "inferred_spec": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "match_level": "none",
            "alternatives": [],
            "evidence": {"size_rule": None},
        }

    def _infer_spec_from_templates(
        self,
        raw_query: str,
        form_code: str,
        template_candidates: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Use supported template profiles only after stronger evidence misses."""
        size = infer_size(raw_query)
        size_key = str(size.size) if size is not None else ""
        counts: Counter[str] = Counter()
        template_ids: list[str] = []
        for candidate in template_candidates:
            if float(candidate.get("score", 0.0)) < 0.60:
                continue
            for profile in candidate.get("spec_profile", []) or []:
                profile_form = normalize_code(profile.get("form_code", ""))
                if profile_form and profile_form != form_code:
                    continue
                distribution = profile.get("size_to_spec_distribution", {})
                selected = distribution.get(size_key, {}) if size_key else {}
                if not selected:
                    selected = profile.get("spec_distribution", {})
                for spec, support in selected.items():
                    counts[normalize_code(spec)] += int(support)
                if selected:
                    template_ids.append(str(candidate.get("template_id", "")))
        if sum(counts.values()) < 2:
            return None
        result = self._spec_result_from_counts(
            counts,
            "template_form_size" if size_key else "template_profile",
            raw_query,
        )
        result["evidence"]["template_ids"] = sorted(set(template_ids))
        result["evidence"]["size_rule"] = size.rule if size is not None else None
        return result

    def _rule_specification(
        self,
        raw_query: str,
        form_code: str,
    ) -> Optional[dict[str, Any]]:
        rule = self.form_prefix_rules.get(form_code)
        if not rule:
            return None
        size = infer_size(raw_query)
        if size is None:
            return None
        specification = f"{rule['prefix']}{size.size}"
        return {
            "inferred_spec": specification,
            "confidence": "high",
            "confidence_score": 0.995,
            "match_level": "mature_form_rule",
            "alternatives": [
                {"spec": specification, "score": 0.995, "support": int(rule["train_support"]) + int(rule["validation_support"])}
            ],
            "evidence": {
                "size_rule": size.rule,
                "form_prefix": rule["prefix"],
                "train_support": rule["train_support"],
                "validation_support": rule["validation_support"],
            },
        }

    def _spec_result_from_counts(
        self,
        counts: Counter[str],
        match_level: str,
        query: str,
    ) -> dict[str, Any]:
        total = sum(counts.values())
        ranked = counts.most_common(10)
        alternatives = [
            {
                "spec": spec,
                "score": round(count / total, 4),
                "support": count,
            }
            for spec, count in ranked
        ]
        top_score = alternatives[0]["score"] if alternatives else 0.0
        confidence = self._confidence_label(top_score, alternatives[0]["support"] if alternatives else 0)
        return {
            "inferred_spec": alternatives[0]["spec"] if confidence != "low" else None,
            "confidence": confidence,
            "confidence_score": round(top_score, 4),
            "match_level": match_level,
            "alternatives": alternatives,
            "evidence": {
                "historical_support": total,
                "query": query,
                "candidate_count": len(counts),
            },
        }

    @staticmethod
    def _rank_candidates(counts: Counter[str], top_k: int) -> list[dict[str, Any]]:
        total = sum(counts.values())
        return [
            {
                "by1": by1,
                "score": round(count / total, 4) if total else 0.0,
                "support": count,
            }
            for by1, count in counts.most_common(top_k)
        ]

    @staticmethod
    def _aggregate_template_candidates(
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Collapse multiple template hits into distinct by1 candidates."""
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            by1 = normalize_code(candidate.get("by1", ""))
            if by1:
                grouped[by1].append(candidate)
        ranked: list[dict[str, Any]] = []
        for by1, items in grouped.items():
            items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
            best = items[0]
            support = sum(max(0, int(item.get("support", 0))) for item in items)
            score = float(best.get("score", 0.0))
            if any(item.get("form_match") for item in items):
                score += 0.03
            ranked.append(
                {
                    "by1": by1,
                    "productName": by1,
                    "score": round(score, 4),
                    "support": support,
                    "form_match": any(item.get("form_match") for item in items),
                    "template_ids": [item.get("template_id") for item in items],
                    "matched_descriptions": [
                        item.get("representative_description", "")
                        for item in items[:3]
                        if item.get("representative_description")
                    ],
                }
            )
        ranked.sort(key=lambda item: (float(item["score"]), int(item["support"])), reverse=True)
        return ranked[: max(1, min(int(top_k), 20))]

    @staticmethod
    def _confidence_label(score: float, support: int) -> str:
        if score >= 0.85 and support >= 2:
            return "high"
        if score >= 0.60:
            return "medium"
        return "low"
