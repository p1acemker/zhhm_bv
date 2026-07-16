"""Conservative field extraction and deterministic valve-description rendering."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .dictionary import BusinessDictionary


FAMILY_NAMES = {
    "butterfly": "BUTTERFLY VALVE",
    "check": "CHECK VALVE",
    "gate": "GATE VALVE",
}

ACCESSORY_RE = re.compile(
    r"^(?:VALVE\s+)?(?:SUPERVISORY\s+SWITCH|INDEX\s+PLATE|"
    r"TURBINE\s+HEAD|GEAR\s*BOX|HANDWHEEL|VERTICAL\s+INDICATOR\s+POST|"
    r"SIGNAL\s+WORM\s+GEAR)\b"
)
SPARE_RE = re.compile(
    r"\b(?:MAINTENANCE|REPAIR|SEAL)\s+KIT\b|\bGASKETS?\b|"
    r"\bSPARE\s+PARTS?\b|^(?:DISC|SEAT|STEM)\s+FOR\b"
)
BODY_CONTEXT_RE = re.compile(r"\b(?:DI|CI|DUCTILE\s+IRON|CAST\s+IRON)\b")
CONNECTION_CONTEXT_RE = re.compile(
    r"\b(?:LUG\s+WAFER|WAFER|GRVD|GROOVED|FLGD|FLANGED|THD|THREADED)\b"
)

DN_TO_INCH = {
    40: '1 1/2', 50: '2', 65: '2 1/2', 80: '3', 100: '4', 125: '5',
    150: '6', 200: '8', 250: '10', 300: '12', 350: '14', 400: '16',
    450: '18', 500: '20', 600: '24', 700: '28', 800: '32', 900: '36',
}
DN_TO_OD = {50: 60, 65: 73, 80: 89, 100: 114, 125: 140, 150: 168, 200: 219, 250: 273, 300: 324}
OD_TO_DN = {value: key for key, value in DN_TO_OD.items()}


class DescriptionDesignEngine:
    """Design canonical descriptions without inventing unsupported attributes."""

    def __init__(self, dictionary: BusinessDictionary | None = None) -> None:
        self.dictionary = dictionary or BusinessDictionary.default()

    def design(
        self,
        query: str,
        *,
        by1: str = "",
        form_code: str = "",
        inferred: Mapping[str, Mapping[str, Any] | str] | None = None,
    ) -> dict[str, Any]:
        """Classify, extract, and render one raw product description."""
        raw = str(query or "").strip()
        normalized = self._normalize(raw)
        role = self._classify_role(normalized)
        family = self._classify_family(normalized, by1)
        if role in {"accessory", "spare_part"}:
            return self._empty_result("excluded", family, role)
        if family is None:
            return self._empty_result("unsupported", None, "other")

        matches = self.dictionary.match_terms(
            normalized,
            family,
            context={"by1": by1, "form_code": form_code},
        )
        attributes: dict[str, dict[str, Any]] = {
            field: {
                "value": match.value,
                "source": "query",
                "confidence": 1.0,
                "evidence": match.source_term,
            }
            for field, match in matches.items()
        }
        self._add_pattern_attributes(normalized, attributes)
        inferred_fields = self._merge_inferred(attributes, inferred or {})
        template_id = self._template_id(family, attributes)
        description = self._render(family, attributes)
        required = {"body_material", "connection", "size"}
        complete = required.issubset(attributes)
        confidence_score = 0.99 if complete and not inferred_fields else 0.95
        if not complete:
            confidence_score = max(0.6, 0.9 - 0.1 * len(required - attributes.keys()))
        warnings = [f"missing_{field}" for field in sorted(required - attributes.keys())]
        return {
            "status": "complete" if complete else "partial",
            "valve_family": family,
            "product_role": "valve",
            "standardized_description": description,
            "template_id": template_id,
            "confidence": self._confidence_label(confidence_score),
            "confidence_score": round(confidence_score, 4),
            "attributes": attributes,
            "inferred_fields": inferred_fields,
            "warnings": warnings,
            "alternatives": [],
            "form_code": str(form_code or "").strip().upper(),
        }

    def render_from_values(
        self,
        family: str,
        values: Mapping[str, Any],
    ) -> str:
        """Render canonical text from already validated field values."""
        attributes = {
            field: {"value": value}
            for field, value in values.items()
            if value is not None and str(value).strip()
        }
        return self._render(family, attributes)

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.upper().replace("“", '"').replace("”", '"').replace("″", '"')
        text = text.replace("BUNA N", "BUNA-N")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _classify_role(text: str) -> str:
        if ACCESSORY_RE.search(text):
            return "accessory"
        if SPARE_RE.search(text):
            return "spare_part"
        return "valve"

    @staticmethod
    def _classify_family(text: str, by1: str = "") -> str | None:
        if re.search(r"\b(?:BALL|CONTROL)\s+VALVE\b", text):
            return None
        if re.search(r"\b(?:BUTTERFLY(?:\s+VALVE)?|BFV|BFLY)\b", text):
            return "butterfly"
        if re.search(
            r"\b(?:CHECK\s+VALVE|SWING\s+CHECK|DUAL\s+PLATE\s+CHECK|"
            r"NON[ -]?RETURN|NRV)\b",
            text,
        ):
            return "check"
        if re.search(r"\b(?:GATE\s+VALVE|RESILIENT\s+SEATED\s+GATE|KNIFE\s+GATE)\b", text):
            return "gate"
        has_context = bool(BODY_CONTEXT_RE.search(text) and CONNECTION_CONTEXT_RE.search(text))
        if re.search(r"\bBV\b", text) and (has_context or "FIRE RISER" in text):
            return "butterfly"
        if re.search(r"\bCV\b", text) and (
            has_context or re.search(r"\b(?:SWING|DUAL\s+PLATE|D\.D\.)\b", text)
        ):
            return "check"
        if re.search(r"\bGV\b", text) and (
            has_context or re.search(r"\b(?:OS&Y|OSY|NRS|RESILIENT)\b", text)
        ):
            return "gate"
        compact = re.sub(r"[^A-Z0-9]", "", str(by1).upper())
        if re.search(r"(?:^|^[A-Z])XD\d", compact):
            return "butterfly"
        if re.search(r"(?:^|^[A-Z])DH?\d", compact):
            return "check"
        if re.search(r"(?:^|^[A-Z])XZ?\d", compact):
            return "gate"
        return None

    def _add_pattern_attributes(
        self,
        text: str,
        attributes: dict[str, dict[str, Any]],
    ) -> None:
        pressure = self._extract_pressure(text)
        if pressure:
            attributes["pressure"] = self._query_attribute(pressure, pressure)
        connection = attributes.get("connection", {}).get("value", "")
        size = self._extract_size(text, connection)
        if size:
            attributes["size"] = self._query_attribute(size, size)
        specials = []
        for pattern, value in [
            (r"\bSTEM\s+PRE[- ]NOTCHED\b", "STEM PRE-NOTCHED"),
            (r"\bDRAIN\s+HOLE\b", "DRAIN HOLE"),
            (r"\bTAMPER\s+SWITCH\b", "TAMPER SWITCH"),
            (r"\bHIGHER\s+LEVER\b", "HIGHER LEVER"),
            (r"\bLONG\s+NECK\b", "LONG NECK"),
            (r"\bLOCKABLE\b", "LOCKABLE"),
        ]:
            if re.search(pattern, text):
                specials.append(value)
        if specials:
            attributes["special_requirements"] = self._query_attribute(
                "; ".join(specials), "; ".join(specials)
            )

    @staticmethod
    def _query_attribute(value: str, evidence: str) -> dict[str, Any]:
        return {
            "value": value,
            "source": "query",
            "confidence": 1.0,
            "evidence": evidence,
        }

    @staticmethod
    def _extract_pressure(text: str) -> str:
        if match := re.search(r"\bPN\s*(\d+)\b", text):
            return f"PN{match.group(1)}"
        if match := re.search(r"\b(\d+(?:\.\d+)?)\s*PSI\b", text):
            return f"{match.group(1)} PSI"
        if match := re.search(r"\b(\d+(?:\.\d+)?)\s*BAR\b", text):
            return f"{match.group(1)} BAR"
        return ""

    @staticmethod
    def _extract_size(text: str, connection: str) -> str:
        inch = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+)"
        combined = re.search(
            rf"({inch})\s*\"\s*/\s*(?:DN\s*(\d+)|(\d+(?:\.\d+)?)\s*MM)",
            text,
        )
        if combined:
            left = re.sub(r"\s+", " ", combined.group(1)).strip()
            if combined.group(2):
                dn = int(combined.group(2))
                if connection == "GROOVED" and dn in DN_TO_OD:
                    return f'{left}"/{DN_TO_OD[dn]}MM'
                return f'{left}"/DN{dn}'
            od = float(combined.group(3))
            od_text = str(int(od)) if od.is_integer() else str(od)
            if connection in {"FLANGED", "WAFER", "LUG", "LUG WAFER"}:
                dn = OD_TO_DN.get(int(round(od)))
                if dn:
                    return f'{left}"/DN{dn}'
            return f'{left}"/{od_text}MM'
        if match := re.search(r"\bDN\s*(\d+)\b", text):
            dn = int(match.group(1))
            inch_value = DN_TO_INCH.get(dn)
            if connection == "GROOVED" and dn in DN_TO_OD and inch_value:
                return f'{inch_value}"/{DN_TO_OD[dn]}MM'
            return f'{inch_value}"/DN{dn}' if inch_value else f"DN{dn}"
        if match := re.search(rf"({inch})\s*\"", text):
            inch_value = re.sub(r"\s+", " ", match.group(1)).strip()
            return f'{inch_value}"'
        return ""

    @staticmethod
    def _merge_inferred(
        attributes: dict[str, dict[str, Any]],
        inferred: Mapping[str, Mapping[str, Any] | str],
    ) -> list[str]:
        added = []
        for field, raw in inferred.items():
            if field in attributes:
                continue
            if isinstance(raw, Mapping):
                value = str(raw.get("value", "")).strip()
                source = str(raw.get("source", "mature_rule"))
                confidence = float(raw.get("confidence", 0.99))
            else:
                value = str(raw).strip()
                source = "mature_rule"
                confidence = 0.99
            if not value or confidence < 0.99:
                continue
            attributes[field] = {
                "value": value,
                "source": source,
                "confidence": confidence,
                "evidence": "validated historical rule",
            }
            added.append(field)
        return sorted(added)

    @staticmethod
    def _template_id(family: str, attributes: Mapping[str, Mapping[str, Any]]) -> str:
        excluded = {"size"}
        signature = "|".join(
            f"{field}={attributes[field]['value']}"
            for field in sorted(attributes)
            if field not in excluded
        )
        digest = hashlib.sha1(f"{family}|{signature}".encode("utf-8")).hexdigest()[:10]
        return f"{family[:3].upper()}-{digest.upper()}"

    @staticmethod
    def _render(family: str, attributes: Mapping[str, Mapping[str, Any]]) -> str:
        value = lambda field: str(attributes.get(field, {}).get("value", "")).strip()
        heading = " ".join(
            part
            for part in [
                value("body_material"),
                value("connection"),
                value("structure"),
                FAMILY_NAMES[family],
            ]
            if part
        )
        segments = [heading]
        if value("seat_material"):
            segments.append(f'{value("seat_material")} SEAT')
        if value("closure_material"):
            closure = "WEDGE" if family == "gate" else "DISC"
            segments.append(f'{value("closure_material")} {closure}')
        for field in [
            "actuation",
            "special_requirements",
            "pressure",
            "standard_certification",
            "size",
        ]:
            if value(field):
                segments.append(value(field))
        return ", ".join(segment for segment in segments if segment)

    @staticmethod
    def _confidence_label(score: float) -> str:
        if score >= 0.95:
            return "high"
        if score >= 0.75:
            return "medium"
        return "low"

    @staticmethod
    def _empty_result(status: str, family: str | None, role: str) -> dict[str, Any]:
        return {
            "status": status,
            "valve_family": family,
            "product_role": role,
            "standardized_description": None,
            "template_id": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "attributes": {},
            "inferred_fields": [],
            "warnings": [],
            "alternatives": [],
        }
