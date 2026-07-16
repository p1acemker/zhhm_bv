from api import (
    AddEDescRequest,
    BatchImportRequest,
    SearchRequest,
    SpecInferenceRequest,
    ValveParseRequest,
    app,
)

from fastapi.testclient import TestClient

import api


def test_supported_routes_are_registered() -> None:
    def has_route(path: str, method: str) -> bool:
        return any(
            route.path == path and method in route.methods
            for route in app.routes
            if getattr(route, "methods", None)
        )

    assert has_route("/edesc/search", "POST")
    assert has_route("/edesc/add", "POST")
    assert has_route("/edesc/batch-import", "POST")
    assert has_route("/spec/infer", "POST")
    assert has_route("/valve/parse", "POST")
    assert not has_route("/recommend", "POST")


def test_search_request_defaults() -> None:
    request = SearchRequest(query="abc")

    assert request.query == "abc"
    assert request.top_k == 5
    assert request.customer == ""
    assert request.form == ""
    assert request.form_code == ""


def test_spec_inference_request_defaults() -> None:
    request = SpecInferenceRequest(query="description", form="D371X4")

    assert request.form == "D371X4"
    assert request.top_k == 50


def test_add_edesc_request_accepts_optional_metadata() -> None:
    request = AddEDescRequest(by1="D371X4", edesc="desc")

    assert request.by1 == "D371X4"
    assert request.edesc == "desc"
    assert request.metadata is None


def test_batch_import_default_strategy() -> None:
    request = BatchImportRequest(by1_list=["D371X4"])

    assert request.by1_list == ["D371X4"]
    assert request.strategy == "most_references"


def test_valve_parse_request_keeps_model_field() -> None:
    request = ValveParseRequest(model="D371X4")

    assert request.model == "D371X4"


class FakeEDescService:
    def search_by_edesc_raw(self, query, top_k=10, customer=None):
        return [{"productName": "D371X4", "score": 0.95}]

    def add_edesc(self, by1, edesc, metadata=None):
        return {"success": True, "message": "ok", "action": "created", "parent_id": "p1"}

    def batch_import(self, by1_list, strategy="most_references"):
        return {"total": len(by1_list), "success_count": len(by1_list), "fail_count": 0, "details": []}


class FakeValveService:
    def parse_with_normalized(self, model):
        return {
            "type": "butterfly valve",
            "driveMode": "manual",
            "connectMode": "lug",
            "form": "centerline",
            "material": "rubber",
            "standardizedProduct": "D371X",
        }


class FakeSpecInferenceService:
    def infer(self, query, top_k=50, customer="", form=""):
        return {
            "query": query,
            "customer": customer,
            "form": form,
            "inferred_spec": "D100",
            "confidence": "high",
            "confidence_score": 0.98,
            "match_level": "description_customer_form",
            "evidence": {},
            "alternatives": [],
        }


class FakeRecommendationService:
    def recommend(self, query, form_code="", customer="", top_k=5):
        return {
            "query": query,
            "form_code": form_code,
            "by1_candidates": [{"by1": "D71XLV99"}],
            "by1_match_level": "description_form_code",
            "inferred_spec": "D100",
            "spec_confidence": "high",
            "spec_confidence_score": 1.0,
            "spec_match_level": "description_form_code",
            "spec_alternatives": [{"spec": "D100"}],
            "evidence": {},
        }


def test_api_routes_delegate_to_services(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_service", lambda: FakeEDescService())
    monkeypatch.setattr(
        api,
        "get_spec_inference_service",
        lambda: FakeSpecInferenceService(),
    )
    monkeypatch.setattr(
        api,
        "get_recommendation_service",
        lambda: FakeRecommendationService(),
    )
    monkeypatch.setattr(api, "get_variety_type_service", lambda: FakeValveService())
    client = TestClient(api.app)

    search_response = client.post(
        "/edesc/search",
        json={"query": "desc", "form_code": "90F"},
    )
    assert search_response.status_code == 200
    assert search_response.json()["data"][0]["productName"] == "D71XLV99"
    assert search_response.json()["inferred_spec"] == "D100"
    assert client.post("/edesc/add", json={"by1": "D371X4", "edesc": "desc"}).status_code == 200
    assert client.post("/edesc/batch-import", json={"by1_list": ["D371X4"]}).status_code == 200
    spec_response = client.post(
        "/spec/infer",
        json={
            "query": "ACME[SEP]desc[SEP]D371X4",
            "customer": "ACME",
            "form": "D371X4",
        },
    )
    assert spec_response.status_code == 200
    assert spec_response.json()["inferred_spec"] == "D100"
    assert client.post("/valve/parse", json={"model": "D371X4"}).status_code == 200


def test_api_marks_reranked_candidates_as_full_vector_index(monkeypatch) -> None:
    class RerankedRecommendationService(FakeRecommendationService):
        def recommend(self, query, form_code="", customer="", top_k=5):
            result = super().recommend(query, form_code, customer, top_k)
            result["by1_match_level"] = "vector_reranked"
            return result

    monkeypatch.setattr(
        api,
        "get_recommendation_service",
        lambda: RerankedRecommendationService(),
    )
    client = TestClient(api.app)

    response = client.post("/edesc/search", json={"query": "unseen"})

    assert response.status_code == 200
    assert response.json()["recommendation_source"] == "full_vector_index"
