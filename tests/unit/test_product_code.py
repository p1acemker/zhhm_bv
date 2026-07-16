from service.product_code import parse_product_code


def test_parse_product_code_extracts_by1_spec_form_material_and_surface() -> None:
    fields = parse_product_code(
        "LD71XLV99_D100_90FQ11L50",
        by1="D71XLV99",
        specification="D100",
        material="Q11",
    )

    assert fields.status == "ok"
    assert fields.code_by1 == "LD71XLV99"
    assert fields.business_prefix == "L"
    assert fields.specification == "D100"
    assert fields.form_code == "90F"
    assert fields.material == "Q11"
    assert fields.surface == "L50"


def test_parse_product_code_supports_leading_business_prefix() -> None:
    fields = parse_product_code(
        "RDWLX_B80_922Q11R40",
        by1="DWLX",
        specification="B80",
        material="Q11",
    )

    assert fields.status == "ok"
    assert fields.business_prefix == "R"
    assert fields.form_code == "922"
    assert fields.surface == "R40"


def test_parse_product_code_accepts_exact_by1_without_business_prefix() -> None:
    fields = parse_product_code(
        "RXD381X_D100_91VQ11R40",
        by1="RXD381X",
        specification="D100",
        material="Q11",
    )

    assert fields.status == "ok"
    assert fields.business_prefix == ""
    assert fields.form_code == "91V"


def test_parse_product_code_quarantines_legacy_numeric_codes() -> None:
    fields = parse_product_code(
        "30103010012",
        by1="DB114",
        specification="B50",
        material="B11",
    )

    assert fields.status == "spec_segment_not_found"
    assert fields.form_code == ""
