from api import (
    AddEDescRequest,
    BatchImportRequest,
    SearchRequest,
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
    assert has_route("/valve/parse", "POST")


def test_search_request_defaults() -> None:
    request = SearchRequest(query="abc")

    assert request.query == "abc"
    assert request.top_k == 10
    assert request.customer is None


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


def test_api_routes_delegate_to_services(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_service", lambda: FakeEDescService())
    monkeypatch.setattr(api, "get_variety_type_service", lambda: FakeValveService())
    client = TestClient(api.app)

    assert client.post("/edesc/search", json={"query": "desc"}).status_code == 200
    assert client.post("/edesc/add", json={"by1": "D371X4", "edesc": "desc"}).status_code == 200
    assert client.post("/edesc/batch-import", json={"by1_list": ["D371X4"]}).status_code == 200
    assert client.post("/valve/parse", json={"model": "D371X4"}).status_code == 200
