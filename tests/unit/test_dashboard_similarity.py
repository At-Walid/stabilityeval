"""The changed-line similarity views of the dashboard (stableagent.dashboard._similarity and
the issue detail helpers of _results): built from the engine's metric rows, never recomputed."""
from __future__ import annotations

import json

import pandas as pd

from stableagent.dashboard._results import (
    _TLABELS,
    comparison_runs,
    control_similarity,
    detail_summary,
)
from stableagent.dashboard._similarity import (
    CONTROL_LABEL,
    default_index,
    patch_lines,
    side_by_side_html,
    side_by_side_rows,
    similarity_dot_plot,
    similarity_rows,
    similarity_table,
)


def metric(name, key, value, **meta):
    return {"metric_name": name, "scope": "agent", "scope_key": key, "metric_value": value,
            "metric_metadata": json.dumps(meta) if meta else None}


def metrics_df():
    return pd.DataFrame([
        metric("control_changed_line_similarity", "a", 0.8, n=3, ci_low=0.6, ci_high=0.95,
               per_issue={"i1": 1.0, "i2": 0.6, "i3": 0.8}),
        metric("changed_line_similarity_mean", "a|paraphrase", 0.5, n=3, ci_low=0.2, ci_high=0.8,
               per_issue={"i1": 0.5, "i2": 0.2, "i3": 0.8}),
        metric("changed_line_similarity_mean", "a|reordering", 0.3, n=2, ci_low=0.1, ci_high=0.5,
               per_issue={"i1": 0.1, "i2": 0.5}),
        metric("changed_line_similarity_vs_control", "a|paraphrase", -0.3, n_pairs=3,
               ci_low=-0.5, ci_high=-0.1, wilcoxon_p=0.25),
        metric("changed_line_similarity_mean", "other|paraphrase", 0.9, n=1, ci_low=0.9,
               ci_high=0.9, per_issue={"i1": 0.9}),
        metric("transformation_sensitivity", "a|paraphrase", 0.0),
    ])


def test_rows_put_the_control_first_then_the_least_similar_transformation():
    rows = similarity_rows(metrics_df(), "a", _TLABELS)
    assert [row["label"] for row in rows] == [CONTROL_LABEL, "Reordering", "Paraphrase"]
    control, reordering, paraphrase = rows
    assert control["is_control"] and control["per_issue"] == {"i1": 1.0, "i2": 0.6, "i3": 0.8}
    assert (paraphrase["delta"], paraphrase["wilcoxon_p"], paraphrase["n_pairs"]) == (-0.3, 0.25, 3)
    assert reordering["delta"] is None  # no comparison stored


def test_no_rows_without_similarity_metrics_or_their_metadata():
    old = pd.DataFrame([metric("flip_rate", "a|paraphrase", 0.0)])
    assert similarity_rows(old, "a", _TLABELS) == []
    assert similarity_rows(metrics_df().drop(columns="metric_metadata"), "a", _TLABELS) == []


def test_table_shows_means_differences_and_exploratory_p_values():
    table = similarity_table(similarity_rows(metrics_df(), "a", _TLABELS))
    assert list(table.columns) == [
        "Variant", "Issues", "Mean [95% CI]", "Δ vs repeat [95% CI]",
        "Wilcoxon p (exploratory)",
    ]
    assert table.iloc[0].tolist() == [CONTROL_LABEL, 3, "0.800 [0.600, 0.950]", "reference", "—"]
    assert table.iloc[2].tolist() == [
        "Paraphrase", 3, "0.500 [0.200, 0.800]", "-0.300 [-0.500, -0.100]", "0.2500"
    ]


