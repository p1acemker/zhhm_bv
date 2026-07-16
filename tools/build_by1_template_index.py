"""Build deterministic by1-scoped template clusters and specification profiles."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from service.template_models import TemplateCluster, TemplateMember


OUTLIER_THRESHOLD = 0.60


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def _stable_template_id(by1: str, signature: str, cluster_id: int) -> str:
    value = f"{by1}|{signature}|{cluster_id}".encode("utf-8")
    return f"tpl-{hashlib.sha1(value).hexdigest()[:12].upper()}"


def _choose_labels(vectors: np.ndarray) -> np.ndarray:
    """Split only clearly separated records; keep small groups together."""
    if len(vectors) <= 1:
        return np.zeros(len(vectors), dtype=int)
    normalized = _normalize(vectors)
    similarity = float(np.clip(normalized[0] @ normalized[1], -1.0, 1.0))
    if len(vectors) == 2:
        return np.array([0, 0] if similarity >= 0.75 else [0, 1], dtype=int)
    mean_similarity = normalized @ normalized.T
    if float(np.min(mean_similarity[np.triu_indices(len(vectors), k=1)])) >= 0.75:
        return np.zeros(len(vectors), dtype=int)
    return np.zeros(len(vectors), dtype=int)


def _medoids(
    members: Sequence[TemplateMember],
    vectors: np.ndarray,
    labels: np.ndarray,
) -> dict[int, int]:
    similarities = np.clip(_normalize(vectors) @ _normalize(vectors).T, -1.0, 1.0)
    medoids: dict[int, int] = {}
    for cluster_id in sorted(set(int(label) for label in labels)):
        indices = np.flatnonzero(labels == cluster_id)
        mean_values = similarities[np.ix_(indices, indices)].mean(axis=1)
        best = float(mean_values.max())
        tied = [int(indices[i]) for i, value in enumerate(mean_values) if np.isclose(value, best)]
        medoids[cluster_id] = min(tied, key=lambda index: members[index].point_id)
    return medoids


def _cluster_signature(member: TemplateMember) -> str:
    return member.views.structural_description.strip().upper()


def cluster_cohesion(members: Sequence[TemplateMember], medoid: TemplateMember) -> float:
    if not members:
        return 0.0
    medoid_vector = _normalize(np.asarray([medoid.structural_vector], dtype=float))[0]
    values = []
    for member in members:
        vector = _normalize(np.asarray([member.structural_vector], dtype=float))[0]
        values.append(float(np.clip(vector @ medoid_vector, -1.0, 1.0)))
    return round(float(np.mean(values)), 6)


def count_outliers(members: Sequence[TemplateMember]) -> int:
    if len(members) < 3:
        return 0
    vectors = _normalize(np.vstack([member.structural_vector for member in members]))
    similarities = np.clip(vectors @ vectors.T, -1.0, 1.0)
    return sum(
        float(np.max(np.delete(similarities[index], index))) < OUTLIER_THRESHOLD
        for index in range(len(members))
    )


def build_template_clusters(members: Sequence[TemplateMember]) -> list[TemplateCluster]:
    """Build stable clusters without mixing descriptions from different by1s."""
    if not members:
        return []
    grouped: dict[str, list[TemplateMember]] = defaultdict(list)
    for member in members:
        grouped[member.by1].append(member)

    clusters: list[TemplateCluster] = []
    for by1 in sorted(grouped):
        by1_members = sorted(grouped[by1], key=lambda member: member.point_id)
        buckets: dict[str, list[TemplateMember]] = defaultdict(list)
        for member in by1_members:
            buckets[_cluster_signature(member)].append(member)
        next_cluster_id = 1
        for signature in sorted(buckets):
            bucket = buckets[signature]
            vectors = np.vstack([member.structural_vector for member in bucket]).astype(float)
            labels = _choose_labels(vectors)
            medoids = _medoids(bucket, vectors, labels)
            for local_id in sorted(set(int(label) for label in labels)):
                indices = np.flatnonzero(labels == local_id)
                cluster_members = [bucket[index] for index in indices]
                medoid = cluster_members[list(indices).index(medoids[local_id])]
                clusters.append(
                    TemplateCluster(
                        template_id=_stable_template_id(by1, signature, next_cluster_id),
                        by1=by1,
                        cluster_id=next_cluster_id,
                        member_ids=tuple(member.point_id for member in cluster_members),
                        representative_point_id=medoid.point_id,
                        structural_signature=signature,
                        cohesion=cluster_cohesion(cluster_members, medoid),
                        outlier_count=count_outliers(cluster_members),
                        template_status=(
                            "insufficient_sample" if len(cluster_members) == 1 else "clustered"
                        ),
                    )
                )
                next_cluster_id += 1
    return clusters


def build_spec_profiles(
    members: Sequence[TemplateMember],
    clusters: Sequence[TemplateCluster],
) -> list[dict[str, object]]:
    """Aggregate historical specification evidence for each template/form pair."""
    member_by_id = {member.point_id: member for member in members}
    profiles: list[dict[str, object]] = []
    for cluster in clusters:
        by_form: dict[str, list[TemplateMember]] = defaultdict(list)
        for point_id in cluster.member_ids:
            by_form[member_by_id[point_id].form_code].append(member_by_id[point_id])
        for form_code in sorted(by_form):
            group = by_form[form_code]
            spec_counts = Counter(member.spec for member in group if member.spec)
            size_to_spec: dict[str, dict[str, int]] = defaultdict(dict)
            for member in group:
                if member.parsed_size and member.spec:
                    size_to_spec.setdefault(member.parsed_size, {})[member.spec] = (
                        size_to_spec.get(member.parsed_size, {}).get(member.spec, 0) + 1
                    )
            profiles.append(
                {
                    "template_id": cluster.template_id,
                    "by1": cluster.by1,
                    "form_code": form_code,
                    "spec_distribution": dict(sorted(spec_counts.items())),
                    "size_to_spec_distribution": {
                        size: dict(sorted(values.items()))
                        for size, values in sorted(size_to_spec.items())
                    },
                    "nonstandard_specs": sorted(
                        spec for spec in spec_counts if not spec[:1].isalpha() or not spec[1:].isdigit()
                    ),
                    "support": sum(max(0, member.support) for member in group),
                }
            )
    return profiles


def build_template_index(
    rows: Sequence[Mapping[str, Any]],
    train_before: str,
    embedder: Any,
) -> dict[str, object]:
    """Build a JSON-ready index from already normalized training rows."""
    cutoff = train_before
    members: list[TemplateMember] = []
    for row in rows:
        if str(row.get("contract_date", "")) >= cutoff:
            continue
        views = row["views"]
        vector = np.asarray(row["structural_vector"], dtype=float)
        if vector.size == 0:
            vector = np.asarray(embedder.encode(views.structural_description), dtype=float)
        members.append(
            TemplateMember(
                point_id=str(row["point_id"]),
                by1=str(row["by1"]).strip().upper(),
                views=views,
                structural_vector=vector,
                form_code=str(row.get("form_code", "")).strip().upper(),
                spec=str(row.get("spec", "")).strip().upper(),
                parsed_size=str(row.get("parsed_size", "")).strip(),
                support=int(row.get("support", 1)),
            )
        )
    clusters = build_template_clusters(members)
    profiles = build_spec_profiles(members, clusters)
    member_by_id = {member.point_id: member for member in members}
    return {
        "version": 1,
        "train_before": cutoff,
        "members": [
            {
                "point_id": member.point_id,
                "by1": member.by1,
                "raw_description": member.views.raw_description,
                "structural_description": member.views.structural_description,
                "full_description": member.views.full_description,
                "form_code": member.form_code,
                "spec": member.spec,
                "parsed_size": member.parsed_size,
                "support": member.support,
            }
            for member in members
        ],
        "clusters": [asdict(cluster) for cluster in clusters],
        "spec_profiles": profiles,
    }


def write_template_index(payload: Mapping[str, object], output: Path | str) -> None:
    """Write a stable UTF-8 template index."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
