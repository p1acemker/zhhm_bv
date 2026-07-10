from scripts.edesc_standardizer import standardize_edesc


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
