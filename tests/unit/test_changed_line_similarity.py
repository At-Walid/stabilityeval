"""Changed-line similarity (stability_eval.metrics.changed_line_similarity): the per-pair value,
the per-transformation summaries, the control (noise floor) and the paired comparison."""
from __future__ import annotations

import pytest

from stability_eval.metrics.changed_line_similarity import (
    EXPLORATORY,
    ChangedLineSimilarity,
    changed_line_similarity,
    changed_lines,
)
from stability_eval.metrics.statistics import bootstrap_mean_ci, wilcoxon_signed_rank


def patch(*changes: str, path: str = "pkg/mod.py", start: int = 10) -> str:
    """A one-hunk diff whose changed lines are ``changes`` (each starting with + or -)."""
    return (
        f"--- a/{path}\n+++ b/{path}\n@@ -{start},3 +{start},3 @@ def f():\n"
        "     context = 1\n" + "".join(f"{line}\n" for line in changes) + "     return context\n"
    )


def test_changed_lines_keep_plus_minus_lines_and_drop_headers_and_context():
    text = patch("-    x = 1", "+    x = 2")
    assert changed_lines(text) == ["-    x = 1", "+    x = 2"]
    assert changed_lines(None) == []
    assert changed_lines("--- a/f\r\n+++ b/f\r\n@@ -1 +1 @@\r\n-a\r\n+b\r\n") == ["-a", "+b"]


def test_identical_edit_at_another_position_is_identical():
    a = patch("-    x = 1", "+    x = 2", start=10)
    b = patch("-    x = 1", "+    x = 2", start=250)
    assert changed_line_similarity(a, b) == 1.0


def test_similarity_is_the_sequencematcher_ratio_over_the_characters_of_the_changed_lines():
    a = patch("-    x = 1", "+    x = 2")
    b = patch("-    x = 1", "+    x = 3")
    # the joined changed lines differ in their last character only: 20 matching of 21 each
    assert changed_line_similarity(a, b) == pytest.approx(2 * 20 / 42)
    assert changed_line_similarity(patch("+a"), patch("-b")) == 0.0


def test_runs_without_a_diff():
    assert changed_line_similarity(None, None) == 1.0
    assert changed_line_similarity(patch("+    x = 2"), None) == 0.0


def test_a_prefix_is_part_of_the_line():
    # a removed line is not the same change as the same line added: 9 of 10 characters match
    assert changed_line_similarity(patch("-    x = 1"), patch("+    x = 1")) == pytest.approx(0.9)


def row(run_id, issue, transformation, value_patch, *, original=False, outcome="success"):
    return {
        "run_id": run_id, "agent_name": "agent", "issue_id": issue,
        "transformation_name": "original" if original else transformation,
        "is_original": original, "patch": value_patch, "outcome": outcome,
    }


ORIG = {
    "i1": patch("-a", "+b"),
    "i2": patch("-c", "+d", "+e"),
    "i3": patch("+f"),
}


def dataset():
    run_data = [row(f"o-{i}", i, None, p, original=True) for i, p in ORIG.items()]
    run_data += [
        row("p-i1", "i1", "paraphrase", patch("-a", "+x")),          # 0.8: 4 of 5 chars
        row("p-i2", "i2", "paraphrase", patch("-c", "+d", "+e")),     # 1.0
        row("p-i3", "i3", "paraphrase", patch("+g")),                 # 0.5: "+" of 2 chars
        row("r-i1", "i1", "reordering", None, outcome="failure"),    # no_patch: 0.0
    ]
    control = [
        row("c-i1", "i1", "original", patch("-a", "+b"), original=True),  # 1.0
        row("c-i2", "i2", "original", patch("-c", "+d"), original=True),  # 10/13
        row("c-i3", "i3", "original", patch("+f"), original=True),        # 1.0
    ]
    return run_data, control


def test_per_run_values_and_their_original():
    run_data, control = dataset()
    results = ChangedLineSimilarity().compute(run_data, control)
    assert results.per_run["p-i1"] == (pytest.approx(0.8), "o-i1")
    assert results.per_run["r-i1"] == (0.0, "o-i1")
    assert results.per_run["c-i2"] == (pytest.approx(10 / 13), "o-i2")
    assert "o-i1" not in results.per_run  # the original is the reference, not compared


def test_per_transformation_summary_with_bootstrap_ci():
    run_data, control = dataset()
    summary = ChangedLineSimilarity().compute(run_data, control).per_transformation[
        ("agent", "paraphrase")
    ]
    assert summary.per_issue == {"i1": pytest.approx(0.8), "i2": 1.0, "i3": 0.5}
    assert summary.mean == pytest.approx(2.3 / 3)
    assert (summary.ci_low, summary.ci_high) == pytest.approx(bootstrap_mean_ci([0.8, 1.0, 0.5]))
    assert summary.metadata()["n"] == 3


def test_control_is_the_noise_floor_and_the_comparison_is_paired_by_issue():
    run_data, control = dataset()
    results = ChangedLineSimilarity().compute(run_data, control)
    assert results.control["agent"].mean == pytest.approx((1.0 + 10 / 13 + 1.0) / 3)
    comparison = results.versus_control[("agent", "paraphrase")]
    differences = [0.8 - 1.0, 1.0 - 10 / 13, 0.5 - 1.0]
    assert comparison.per_issue == {
        issue: pytest.approx(d) for issue, d in zip(["i1", "i2", "i3"], differences)
    }
    assert comparison.mean_difference == pytest.approx(sum(differences) / 3)
    assert comparison.wilcoxon == wilcoxon_signed_rank(list(comparison.per_issue.values()))
    meta = comparison.metadata()
    assert meta["analysis"] == EXPLORATORY
    assert meta["n_pairs"] == 3 and meta["resamples"] == 5000 and meta["seed"] == 42
    # reordering exists for i1 only: paired on that issue alone
    assert results.versus_control[("agent", "reordering")].n_pairs == 1


def test_excluded_runs_and_issues_without_a_scored_original_are_not_compared():
    run_data, control = dataset()
    run_data = [r for r in run_data if r["run_id"] != "o-i3"]  # i3's original excluded
    run_data.append(row("t-i1", "i1", "typo_injection", patch("-a", "+b"), outcome="excluded"))
    results = ChangedLineSimilarity().compute(run_data, control)
    assert "p-i3" not in results.per_run and "c-i3" not in results.per_run
    assert "t-i1" not in results.per_run
    assert ("agent", "typo_injection") not in results.per_transformation
    assert results.per_transformation[("agent", "paraphrase")].n == 2


def test_without_control_runs_there_is_no_comparison():
    run_data, _ = dataset()
    results = ChangedLineSimilarity().compute(run_data, [])
    assert results.control == {} and results.versus_control == {}
    assert ("agent", "paraphrase") in results.per_transformation
