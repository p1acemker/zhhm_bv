from tools.evaluate_description_design import evaluate_review_rows


def test_evaluate_review_rows_reports_approved_and_corrected_metrics() -> None:
    rows = [
        {
            "approved": "yes",
            "predicted_family": "butterfly",
            "predicted_role": "valve",
            "predicted_description": "A",
            "template_id": "BUT-1",
            "body_material": "DUCTILE IRON",
            "inferred_fields": "body_material",
        },
        {
            "approved": "no",
            "predicted_family": "butterfly",
            "corrected_family": "check",
            "predicted_role": "valve",
            "corrected_role": "valve",
            "predicted_description": "B",
            "corrected_description": "C",
            "template_id": "BUT-2",
            "corrected_template_id": "CHE-2",
            "body_material": "DUCTILE IRON",
            "corrected_body_material": "CAST IRON",
            "inferred_fields": "body_material",
        },
    ]

    result = evaluate_review_rows(rows)

    assert result["reviewed_rows"] == 2
    assert result["description_approval_rate"] == 0.5
    assert result["family_accuracy"] == 0.5
    assert result["role_accuracy"] == 1.0
    assert result["critical_field_accuracy"] == 0.5
    assert result["autofill_accuracy"] == 0.5
