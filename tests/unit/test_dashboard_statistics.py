from stability_eval.dashboard._statistics import paired_transformation_tests


def test_exact_paired_test_and_holm_correction():
    rows = []
    outcomes = [
        ("success", "failure", "success"),
        ("success", "failure", "success"),
        ("success", "failure", "failure"),
        ("failure", "failure", "success"),
    ]
    for index, (original, typo, paraphrase) in enumerate(outcomes):
        issue_id = f"issue-{index}"
        rows.extend([
            {"issue_id": issue_id, "transformation_name": "original", "status": original},
            {"issue_id": issue_id, "transformation_name": "typo", "status": typo},
            {"issue_id": issue_id, "transformation_name": "paraphrase", "status": paraphrase},
        ])

    results, duplicates = paired_transformation_tests(rows)
    by_name = {result["transformation"]: result for result in results}
    assert duplicates == 0
    assert by_name["typo"]["n_pairs"] == 4
    assert by_name["typo"]["regressions"] == 3
    assert by_name["typo"]["improvements"] == 0
    assert by_name["typo"]["p_value"] == 0.25
    assert by_name["typo"]["p_holm"] == 0.5
    assert by_name["paraphrase"]["p_holm"] == 1.0


def test_excludes_errors_incomplete_pairs_and_duplicate_cells():
    rows = [
        {"issue_id": "a", "transformation_name": "original", "status": "success"},
        {"issue_id": "a", "transformation_name": "typo", "status": "failure"},
        {"issue_id": "b", "transformation_name": "original", "status": "success"},
        {"issue_id": "b", "transformation_name": "typo", "status": "error"},
        {"issue_id": "c", "transformation_name": "original", "status": "success"},
        {"issue_id": "c", "transformation_name": "typo", "status": "failure"},
        {"issue_id": "c", "transformation_name": "typo", "status": "success"},
    ]
    results, duplicates = paired_transformation_tests(rows)
    assert duplicates == 1
    assert results[0]["n_pairs"] == 1
    assert results[0]["p_value"] == 1.0
