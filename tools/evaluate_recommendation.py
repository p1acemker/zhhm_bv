"""Evaluate the deterministic recommendation service on a chronological holdout."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.product_code import parse_product_code
from service.recommendation import RecommendationService, normalize_code


def evaluate(frame: pd.DataFrame, service: RecommendationService) -> dict:
    by1_correct = spec_correct = 0
    by1_answered = spec_answered = 0
    by1_levels = Counter()
    spec_levels = Counter()
    for row in frame.itertuples(index=False):
        result = service.recommend(
            query=row.raw_description,
            form_code=row.form_code,
            top_k=5,
        )
        by1_levels[result["by1_match_level"]] += 1
        spec_levels[result["spec_match_level"]] += 1
        by1_candidates = [item["by1"] for item in result["by1_candidates"]]
        if by1_candidates:
            by1_answered += 1
        if row.by1 in by1_candidates:
            by1_correct += 1
        if result["inferred_spec"] is not None:
            spec_answered += 1
        if result["inferred_spec"] == row.spec:
            spec_correct += 1
    return {
        "rows": len(frame),
        "by1_top5": {
            "answered": by1_answered,
            "coverage": round(by1_answered / len(frame), 4) if len(frame) else 0,
            "overall_accuracy": round(by1_correct / len(frame), 4) if len(frame) else 0,
            "answered_accuracy": round(by1_correct / by1_answered, 4)
            if by1_answered
            else 0,
            "stages": dict(by1_levels),
        },
        "spec_top1": {
            "answered": spec_answered,
            "coverage": round(spec_answered / len(frame), 4) if len(frame) else 0,
            "overall_accuracy": round(spec_correct / len(frame), 4) if len(frame) else 0,
            "answered_accuracy": round(spec_correct / spec_answered, 4)
            if spec_answered
            else 0,
            "stages": dict(spec_levels),
        },
    }


def load_holdout(input_path: Path, holdout_from: str) -> pd.DataFrame:
    frame = pd.read_excel(
        input_path,
        usecols=["合同日期", "产品编码", "品种", "规格", "材质分类", "英文描述"],
    )
    frame["date"] = pd.to_datetime(frame["合同日期"], errors="coerce")
    parsed = frame.apply(
        lambda row: parse_product_code(
            row["产品编码"], row["品种"], row["规格"], row["材质分类"]
        ),
        axis=1,
    )
    frame["form_code"] = parsed.map(
        lambda item: item.form_code if item.status == "ok" else ""
    )
    frame["raw_description"] = frame["英文描述"].fillna("").astype(str)
    frame["by1"] = frame["品种"].map(normalize_code)
    frame["spec"] = frame["规格"].map(normalize_code)
    return frame[
        (frame["date"] >= pd.Timestamp(holdout_from))
        & frame["raw_description"].ne("")
        & frame["by1"].ne("")
        & frame["spec"].ne("")
        & frame["form_code"].ne("")
    ].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--holdout-from", default="2024-09-01")
    args = parser.parse_args()
    frame = load_holdout(args.input, args.holdout_from)
    service = RecommendationService(args.index)
    result = {"row_level": evaluate(frame, service)}
    deduplicated = frame.drop_duplicates(
        subset=["合同日期", "产品编码", "英文描述"]
    )
    result["deduplicated"] = evaluate(deduplicated, service)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
