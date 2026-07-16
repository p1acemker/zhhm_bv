"""Optional HTTP reranking for low-evidence recommendation candidates."""

from __future__ import annotations

from math import isfinite, log1p
import json
import logging
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


def parse_rerank_response(
    payload: Any,
    document_count: int,
) -> dict[int, float]:
    """Extract ``document index -> score`` from common reranker responses."""
    if isinstance(payload, Mapping):
        entries = payload.get("results", payload.get("data", payload.get("scores", [])))
    else:
        entries = payload
    if not isinstance(entries, list):
        return {}

    scores: dict[int, float] = {}
    for position, item in enumerate(entries):
        if isinstance(item, Mapping):
            index = item.get("index", item.get("document_index", position))
            value = item.get("relevance_score", item.get("score"))
        else:
            index = position
            value = item
        try:
            index = int(index)
            score = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < document_count and isfinite(score):
            scores[index] = score
    return scores


class RerankerClient:
    """Small dependency-free client for a configured reranker HTTP endpoint."""

    def __init__(self, url: str, timeout: float = 3.0, model: str = "") -> None:
        self.url = url.strip()
        self.timeout = max(0.1, float(timeout))
        self.model = model.strip()

    @classmethod
    def from_config(cls) -> "RerankerClient | None":
        """Build a client only when an endpoint is explicitly configured."""
        from config import RERANKER_MODEL, RERANKER_TIMEOUT, RERANKER_URL

        url = RERANKER_URL.strip()
        if not url:
            return None
        return cls(
            url=url,
            timeout=RERANKER_TIMEOUT,
            model=RERANKER_MODEL,
        )

    def rerank(self, query: str, documents: list[str]) -> dict[int, float]:
        """Return scores keyed by the original document index."""
        body: dict[str, Any] = {"query": query, "documents": documents}
        if self.model:
            body["model"] = self.model
        request = Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"reranker request failed: {exc}") from exc
        scores = parse_rerank_response(payload, len(documents))
        if len(scores) != len(documents):
            raise RuntimeError("reranker response did not score every document")
        return scores


class CandidateReranker:
    """Apply reranker scores while retaining vector and historical evidence."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def rerank(
        self,
        query: str,
        form_code: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return reranked candidates or the original list on degradation."""
        if not candidates:
            return candidates
        documents = [self._document(candidate) for candidate in candidates]
        try:
            scores = self.client.rerank(
                " ".join(part for part in (query.strip(), form_code.strip()) if part),
                documents,
            )
            if len(scores) != len(candidates):
                raise RuntimeError("incomplete reranker scores")
        except Exception as exc:
            logger.warning("Recommendation reranking failed: %s", exc)
            return candidates

        reranker_values = [scores[index] for index in range(len(candidates))]
        low = min(reranker_values)
        high = max(reranker_values)
        span = high - low
        ranked: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            item = dict(candidate)
            reranker_score = reranker_values[index]
            normalized_reranker = (
                (reranker_score - low) / span if span else 0.5
            )
            vector_score = float(item.get("vector_score", item.get("score", 0.0)))
            form_match = 1.0 if item.get("form_match") else 0.0
            support = log1p(max(0, int(item.get("support", 0))))
            item["reranker_score"] = round(reranker_score, 4)
            item["reranker_used"] = True
            item["score"] = round(
                0.70 * normalized_reranker
                + 0.20 * vector_score
                + 0.05 * form_match
                + 0.05 * min(support / 6.0, 1.0),
                4,
            )
            ranked.append(item)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    @staticmethod
    def _document(candidate: Mapping[str, Any]) -> str:
        descriptions = [
            str(value).strip()
            for value in candidate.get("matched_descriptions", [])
            if str(value).strip()
        ]
        evidence = " | ".join(descriptions[:3])
        by1 = str(candidate.get("by1") or candidate.get("productName") or "")
        return f"{by1}: {evidence}".strip()
