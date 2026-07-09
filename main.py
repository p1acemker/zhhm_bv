# -*- coding: utf-8 -*-
"""CLI entry point for product search maintenance tasks."""

import csv
import sys
from collections import defaultdict

from config import EMBEDDING_API_URL, EMBEDDING_DIM, EMBEDDING_MODEL, QDRANT_URL
from embedder import BGEEmbedder
from qdrant_store import QdrantVectorStore
from qdrant_client.models import PointStruct
from utils.id_utils import generate_child_id, generate_parent_id


def _print_usage() -> None:
    print("Usage:")
    print("  python main.py import <csv_file>  # import standardized CSV data")
    print("  python main.py clear              # clear all collection data")
    print("  python main.py rebuild            # rebuild collections")


class ProductSearchEngine:
    """Maintenance wrapper around the embedding service and Qdrant store."""

    def __init__(self) -> None:
        print("=" * 50)
        print("Initializing product search maintenance engine")
        print("=" * 50)

        print("\n[1/2] Checking embedding service...")
        self.embedder = BGEEmbedder()
        if self.embedder.health_check():
            print(f"  [OK] Embedding service is healthy ({EMBEDDING_MODEL}, {EMBEDDING_DIM} dims)")
        else:
            raise ConnectionError(f"Unable to reach embedding service: {EMBEDDING_API_URL}")

        print("\n[2/2] Connecting to Qdrant...")
        self.store = QdrantVectorStore()
        self.store.init_collections()
        print(f"  [OK] Qdrant connected ({QDRANT_URL})")

        print("\n" + "=" * 50)
        print("Maintenance engine initialized")
        print("=" * 50)

    def import_from_csv(self, csv_file: str) -> None:
        """Import standardized CSV data into Qdrant collections."""
        with open(csv_file, "r", encoding="utf-8") as file_obj:
            rows = list(csv.DictReader(file_obj))

        print(f"Loaded {len(rows)} rows")

        by1_edescs: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            by1_edescs[row["by1"]].append(row["standardized"])

        for by1 in list(by1_edescs.keys()):
            by1_edescs[by1] = list(set(by1_edescs[by1]))

        total = len(by1_edescs)
        total_edescs = sum(len(values) for values in by1_edescs.values())
        print(f"Unique by1 values: {total}, total edesc values: {total_edescs}")

        success = 0
        for index, (by1, edesc_list) in enumerate(sorted(by1_edescs.items())):
            parent_id = generate_parent_id(by1)

            try:
                embeddings = self.embedder.encode(edesc_list)
            except Exception as exc:
                print(f"  [{by1}] Encoding failed: {exc}")
                continue

            self.store.client.upsert(
                collection_name=self.store.parent_collection,
                points=[
                    PointStruct(
                        id=parent_id,
                        vector=[0.0] * 4,
                        payload={
                            "productName": by1,
                            "edesc_list": edesc_list,
                            "edesc_count": len(edesc_list),
                            "metadata": {"by1": by1, "edesc_count": len(edesc_list)},
                        },
                    )
                ],
            )

            child_points = []
            for child_index, embedding in enumerate(embeddings):
                vector = list(embedding) if not isinstance(embedding, list) else embedding
                child_id = generate_child_id(parent_id, child_index)
                child_points.append(
                    PointStruct(
                        id=child_id,
                        vector=vector,
                        payload={
                            "parent_id": parent_id,
                            "edesc_index": child_index,
                            "edesc_text": edesc_list[child_index],
                            "productName": by1,
                        },
                    )
                )

            if child_points:
                self.store.client.upsert(
                    collection_name=self.store.child_collection,
                    points=child_points,
                )

            success += 1
            if (index + 1) % 20 == 0:
                print(f"  Progress: {index + 1}/{total}")

        print(f"\nImport complete: {success} products")
        stats = self.store.get_stats()
        print(f"  Parent collection: {stats['parent_collection']['points_count']}")
        print(f"  Child collection: {stats['child_collection']['points_count']}")

    def clear_all(self) -> None:
        """Clear all Qdrant collection data."""
        self.store.clear_collections()
        print("Cleared all collection data")

    def rebuild_collections(self) -> None:
        """Delete and recreate the Qdrant collections."""
        self.store.rebuild_collections()
        print("Rebuilt collections")


if __name__ == "__main__":
    engine = ProductSearchEngine()

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "import" and len(sys.argv) > 2:
            engine.import_from_csv(sys.argv[2])
        elif command == "clear":
            engine.clear_all()
        elif command == "rebuild":
            engine.rebuild_collections()
        else:
            _print_usage()
    else:
        _print_usage()
