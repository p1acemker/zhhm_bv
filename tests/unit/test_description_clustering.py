import numpy as np
from pathlib import Path
import pytest
import subprocess
import sys
from types import SimpleNamespace

pytest.importorskip("sklearn", reason="description clustering requires scikit-learn")

from tools.cluster_by1_descriptions import (
    DescriptionPoint,
    build_export_payload,
    cluster_all,
    cluster_by1,
    load_points,
)


def point(
    point_id: str,
    vector: list[float],
    description: str,
    by1: str = "D71X4",
) -> DescriptionPoint:
    return DescriptionPoint(
        point_id=point_id,
        by1=by1,
        vector=np.asarray(vector, dtype=float),
        description=description,
        example=description,
        semantic_description=description,
        form_code="90F",
        spec="D100",
        support=1,
    )


def test_single_description_is_marked_insufficient() -> None:
    result = cluster_by1([point("1", [1.0, 0.0], "single")])

    assert result.status == "insufficient_sample"
    assert result.cluster_count == 1
    assert result.assignments[0].cluster_id == 1
    assert result.assignments[0].representative == "single"


def test_two_similar_descriptions_stay_in_one_cluster() -> None:
    result = cluster_by1(
        [
            point("1", [1.0, 0.0], "first"),
            point("2", [0.99, 0.01], "second"),
        ]
    )

    assert result.cluster_count == 1
    assert {item.cluster_id for item in result.assignments} == {1}


def test_two_dissimilar_descriptions_form_two_clusters() -> None:
    result = cluster_by1(
        [
            point("1", [1.0, 0.0], "horizontal"),
            point("2", [0.0, 1.0], "vertical"),
        ]
    )

    assert result.cluster_count == 2
    assert {item.cluster_id for item in result.assignments} == {1, 2}


def test_separated_description_groups_form_two_clusters() -> None:
    result = cluster_by1(
        [
            point("1", [1.0, 0.0], "horizontal one"),
            point("2", [0.99, 0.01], "horizontal two"),
            point("3", [0.0, 1.0], "vertical one"),
            point("4", [0.01, 0.99], "vertical two"),
        ]
    )

    labels = {item.point.point_id: item.cluster_id for item in result.assignments}
    assert result.cluster_count == 2
    assert labels["1"] == labels["2"]
    assert labels["3"] == labels["4"]
    assert labels["1"] != labels["3"]


def test_representatives_are_members_and_cluster_ids_are_contiguous() -> None:
    result = cluster_by1(
        [
            point("1", [1.0, 0.0], "a"),
            point("2", [0.98, 0.02], "b"),
            point("3", [0.0, 1.0], "c"),
            point("4", [0.02, 0.98], "d"),
        ]
    )

    descriptions = {item.point.description for item in result.assignments}
    assert {item.cluster_id for item in result.assignments} == set(
        range(1, result.cluster_count + 1)
    )
    assert all(item.representative in descriptions for item in result.assignments)


def test_isolated_description_is_flagged_as_outlier() -> None:
    result = cluster_by1(
        [
            point("1", [1.0, 0.0], "common one"),
            point("2", [0.99, 0.01], "common two"),
            point("3", [0.98, 0.02], "common three"),
            point("4", [-1.0, 0.0], "isolated"),
        ]
    )

    isolated = next(
        item for item in result.assignments if item.point.description == "isolated"
    )
    assert isolated.is_outlier is True
    assert isolated.nearest_neighbor_similarity < 0.60


def test_load_points_reads_all_qdrant_pages() -> None:
    class FakeClient:
        def __init__(self):
            self.offsets = []

        def scroll(self, **kwargs):
            self.offsets.append(kwargs.get("offset"))
            if kwargs.get("offset") is None:
                return [
                    SimpleNamespace(
                        id="1",
                        vector=[1.0, 0.0],
                        payload={
                            "by1": "A",
                            "description": "first",
                            "example": "first example",
                            "semantic_description": "first semantic",
                            "form_code": "F1",
                            "spec": "D10",
                            "support": 2,
                        },
                    )
                ], "next"
            return [
                SimpleNamespace(
                    id="2",
                    vector=[0.0, 1.0],
                    payload={
                        "by1": "B",
                        "description": "second",
                        "example": "second example",
                        "semantic_description": "second semantic",
                        "form_code": "F2",
                        "spec": "D20",
                        "support": 3,
                    },
                )
            ], None

    client = FakeClient()
    points = load_points(client, "children", batch_size=1)

    assert client.offsets == [None, "next"]
    assert [item.point_id for item in points] == ["1", "2"]
    assert points[1].support == 3


def test_export_payload_reconciles_rows_and_representatives() -> None:
    results = cluster_all(
        [
            point("1", [1.0, 0.0], "a one", by1="A"),
            point("2", [0.99, 0.01], "a two", by1="A"),
            point("3", [0.0, 1.0], "b one", by1="B"),
        ]
    )
    payload = build_export_payload(results, source_collection="children")

    assert payload["metadata"]["by1_count"] == 2
    assert payload["metadata"]["description_count"] == 3
    assert len(payload["variety_summary"]) == 2
    assert len(payload["detail"]) == 3
    detail_descriptions = {row["description"] for row in payload["detail"]}
    assert all(
        row["representative"] in detail_descriptions for row in payload["detail"]
    )
    for by1 in {row["by1"] for row in payload["detail"]}:
        ids = {
            row["cluster_id"] for row in payload["detail"] if row["by1"] == by1
        }
        assert ids == set(range(1, len(ids) + 1))


def test_clustering_script_runs_directly_from_repository_root() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "tools/cluster_by1_descriptions.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
