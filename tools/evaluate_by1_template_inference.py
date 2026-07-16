"""Evaluate by1-template and specification predictions without time leakage."""

from __future__ import annotations

from collections import Counter
from datetime import date
import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def _iso(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def evaluate_prediction(
    prediction: Mapping[str, Any],
    truth: Mapping[str, Any],
) -> dict[str, bool]:
    """Return independent by1, spec, and joint correctness flags."""
    candidates = [
        str(item.get("by1", ""))
        for item in prediction.get("by1_candidates", [])[:5]
    ]
    actual_by1 = str(truth.get("by1", ""))
    predicted_spec = prediction.get("inferred_spec")
    actual_spec = truth.get("spec")
    by1_top1 = bool(candidates and candidates[0] == actual_by1)
    by1_top5 = bool(actual_by1 and actual_by1 in candidates)
    spec_top1 = bool(predicted_spec and actual_spec and predicted_spec == actual_spec)
    return {
        "by1_top1": by1_top1,
        "by1_top5": by1_top5,
        "spec_top1": spec_top1,
        "joint": by1_top5 and spec_top1,
    }


def _ratio(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 0.0


def _template_metrics(templates: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    values = list(templates)
    if not values:
        return {
            "template_purity": 0.0,
            "template_cohesion": 0.0,
            "template_coverage": 0.0,
            "spec_consistency": 0.0,
        }
    cohesion = [float(item.get("cohesion", 0.0)) for item in values]
    support = sum(int(item.get("support", 0)) for item in values)
    members = sum(int(item.get("member_count", 0)) for item in values)
    return {
        "template_purity": _ratio(
            sum(int(item.get("by1_count", 1)) == 1 for item in values), len(values)
        ),
        "template_cohesion": round(sum(cohesion) / len(cohesion), 4),
        "template_coverage": _ratio(members, support or members),
        "spec_consistency": _ratio(
            sum(bool(item.get("spec_consistent", False)) for item in values),
            len(values),
        ),
    }


def evaluate_rows(
    rows: Iterable[Mapping[str, Any]],
    train_before: str,
    validation_before: str,
    mode: str = "shadow",
) -> dict[str, object]:
    """Evaluate supplied prediction rows using a strict chronological split."""
    rows = list(rows)
    train = [row for row in rows if _iso(row.get("contract_date")) < train_before]
    evaluation = [row for row in rows if _iso(row.get("contract_date")) >= train_before]
    validation = [
        row
        for row in evaluation
        if _iso(row.get("contract_date")) < validation_before
    ]
    holdout = [
        row
        for row in evaluation
        if _iso(row.get("contract_date")) >= validation_before
    ]
    flags = [
        evaluate_prediction(row.get("prediction", {}), row)
        for row in evaluation
    ]
    answered_specs = [
        (row, flag)
        for row, flag in zip(evaluation, flags)
        if row.get("prediction", {}).get("inferred_spec")
    ]
    return {
        "mode": mode,
        "training_rows": len(train),
        "evaluation_rows": len(evaluation),
        "validation_rows": len(validation),
        "holdout_rows": len(holdout),
        "by1_top1": _ratio(sum(flag["by1_top1"] for flag in flags), len(flags)),
        "by1_top5": _ratio(sum(flag["by1_top5"] for flag in flags), len(flags)),
        "by1_coverage": _ratio(
            sum(bool(row.get("prediction", {}).get("by1_candidates")) for row in evaluation),
            len(evaluation),
        ),
        "spec_top1": _ratio(sum(flag["spec_top1"] for flag in flags), len(flags)),
        "spec_answered_accuracy": _ratio(
            sum(flag["spec_top1"] for _, flag in answered_specs), len(answered_specs)
        ),
        "joint_accuracy": _ratio(sum(flag["joint"] for flag in flags), len(flags)),
        "high_confidence_accuracy": _ratio(
            sum(
                flag["joint"]
                for row, flag in zip(evaluation, flags)
                if row.get("prediction", {}).get("spec_confidence") == "high"
            ),
            sum(
                row.get("prediction", {}).get("spec_confidence") == "high"
                for row in evaluation
            ),
        ),
        "segments": {
            "with_form_code": sum(bool(row.get("form_code")) for row in evaluation),
            "without_form_code": sum(not bool(row.get("form_code")) for row in evaluation),
        },
        **_template_metrics(row.get("template", {}) for row in evaluation),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=False)
    parser.add_argument("--train-before", default="2024-04-28")
    parser.add_argument("--validation-before", default="2024-09-01")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate_rows(rows, args.train_before, args.validation_before)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
