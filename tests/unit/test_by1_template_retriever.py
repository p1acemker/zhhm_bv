import json
from pathlib import Path

from scripts.edesc_standardizer import standardize_description_views
from service.by1_template_retriever import By1TemplateRetriever


class FakeEmbedder:
    def encode(self, text, batch_size=None):
        if text == "raise":
            raise RuntimeError("offline")
        return [1.0, 0.0]


def make_retriever(tmp_path: Path, *templates: dict) -> By1TemplateRetriever:
    path = tmp_path / "templates.json"
    path.write_text(json.dumps({"version": 1, "templates": templates}), encoding="utf-8")
    return By1TemplateRetriever(path, FakeEmbedder())


def hit(template_id: str, attributes: dict, **extra: object) -> dict:
    return {
        "template_id": template_id,
        "by1": extra.pop("by1", "D71X"),
        "attributes": attributes,
        "representative_vector": [1.0, 0.0],
        "representative_description": template_id,
        "supported_form_codes": extra.pop("supported_form_codes", ["90F"]),
        "spec_profiles": [],
        "support": extra.pop("support", 1),
        **extra,
    }


def test_explicit_connection_conflict_is_filtered(tmp_path: Path) -> None:
    retriever = make_retriever(
        tmp_path,
        hit("wrong", {"connection": "FLANGED"}),
        hit("right", {"connection": "WAFER"}),
    )
    views = standardize_description_views('DI WAFER BUTTERFLY VALVE 4"/DN100')

    result = retriever.retrieve(views, form_code="90F", top_k=5)

    assert [item["template_id"] for item in result] == ["right"]


def test_retrieval_error_returns_empty_candidates(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path, hit("one", {"connection": "WAFER"}))
    retriever.embedder = FakeEmbedder()
    views = standardize_description_views("DI WAFER BUTTERFLY VALVE DN100")
    retriever.embedder.encode = lambda text: (_ for _ in ()).throw(RuntimeError("offline"))

    assert retriever.retrieve(views, form_code="90F") == []


def test_form_match_and_spec_profile_are_returned(tmp_path: Path) -> None:
    retriever = make_retriever(
        tmp_path,
        hit(
            "one",
            {"connection": "WAFER"},
            supported_form_codes=["90F"],
            spec_profiles=[{"form_code": "90F", "spec_distribution": {"D100": 3}}],
        ),
    )
    views = standardize_description_views("DI WAFER BUTTERFLY VALVE DN100")

    result = retriever.retrieve(views, form_code="90F")

    assert result[0]["form_match"] is True
    assert result[0]["spec_profile"][0]["spec_distribution"]["D100"] == 3
