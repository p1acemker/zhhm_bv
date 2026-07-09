from api import (
    AddEDescRequest,
    BatchImportRequest,
    SearchRequest,
    ValveParseRequest,
    app,
)


def test_supported_routes_are_registered() -> None:
    routes = {
        (next(iter(route.methods)), route.path)
        for route in app.routes
        if getattr(route, "methods", None)
    }

    assert ("POST", "/edesc/search") in routes
    assert ("POST", "/edesc/add") in routes
    assert ("POST", "/edesc/batch-import") in routes
    assert ("POST", "/valve/parse") in routes


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
