"""Build time-validated deterministic specification rules from order history."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.spec_rules import infer_size, normalize_code, parse_specification


DEFAULT_INPUT = ROOT / "history_orders.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "spec_inference_rules.json"
DESCRIPTION_COLUMN = "英文描述"
DATE_COLUMN = "合同日期"
FORM_COLUMN = "品种"
SPEC_COLUMN = "规格"


def _prefix_statistics(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    statistics: dict[str, dict[str, Any]] = {}
    for form, values in frame.groupby("form")["spec_prefix"]:
        counts = Counter(values)
        prefix, prefix_support = counts.most_common(1)[0]
        total = sum(counts.values())
        statistics[form] = {
            "prefix": prefix,
            "support": total,
            "purity": prefix_support / total,
        }
    return statistics


def _combined_statistics(
    frame: pd.DataFrame,
    form_prefixes: dict[str, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    statistics = {
        form: {"support": 0, "correct": 0} for form in form_prefixes
    }
    relevant = frame[frame["form"].isin(form_prefixes)]
    for row in relevant.itertuples(index=False):
        size_result = infer_size(str(getattr(row, DESCRIPTION_COLUMN)))
        if size_result is None:
            continue
        form_stats = statistics[row.form]
        form_stats["support"] += 1
        inferred = form_prefixes[row.form]["prefix"] + size_result.size
        if inferred == row.spec_prefix + row.spec_size:
            form_stats["correct"] += 1
    return statistics


def build_rules(
    input_path: Path,
    train_before: str = "2024-04-28",
    holdout_from: str = "2024-09-01",
    min_train_support: int = 20,
    min_validation_support: int = 5,
) -> dict[str, Any]:
    """Derive rules in two windows and evaluate them on a later blind holdout."""
    frame = pd.read_excel(
        input_path,
        usecols=[DATE_COLUMN, FORM_COLUMN, SPEC_COLUMN, DESCRIPTION_COLUMN],
    )
    input_rows = len(frame)
    frame["date"] = pd.to_datetime(frame[DATE_COLUMN], errors="coerce")
    frame["form"] = frame[FORM_COLUMN].map(normalize_code)
    frame["parsed_spec"] = frame[SPEC_COLUMN].map(parse_specification)
    frame = frame[
        frame["date"].notna()
        & frame["form"].ne("")
        & frame["parsed_spec"].notna()
        & frame[DESCRIPTION_COLUMN].notna()
    ].copy()
    frame[["spec_prefix", "spec_size"]] = pd.DataFrame(
        frame["parsed_spec"].tolist(),
        index=frame.index,
    )

    train_boundary = pd.Timestamp(train_before)
    holdout_boundary = pd.Timestamp(holdout_from)
    train = frame[frame["date"] < train_boundary]
    validation = frame[
        (frame["date"] >= train_boundary) & (frame["date"] < holdout_boundary)
    ]
    holdout = frame[frame["date"] >= holdout_boundary]

    train_stats = _prefix_statistics(train)
    validation_stats = _prefix_statistics(validation)
    form_prefixes: dict[str, dict[str, Any]] = {}
    for form, train_rule in train_stats.items():
        validation_rule = validation_stats.get(form)
        if not validation_rule:
            continue
        if train_rule["support"] < min_train_support or train_rule["purity"] != 1.0:
            continue
        if (
            validation_rule["support"] < min_validation_support
            or validation_rule["purity"] != 1.0
            or validation_rule["prefix"] != train_rule["prefix"]
        ):
            continue
        form_prefixes[form] = {
            "prefix": train_rule["prefix"],
            "train_support": train_rule["support"],
            "validation_support": validation_rule["support"],
        }

    train_combined = _combined_statistics(train, form_prefixes)
    validation_combined = _combined_statistics(validation, form_prefixes)
    for form in list(form_prefixes):
        train_rule = train_combined[form]
        validation_rule = validation_combined[form]
        train_invalid = (
            train_rule["support"] < min_train_support
            or train_rule["support"] > train_rule["correct"]
        )
        validation_invalid = (
            validation_rule["support"] < min_validation_support
            or validation_rule["support"] > validation_rule["correct"]
        )
        if train_invalid or validation_invalid:
            del form_prefixes[form]
            continue
        form_prefixes[form]["train_combined_support"] = train_rule["support"]
        form_prefixes[form]["validation_combined_support"] = validation_rule["support"]

    prefix_rows = holdout[holdout["form"].isin(form_prefixes)]
    prefix_correct = sum(
        form_prefixes[row.form]["prefix"] == row.spec_prefix
        for row in prefix_rows.itertuples(index=False)
    )
    combined_covered = 0
    combined_correct = 0
    for row in prefix_rows.itertuples(index=False):
        size_result = infer_size(str(getattr(row, DESCRIPTION_COLUMN)))
        if size_result is None:
            continue
        combined_covered += 1
        inferred = form_prefixes[row.form]["prefix"] + size_result.size
        if inferred == row.spec_prefix + row.spec_size:
            combined_correct += 1

    valid_dates = frame["date"].dropna()
    return {
        "version": 1,
        "source": {
            "file": input_path.name,
            "input_rows": input_rows,
            "standard_spec_rows": len(frame),
            "date_min": str(valid_dates.min().date()) if not valid_dates.empty else None,
            "date_max": str(valid_dates.max().date()) if not valid_dates.empty else None,
        },
        "criteria": {
            "train_before": train_before,
            "holdout_from": holdout_from,
            "min_train_support": min_train_support,
            "min_train_purity": 1.0,
            "min_validation_support": min_validation_support,
            "min_validation_purity": 1.0,
            "min_train_combined_purity": 1.0,
            "min_train_combined_support": min_train_support,
            "min_validation_combined_purity": 1.0,
            "min_validation_combined_support": min_validation_support,
        },
        "windows": {
            "train_rows": len(train),
            "validation_rows": len(validation),
            "holdout_rows": len(holdout),
        },
        "holdout_metrics": {
            "prefix_covered": len(prefix_rows),
            "prefix_coverage": round(len(prefix_rows) / len(holdout), 4),
            "prefix_accuracy": round(prefix_correct / len(prefix_rows), 4)
            if len(prefix_rows)
            else 0.0,
            "combined_covered": combined_covered,
            "combined_coverage": round(combined_covered / len(holdout), 4),
            "combined_accuracy": round(combined_correct / combined_covered, 4)
            if combined_covered
            else 0.0,
        },
        "form_prefixes": dict(sorted(form_prefixes.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-before", default="2024-04-28")
    parser.add_argument("--holdout-from", default="2024-09-01")
    parser.add_argument("--min-train-support", type=int, default=20)
    parser.add_argument("--min-validation-support", type=int, default=5)
    args = parser.parse_args()

    payload = build_rules(
        args.input,
        train_before=args.train_before,
        holdout_from=args.holdout_from,
        min_train_support=args.min_train_support,
        min_validation_support=args.min_validation_support,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = payload["holdout_metrics"]
    print(
        f"Wrote {len(payload['form_prefixes'])} rules to {args.output}; "
        f"holdout combined accuracy={metrics['combined_accuracy']:.2%}, "
        f"coverage={metrics['combined_coverage']:.2%}"
    )


if __name__ == "__main__":
    main()
