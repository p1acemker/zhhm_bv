from types import SimpleNamespace

from tools.evaluate_template_retrieval import (
    _evaluate_cases,
    calculate_metrics,
    render_console_result,
)


def test_calculate_metrics_separates_seen_and_unseen_templates() -> None:
    results = [
        {"target_template_id": "A", "candidate_ids": ["A", "B"], "seen_in_index": True},
        {"target_template_id": "B", "candidate_ids": ["C", "B", "A"], "seen_in_index": True},
        {"target_template_id": "D", "candidate_ids": ["A", "B", "C"], "seen_in_index": False},
    ]

    metrics = calculate_metrics(results)

    assert metrics["cases"] == 3
    assert metrics["recall_at_20"] == 2 / 3
    assert metrics["accuracy_at_3"] == 2 / 3
    assert metrics["seen_template"]["cases"] == 2
    assert metrics["seen_template"]["recall_at_20"] == 1.0
    assert metrics["unseen_template"]["cases"] == 1
    assert metrics["unseen_template"]["recall_at_20"] == 0.0


def test_calculate_metrics_uses_case_weight_for_row_level_results() -> None:
    metrics = calculate_metrics(
        [
            {
                "target_template_id": "A",
                "candidate_ids": ["A"],
                "seen_in_index": True,
                "case_weight": 9,
            },
            {
                "target_template_id": "B",
                "candidate_ids": ["A"],
                "seen_in_index": True,
                "case_weight": 1,
            },
        ]
    )

    assert metrics["cases"] == 10
    assert metrics["recall_at_20"] == 0.9
    assert metrics["accuracy_at_3"] == 0.9


def test_evaluation_uses_query_and_form_without_target_by1_as_input() -> None:
    class CapturingEngine:
        def __init__(self) -> None:
            self.by1 = None
            self.form_code = None

        def design(self, query, *, by1, form_code, inferred):
            self.by1 = by1
            self.form_code = form_code
            return {"product_role": "valve", "valve_family": "butterfly", "attributes": {}}

    class FakeEmbedder:
        def encode(self, texts, batch_size=None):
            return [[1.0] for _ in texts]

    class CapturingRetriever:
        def __init__(self) -> None:
            self.embedder = FakeEmbedder()
            self.by1 = None
            self.form_code = None

        def retrieve_with_vector(self, vector, query, design, *, by1, form_code, top_k):
            self.by1 = by1
            self.form_code = form_code
            return [{"template_id": "BUT-1", "by1": ["D71X"], "form_codes": ["90F"]}]

    engine = CapturingEngine()
    retriever = CapturingRetriever()
    service = SimpleNamespace(engine=engine, mature_rules={})
    results = _evaluate_cases(
        [
            {
                "query": "DI WAFER BUTTERFLY VALVE",
                "by1": "D71X",
                "form_code": "90F",
                "template_id": "BUT-1",
                "case_weight": 1,
            }
        ],
        retriever,
        service,
        {"BUT-1"},
    )

    assert engine.by1 == ""
    assert engine.form_code == "90F"
    assert retriever.by1 == ""
    assert retriever.form_code == "90F"
    assert results[0]["input"] == {"query": "DI WAFER BUTTERFLY VALVE", "form_code": "90F"}
    assert results[0]["candidates"][0]["by1"] == ["D71X"]


def test_console_result_is_encodable_by_windows_console() -> None:
    rendered = render_console_result({"query": "V\u00c1LVULA"})

    assert rendered.encode("gbk")
