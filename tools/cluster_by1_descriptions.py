"""Cluster historical product descriptions independently for each by1."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

import numpy as np
try:
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score
except ImportError as exc:  # pragma: no cover - depends on the analysis runtime
    raise RuntimeError(
        "description clustering requires scikit-learn; use the configured "
        "analysis Python runtime"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TWO_POINT_SIMILARITY = 0.75
MIN_ADJUSTED_SILHOUETTE = 0.18
OUTLIER_NEIGHBOR_SIMILARITY = 0.60
MAX_CLUSTERS = 8


@dataclass(frozen=True)
class DescriptionPoint:
    """One aggregated historical description and its semantic vector."""

    point_id: str
    by1: str
    vector: np.ndarray
    description: str
    example: str
    semantic_description: str
    form_code: str
    spec: str
    support: int


@dataclass(frozen=True)
class ClusterAssignment:
    """Cluster membership and explainability fields for one description."""

    point: DescriptionPoint
    cluster_id: int
    representative: str
    similarity_to_medoid: float
    nearest_neighbor_similarity: float
    is_outlier: bool


@dataclass(frozen=True)
class By1ClusteringResult:
    """Complete deterministic clustering result for one by1."""

    by1: str
    status: str
    cluster_count: int
    silhouette: float
    average_cohesion: float
    assignments: tuple[ClusterAssignment, ...]


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def _choose_labels(vectors: np.ndarray) -> tuple[np.ndarray, float]:
    count = len(vectors)
    if count == 1:
        return np.zeros(1, dtype=int), 0.0
    similarities = np.clip(vectors @ vectors.T, -1.0, 1.0)
    if count == 2:
        labels = np.array([0, 0] if similarities[0, 1] >= TWO_POINT_SIMILARITY else [0, 1])
        return labels, 0.0

    best_labels = np.zeros(count, dtype=int)
    best_silhouette = 0.0
    best_adjusted = float("-inf")
    for cluster_count in range(2, min(MAX_CLUSTERS, count - 1) + 1):
        labels = AgglomerativeClustering(
            n_clusters=cluster_count,
            metric="cosine",
            linkage="average",
        ).fit_predict(vectors)
        score = float(silhouette_score(vectors, labels, metric="cosine"))
        sizes = np.bincount(labels)
        singleton_ratio = float(np.count_nonzero(sizes == 1) / cluster_count)
        adjusted = score - 0.05 * (cluster_count - 2) - 0.12 * singleton_ratio
        if adjusted > best_adjusted:
            best_adjusted = adjusted
            best_silhouette = score
            best_labels = labels
    if best_adjusted < MIN_ADJUSTED_SILHOUETTE:
        return np.zeros(count, dtype=int), 0.0
    return best_labels, best_silhouette


def _contiguous_labels(labels: np.ndarray, points: Sequence[DescriptionPoint]) -> np.ndarray:
    ordered = sorted(
        set(int(label) for label in labels),
        key=lambda label: min(
            points[index].point_id
            for index, current in enumerate(labels)
            if int(current) == label
        ),
    )
    mapping = {label: index + 1 for index, label in enumerate(ordered)}
    return np.asarray([mapping[int(label)] for label in labels], dtype=int)


def cluster_by1(points: Sequence[DescriptionPoint]) -> By1ClusteringResult:
    """Cluster one by1's descriptions using deterministic cosine similarity."""
    if not points:
        raise ValueError("points must not be empty")
    by1_values = {point.by1 for point in points}
    if len(by1_values) != 1:
        raise ValueError("all points must belong to the same by1")

    ordered_points = tuple(sorted(points, key=lambda point: point.point_id))
    vectors = _normalize(np.vstack([point.vector for point in ordered_points]))
    similarities = np.clip(vectors @ vectors.T, -1.0, 1.0)
    raw_labels, silhouette = _choose_labels(vectors)
    labels = _contiguous_labels(raw_labels, ordered_points)

    representatives: dict[int, int] = {}
    for cluster_id in sorted(set(labels)):
        member_indices = np.flatnonzero(labels == cluster_id)
        member_similarities = similarities[np.ix_(member_indices, member_indices)]
        mean_similarities = member_similarities.mean(axis=1)
        best_value = float(mean_similarities.max())
        tied = [
            int(member_indices[index])
            for index, value in enumerate(mean_similarities)
            if np.isclose(float(value), best_value)
        ]
        representatives[cluster_id] = min(
            tied,
            key=lambda index: ordered_points[index].point_id,
        )

    assignments: list[ClusterAssignment] = []
    for index, point in enumerate(ordered_points):
        cluster_id = int(labels[index])
        medoid_index = representatives[cluster_id]
        if len(ordered_points) == 1:
            nearest_similarity = 1.0
        else:
            nearest_similarity = float(
                np.max(np.delete(similarities[index], index))
            )
        assignments.append(
            ClusterAssignment(
                point=point,
                cluster_id=cluster_id,
                representative=ordered_points[medoid_index].description,
                similarity_to_medoid=float(similarities[index, medoid_index]),
                nearest_neighbor_similarity=nearest_similarity,
                is_outlier=(
                    len(ordered_points) >= 3
                    and nearest_similarity < OUTLIER_NEIGHBOR_SIMILARITY
                ),
            )
        )

    status = "insufficient_sample" if len(ordered_points) == 1 else "clustered"
    return By1ClusteringResult(
        by1=next(iter(by1_values)),
        status=status,
        cluster_count=len(set(labels)),
        silhouette=round(float(silhouette), 6),
        average_cohesion=round(
            float(np.mean([item.similarity_to_medoid for item in assignments])),
            6,
        ),
        assignments=tuple(assignments),
    )


