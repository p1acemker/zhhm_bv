import json
from pathlib import Path

from service.description_design import BusinessDictionary
from service.description_design.service import DescriptionDesignService


def test_business_dictionary_loads_compiled_excel_payload(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "source_sha256": "abc",
                "sheets": {
                    "词语映射": [
                        {
                            "raw_term": "CUSTOM WAFER",
                            "canonical_term": "WAFER",
                            "field": "connection",
                            "family_scope": "butterfly",
                            "priority": 50,
                            "active": True,
                        }
                    ],
                    "品种形式规则": [],
                },
            }
        ),
        encoding="utf-8",
    )

    dictionary = BusinessDictionary.from_compiled_json(path)
    matches = dictionary.match_terms("CUSTOM WAFER BV", family="butterfly")

    assert matches["connection"].value == "WAFER"


def test_design_service_uses_mature_rules_and_attaches_retrieval_alternatives(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dictionary.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "source_sha256": "abc",
                "sheets": {
                    "词语映射": [],
                    "品种形式规则": [
                        {
                            "by1": "D71X",
                            "form_code": "90F",
                            "field": "body_material",
                            "value": "DUCTILE IRON",
                            "confidence": 0.99,
                            "active": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeRetriever:
        def retrieve(self, query, query_design, by1="", form_code="", top_k=3):
            assert by1 == "D71X"
            assert form_code == "90F"
            return [
                {
                    "template_id": "BUT-1",
                    "standardized_description": 'old candidate 6"/DN150',
                    "score": 0.95,
                    "_attributes": {"connection": "WAFER"},
                }
            ]

    service = DescriptionDesignService.from_dictionary_path(
        path,
        retriever=FakeRetriever(),
    )
    result = service.design(
        'WAFER BUTTERFLY VALVE 4"/DN100',
        by1_candidates=[{"by1": "D71X"}],
        form_code="90F",
    )

    assert result["attributes"]["body_material"]["source"] == "mature_rule"
    assert result["inferred_fields"] == ["body_material"]
    assert result["alternatives"][0]["template_id"] == "BUT-1"
    assert result["alternatives"][0]["standardized_description"].endswith(
        '4"/DN100'
    )
