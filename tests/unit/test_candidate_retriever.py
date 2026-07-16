from types import SimpleNamespace

from service.candidate_retriever import CandidateRetriever


class FakeEmbedder:
    def encode(self, text):
        assert "DN100" not in text
        return [0.1, 0.2]


class FakeClient:
    def query_points(self, **kwargs):
        assert kwargs["limit"] == 100
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=0.90,
                    payload={
                        "by1": "D71X4",
                        "form_code": "901",
                        "support": 5,
                        "example": "candidate one",
                    },
                ),
                SimpleNamespace(
                    score=0.89,
                    payload={
                        "by1": "D71XLV99",
                        "form_code": "90F",
                        "support": 4,
                        "example": "candidate two",
                    },
                ),
                SimpleNamespace(
                    score=0.85,
                    payload={
                        "by1": "D71XLV99",
                        "form_code": "90F",
                        "support": 3,
                        "example": "candidate three",
                    },
                ),
            ]
        )


def test_candidate_retriever_aggregates_by1_and_boosts_form_match() -> None:
    retriever = CandidateRetriever(
        client=FakeClient(),
        embedder=FakeEmbedder(),
        child_collection="recommendation_child_v1",
        child_limit=100,
    )

    candidates = retriever.retrieve(
        'DI LUG WAFER BV, EPDM SEAT, 4"/DN100',
        form_code="90F",
        top_k=5,
    )

    assert candidates[0]["by1"] == "D71XLV99"
    assert candidates[0]["form_match"] is True
    assert candidates[0]["support"] == 7
    assert len(candidates) == 2
