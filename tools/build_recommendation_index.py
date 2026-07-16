"""Build the row-derived by1/form/specification recommendation index."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.product_code import parse_product_code
from service.spec_rules import infer_size, parse_specification
from scripts.edesc_standardizer import standardize_edesc_for_by1


DEFAULT_INPUT = ROOT / "history_orders.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "recommendation_index.json"
DATE_COLUMN = "合同日期"
CODE_COLUMN = "产品编码"
BY1_COLUMN = "品种"
SPEC_COLUMN = "规格"
MATERIAL_COLUMN = "材质分类"
DESCRIPTION_COLUMN = "英文描述"
CUSTOMER_COLUMN = "客户简称"
REQUIRED_COLUMNS = [
    DATE_COLUMN,
    CODE_COLUMN,
    BY1_COLUMN,
    SPEC_COLUMN,
    MATERIAL_COLUMN,
    DESCRIPTION_COLUMN,
    CUSTOMER_COLUMN,
]
TRAIN_BEFORE = "2024-04-28"
VALIDATION_BEFORE = "2024-09-01"


def normalize_text(value: object) -> str:
    """Normalize free text without inventing missing attributes."""
    if pd.isna(value):
        return ""
    text = str(value).upper().replace("BUNA-N", "NBR")
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_code(value: object) -> str:
    """Normalize compact labels used as index keys."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value).upper())


