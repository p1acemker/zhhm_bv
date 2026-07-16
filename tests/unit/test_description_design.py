from service.description_design import (
    BusinessDictionary,
    DescriptionDesignEngine,
    ExceptionRule,
    TermRule,
)


def test_dictionary_prefers_longest_scoped_phrase() -> None:
    dictionary = BusinessDictionary.default()

    matches = dictionary.match_terms(
        "DI LUG WAFER BUTTERFLY VALVE",
        family="butterfly",
    )

    assert matches["connection"].value == "LUG WAFER"


def test_description_exception_overrides_normal_term_match() -> None:
    dictionary = BusinessDictionary(
        [TermRule("WAFER", "WAFER", "connection")],
        exceptions=[
            ExceptionRule(
                match_field="description",
                match_value="SPECIAL SERIES",
                override_field="connection",
                override_value="FLANGED",
                reason="approved business exception",
            )
        ],
    )

    matches = dictionary.match_terms(
        "SPECIAL SERIES WAFER BUTTERFLY VALVE",
        family="butterfly",
    )

    assert matches["connection"].value == "FLANGED"
    assert matches["connection"].source_term == "EXCEPTION:SPECIAL SERIES"


def test_butterfly_description_is_rendered_with_full_english_terms() -> None:
    result = DescriptionDesignEngine().design(
        'DI LUG WAFER BV, EPDM SEAT, SS316 DISC, GEAR, PN16, 4"/DN100'
    )

    assert result["status"] == "complete"
    assert result["valve_family"] == "butterfly"
    assert result["product_role"] == "valve"
    assert result["attributes"]["body_material"]["value"] == "DUCTILE IRON"
    assert result["attributes"]["connection"]["value"] == "LUG WAFER"
    assert result["standardized_description"] == (
        "DUCTILE IRON LUG WAFER BUTTERFLY VALVE, EPDM SEAT, "
        "STAINLESS STEEL 316 DISC, GEAR OPERATED, PN16, 4\"/DN100"
    )
    assert " DI " not in f' {result["standardized_description"]} '
    assert " BV" not in result["standardized_description"]


def test_ball_valve_is_not_misclassified_from_bv_text() -> None:
    result = DescriptionDesignEngine().design(
        'BRONZE BALL VALVE, FULL PORT, 2"'
    )

    assert result["status"] == "unsupported"
    assert result["valve_family"] is None


def test_accessory_is_excluded_before_valve_family_design() -> None:
    result = DescriptionDesignEngine().design(
        'SUPERVISORY SWITCH FOR OS&Y GATE VALVE 2"-16"'
    )

    assert result["status"] == "excluded"
    assert result["product_role"] == "accessory"
    assert result["standardized_description"] is None


def test_check_and_gate_abbreviations_require_valve_context() -> None:
    engine = DescriptionDesignEngine()

    check = engine.design('DI FLGD SWING CV, AWWA C508, 6"/DN150')
    gate = engine.design(
        'DI FLGD OS&Y GV, STEM PRE-NOTCHED, HANDWHEEL, PN16, 6"/DN150'
    )

    assert check["valve_family"] == "check"
    assert "CHECK VALVE" in check["standardized_description"]
    assert gate["valve_family"] == "gate"
    assert "GATE VALVE" in gate["standardized_description"]


def test_grooved_size_keeps_pipe_outside_diameter() -> None:
    result = DescriptionDesignEngine().design(
        'DI GRVD FIRE RISER BV, DI+EPDM DISC, 4"/114MM'
    )

    assert result["attributes"]["size"]["value"] == '4"/114MM'
    assert result["standardized_description"].endswith('4"/114MM')


def test_template_id_is_stable_across_sizes() -> None:
    engine = DescriptionDesignEngine()

    first = engine.design(
        'DI FLGD SWING CV, AWWA C508, 4"/DN100'
    )
    second = engine.design(
        'DI FLGD SWING CV, AWWA C508, 6"/DN150'
    )

    assert first["template_id"] == second["template_id"]
    assert first["standardized_description"] != second["standardized_description"]
