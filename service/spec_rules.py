"""Deterministic specification rules validated against historical orders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional


DN_RE = re.compile(r"\bDN\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
MM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*MM\b", re.IGNORECASE)
INCH_RE = re.compile(
    r"(?<![\d/])(\d+\s*[- ]\s*\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
    r"\s*[\"\u201d\u2033]",
    re.IGNORECASE,
)
GROOVED_RE = re.compile(r"\b(?:GROOVED|GROOVE|GRVD|GRV)\b|\bBVG-", re.IGNORECASE)
SUITABLE_RE = re.compile(r"\bSUIT(?:ABLE)?\s+FOR\b", re.IGNORECASE)
CTS_RE = re.compile(r"\b(?:CTS|COP|COPPER)\b", re.IGNORECASE)
COP_INCH_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s+(?:COP|COPPER)\b", re.IGNORECASE)
SPEC_RE = re.compile(r"^([A-Z]+)(\d+(?:\.\d+)?)$")

GROOVED_DN_TO_OD = {
    "50": "60",
    "65": "76",
    "80": "89",
    "100": "114",
    "125": "140",
    "150": "168",
    "200": "219",
    "250": "273",
    "300": "324",
    "350": "356",
    "400": "406",
    "450": "457",
    "500": "508",
    "600": "610",
}
GROOVED_INCH_TO_OD = {
    Decimal("2"): "60",
    Decimal("2.5"): "76",
    Decimal("3"): "89",
    Decimal("4"): "114",
    Decimal("5"): "140",
    Decimal("6"): "168",
    Decimal("8"): "219",
    Decimal("10"): "273",
    Decimal("12"): "324",
    Decimal("14"): "356",
    Decimal("16"): "406",
    Decimal("18"): "457",
    Decimal("20"): "508",
    Decimal("24"): "610",
}
GROOVED_PRODUCT_OD = {
    "GD48638N": {
        Decimal("2.5"): "73",
        Decimal("5"): "141",
    }
}
SIZE_RULE_RELIABILITY = {
    "dn_size": 0.997,
    "explicit_mm": 0.999,
    "suitable_range_max": 1.0,
    "grooved_explicit_mm": 0.999,
    "grooved_inch_to_od": 0.992,
    "grooved_dn_to_od": 0.995,
    "grooved_cts_inch_to_od": 1.0,
    "grooved_product_inch_to_od": 1.0,
}


def normalize_code(value: object) -> str:
    """Normalize a compact product code."""
    return re.sub(r"\s+", "", str(value).upper()) if value is not None else ""


def normalize_number(value: str) -> str:
    """Normalize decimal padding while preserving integer zeroes."""
    return value.rstrip("0").rstrip(".") if "." in value else value


def parse_specification(value: object) -> Optional[tuple[str, str]]:
    """Split a standard specification into alphabetic prefix and size."""
    match = SPEC_RE.fullmatch(normalize_code(value))
    if not match:
        return None
    return match.group(1), normalize_number(match.group(2))


@dataclass(frozen=True)
class SizeRuleResult:
    """A size selected by one deterministic description rule."""

    size: str
    rule: str
    reliability: float


@dataclass(frozen=True)
class SpecificationRuleResult:
    """A complete specification assembled from form and size rules."""

    specification: str
    prefix: str
    size: str
    size_rule: str
    confidence_score: float
    train_support: int
    validation_support: int


def infer_size(description: str) -> Optional[SizeRuleResult]:
    """Infer a standard size from explicit DN, mm, range, or grooved notation."""
    text = str(description)
    dn_values = [_valid_number(value) for value in DN_RE.findall(text)]
    mm_values = [_rounded_mm(value) for value in MM_RE.findall(text)]
    dn_values = [value for value in dn_values if value]
    mm_values = [value for value in mm_values if value]
    grooved = bool(GROOVED_RE.search(text))

    if grooved:
        inch_values = [_parse_inches(value) for value in INCH_RE.findall(text)]
        if not inch_values:
            inch_values = [_parse_inches(value) for value in COP_INCH_RE.findall(text)]
        inch_values = [value for value in inch_values if value]
        if inch_values:
            mapped = _grooved_od(text, inch_values[-1])
        else:
            mapped = None
        if mapped:
            if mm_values and abs(Decimal(mm_values[-1]) - Decimal(mapped)) <= Decimal("3"):
                return _size_result(mm_values[-1], "grooved_explicit_mm")
            if CTS_RE.search(text):
                return _size_result(mapped, "grooved_cts_inch_to_od")
            if any(code in text.upper() for code in GROOVED_PRODUCT_OD):
                return _size_result(mapped, "grooved_product_inch_to_od")
            return _size_result(mapped, "grooved_inch_to_od")

        # A lone mm value in grooved text may be nominal DN or actual pipe OD.
        # Historical orders contain both conventions, so the mature rule abstains.
        if mm_values:
            return None
        mapped_dn = [GROOVED_DN_TO_OD.get(value) for value in dn_values]
        mapped_dn = [value for value in mapped_dn if value]
        if mapped_dn:
            selected = max(mapped_dn, key=Decimal) if SUITABLE_RE.search(text) else mapped_dn[-1]
            return _size_result(selected, "grooved_dn_to_od")
        return None

    if mm_values:
        selected = max(mm_values, key=Decimal) if SUITABLE_RE.search(text) else mm_values[-1]
        rule = "suitable_range_max" if SUITABLE_RE.search(text) else "explicit_mm"
        return _size_result(selected, rule)
    if dn_values:
        selected = max(dn_values, key=Decimal) if SUITABLE_RE.search(text) else dn_values[-1]
        rule = "suitable_range_max" if SUITABLE_RE.search(text) else "dn_size"
        return _size_result(selected, rule)
    return None


class MatureSpecRules:
    """Load form-prefix rules that remained stable across time windows."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if payload.get("version") != 1:
            raise ValueError("Unsupported specification rules version")
        raw_rules = payload.get("form_prefixes", {})
        self._form_prefixes: dict[str, Mapping[str, Any]] = {
            normalize_code(form): rule for form, rule in raw_rules.items()
        }
        self.source: Mapping[str, Any] = payload.get("source", {})
        self.holdout_metrics: Mapping[str, Any] = payload.get("holdout_metrics", {})

    @classmethod
    def from_path(cls, path: str | Path) -> "MatureSpecRules":
        """Load and validate a generated JSON rules file."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload)

    def infer(self, description: str, form: str) -> Optional[SpecificationRuleResult]:
        """Infer a specification only when both prefix and size rules apply."""
        normalized_form = normalize_code(form)
        prefix_rule = self._form_prefixes.get(normalized_form)
        if not prefix_rule:
            return None
        size_result = infer_size(description)
        if size_result is None:
            return None

        prefix = normalize_code(prefix_rule.get("prefix"))
        if not prefix.isalpha():
            return None
        train_support = int(prefix_rule.get("train_support", 0))
        validation_support = int(prefix_rule.get("validation_support", 0))
        confidence_score = min(size_result.reliability, 0.995)
        return SpecificationRuleResult(
            specification=f"{prefix}{size_result.size}",
            prefix=prefix,
            size=size_result.size,
            size_rule=size_result.rule,
            confidence_score=confidence_score,
            train_support=train_support,
            validation_support=validation_support,
        )


def _size_result(size: str, rule: str) -> SizeRuleResult:
    return SizeRuleResult(size=size, rule=rule, reliability=SIZE_RULE_RELIABILITY[rule])


def _valid_number(value: str) -> Optional[str]:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if number <= 0 or number > 2000:
        return None
    return normalize_number(value)


def _rounded_mm(value: str) -> Optional[str]:
    valid = _valid_number(value)
    if valid is None:
        return None
    return str(Decimal(valid).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_inches(value: str) -> Optional[Decimal]:
    text = re.sub(r"\s*-\s*", " ", value.strip())
    try:
        if " " in text and "/" in text:
            whole, fraction = text.split(None, 1)
            numerator, denominator = fraction.split("/", 1)
            return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            if len(numerator) > 1 and Decimal(numerator) >= 10:
                whole = numerator[:-1]
                numerator = numerator[-1]
                return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
            return Decimal(numerator) / Decimal(denominator)
        return Decimal(text)
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def _grooved_od(description: str, inches: Decimal) -> Optional[str]:
    upper = description.upper()
    if CTS_RE.search(upper):
        millimetres = (inches + Decimal("0.125")) * Decimal("25.4")
        return str(millimetres.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    for product_code, mapping in GROOVED_PRODUCT_OD.items():
        if product_code in upper and inches in mapping:
            return mapping[inches]
    return GROOVED_INCH_TO_OD.get(inches)
