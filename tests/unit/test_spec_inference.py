import json
from pathlib import Path

import pytest

from service.spec_inference import (
    SpecInferenceService,
    customer_fingerprint,
    parse_request_context,
)


@pytest.fixture
def inference_service(tmp_path: Path) -> SpecInferenceService:
    payload = {
        "version": 1,
        "source": {"rows": 10},
        "records": [
            {
                "description": "DI LUG WAFER BV EPDM SEAT DN100",
                "example": "DI LUG WAFER BV, EPDM SEAT, 4\"/DN100",
                "form": "D371X4",
                "spec": "D100",
                "count": 6,
                "customers": [[customer_fingerprint("ACME"), 6]],
            },
            {
                "description": "DI LUG WAFER BV EPDM SEAT DN100",
                "example": "DI LUG WAFER BV, EPDM SEAT, 4\"/DN100",
                "form": "D371X7",
                "spec": "B100",
                "count": 2,
                "customers": [[customer_fingerprint("OTHER"), 2]],
            },
            {
                "description": "DI LUG WAFER BV EPDM SEAT DN80",
                "example": "DI LUG WAFER BV, EPDM SEAT, 3\"/DN80",
                "form": "D371X4",
                "spec": "D80",
                "count": 2,
                "customers": [[customer_fingerprint("ACME"), 2]],
            },
        ],
    }
    index_path = tmp_path / "spec_index.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    return SpecInferenceService(index_path)


def test_parse_request_context_supports_sep_and_explicit_overrides() -> None:
    parsed = parse_request_context(
        "ACME [SEP] DI LUG WAFER BV [SEP] D371X4",
        customer="Explicit Customer",
    )

    assert parsed == ("DI LUG WAFER BV", "Explicit Customer", "D371X4")


def test_infer_uses_description_customer_form_history(
    inference_service: SpecInferenceService,
) -> None:
    result = inference_service.infer(
        "ACME[SEP]DI LUG WAFER BV EPDM SEAT DN100[SEP]D371X4"
    )

    assert result["inferred_spec"] == "D100"
    assert result["confidence"] == "high"
    assert result["match_level"] == "description_customer_form"
    assert result["customer"] == "ACME"
    assert result["form"] == "D371X4"
    assert result["evidence"]["size_candidates"] == ["100"]


def test_infer_uses_fuzzy_description_with_size_and_form_context(
    inference_service: SpecInferenceService,
) -> None:
    result = inference_service.infer(
        query="DI LUG WAFER BUTTERFLY EPDM SEAT DN80",
        customer="ACME",
        form="D371X4",
    )

    assert result["inferred_spec"] == "D80"
    assert result["match_level"] == "fuzzy_description"
    assert result["evidence"]["size_candidates"] == ["80"]
    assert result["evidence"]["size_match"] is True
    assert result["evidence"]["form_match"] is True


def test_infer_abstains_without_description_evidence(
    inference_service: SpecInferenceService,
) -> None:
    result = inference_service.infer("UNRELATED PRODUCT TEXT")

    assert result["inferred_spec"] is None
    assert result["confidence"] == "low"
    assert result["match_level"] == "none"
