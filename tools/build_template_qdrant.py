"""Build and atomically activate a versioned Qdrant description-template collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _collection_name(version: str) -> str:
    safe_version = re.sub(r"[^a-zA-Z0-9]+", "_", version).strip("_").lower()
    if not safe_version:
        raise ValueError("template index version must contain letters or digits")
    return f"edesc_templates_{safe_version}"


def _point_id(template_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"edesc-template:{template_id}"))


def build_template_collection(
    index_path: Path | str,
    *,
    client: Any,
    embedder: Any,
    alias: str = "edesc_templates_current",
    recreate: bool = False,
) -> dict[str, Any]:
    """Create, populate, validate, and activate one physical collection."""
    index_path = Path(index_path)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    version = str(payload.get("version", "")).strip()
    templates = [
        item
        for item in payload.get("templates", [])
        if item.get("template_id") and item.get("semantic_text")
    ]
    if not templates:
        raise ValueError("template index contains no usable templates")
    physical = _collection_name(version)
    if client.collection_exists(physical):
        if not recreate:
            raise RuntimeError(f"collection already exists: {physical}")
        client.delete_collection(physical)

    vectors = embedder.encode([item["semantic_text"] for item in templates], batch_size=64)
    if len(vectors) != len(templates) or not vectors or not vectors[0]:
        raise RuntimeError("embedding service returned an invalid vector batch")
    vector_size = len(vectors[0])
    client.create_collection(
        collection_name=physical,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        metadata={"source": index_path.name, "dictionary_version": version},
    )
    for field in [
        "template_id",
        "valve_family",
        "product_role",
        "supported_by1",
        "form_codes",
        "dictionary_version",
    ]:
        client.create_payload_index(
            collection_name=physical,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    points = [
        PointStruct(
            id=_point_id(item["template_id"]),
            vector=vector,
            payload=item,
        )
        for item, vector in zip(templates, vectors)
    ]
    for start in range(0, len(points), 256):
        client.upsert(physical, points=points[start : start + 256], wait=True)
    collection = client.get_collection(physical)
    if collection.points_count != len(points):
        raise RuntimeError(
            f"Qdrant validation failed: expected {len(points)} points, got {collection.points_count}"
        )

    aliases = {item.alias_name for item in client.get_aliases().aliases}
    operations = []
    if alias in aliases:
        operations.append(
            DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias))
        )
    operations.append(
        CreateAliasOperation(
            create_alias=CreateAlias(collection_name=physical, alias_name=alias)
        )
    )
    client.update_collection_aliases(operations)
    return {
        "physical_collection": physical,
        "alias": alias,
        "points": collection.points_count,
        "dictionary_version": version,
    }


def main() -> None:
    from config import EDESC_TEMPLATE_ALIAS, QDRANT_URL
    from embedder import BGEEmbedder

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--qdrant-url", default=QDRANT_URL)
    parser.add_argument("--alias", default=EDESC_TEMPLATE_ALIAS)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    result = build_template_collection(
        args.index,
        client=QdrantClient(url=args.qdrant_url, timeout=120, check_compatibility=False),
        embedder=BGEEmbedder(timeout=120),
        alias=args.alias,
        recreate=args.recreate,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
