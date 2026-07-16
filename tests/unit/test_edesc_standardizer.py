from scripts.edesc_standardizer import (
    standardize_description_views,
    standardize_edesc,
    standardize_edesc_for_by1,
)


def test_standardize_edesc_preserves_the_api_search_representation() -> None:
    result = standardize_edesc(
        "DI LUG WAFER BUTTERFLY VALVE EPDM SEAT SS316 DISC GEAR DN100 PN16"
    )

    assert result["standardized"] == (
        'DI LUG WAFER BFV,EPDM SEAT,SS316 DISC,GEAR,4"/DN100,PN16'
    )
    assert result["segments"] == {
        "body": "DI LUG WAFER BFV",
        "seat": "EPDM SEAT",
        "disc": "SS316 DISC",
        "actuation": "GEAR",
        "size": '4"/DN100',
        "pressure": "PN16",
        "extra": "",
    }


def test_unknown_materials_are_not_invented_for_vector_search() -> None:
    result = standardize_edesc("DI WAFER BUTTERFLY VALVE GEAR DN100 PN16")

    assert result["segments"]["seat"] == ""
    assert result["segments"]["disc"] == ""
    assert "EPDM" not in result["standardized"]
    assert "DI DISC" not in result["standardized"]


def test_by1_representation_removes_size_but_keeps_structure() -> None:
    semantic = standardize_edesc_for_by1(
        "DI LUG WAFER BUTTERFLY VALVE EPDM SEAT SS316 DISC GEAR DN100 PN16"
    )

    assert semantic == "DI LUG WAFER BFV,EPDM SEAT,SS316 DISC,GEAR,PN16"
    assert "DN100" not in semantic


def test_by1_representation_does_not_turn_accessories_into_valves() -> None:
    semantic = standardize_edesc_for_by1("PTFE Gasket-WP 6")

    assert semantic == "PTFE GASKET WP 6"
    assert "BFV" not in semantic


def test_views_keep_raw_full_and_size_reduced_structural_text() -> None:
    raw = 'DI LUG WAFER BUTTERFLY VALVE EPDM SEAT GEAR 4"/DN100 PN16'

    result = standardize_description_views(raw)

    assert result.raw_description == raw
    assert "DN100" not in result.structural_description
    assert "WAFER" in result.structural_description
    assert "EPDM" in result.structural_description
    assert "DN100" in result.full_description
    assert result.attributes["connection"].value == "LUG WAFER"


def test_missing_material_is_unknown_not_epdm_or_di() -> None:
    result = standardize_description_views("DI WAFER BUTTERFLY VALVE DN100")

    seat = result.attributes.get("seat_material")
    assert seat is None or seat.value in (None, "unknown")
    assert "EPDM" not in result.structural_description
    assert "DI DISC" not in result.structural_description