def test_dot_plot_has_issue_dots_a_mean_with_ci_per_row_and_the_control_line():
    rows = similarity_rows(metrics_df(), "a", _TLABELS)
    fig = similarity_dot_plot(rows)
    assert len(fig.data) == 2 * len(rows)  # faint issue dots + mean with its CI, per row
    dots, mean = fig.data[0], fig.data[1]  # the control row comes first
    assert sorted(dots.x) == [0.6, 0.8, 1.0] and dots.marker.opacity < 0.5
    assert mean.x == (0.8,) and list(mean.error_x.array) == [0.95 - 0.8]
    assert list(fig.layout.yaxis.ticktext) == [CONTROL_LABEL, "Reordering", "Paraphrase"]
    (line,) = fig.layout.shapes
    assert (line.x0, line.line.dash) == (0.8, "dash")


def test_dot_plot_without_control_has_no_reference_line():
    rows = [row for row in similarity_rows(metrics_df(), "a", _TLABELS) if not row["is_control"]]
    assert similarity_dot_plot(rows).layout.shapes == ()


PATCH_A = "--- a/m.py\n+++ b/m.py\n@@ -1,3 +1,3 @@\n ctx\n-x = 1\n+x = 2\n end\n"
PATCH_B = "--- a/m.py\n+++ b/m.py\n@@ -5,3 +5,4 @@\n ctx\n-x = 1\n+x = 3\n+y = <b>\n end\n"


def test_side_by_side_rows_align_equal_lines_and_mark_changed_characters():
    rows = side_by_side_rows(patch_lines(PATCH_A), patch_lines(PATCH_B))
    tags = [row[0] for row in rows]
    assert tags == ["equal", "equal", "replace", "equal", "equal", "replace", "insert", "equal"]
    _tag, _ln, left, _rn, right = rows[5]
    assert left == '+x = <mark style="background:rgba(220, 38, 38, 0.32);color:inherit">2</mark>'
    assert "3</mark>" in right
    assert rows[6][4] == "+y = &lt;b&gt;"  # escaped, never rendered as HTML


def test_changed_lines_only_compares_what_the_similarity_compares():
    assert patch_lines(PATCH_B, changed_only=True) == ["-x = 1", "+x = 3", "+y = <b>"]
    assert patch_lines(None) == []


def test_side_by_side_html_titles_and_empty_patches():
    page = side_by_side_html(patch_lines(PATCH_A), [], "Original issue — patch", "Reordering")
    assert "Original issue — patch" in page and "Reordering" in page
    assert "(both patches are empty)" in side_by_side_html([], [], "a", "b")


def runs_frame():
    def run(run_id, transformation, *, original=False, control=False, index=0, patch="p"):
        return {"run_id": run_id, "issue_id": "psf__requests-2317", "is_original": original,
                "control_repeat": control, "run_index": index, "patch": patch,
                "transformation_name": transformation, "status": "success",
                "outcome": "success"}
    return pd.DataFrame([
        run("o", "original", original=True),
        run("r", "reordering"),
        run("p", "paraphrase"),
        run("c", "original", original=True, control=True, index=1),
    ])


def test_comparison_runs_offer_every_variant_then_the_repeat_of_the_original():
    candidates = comparison_runs(runs_frame(), "psf__requests-2317")
    assert list(candidates) == ["Reordering", "Paraphrase", CONTROL_LABEL]
    assert candidates[CONTROL_LABEL]["run_id"] == "c"
    assert comparison_runs(runs_frame(), None) == {}
    assert default_index(list(candidates), _TLABELS["reordering"]) == 0
    assert default_index(list(candidates), "Missing") == 0


def test_detail_summary_gives_both_outcomes_and_the_similarity_against_the_repeat():
    frame = runs_frame()
    similarity = {"r": 0.42, "c": 0.8}
    control = control_similarity(frame, "psf__requests-2317", similarity)
    assert control == 0.8
    line = detail_summary("Reordering", "success", frame.iloc[1], similarity, control)
    assert line == (
        "Original run: **success** · Reordering run: **success** · changed-line similarity "
        "**0.420** (repeat of the original on this issue: 0.800)"
    )
    assert "repeat of the original on this issue" not in detail_summary(
        CONTROL_LABEL, "success", frame.iloc[3], similarity, control
    )
