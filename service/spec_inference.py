"""Infer product specifications from historical order descriptions."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Optional

from .spec_rules import MatureSpecRules, SpecificationRuleResult


SEP_RE = re.compile(r"\s*\[SEP\]\s*", re.IGNORECASE)
SPEC_NUMBER_RE = re.compile(r"[A-Z]+(\d+(?:\.\d+)?)")
DN_RE = re.compile(r"\bDN\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
MM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*MM\b", re.IGNORECASE)
STAGE_RELIABILITY = {
    "description_customer_form": 0.984,
    "description_form": 0.868,
    "description_customer": 0.940,
    "description": 0.952,
}


def normalize_text(value: str) -> str:
    """Normalize descriptions and customer names for deterministic matching."""
    text = value.upper().replace("BUNA-N", "NBR")
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_code(value: str) -> str:
    """Normalize compact form and specification codes."""
    return re.sub(r"\s+", "", value.upper())


def customer_fingerprint(value: str) -> str:
    """Return the historical index key for a customer name."""
    normalized = normalize_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def parse_request_context(query: str, customer: str = "", form: str = "") -> tuple[str, str, str]:
    """Extract query context from either separate fields or a ``[SEP]`` string."""
    raw_query = query.strip()
    parsed_customer = ""
    parsed_form = ""
    if "[SEP]" in raw_query.upper():
        parts = SEP_RE.split(raw_query, maxsplit=2)
        parsed_customer = parts[0].strip() if parts else ""
        raw_query = parts[1].strip() if len(parts) > 1 else ""
        parsed_form = parts[2].strip() if len(parts) > 2 else ""

    resolved_customer = customer.strip() or parsed_customer
    resolved_form = form.strip() or parsed_form
    if not raw_query:
        raise ValueError("query must contain a product description")
    return raw_query, resolved_customer, resolved_form


def extract_size_candidates(description: str) -> set[str]:
    """Return DN or millimetre values that can constrain specification candidates."""
    values = set(DN_RE.findall(description))
    values.update(MM_RE.findall(description))
    return {_normalize_number(value) for value in values}


def specification_number(specification: str) -> Optional[str]:
    """Return the numeric component of a compact specification code."""
    match = SPEC_NUMBER_RE.fullmatch(specification)
    if not match:
        return None
    return _normalize_number(match.group(1))


def _normalize_number(value: str) -> str:
    """Remove decimal padding without changing integer place values."""
    return value.rstrip("0").rstrip(".") if "." in value else value


@dataclass(frozen=True)
class HistoricalRecord:
    """One aggregated description/form/specification combination."""

    description: str
    example: str
    form: str
    spec: str
    count: int
    customers: frozenset[str]
    tokens: frozenset[str]


class SpecInferenceService:
    """Use an aggregated historical index to infer specifications."""

    def __init__(
        self,
        index_path: str | Path,
        rules_path: str | Path | None = None,
    ) -> None:
        self.index_path = Path(index_path)
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ValueError("Unsupported specification index version")

        self.source: Mapping[str, Any] = payload.get("source", {})
        self._rules = MatureSpecRules.from_path(rules_path) if rules_path else None
        self._records: list[HistoricalRecord] = []
        self._records_by_description: dict[str, list[HistoricalRecord]] = defaultdict(list)
        self._description_specs: dict[str, Counter[str]] = defaultdict(Counter)
        self._description_form_specs: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        self._description_customer_specs: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        self._description_customer_form_specs: dict[
            tuple[str, str, str], Counter[str]
        ] = defaultdict(Counter)

        for item in payload.get("records", []):
            customer_counts = {
                str(customer): int(count)
                for customer, count in item.get("customers", [])
                if str(customer)
            }
            description = normalize_text(str(item["description"]))
            form = normalize_code(str(item["form"]))
            spec = normalize_code(str(item["spec"]))
            count = int(item.get("count", 1))
            record = HistoricalRecord(
                description=description,
                example=str(item.get("example", item["description"])),
                form=form,
                spec=spec,
                count=count,
                customers=frozenset(customer_counts),
                tokens=frozenset(description.split()),
            )
            self._records.append(record)
            self._records_by_description[description].append(record)
            self._description_specs[description][spec] += count
            self._description_form_specs[(description, form)][spec] += count
            for customer, customer_count in customer_counts.items():
                self._description_customer_specs[(description, customer)][spec] += customer_count
                self._description_customer_form_specs[
                    (description, customer, form)
                ][spec] += customer_count

        self._token_descriptions: dict[str, set[str]] = defaultdict(set)
        for description in self._records_by_description:
            for token in description.split():
                self._token_descriptions[token].add(description)
        description_count = max(len(self._records_by_description), 1)
        self._token_idf = {
            token: math.log((description_count + 1) / (len(descriptions) + 1)) + 1.0
            for token, descriptions in self._token_descriptions.items()
        }
        self._unknown_token_idf = math.log(description_count + 1) + 1.0

    def infer(
        self,
        query: str,
        customer: str = "",
        form: str = "",
        top_k: int = 50,
    ) -> dict[str, Any]:
        """Infer a specification and return ranked alternatives with evidence."""
        raw_query, raw_customer, raw_form = parse_request_context(query, customer, form)
        description = normalize_text(raw_query)
        normalized_customer = customer_fingerprint(raw_customer)
        normalized_form = normalize_code(raw_form)
        if not description:
            raise ValueError("query must contain searchable characters")

        sizes = extract_size_candidates(raw_query)
        exact = self._find_strong_exact(
            description,
            normalized_customer,
            normalized_form,
        )
        if exact is not None:
            counts, match_level = exact
            return self._exact_result(
                raw_query,
                raw_customer,
                raw_form,
                counts,
                match_level,
                sizes,
                top_k,
            )

        if self._rules is not None and normalized_form:
            rule_result = self._rules.infer(raw_query, normalized_form)
            if rule_result is not None:
                return self._rule_result(
                    raw_query,
                    raw_customer,
                    raw_form,
                    rule_result,
                    sizes,
                )

        exact = self._find_fallback_exact(
            description,
            normalized_customer,
            normalized_form,
        )
        if exact is not None:
            counts, match_level = exact
            return self._exact_result(
                raw_query,
                raw_customer,
                raw_form,
                counts,
                match_level,
                sizes,
                top_k,
            )

        return self._fuzzy_result(
            raw_query,
            raw_customer,
            raw_form,
            description,
            normalized_customer,
            normalized_form,
            sizes,
            top_k,
        )

    def _find_strong_exact(
        self,
        description: str,
        customer: str,
        form: str,
    ) -> Optional[tuple[Counter[str], str]]:
        if customer and form:
            counts = self._description_customer_form_specs.get(
                (description, customer, form)
            )
            if counts:
                return counts, "description_customer_form"
        return None

    def _find_fallback_exact(
        self,
        description: str,
        customer: str,
        form: str,
    ) -> Optional[tuple[Counter[str], str]]:
        if form:
            counts = self._description_form_specs.get((description, form))
            if counts:
                return counts, "description_form"
        if customer:
            counts = self._description_customer_specs.get((description, customer))
            if counts:
                return counts, "description_customer"
        counts = self._description_specs.get(description)
        return (counts, "description") if counts else None

    def _rule_result(
        self,
        query: str,
        customer: str,
        form: str,
        rule: SpecificationRuleResult,
        description_sizes: set[str],
    ) -> dict[str, Any]:
        support = rule.train_support + rule.validation_support
        holdout_metrics = self._rules.holdout_metrics if self._rules else {}
        return {
            "query": query,
            "customer": customer,
            "form": form,
            "inferred_spec": rule.specification,
            "confidence": "high",
            "confidence_score": round(rule.confidence_score, 4),
            "match_level": "mature_rule",
            "evidence": {
                "rule_path": ["stable_form_prefix", rule.size_rule],
                "form_prefix": rule.prefix,
                "inferred_size": rule.size,
                "description_size_candidates": sorted(description_sizes),
                "train_support": rule.train_support,
                "validation_support": rule.validation_support,
                "historical_support": support,
                "holdout_combined_accuracy": holdout_metrics.get("combined_accuracy"),
                "source_rows": self.source.get("rows"),
            },
            "alternatives": [
                {
                    "spec": rule.specification,
                    "score": round(rule.confidence_score, 4),
                    "support": support,
                    "size_match": True,
                }
            ],
        }

    def _exact_result(
        self,
        query: str,
        customer: str,
        form: str,
        counts: Counter[str],
        match_level: str,
        sizes: set[str],
        top_k: int,
    ) -> dict[str, Any]:
        total = sum(counts.values())
        ranked = counts.most_common(max(1, top_k))
        alternatives = [
            {
                "spec": spec,
                "score": round(count / total, 4),
                "support": count,
                "size_match": specification_number(spec) in sizes if sizes else None,
            }
            for spec, count in ranked
        ]
        top_share = alternatives[0]["score"]
        calibrated_score = round(top_share * STAGE_RELIABILITY[match_level], 4)
        confidence = self._confidence_label(calibrated_score, alternatives[0]["support"])
        inferred_spec = alternatives[0]["spec"] if confidence != "low" else None
        return {
            "query": query,
            "customer": customer,
            "form": form,
            "inferred_spec": inferred_spec,
            "confidence": confidence,
            "confidence_score": calibrated_score,
            "match_level": match_level,
            "evidence": {
                "historical_support": total,
                "candidate_count": len(counts),
                "size_candidates": sorted(sizes),
                "source_rows": self.source.get("rows"),
            },
            "alternatives": alternatives,
        }

    def _fuzzy_result(
        self,
        query: str,
        customer: str,
        form: str,
        description: str,
        normalized_customer: str,
        normalized_form: str,
        sizes: set[str],
        top_k: int,
    ) -> dict[str, Any]:
        query_tokens = frozenset(description.split())
        candidate_descriptions: set[str] = set()
        for token in query_tokens:
            candidate_descriptions.update(self._token_descriptions.get(token, set()))

        description_scores = [
            (self._weighted_jaccard(query_tokens, frozenset(candidate.split())), candidate)
            for candidate in candidate_descriptions
        ]
        description_scores = [item for item in description_scores if item[0] >= 0.20]
        description_scores.sort(reverse=True)

        best_by_spec: dict[str, dict[str, Any]] = {}
        for similarity, candidate_description in description_scores[:100]:
            for record in self._records_by_description[candidate_description]:
                spec_number = specification_number(record.spec)
                size_match = spec_number in sizes if sizes and spec_number else None
                size_factor = 1.30 if size_match else (0.45 if sizes and spec_number else 1.0)
                form_match = bool(normalized_form and record.form == normalized_form)
                customer_match = bool(
                    normalized_customer and normalized_customer in record.customers
                )
                context_factor = 1.0
                if form_match:
                    context_factor += 0.12
                if customer_match:
                    context_factor += 0.08
                support_factor = 1.0 + min(math.log1p(record.count) * 0.03, 0.12)
                rank_score = similarity * size_factor * context_factor * support_factor
                candidate = {
                    "spec": record.spec,
                    "rank_score": rank_score,
                    "description_similarity": similarity,
                    "support": record.count,
                    "size_match": size_match,
                    "customer_match": customer_match,
                    "form_match": form_match,
                    "matched_description": record.example,
                }
                previous = best_by_spec.get(record.spec)
                if previous is None or rank_score > previous["rank_score"]:
                    best_by_spec[record.spec] = candidate

        ranked = sorted(
            best_by_spec.values(),
            key=lambda item: item["rank_score"],
            reverse=True,
        )
        if not ranked:
            return self._empty_result(query, customer, form, sizes)

        top_rank_score = ranked[0]["rank_score"]
        alternatives = []
        for item in ranked[: max(1, top_k)]:
            alternatives.append(
                {
                    "spec": item["spec"],
                    "score": round(item["rank_score"] / top_rank_score, 4),
                    "support": item["support"],
                    "description_similarity": round(item["description_similarity"], 4),
                    "size_match": item["size_match"],
                    "customer_match": item["customer_match"],
                    "form_match": item["form_match"],
                }
            )

        best = ranked[0]
        second_score = ranked[1]["rank_score"] if len(ranked) > 1 else 0.0
        margin = (top_rank_score - second_score) / top_rank_score if top_rank_score else 0.0
        confidence_score = best["description_similarity"]
        if best["size_match"]:
            confidence_score += 0.10
        elif sizes and best["size_match"] is False:
            confidence_score -= 0.20
        if best["form_match"]:
            confidence_score += 0.05
        if best["customer_match"]:
            confidence_score += 0.05
        if margin < 0.05:
            confidence_score -= 0.15
        confidence_score = round(min(max(confidence_score, 0.0), 1.0), 4)
        confidence = self._confidence_label(confidence_score, best["support"])
        inferred_spec = best["spec"] if confidence != "low" else None
        return {
            "query": query,
            "customer": customer,
            "form": form,
            "inferred_spec": inferred_spec,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "match_level": "fuzzy_description",
            "evidence": {
                "matched_description": best["matched_description"],
                "description_similarity": round(best["description_similarity"], 4),
                "historical_support": best["support"],
                "size_candidates": sorted(sizes),
                "size_match": best["size_match"],
                "customer_match": best["customer_match"],
                "form_match": best["form_match"],
                "top_margin": round(margin, 4),
                "source_rows": self.source.get("rows"),
            },
            "alternatives": alternatives,
        }

    def _weighted_jaccard(
        self,
        left: frozenset[str],
        right: frozenset[str],
    ) -> float:
        intersection = left & right
        union = left | right
        if not union:
            return 0.0
        shared_weight = sum(self._token_weight(token) for token in intersection)
        union_weight = sum(self._token_weight(token) for token in union)
        return shared_weight / union_weight if union_weight else 0.0

    def _token_weight(self, token: str) -> float:
        return self._token_idf.get(token, self._unknown_token_idf)

    @staticmethod
    def _confidence_label(score: float, support: int) -> str:
        if score >= 0.85 and support >= 2:
            return "high"
        if score >= 0.60:
            return "medium"
        return "low"

    def _empty_result(
        self,
        query: str,
        customer: str,
        form: str,
        sizes: Iterable[str],
    ) -> dict[str, Any]:
        return {
            "query": query,
            "customer": customer,
            "form": form,
            "inferred_spec": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "match_level": "none",
            "evidence": {
                "size_candidates": sorted(sizes),
                "source_rows": self.source.get("rows"),
            },
            "alternatives": [],
        }
