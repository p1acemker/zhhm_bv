from tools.evaluate_by1_template_inference import evaluate_prediction, evaluate_rows


def fixture_rows(*items):
    return [
        {"contract_date": date, "by1": by1, "spec": spec}
        for date, by1, spec in items
    ]


def test_test_rows_do_not_contribute_to_template_statistics() -> None:
    result = evaluate_rows(
        fixture_rows(
            ("2024-01-01", "D71X", "D100"),
            ("2024-05-01", "D72X", "D100"),
        ),
        train_before="2024-04-28",
        validation_before="2024-09-01",
        mode="shadow",
    )

    assert result["training_rows"] == 1
    assert result["evaluation_rows"] == 1


def test_joint_accuracy_requires_by1_and_spec_to_be_correct() -> None:
    prediction = {"by1_candidates": [{"by1": "D71X"}], "inferred_spec": "D100"}
    truth = {"by1": "D71X", "spec": "D150"}

    result = evaluate_prediction(prediction, truth)

    assert result == {
        "by1_top1": True,
        "by1_top5": True,
        "spec_top1": False,
        "joint": False,
    }
