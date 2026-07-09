from typing import Any, Dict, List, Optional

import service.edesc_service as edesc_module
from service.edesc_service import EDescService


class FakeStore:
    def get_stats(self) -> Dict[str, Any]:
        return {
            "parent_collection": {"name": "parents", "points_count": 1},
            "child_collection": {"name": "children", "points_count": 2},
        }


class FakeEmbedder:
    def __init__(self) -> None:
        self.inputs: List[Any] = []

    def encode(self, texts: Any, batch_size: int = 32) -> Any:
        self.inputs.append(texts)
        if isinstance(texts, list):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        return [1.0, 0.0, 0.0, 0.0]


class FakeRepo:
    def __init__(self) -> None:
        self.products: Dict[str, Dict[str, Any]] = {
            "D371X4": {
                "by1": "D371X4",
                "parent_id": "parent-D371X4",
                "edesc_list": ["STANDARD DESC"],
                "edesc_count": 1,
                "metadata": {"by1": "D371X4", "edesc_count": 1},
            },
            "D371X7": {
                "by1": "D371X7",
                "parent_id": "parent-D371X7",
                "edesc_list": ["SOURCE DESC", "SECOND DESC"],
                "edesc_count": 2,
                "metadata": {"by1": "D371X7", "edesc_count": 2},
            },
        }
        self.deleted: List[str] = []

    def search(
        self, query_vector: List[float], top_k: int = 10, score_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        return [
            {
                "productName": "D371X4",
                "edesc_list": ["STANDARD DESC"],
                "edesc_count": 1,
                "parent_id": "parent-D371X4",
                "score": 0.95,
                "matched_edescs": ["STANDARD DESC"],
                "metadata": {},
            }
        ][:top_k]

    def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        return self.products.get(by1)

    def get_all_by1s(self) -> List[str]:
        return list(self.products)

    def delete_by_parent_id(self, parent_id: str) -> None:
        self.deleted.append(parent_id)

    def add_product_with_edesc_list(
        self, product_name: str, edesc_list: List[str], embedding_func: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        embedding_func(edesc_list)
        parent_id = f"parent-{product_name}"
        self.products[product_name] = {
            "by1": product_name,
            "parent_id": parent_id,
            "edesc_list": edesc_list,
            "edesc_count": len(edesc_list),
            "metadata": metadata or {},
        }
        return parent_id


def make_service() -> EDescService:
    return EDescService(store=FakeStore(), embedder=FakeEmbedder(), repo=FakeRepo())


def test_search_by_edesc_raw_standardizes_and_adds_customer_specs(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "STANDARD DESC")
    service = make_service()
    service._spec_rules = {"D371X4": {"ACME": ["DN100"]}}

    results = service.search_by_edesc_raw("raw desc", top_k=10, customer="ACME")

    assert results[0]["productName"] == "D371X4"
    assert results[0]["matched_specs"] == ["DN100"]


def test_add_edesc_detects_duplicate(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "STANDARD DESC")

    result = make_service().add_edesc("D371X4", "raw desc")

    assert result["success"] is False
    assert result["is_duplicate"] is True
    assert result["existing_edesc_count"] == 1


def test_add_edesc_appends_new_standardized_description(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "NEW DESC")
    service = make_service()

    result = service.add_edesc("D371X4", "new desc", metadata={"source": "unit"})

    assert result["success"] is True
    assert result["action"] == "appended"
    assert result["new_edesc_count"] == 2


def test_batch_import_isolates_per_item_results(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: text)

    result = make_service().batch_import(["D371X9", "D371X4"])

    assert result["total"] == 2
    assert result["success_count"] == 1
    assert result["fail_count"] == 1
    assert result["details"][0]["success"] is True
    assert result["details"][1]["success"] is False
