"""Measure full-label vector candidate recall on a chronological holdout."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.product_code import parse_product_code
from service.recommendation import RecommendationService, normalize_code
from scripts.edesc_standardizer import standardize_edesc_for_by1


def post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def embed(texts: list[str], url: str) -> dict[str, list[float]]:
    vectors = {}
    for start in range(0, len(texts), 64):
        batch = texts[start : start + 64]
        response = post_json(url, {"model": "bge-m3", "input": batch})
        for text, item in zip(batch, response["data"]):
            vectors[text] = item["embedding"]
    return vectors


def aggregate(hits: list[dict], form_code: str) -> list[str]:
    grouped = defaultdict(lambda: {"scores": [], "form_match": False})
    for hit in hits:
        payload = hit.get("payload", {})
        by1 = normalize_code(payload.get("by1") or payload.get("productName"))
        if not by1:
            continue
        grouped[by1]["scores"].append(float(hit["score"]))
        grouped[by1]["form_match"] = grouped[by1]["form_match"] or bool(
            form_code and payload.get("form_code") == form_code
        )
    ranked = []
    for by1, item in grouped.items():
        scores = sorted(item["scores"], reverse=True)
        mean_score = sum(scores[:3]) / min(len(scores), 3)
        score = 0.85 * scores[0] + 0.15 * mean_score
        if item["form_match"]:
            score += 0.03
        ranked.append((score, by1))
    ranked.sort(reverse=True)
    return [by1 for _, by1 in ranked[:50]]


def load_holdout(input_path: Path, holdout_from: str) -> pd.DataFrame:
    frame = pd.read_excel(
        input_path,
        usecols=["合同日期", "订单号", "产品编码", "品种", "规格", "材质分类", "英文描述"],
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
    frame["semantic_description"] = frame["raw_description"].map(
        standardize_edesc_for_by1
    )
    frame["by1"] = frame["品种"].map(normalize_code)
    return frame[
        (frame["date"] >= pd.Timestamp(holdout_from))
        & frame["raw_description"].ne("")
        & frame["semantic_description"].ne("")
        & frame["form_code"].ne("")
        & frame["by1"].ne("")
    ].copy()


def metrics(frame: pd.DataFrame, rankings: dict[tuple[str, str], list[str]]) -> dict:
    top5 = top50 = 0
    for row in frame.itertuples(index=False):
        candidates = rankings[(row.semantic_description, row.form_code)]
        if row.by1 in candidates[:5]:
            top5 += 1
        if row.by1 in candidates:
            top50 += 1
    return {
        "rows": len(frame),
        "vector_top5_accuracy": round(top5 / len(frame), 4) if len(frame) else 0,
        "candidate_recall_at_50": round(top50 / len(frame), 4) if len(frame) else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--historical-index", type=Path, required=True)
    parser.add_argument("--holdout-from", default="2024-09-01")
    parser.add_argument("--embedding-url", default="http://10.0.12.12:9997/v1/embeddings")
    parser.add_argument("--qdrant-url", default="http://10.0.8.238:6333")
    parser.add_argument("--child-collection", required=True)
    parser.add_argument("--child-limit", type=int, default=100)
    parser.add_argument("--only-history-misses", action="store_true")
    args = parser.parse_args()

    frame = load_holdout(args.input, args.holdout_from)
    historical = RecommendationService(args.historical_index)
    historical_payload = json.loads(args.historical_index.read_text(encoding="utf-8"))
    known_labels = {record["by1"] for record in historical_payload["records"]}
    history_miss = []
    for index, row in frame.iterrows():
        result = historical.recommend(
            row.raw_description,
            form_code=row.form_code,
            top_k=5,
        )
        if not result["by1_candidates"]:
            history_miss.append(index)
    missed = frame.loc[history_miss]
    evaluation_frame = missed if args.only_history_misses else frame

    unique_semantic = list(dict.fromkeys(evaluation_frame["semantic_description"]))
    vectors = embed(unique_semantic, args.embedding_url)
    pairs = list(
        dict.fromkeys(
            zip(
                evaluation_frame["semantic_description"],
                evaluation_frame["form_code"],
            )
        )
    )
    rankings = {}
    for semantic, form_code in pairs:
        response = post_json(
            f"{args.qdrant_url}/collections/{args.child_collection}/points/query",
            {
                "query": vectors[semantic],
                "limit": args.child_limit,
                "with_payload": True,
            },
        )
        rankings[(semantic, form_code)] = aggregate(
            response["result"]["points"], form_code
        )

    deduplicated = evaluation_frame.drop_duplicates(
        subset=["订单号", "产品编码", "英文描述"]
    )
    output = {
        "all_rows": metrics(evaluation_frame, rankings),
        "deduplicated": metrics(deduplicated, rankings),
        "known_label_rows": metrics(
            evaluation_frame[evaluation_frame["by1"].isin(known_labels)],
            rankings,
        ),
        "label_coverage": {
            "known": int(evaluation_frame["by1"].isin(known_labels).sum()),
            "unknown": int((~evaluation_frame["by1"].isin(known_labels)).sum()),
        },
        "queries": {
            "unique_semantic": len(unique_semantic),
            "unique_semantic_form_pairs": len(pairs),
            "child_limit": args.child_limit,
        },
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
