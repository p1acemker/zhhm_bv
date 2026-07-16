from types import SimpleNamespace

from service.description_design import DescriptionDesignEngine
from service.description_design.retriever import TemplateRetriever


class FakeEmbedder:
    def encode(self, text, batch_size=None):
        if isinstance(text, list):
            return [[1.0, 0.0, 0.0, 0.0] for _ in text]
        return [1.0, 0.0, 0.0, 0.0]


class FakeClient:
    def __init__(self, points):
        self.points = points
        self.last_filter = None

    def query_points(self, **kwargs):
        self.last_filter = kwargs.get("query_filter")
        return SimpleNamespace(points=self.points)


def _hit(score, template_id, attributes, by1=None, form_codes=None, support=1):
    return SimpleNamespace(
        score=score,
        payload={
            "template_id": template_id,
            "valve_family": "butterfly",
            "product_role": "valve",
            "attributes": attributes,
            "standardized_description": f"template {template_id}",
            "supported_by1": by1 or [],
            "form_codes": form_codes or [],
            "support": support,
        },
    )


def test_template_retriever_rejects_explicit_field_conflicts() -> None:
    query_design = DescriptionDesignEngine().design(
        'DI WAFER BV, EPDM SEAT, 4"/DN100'
    )
    client = FakeClient(
        [
            _hit(0.99, "wrong", {"connection": "FLANGED", "seat_material": "EPDM"}),
            _hit(0.90, "right", {"connection": "WAFER", "seat_material": "EPDM"}),
        ]
    )
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates")

    results = retriever.retrieve(
        "query",
        query_design,
        by1="D71X",
        form_code="90F",
    )

    assert [item["template_id"] for item in results] == ["right"]
    assert client.last_filter is not None


def test_template_retriever_prefers_structured_context_and_support() -> None:
    query_design = DescriptionDesignEngine().design(
        'DI WAFER BV, EPDM SEAT, 4"/DN100'
    )
    client = FakeClient(
        [
            _hit(0.91, "vector", {"connection": "WAFER"}, support=2),
            _hit(
                0.89,
                "context",
                {"connection": "WAFER", "seat_material": "EPDM"},
                by1=["D71X"],
                form_codes=["90F"],
                support=20,
            ),
        ]
    )
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates")

    results = retriever.retrieve(
        "query",
        query_design,
        by1="D71X",
        form_code="90F",
    )

    assert results[0]["template_id"] == "context"
    assert results[0]["by1_form_match"] is True
    assert results[0]["field_match_ratio"] > results[1]["field_match_ratio"]
    assert results[0]["by1"] == ["D71X"]
    assert results[0]["form_codes"] == ["90F"]


def test_template_retriever_falls_back_when_reranker_fails() -> None:
    class FailingReranker:
        def rerank(self, query, form_code, candidates):
            raise RuntimeError("offline")

    design = DescriptionDesignEngine().design('DI WAFER BV, 4"/DN100')
    client = FakeClient([_hit(0.9, "one", {"connection": "WAFER"})])
    retriever = TemplateRetriever(
        client,
        FakeEmbedder(),
        "templates",
        reranker=FailingReranker(),
    )

    results = retriever.retrieve("query", design)

    assert results[0]["template_id"] == "one"
    assert results[0]["reranker_used"] is False


def test_template_retriever_honors_evaluation_top_k_up_to_candidate_limit() -> None:
    design = DescriptionDesignEngine().design('DI WAFER BV, 4"/DN100')
    client = FakeClient(
        [
            _hit(0.99 - index * 0.01, f"template-{index}", {"connection": "WAFER"})
            for index in range(20)
        ]
    )
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates", candidate_limit=100)

    results = retriever.retrieve("query", design, top_k=20)

    assert len(results) == 20
    assert results[-1]["template_id"] == "template-19"


def test_template_retriever_uses_precomputed_vector_for_batch_evaluation() -> None:
    design = DescriptionDesignEngine().design('DI WAFER BV, 4"/DN100')
    client = FakeClient([_hit(0.9, "one", {"connection": "WAFER"})])
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates")

    results = retriever.retrieve_with_vector([0.0, 1.0, 0.0, 0.0], "query", design)

    assert results[0]["template_id"] == "one"


def test_template_retriever_does_not_treat_size_as_template_conflict() -> None:
    design = DescriptionDesignEngine().design('DI WAFER BV, EPDM SEAT, 4"/DN100')
    client = FakeClient(
        [
            _hit(
                0.9,
                "same-template-different-size",
                {"connection": "WAFER", "seat_material": "EPDM", "size": "2\"/DN50"},
            )
        ]
    )
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates")

    results = retriever.retrieve("query", design)

    assert [item["template_id"] for item in results] == ["same-template-different-size"]


def test_template_retriever_uses_form_when_by1_is_not_an_input() -> None:
    design = DescriptionDesignEngine().design('DI WAFER BV, EPDM SEAT, 4"/DN100')
    client = FakeClient(
        [
            _hit(0.99, "vector-only", {"connection": "WAFER", "seat_material": "EPDM"}),
            _hit(
                0.90,
                "form-match",
                {"connection": "WAFER", "seat_material": "EPDM"},
                form_codes=["90F"],
            ),
        ]
    )
    retriever = TemplateRetriever(client, FakeEmbedder(), "templates")

    results = retriever.retrieve("query", design, form_code="90F")

    assert results[0]["template_id"] == "form-match"
    assert results[0]["form_match"] is True
