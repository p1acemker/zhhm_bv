import pytest

from service.variety_type import VarietyTypeService


def test_parse_with_normalized_returns_expected_keys() -> None:
    result = VarietyTypeService().parse_with_normalized("D371X4")
    normalized_key = "standardizedProduct" if "standardizedProduct" in result else "标准化品种"

    assert set(result) == {
        "type",
        "driveMode",
        "connectMode",
        "form",
        "material",
        normalized_key,
    }
    assert result[normalized_key] == "D371X"


def test_parse_with_normalized_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        VarietyTypeService().parse_with_normalized(" ")
