import numpy as np

from service.template_models import DescriptionViews, TemplateMember
from tools.build_by1_template_index import build_spec_profiles, build_template_clusters


def make_members(*items: tuple[str, str, str]) -> list[TemplateMember]:
    vectors = {
        "WAFER EPDM GEAR": np.array([1.0, 0.0, 0.0]),
        "GROOVED EPDM GEAR": np.array([0.0, 1.0, 0.0]),
    }
    result = []
    for index, (by1, structural, spec) in enumerate(items):
        result.append(
            TemplateMember(
                point_id=f"p{index}",
                by1=by1,
                views=DescriptionViews(
                    raw_description=structural,
                    normalized_description=structural,
                    structural_description=structural,
                    full_description=f"{structural} {spec}",
                    attributes={},
                ),
                structural_vector=vectors[structural],
                form_code="90F",
                spec=spec,
                parsed_size=spec.removeprefix("D") if spec.startswith("D") else "",
                support=1,
            )
        )
    return result


def test_same_by1_can_produce_two_structural_templates() -> None:
    members = make_members(
        ("D71XLV99", "WAFER EPDM GEAR", "D100"),
        ("D71XLV99", "WAFER EPDM GEAR", "D150"),
        ("D71XLV99", "GROOVED EPDM GEAR", "D100"),
    )

    clusters = build_template_clusters(members)

    assert len(clusters) == 2
    assert {cluster.by1 for cluster in clusters} == {"D71XLV99"}
    assert all(cluster.representative_point_id in cluster.member_ids for cluster in clusters)


def test_spec_profile_keeps_size_to_spec_mapping_and_nonstandard_values() -> None:
    members = make_members(
        ("D71XLV99", "WAFER EPDM GEAR", "D100"),
        ("D71XLV99", "WAFER EPDM GEAR", "D150"),
        ("D71XLV99", "WAFER EPDM GEAR", "N125X1220"),
    )
    clusters = build_template_clusters(members)

    profiles = build_spec_profiles(members, clusters)

    assert profiles[0]["size_to_spec_distribution"]["100"]["D100"] == 1
    assert "N125X1220" in profiles[0]["nonstandard_specs"]
