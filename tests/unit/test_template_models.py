from service.template_models import AttributeEvidence, DescriptionViews


def test_attribute_evidence_is_immutable_and_serializable() -> None:
    evidence = AttributeEvidence(
        value="EPDM",
        source="query",
        confidence=1.0,
        evidence="EPDM SEAT",
    )

    assert evidence.value == "EPDM"
    assert evidence.source == "query"
    assert evidence.confidence == 1.0


def test_description_views_keep_raw_and_distinct_text_views() -> None:
    views = DescriptionViews(
        raw_description="raw",
        normalized_description="RAW",
        structural_description="STRUCTURAL",
        full_description="FULL",
        attributes={},
    )

    assert views.raw_description == "raw"
    assert views.structural_description != views.full_description
