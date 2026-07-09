import pytest

from strategy.import_strategy import Candidate, prefix_similarity, rank_prefix_matches, select_best


def test_candidate_to_dict_rounds_score() -> None:
    candidate = Candidate(
        by1="D371X4",
        score=0.87654,
        prefix_match_len=4,
        edesc_count=12,
    )

    assert candidate.to_dict() == {
        "by1": "D371X4",
        "score": 0.8765,
        "prefix_match_len": 4,
        "edesc_count": 12,
    }


def test_select_best_prefers_highest_edesc_count() -> None:
    selected = select_best(
        [
            Candidate(by1="A", score=0.9, prefix_match_len=2, edesc_count=1),
            Candidate(by1="B", score=0.5, prefix_match_len=1, edesc_count=5),
        ]
    )

    assert selected.by1 == "B"


def test_select_best_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError):
        select_best([])


def test_prefix_similarity_scores_common_prefix() -> None:
    assert prefix_similarity("D371X4", "D371X7") == pytest.approx(5 / 6)
    assert prefix_similarity("D371X4", "Q41F") == 0.0


def test_rank_prefix_matches_excludes_identical_and_sorts() -> None:
    results = rank_prefix_matches("D371X4", ["D371X4", "D371X7", "D37A", "Q41F"], top_k=2)

    assert [item["by1"] for item in results] == ["D371X7", "D37A"]
    assert results[0]["prefix_match_len"] == 5
