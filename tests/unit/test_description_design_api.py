from fastapi.testclient import TestClient

import api


class FakeRecommendationService:
    def recommend(self, query, form_code="", customer="", top_k=5):
        return {
            "by1_candidates": [{"by1": "D71X", "score": 1.0, "support": 2}],
            "by1_match_level": "description_form_code",
            "inferred_spec": "D100",
            "spec_confidence": "high",
            "spec_confidence_score": 1.0,
            "spec_match_level": "description_form_code",
            "spec_alternatives": [],
            "evidence": {},
        }


class FakeDesignService:
    def __init__(self):
        self.calls = 0

    def design(self, query, by1_candidates=None, form_code=""):
        self.calls += 1
        return {
            "status": "complete",
            "valve_family": "butterfly",
            "product_role": "valve",
            "standardized_description": "DUCTILE IRON WAFER BUTTERFLY VALVE",
            "template_id": "BUT-1",
            "confidence": "high",
            "confidence_score": 0.99,
            "attributes": {},
            "inferred_fields": [],
            "warnings": [],
            "alternatives": [],
        }


def _configure(monkeypatch, mode):
    design = FakeDesignService()
    monkeypatch.setattr(api, "get_recommendation_service", lambda: FakeRecommendationService())
    monkeypatch.setattr(api, "get_description_design_service", lambda: design)
    monkeypatch.setattr(api, "get_description_design_mode", lambda: mode)
    return design


def test_search_on_mode_adds_description_design(monkeypatch) -> None:
    design = _configure(monkeypatch, "on")

    response = TestClient(api.app).post(
        "/edesc/search",
        json={"query": 'DI WAFER BV 4"/DN100', "form_code": "90F"},
    )

    assert response.status_code == 200
    assert response.json()["description_design"]["template_id"] == "BUT-1"
    assert design.calls == 1


def test_search_shadow_mode_computes_without_changing_response(monkeypatch) -> None:
    design = _configure(monkeypatch, "shadow")

    response = TestClient(api.app).post("/edesc/search", json={"query": "DI WAFER BV"})

    assert response.status_code == 200
    assert "description_design" not in response.json()
    assert design.calls == 1


def test_search_off_mode_does_not_initialize_design_service(monkeypatch) -> None:
    design = _configure(monkeypatch, "off")

    response = TestClient(api.app).post("/edesc/search", json={"query": "DI WAFER BV"})

    assert response.status_code == 200
    assert "description_design" not in response.json()
    assert design.calls == 0


def test_search_passes_vector_fallback_products_to_description_design(monkeypatch) -> None:
    class EmptyRecommendationService(FakeRecommendationService):
        def recommend(self, query, form_code="", customer="", top_k=5):
            result = super().recommend(query, form_code, customer, top_k)
            result["by1_candidates"] = []
            result["by1_match_level"] = "none"
            return result

    class VectorService:
        def search_by_edesc_raw(self, query, top_k=5, customer=None):
            return [{"productName": "D71X", "score": 0.8}]

    class CapturingDesignService(FakeDesignService):
        def design(self, query, by1_candidates=None, form_code=""):
            assert by1_candidates[0]["productName"] == "D71X"
            return super().design(query, by1_candidates, form_code)

    design = CapturingDesignService()
    monkeypatch.setattr(api, "get_recommendation_service", lambda: EmptyRecommendationService())
    monkeypatch.setattr(api, "get_service", lambda: VectorService())
    monkeypatch.setattr(api, "get_description_design_service", lambda: design)
    monkeypatch.setattr(api, "get_description_design_mode", lambda: "on")

    response = TestClient(api.app).post("/edesc/search", json={"query": "DI WAFER BV"})

    assert response.status_code == 200
    assert design.calls == 1
