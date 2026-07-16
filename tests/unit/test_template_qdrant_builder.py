import json
from pathlib import Path

from qdrant_client import QdrantClient

from tools.build_template_qdrant import build_template_collection


class FakeEmbedder:
    def encode(self, texts, batch_size=None):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def test_build_template_collection_creates_version_and_current_alias(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "templates.json"
    index_path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "templates": [
                    {
                        "template_id": "BUT-1",
                        "valve_family": "butterfly",
                        "product_role": "valve",
                        "attributes": {"connection": "WAFER"},
                        "standardized_description": "DUCTILE IRON WAFER BUTTERFLY VALVE",
                        "supported_by1": ["D71X"],
                        "form_codes": ["90F"],
                        "support": 10,
                        "dictionary_version": "test-v1",
                        "semantic_text": "butterfly connection wafer",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client = QdrantClient(":memory:")

    result = build_template_collection(
        index_path,
        client=client,
        embedder=FakeEmbedder(),
        alias="edesc_templates_current",
    )

    assert result["points"] == 1
    assert client.collection_exists("edesc_templates_test_v1")
    aliases = {item.alias_name: item.collection_name for item in client.get_aliases().aliases}
    assert aliases["edesc_templates_current"] == "edesc_templates_test_v1"