def load_points(client: object, collection_name: str, batch_size: int = 256) -> list[DescriptionPoint]:
    """Read every child payload and vector from a Qdrant collection."""
    points: list[DescriptionPoint] = []
    offset = None
    seen_offsets: set[str] = set()
    while True:
        page, next_offset = client.scroll(
            collection_name=collection_name,
            limit=max(1, int(batch_size)),
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for item in page:
            payload = item.payload or {}
            vector = item.vector
            if isinstance(vector, dict):
                vector = next(iter(vector.values()), None)
            if not payload.get("by1") or vector is None:
                continue
            points.append(
                DescriptionPoint(
                    point_id=str(item.id),
                    by1=str(payload.get("by1", "")).strip().upper(),
                    vector=np.asarray(vector, dtype=float),
                    description=str(payload.get("description", "")).strip(),
                    example=str(payload.get("example", "")).strip(),
                    semantic_description=str(
                        payload.get("semantic_description", "")
                    ).strip(),
                    form_code=str(payload.get("form_code", "")).strip(),
                    spec=str(payload.get("spec", "")).strip(),
                    support=max(0, int(payload.get("support", 0))),
                )
            )
        if next_offset is None:
            break
        offset_key = str(next_offset)
        if offset_key in seen_offsets:
            raise RuntimeError("Qdrant scroll returned a repeated offset")
        seen_offsets.add(offset_key)
        offset = next_offset
    return sorted(points, key=lambda item: (item.by1, item.point_id))


def cluster_all(points: Sequence[DescriptionPoint]) -> list[By1ClusteringResult]:
    """Cluster all points after separating them by by1."""
    grouped: dict[str, list[DescriptionPoint]] = defaultdict(list)
    for item in points:
        grouped[item.by1].append(item)
    return [cluster_by1(grouped[by1]) for by1 in sorted(grouped)]


def build_export_payload(
    results: Sequence[By1ClusteringResult],
    source_collection: str,
) -> dict[str, object]:
    """Build reconciled summary and detail records for JSON and Excel."""
    variety_summary: list[dict[str, object]] = []
    cluster_summary: list[dict[str, object]] = []
    detail: list[dict[str, object]] = []

    for result in results:
        assignments = list(result.assignments)
        variety_summary.append(
            {
                "by1": result.by1,
                "description_count": len(assignments),
                "support_total": sum(item.point.support for item in assignments),
                "cluster_count": result.cluster_count,
                "silhouette": result.silhouette,
                "average_cohesion": result.average_cohesion,
                "outlier_count": sum(item.is_outlier for item in assignments),
                "status": result.status,
            }
        )
        for cluster_id in range(1, result.cluster_count + 1):
            members = [
                item for item in assignments if item.cluster_id == cluster_id
            ]
            cluster_summary.append(
                {
                    "by1": result.by1,
                    "cluster_id": cluster_id,
                    "member_count": len(members),
                    "support_total": sum(item.point.support for item in members),
                    "representative": members[0].representative,
                    "form_codes": ", ".join(
                        sorted({item.point.form_code for item in members if item.point.form_code})
                    ),
                    "specifications": ", ".join(
                        sorted({item.point.spec for item in members if item.point.spec})
                    ),
                    "average_cohesion": round(
                        float(np.mean([item.similarity_to_medoid for item in members])),
                        6,
                    ),
                    "outlier_count": sum(item.is_outlier for item in members),
                }
            )
        for item in assignments:
            detail.append(
                {
                    "point_id": item.point.point_id,
                    "by1": result.by1,
                    "cluster_id": item.cluster_id,
                    "description": item.point.description,
                    "example": item.point.example,
                    "semantic_description": item.point.semantic_description,
                    "representative": item.representative,
                    "form_code": item.point.form_code,
                    "spec": item.point.spec,
                    "support": item.point.support,
                    "similarity_to_medoid": round(item.similarity_to_medoid, 6),
                    "nearest_neighbor_similarity": round(
                        item.nearest_neighbor_similarity, 6
                    ),
                    "is_outlier": item.is_outlier,
                }
            )

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_collection": source_collection,
        "by1_count": len(variety_summary),
        "description_count": len(detail),
        "cluster_count": len(cluster_summary),
        "insufficient_by1_count": sum(
            row["status"] == "insufficient_sample" for row in variety_summary
        ),
        "outlier_count": sum(bool(row["is_outlier"]) for row in detail),
    }
    return {
        "metadata": metadata,
        "variety_summary": variety_summary,
        "cluster_summary": cluster_summary,
        "detail": detail,
    }


def main() -> None:
    """Run clustering against the configured Qdrant child collection."""
    from qdrant_client import QdrantClient

    from config import QDRANT_URL, RECOMMENDATION_CHILD_COLLECTION

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=QDRANT_URL)
    parser.add_argument("--collection", default=RECOMMENDATION_CHILD_COLLECTION)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("results/by1_description_clusters.json"),
    )
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    client = QdrantClient(
        url=args.qdrant_url,
        timeout=60,
        check_compatibility=False,
    )
    points = load_points(client, args.collection, batch_size=args.batch_size)
    results = cluster_all(points)
    payload = build_export_payload(results, source_collection=args.collection)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
