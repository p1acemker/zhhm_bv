"""Build the compact specification inference index from historical orders."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "history_orders.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "spec_inference_index.json"
REQUIRED_COLUMNS = [
    "客户简称",
    "单证客户名称",
    "合同日期",
    "品种",
    "规格",
    "英文描述",
]


def normalize_text(value: object) -> str:
    """Normalize free text for deterministic lookup."""
    if pd.isna(value):
        return ""
    text = str(value).upper().replace("BUNA-N", "NBR")
    text = re.sub(r"[_\W]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_code(value: object) -> str:
    """Normalize compact product and specification codes."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value).upper())


def customer_fingerprint(value: str) -> str:
    """Return a deterministic non-plaintext customer lookup key."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_index(input_path: Path, before_date: Optional[str] = None) -> dict[str, Any]:
    """Aggregate historical rows into runtime records."""
    frame = pd.read_excel(input_path, usecols=REQUIRED_COLUMNS)
    frame = frame.dropna(subset=["英文描述", "规格", "品种"]).copy()
    frame["description"] = frame["英文描述"].map(normalize_text)
    frame["form"] = frame["品种"].map(normalize_code)
    frame["spec"] = frame["规格"].map(normalize_code)
    frame["customer_short"] = frame["客户简称"].map(normalize_text)
    frame["customer_document"] = frame["单证客户名称"].map(normalize_text)
    frame["date"] = pd.to_datetime(frame["合同日期"], errors="coerce")
    if before_date:
        frame = frame[frame["date"] < pd.Timestamp(before_date)]
    frame = frame[
        frame["description"].ne("")
        & frame["form"].ne("")
        & frame["spec"].ne("")
    ]

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in frame.itertuples(index=False):
        key = (row.description, row.form, row.spec)
        record = grouped.setdefault(
            key,
            {
                "description": row.description,
                "example": str(getattr(row, "英文描述")),
                "form": row.form,
                "spec": row.spec,
                "count": 0,
                "customers": Counter(),
            },
        )
        record["count"] += 1
        customers = {row.customer_short, row.customer_document} - {""}
        record["customers"].update(customer_fingerprint(customer) for customer in customers)

    records = []
    for record in grouped.values():
        records.append(
            {
                "description": record["description"],
                "example": record["example"],
                "form": record["form"],
                "spec": record["spec"],
                "count": record["count"],
                "customers": sorted(record["customers"].items()),
            }
        )
    records.sort(key=lambda item: (item["description"], item["form"], item["spec"]))

    valid_dates = frame["date"].dropna()
    return {
        "version": 1,
        "source": {
            "file": input_path.name,
            "rows": int(len(frame)),
            "date_min": str(valid_dates.min().date()) if not valid_dates.empty else None,
            "date_max": str(valid_dates.max().date()) if not valid_dates.empty else None,
            "descriptions": int(frame["description"].nunique()),
            "forms": int(frame["form"].nunique()),
            "specs": int(frame["spec"].nunique()),
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--before-date",
        help="Optionally include only rows before this ISO date.",
    )
    args = parser.parse_args()

    index = build_index(args.input, before_date=args.before_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Wrote {len(index['records'])} records from "
        f"{index['source']['rows']} rows to {args.output}"
    )


if __name__ == "__main__":
    main()
