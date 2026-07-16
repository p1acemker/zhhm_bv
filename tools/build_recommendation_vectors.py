"""Build versioned Qdrant collections from the recommendation JSON index."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    EMBEDDING_DIM,
    QDRANT_URL,
    RECOMMENDATION_CHILD_COLLECTION,
    RECOMMENDATION_INDEX_PATH,
    RECOMMENDATION_PARENT_COLLECTION,
)
from embedder import BGEEmbedder
from utils.id_utils import generate_parent_id


def _child_id(record: dict) -> str:
    key = "|".join(
        [
            record.get("by1", ""),
            record.get("form_code", ""),
            record.get("spec", ""),
            record.get("description", ""),
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _batched(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def build_collections(
    index_path: Path,
    qdrant_url: str,
    parent_collection: str,
    child_collection: str,
    recreate: bool = False,
    embedding_batch_size: int = 64,
    upsert_batch_size: int = 256,
) -> dict:
    """Create parent/child collections and upload all indexed records."""
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    records = [
        record
        for record in payload.get("records", [])
        if record.get("by1") and record.get("semantic_description")
    ]
    client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False)
    existing = [
        name
        for name in [parent_collection, child_collection]
        if client.collection_exists(name)
    ]
    if existing and not recreate:
        raise RuntimeError(
            f"Collections already exist: {', '.join(existing)}; pass --recreate explicitly"
        )
    if recreate:
        for name in existing:
            client.delete_collection(name)

    client.create_collection(
        collection_name=parent_collection,
        vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        metadata={"source": index_path.name, "version": 1},
    )
    client.create_collection(
        collection_name=child_collection,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        metadata={"source": index_path.name, "version": 1},
    )
    for field in ["parent_id", "by1", "form_code", "spec", "spec_prefix"]:
        client.create_payload_index(
            collection_name=child_collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    parent_data = defaultdict(
        lambda: {
            "description_count": 0,
            "support": 0,
            "form_codes": set(),
            "specifications": set(),
            "materials": set(),
            "date_min": None,
            "date_max": None,
        }
    )
    for record in records:
        item = parent_data[record["by1"]]
        item["description_count"] += 1
        item["support"] += int(record.get("count", 1))
        if record.get("form_code"):
            item["form_codes"].add(record["form_code"])
        if record.get("spec"):
            item["specifications"].add(record["spec"])
        item["materials"].update(value for value, _ in record.get("materials", []))
        dates = [value for value in [record.get("date_min"), record.get("date_max")] if value]
        if dates:
            item["date_min"] = min([item["date_min"], *dates] if item["date_min"] else dates)
            item["date_max"] = max([item["date_max"], *dates] if item["date_max"] else dates)

    parent_points = []
    for by1, item in sorted(parent_data.items()):
        parent_points.append(
            PointStruct(
                id=generate_parent_id(f"recommendation:{by1}"),
                vector=[0.0, 0.0, 0.0, 0.0],
                payload={
                    "by1": by1,
                    "productName": by1,
                    "description_count": item["description_count"],
                    "support": item["support"],
                    "form_codes": sorted(item["form_codes"]),
                    "specifications": sorted(item["specifications"]),
                    "materials": sorted(item["materials"]),
                    "date_min": item["date_min"],
                    "date_max": item["date_max"],
                    "index_version": 1,
                },
            )
        )
    for batch in _batched(parent_points, upsert_batch_size):
        client.upsert(parent_collection, points=batch, wait=True)

    embedder = BGEEmbedder(timeout=120)
    texts = [record["semantic_description"] for record in records]
    vectors = embedder.encode(texts, batch_size=embedding_batch_size)
    child_points = []
    for record, vector in zip(records, vectors):
        parent_id = generate_parent_id(f"recommendation:{record['by1']}")
        child_points.append(
            PointStruct(
                id=_child_id(record),
                vector=vector,
                payload={
                    "parent_id": parent_id,
                    "by1": record["by1"],
                    "productName": record["by1"],
                    "description": record["description"],
                    "semantic_description": record["semantic_description"],
                    "example": record.get("example", ""),
                    "form_code": record.get("form_code", ""),
                    "spec": record.get("spec", ""),
                    "spec_prefix": record.get("spec_prefix", ""),
                    "spec_size": record.get("spec_size", ""),
                    "materials": [value for value, _ in record.get("materials", [])],
                    "surfaces": [value for value, _ in record.get("surfaces", [])],
                    "support": int(record.get("count", 1)),
                    "date_min": record.get("date_min"),
                    "date_max": record.get("date_max"),
                    "customer_hashes": [value for value, _ in record.get("customers", [])],
                    "index_version": 1,
                },
            )
        )
    for batch in _batched(child_points, upsert_batch_size):
        client.upsert(child_collection, points=batch, wait=True)

    parent_info = client.get_collection(parent_collection)
    child_info = client.get_collection(child_collection)
    return {
        "parent_collection": parent_collection,
        "child_collection": child_collection,
        "parents": parent_info.points_count,
        "children": child_info.points_count,
        "source_records": len(records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path(RECOMMENDATION_INDEX_PATH))
    parser.add_argument("--qdrant-url", default=QDRANT_URL)
    parser.add_argument("--parent-collection", default=RECOMMENDATION_PARENT_COLLECTION)
    parser.add_argument("--child-collection", default=RECOMMENDATION_CHILD_COLLECTION)
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--upsert-batch-size", type=int, default=256)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    result = build_collections(
        index_path=args.index,
        qdrant_url=args.qdrant_url,
        parent_collection=args.parent_collection,
        child_collection=args.child_collection,
        recreate=args.recreate,
        embedding_batch_size=args.embedding_batch_size,
        upsert_batch_size=args.upsert_batch_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
