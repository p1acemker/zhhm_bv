import json
from pathlib import Path

from service.recommendation import (
    RecommendationService,
    customer_fingerprint,
    parse_recommendation_context,
)


def _write_index(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {"indexed_rows": 10, "date_max": "2024-12-20"},
                "criteria": {},
                "form_prefix_rules": {
                    "90F": {
                        "prefix": "D",
                        "train_support": 62,
                        "validation_support": 14,
                    }
                },
                "records": [
                    {
                        "description": "DI LUG WAFER BV EPDM SEAT DN100",
                        "example": "DI LUG WAFER BV,EPDM SEAT,4\"/DN100",
                        "form_code": "90F",
                        "by1": "D71XLV99",
                        "spec": "D100",
                        "count": 6,
                        "customers": [[customer_fingerprint("ACME"), 6]],
                    },
                    {
                        "description": "DI LUG WAFER BV EPDM SEAT DN100",
                        "example": "DI LUG WAFER BV,EPDM SEAT,4\"/DN100",
                        "form_code": "90F",
                        "by1": "D71X4",
                        "spec": "D100",
                        "count": 2,
                        "customers": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_parse_recommendation_context_supports_sep() -> None:
    assert parse_recommendation_context(
        "ACME[SEP]DI LUG WAFER BV[SEP]90F"
    ) == ("DI LUG WAFER BV", "ACME", "90F")


def test_recommendation_returns_by1_top5_and_exact_spec(tmp_path: Path) -> None:
    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(index_path)

    result = service.recommend(
        "DI LUG WAFER BV EPDM SEAT DN100",
        form_code="90F",
        customer="ACME",
    )

    assert result["by1_candidates"][0]["by1"] == "D71XLV99"
    assert result["by1_match_level"] == "description_form_customer"
    assert result["inferred_spec"] == "D100"
    assert result["spec_match_level"] == "description_form_customer"


def test_recommendation_uses_mature_rule_for_unseen_description(tmp_path: Path) -> None:
    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(index_path)

    result = service.recommend(
        'UNSEEN DI WAFER BV, 4"/DN100',
        form_code="90F",
    )

    assert result["by1_candidates"] == []
    assert result["inferred_spec"] == "D100"
    assert result["spec_match_level"] == "mature_form_rule"


def test_recommendation_uses_vector_retriever_when_history_is_missing(
    tmp_path: Path,
) -> None:
    class FakeRetriever:
        def retrieve(self, query, form_code="", top_k=5):
            return [
                {
                    "by1": "D71X4",
                    "productName": "D71X4",
                    "score": 0.91,
                    "support": 3,
                }
            ]

    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(index_path, retriever=FakeRetriever())

    result = service.recommend("UNSEEN WAFER VALVE", form_code="901")

    assert result["by1_candidates"][0]["by1"] == "D71X4"
    assert result["by1_match_level"] == "vector_full_index"


def test_recommendation_reranks_vector_candidates_only(tmp_path: Path) -> None:
    class FakeRetriever:
        def retrieve(self, query, form_code="", top_k=5):
            return [
                {
                    "by1": "D71X4",
                    "score": 0.95,
                    "support": 3,
                    "matched_descriptions": ["candidate one"],
                },
                {
                    "by1": "D71XLV99",
                    "score": 0.90,
                    "support": 4,
                    "matched_descriptions": ["candidate two"],
                },
            ]

    class FakeReranker:
        def rerank(self, query, form_code, candidates):
            assert form_code == "90F"
            candidates[0]["reranker_score"] = 0.20
            candidates[0]["reranker_used"] = True
            candidates[1]["reranker_score"] = 0.95
            candidates[1]["reranker_used"] = True
            candidates.reverse()
            return candidates

    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(
        index_path,
        retriever=FakeRetriever(),
        reranker=FakeReranker(),
    )

    result = service.recommend("UNSEEN WAFER VALVE", form_code="90F")

    assert result["by1_candidates"][0]["by1"] == "D71XLV99"
    assert result["by1_match_level"] == "vector_reranked"


class FakeTemplateRetriever:
    def __init__(self, candidates):
        self.candidates = candidates

    def retrieve(self, views, form_code, top_k=50):
        return list(self.candidates)


def test_template_candidates_are_aggregated_to_distinct_by1_values(tmp_path: Path) -> None:
    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(
        index_path,
        template_retriever=FakeTemplateRetriever(
            [
                {
                    "template_id": "t1",
                    "by1": "D71X",
                    "score": 0.91,
                    "form_match": True,
                    "support": 5,
                    "spec_profile": [],
                },
                {
                    "template_id": "t2",
                    "by1": "D71X",
                    "score": 0.88,
                    "form_match": True,
                    "support": 3,
                    "spec_profile": [],
                },
                {
                    "template_id": "t3",
                    "by1": "D72X",
                    "score": 0.89,
                    "form_match": False,
                    "support": 2,
                    "spec_profile": [],
                },
            ]
        ),
    )

    result = service.recommend("UNSEEN WAFER VALVE", form_code="901", top_k=5)

    assert [item["by1"] for item in result["by1_candidates"]] == ["D71X", "D72X"]
    assert result["template_candidates"][0]["template_id"] == "t1"
    assert result["by1_match_level"] == "template_retrieval"


def test_weak_template_spec_evidence_abstains(tmp_path: Path) -> None:
    index_path = tmp_path / "recommendation.json"
    _write_index(index_path)
    service = RecommendationService(
        index_path,
        template_retriever=FakeTemplateRetriever(
            [
                {
                    "template_id": "weak",
                    "by1": "D71X",
                    "score": 0.41,
                    "form_match": True,
                    "support": 1,
                    "spec_profile": [
                        {
                            "form_code": "901",
                            "size_to_spec_distribution": {"100": {"D100": 1}},
                        }
                    ],
                }
            ]
        ),
    )

    result = service.recommend('UNSEEN WAFER VALVE 4"/DN100', form_code="901")

    assert result["inferred_spec"] is None
    assert result["spec_confidence"] == "low"