def customer_fingerprint(value: object) -> str:
    """Store customer evidence without retaining plaintext names."""
    normalized = normalize_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _prefix_rules(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Build form-code prefix rules with a time-separated validation gate."""
    standard = frame[frame["parsed_spec"].notna() & frame["form_code"].ne("")]
    train = standard[standard["date"] < pd.Timestamp(TRAIN_BEFORE)]
    validation = standard[
        (standard["date"] >= pd.Timestamp(TRAIN_BEFORE))
        & (standard["date"] < pd.Timestamp(VALIDATION_BEFORE))
    ]

    def prefix_stats(window: pd.DataFrame) -> dict[str, tuple[str, int, float]]:
        result = {}
        for form_code, values in window.groupby("form_code")["spec_prefix"]:
            counts = Counter(values)
            prefix, support = counts.most_common(1)[0]
            total = sum(counts.values())
            result[form_code] = (prefix, total, support / total)
        return result

    train_stats = prefix_stats(train)
    validation_stats = prefix_stats(validation)
    candidates: dict[str, dict[str, Any]] = {}
    for form_code, (prefix, support, purity) in train_stats.items():
        later = validation_stats.get(form_code)
        if not later:
            continue
        if support < 20 or purity != 1.0:
            continue
        if later[1] < 5 or later[2] != 1.0 or later[0] != prefix:
            continue
        candidates[form_code] = {
            "prefix": prefix,
            "train_support": support,
            "validation_support": later[1],
        }

    def combined_stats(window: pd.DataFrame) -> dict[str, tuple[int, int]]:
        stats = {form_code: [0, 0] for form_code in candidates}
        for row in window[window["form_code"].isin(candidates)].itertuples(index=False):
            size_result = infer_size(row.raw_description)
            if size_result is None:
                continue
            stats[row.form_code][0] += 1
            if candidates[row.form_code]["prefix"] + size_result.size == row.spec:
                stats[row.form_code][1] += 1
        return {key: tuple(value) for key, value in stats.items()}

    train_combined = combined_stats(train)
    validation_combined = combined_stats(validation)
    rules = {}
    for form_code, item in candidates.items():
        train_support, train_correct = train_combined[form_code]
        validation_support, validation_correct = validation_combined[form_code]
        if train_support < 20 or train_support != train_correct:
            continue
        if validation_support < 5 or validation_support != validation_correct:
            continue
        rules[form_code] = {
            **item,
            "train_combined_support": train_support,
            "validation_combined_support": validation_support,
        }
    return dict(sorted(rules.items()))


def build_index(input_path: Path, before_date: Optional[str] = None) -> dict[str, Any]:
    """Build a compact, reproducible recommendation index from order rows."""
    frame = pd.read_excel(input_path, usecols=REQUIRED_COLUMNS)
    input_rows = len(frame)
    frame["date"] = pd.to_datetime(frame[DATE_COLUMN], errors="coerce")
    frame["raw_description"] = frame[DESCRIPTION_COLUMN].fillna("").astype(str)
    frame["description"] = frame[DESCRIPTION_COLUMN].map(normalize_text)
    frame["by1"] = frame[BY1_COLUMN].map(normalize_code)
    frame["spec"] = frame[SPEC_COLUMN].map(normalize_code)
    frame["material"] = frame[MATERIAL_COLUMN].map(normalize_code)
    frame["parsed_spec"] = frame["spec"].map(parse_specification)
    parsed = frame.apply(
        lambda row: parse_product_code(
            row[CODE_COLUMN], row[BY1_COLUMN], row[SPEC_COLUMN], row[MATERIAL_COLUMN]
        ),
        axis=1,
    )
    frame["code_status"] = parsed.map(lambda item: item.status)
    frame["business_prefix"] = parsed.map(lambda item: item.business_prefix)
    frame["surface"] = parsed.map(
        lambda item: item.surface if item.status == "ok" else ""
    )
    frame["form_code"] = parsed.map(
        lambda item: item.form_code if item.status == "ok" else ""
    )
    if before_date:
        frame = frame[frame["date"] < pd.Timestamp(before_date)].copy()

    valid_records = frame[
        frame["description"].ne("") & frame["by1"].ne("") & frame["spec"].ne("")
    ]
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in valid_records.itertuples(index=False):
        key = (row.description, row.form_code, row.by1, row.spec)
        parsed_spec = parse_specification(row.spec)
        record = grouped.setdefault(
            key,
            {
                "description": row.description,
                "semantic_description": standardize_edesc_for_by1(
                    row.raw_description
                ),
                "example": row.raw_description,
                "form_code": row.form_code,
                "by1": row.by1,
                "spec": row.spec,
                "spec_prefix": parsed_spec[0] if parsed_spec else "",
                "spec_size": parsed_spec[1] if parsed_spec else "",
                "count": 0,
                "customers": Counter(),
                "materials": Counter(),
                "surfaces": Counter(),
                "business_prefixes": Counter(),
                "date_min": None,
                "date_max": None,
            },
        )
        record["count"] += 1
        if row.material:
            record["materials"][row.material] += 1
        if row.surface:
            record["surfaces"][row.surface] += 1
        if row.business_prefix:
            record["business_prefixes"][row.business_prefix] += 1
        if pd.notna(row.date):
            record["date_min"] = (
                row.date
                if record["date_min"] is None
                else min(record["date_min"], row.date)
            )
            record["date_max"] = (
                row.date
                if record["date_max"] is None
                else max(record["date_max"], row.date)
            )
        fingerprint = customer_fingerprint(row.客户简称)
        if fingerprint:
            record["customers"][fingerprint] += 1

    records = []
    counter_fields = {"customers", "materials", "surfaces", "business_prefixes"}
    for record in grouped.values():
        records.append(
            {
                **{
                    key: value
                    for key, value in record.items()
                    if key not in counter_fields | {"date_min", "date_max"}
                },
                "customers": sorted(record["customers"].items()),
                "materials": sorted(record["materials"].items()),
                "surfaces": sorted(record["surfaces"].items()),
                "business_prefixes": sorted(record["business_prefixes"].items()),
                "date_min": str(record["date_min"].date())
                if record["date_min"] is not None
                else None,
                "date_max": str(record["date_max"].date())
                if record["date_max"] is not None
                else None,
            }
        )
    records.sort(key=lambda item: (item["description"], item["form_code"], item["by1"]))

    valid_dates = frame["date"].dropna()
    parse_status = Counter(frame["code_status"])
    rule_frame = frame[
        frame["description"].ne("")
        & frame["form_code"].ne("")
        & frame["parsed_spec"].notna()
    ].copy()
    rule_frame[["spec_prefix", "spec_number"]] = pd.DataFrame(
        rule_frame["parsed_spec"].tolist(), index=rule_frame.index
    )
    return {
        "version": 1,
        "source": {
            "file": input_path.name,
            "input_rows": input_rows,
            "indexed_rows": int(len(valid_records)),
            "date_min": str(valid_dates.min().date()) if not valid_dates.empty else None,
            "date_max": str(valid_dates.max().date()) if not valid_dates.empty else None,
            "descriptions": int(valid_records["description"].nunique()),
            "by1s": int(valid_records["by1"].nunique()),
            "specifications": int(valid_records["spec"].nunique()),
            "form_codes": int(valid_records["form_code"].nunique()),
            "parser_status": dict(parse_status),
        },
        "criteria": {
            "train_before": TRAIN_BEFORE,
            "validation_before": VALIDATION_BEFORE,
            "min_train_support": 20,
            "min_validation_support": 5,
            "min_purity": 1.0,
        },
        "form_prefix_rules": _prefix_rules(rule_frame),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--before-date", help="Index only rows before this ISO date.")
    args = parser.parse_args()
    payload = build_index(args.input, before_date=args.before_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(payload['records'])} records and "
        f"{len(payload['form_prefix_rules'])} form rules to {args.output}"
    )


if __name__ == "__main__":
    main()
