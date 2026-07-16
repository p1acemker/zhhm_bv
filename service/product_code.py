"""Parse the structured product-code fields used by recommendation indexes."""

from __future__ import annotations

from dataclasses import dataclass
import re


def normalize_code(value: object) -> str:
    """Normalize a compact product, form, or specification code."""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).upper())


@dataclass(frozen=True)
class ProductCodeFields:
    """Fields extracted from ``<by1>_<spec>_<form><material><surface>``."""

    raw_code: str
    code_by1: str
    business_prefix: str
    specification: str
    form_code: str
    material: str
    surface: str
    status: str


def parse_product_code(
    product_code: object,
    by1: object = "",
    specification: object = "",
    material: object = "",
) -> ProductCodeFields:
    """Extract and validate product-code segments against row labels."""
    raw_code = normalize_code(product_code)
    expected_by1 = normalize_code(by1)
    expected_spec = normalize_code(specification)
    expected_material = normalize_code(material)
    empty = ProductCodeFields(
        raw_code=raw_code,
        code_by1="",
        business_prefix="",
        specification="",
        form_code="",
        material="",
        surface="",
        status="missing_code" if not raw_code else "invalid",
    )
    if not raw_code:
        return empty

    parts = raw_code.split("_")
    spec_index = next(
        (
            index
            for index, part in enumerate(parts)
            if part and (not expected_spec or part == expected_spec)
        ),
        None,
    )
    if spec_index is None or spec_index == 0 or spec_index >= len(parts) - 1:
        return ProductCodeFields(
            **{**empty.__dict__, "status": "spec_segment_not_found"}
        )

    code_by1 = "_".join(parts[:spec_index])
    specification_value = parts[spec_index]
    tail = "_".join(parts[spec_index + 1 :])
    material_index = tail.find(expected_material) if expected_material else -1
    if material_index < 0:
        return ProductCodeFields(
            raw_code=raw_code,
            code_by1=code_by1,
            business_prefix=_business_prefix(code_by1, expected_by1),
            specification=specification_value,
            form_code="",
            material="",
            surface="",
            status="material_not_found",
        )

    form_code = tail[:material_index].strip("_")
    surface = tail[material_index + len(expected_material) :].strip("_")
    prefix = _business_prefix(code_by1, expected_by1)
    status = "ok"
    if not expected_by1 or not code_by1.endswith(expected_by1):
        status = "by1_mismatch"
    elif not form_code:
        status = "empty_form_code"
    elif not expected_material:
        status = "missing_material_label"
    elif code_by1 != expected_by1 and not prefix:
        status = "business_prefix_missing"
    return ProductCodeFields(
        raw_code=raw_code,
        code_by1=code_by1,
        business_prefix=prefix,
        specification=specification_value,
        form_code=form_code,
        material=expected_material,
        surface=surface,
        status=status,
    )


def _business_prefix(code_by1: str, expected_by1: str) -> str:
    if not expected_by1 or not code_by1.endswith(expected_by1):
        return ""
    prefix = code_by1[: -len(expected_by1)]
    return prefix if len(prefix) == 1 else ""
