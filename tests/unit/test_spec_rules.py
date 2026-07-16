import json
from pathlib import Path

from service.spec_inference import SpecInferenceService, customer_fingerprint
from service.spec_rules import MatureSpecRules, infer_size


def _rules_payload() -> dict:
    return {
        "version": 1,
        "source": {"standard_spec_rows": 100},
        "holdout_metrics": {"combined_accuracy": 1.0},
        "form_prefixes": {
            "D71XLV99": {
                "prefix": "D",
                "train_support": 53,
                "validation_support": 10,
            }
        },
    }


def test_infer_size_uses_explicit_dn_and_suitable_range() -> None:
    single = infer_size('DI WAFER BV, 4"/DN100')
    suitable = infer_size("SUITABLE FOR DN50, DN65 AND DN80")

    assert single is not None
    assert (single.size, single.rule) == ("100", "dn_size")
    assert suitable is not None
    assert (suitable.size, suitable.rule) == ("80", "suitable_range_max")


def test_infer_size_maps_grooved_nominal_size_to_pipe_od() -> None:
    result = infer_size('DI GROOVED BV, 4"/DN100')
    compact_fraction = infer_size('GROOVED BV, 21/2"/DN65')

    assert result is not None
    assert (result.size, result.rule) == ("114", "grooved_inch_to_od")
    assert compact_fraction is not None
    assert compact_fraction.size == "76"


def test_infer_size_handles_grooved_mm_conflicts_conservatively() -> None:
    close_mm = infer_size('DI GRVD BV, 6"/165MM')
    nominal_mm = infer_size('DI GRVD BV, 3"/80MM')
    ambiguous_mm = infer_size("DI 80MM GRV END BV")

    assert close_mm is not None
    assert (close_mm.size, close_mm.rule) == ("165", "grooved_explicit_mm")
    assert nominal_mm is not None
    assert (nominal_mm.size, nominal_mm.rule) == ("89", "grooved_inch_to_od")
    assert ambiguous_mm is None


def test_infer_size_supports_validated_grooved_od_conventions() -> None:
    cts = infer_size('3" BRZ BDY GRVD CTS BFV')
    copper_without_quote = infer_size("6 COP GRV BFV")
    product_exception = infer_size('GD48638N 2 1/2" GROOVE BUTTERFLY VALVE')
    explicit_product_mm = infer_size(
        'GD48638N 2 1/2" GROOVE BUTTERFLY VALVE (76 mm)'
    )

    assert cts is not None
    assert (cts.size, cts.rule) == ("79", "grooved_cts_inch_to_od")
    assert copper_without_quote is not None
    assert copper_without_quote.size == "156"
    assert product_exception is not None
    assert (product_exception.size, product_exception.rule) == (
        "73",
        "grooved_product_inch_to_od",
    )
    assert explicit_product_mm is not None
    assert explicit_product_mm.size == "76"


def test_mature_rules_require_a_validated_form_and_parseable_size() -> None:
    rules = MatureSpecRules(_rules_payload())

    result = rules.infer("DI WAFER BV DN100", "D71XLV99")

    assert result is not None
    assert result.specification == "D100"
    assert result.train_support == 53
    assert rules.infer("DI WAFER BV DN100", "UNKNOWN") is None
    assert rules.infer("DI WAFER BV", "D71XLV99") is None


def test_service_uses_mature_rule_for_an_unseen_description(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {"rows": 100},
                "records": [
                    {
                        "description": "OTHER PRODUCT DN50",
                        "example": "OTHER PRODUCT DN50",
                        "form": "OTHER",
                        "spec": "B50",
                        "count": 2,
                        "customers": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(_rules_payload()), encoding="utf-8")
    service = SpecInferenceService(index_path, rules_path)

    result = service.infer("NOVEL DI WAFER BV DN100", form="D71XLV99")

    assert result["inferred_spec"] == "D100"
    assert result["match_level"] == "mature_rule"
    assert result["confidence"] == "high"
    assert result["evidence"]["rule_path"] == ["stable_form_prefix", "dn_size"]


def test_contextual_exact_history_precedes_mature_rule(tmp_path: Path) -> None:
    description = "SPECIAL DI WAFER BV DN100"
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {"rows": 2},
                "records": [
                    {
                        "description": description,
                        "example": description,
                        "form": "D71XLV99",
                        "spec": "D125",
                        "count": 2,
                        "customers": [
                            [customer_fingerprint("ACME"), 2]
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(_rules_payload()), encoding="utf-8")
    service = SpecInferenceService(index_path, rules_path)

    result = service.infer(description, customer="ACME", form="D71XLV99")

    assert result["inferred_spec"] == "D125"
    assert result["match_level"] == "description_customer_form"


def test_mature_rule_precedes_less_specific_exact_history(tmp_path: Path) -> None:
    description = "SPECIAL DI WAFER BV DN100"
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {"rows": 2},
                "records": [
                    {
                        "description": description,
                        "example": description,
                        "form": "D71XLV99",
                        "spec": "D125",
                        "count": 2,
                        "customers": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(_rules_payload()), encoding="utf-8")
    service = SpecInferenceService(index_path, rules_path)

    result = service.infer(description, form="D71XLV99")

    assert result["inferred_spec"] == "D100"
    assert result["match_level"] == "mature_rule"
