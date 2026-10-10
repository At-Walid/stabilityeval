"""Unit tests for the "localization success" outcome (stability_eval.metrics.outcome)."""
from __future__ import annotations

import pytest

from stability_eval.metrics.outcome import (
    EXCLUDED,
    FAILURE,
    SUCCESS,
    displayed_outcome,
    exclusion_counts,
    localize,
    outcome_value,
    recorded_outcomes,
    recorded_run_values,
    run_outcome,
)
from stability_eval.metrics.patch_similarity import file_overlap_jaccard, patch_files


def diff(*paths: str) -> str:
    return "\n".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new" for p in paths
    )


# ---------------------------------------------------------------------------
# patch_files / file_overlap_jaccard
# ---------------------------------------------------------------------------


def test_patch_files_lists_each_modified_file_once_in_order():
    assert patch_files(diff("pkg/a.py", "pkg/b.py", "pkg/a.py")) == ["pkg/a.py", "pkg/b.py"]


def test_patch_files_names_created_and_deleted_files():
    created = "--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+x"
    deleted = "--- a/pkg/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x"
    assert patch_files(created + "\n" + deleted) == ["pkg/new.py", "pkg/old.py"]


def test_patch_files_handles_crlf_and_missing_patches():
    assert patch_files(diff("pkg/a.py").replace("\n", "\r\n")) == ["pkg/a.py"]
    assert patch_files(None) == []
    assert patch_files("no diff here") == []


def test_file_overlap_jaccard():
    assert file_overlap_jaccard(["a", "b"], ["a"]) == 0.5
    assert file_overlap_jaccard(["a"], ["a"]) == 1.0
    assert file_overlap_jaccard(["a"], ["b"]) == 0.0
    assert file_overlap_jaccard([], []) == 0.0


# ---------------------------------------------------------------------------
# localize
# ---------------------------------------------------------------------------


def test_localization_matches_when_every_gold_file_is_modified():
    result = localize(diff("pkg/core.py", "pkg/util.py"), gold_patch=diff("pkg/core.py"))
    assert result.localization_match is True
    assert result.files_in_patch == ["pkg/core.py", "pkg/util.py"]
    assert result.files_in_gold == ["pkg/core.py"]
    assert result.file_overlap_jaccard == 0.5  # extra files lower the overlap, not the match


def test_partial_localization_does_not_match():
    result = localize(diff("pkg/core.py"), gold_patch=diff("pkg/core.py", "pkg/api.py"))
    assert result.localization_match is False
    assert result.file_overlap_jaccard == 0.5


def test_wrong_file_does_not_match():
    result = localize(diff("pkg/other.py"), gold_patch=diff("pkg/core.py"))
    assert result.localization_match is False
    assert result.file_overlap_jaccard == 0.0


def test_missing_patch_does_not_match():
    result = localize(None, gold_patch=diff("pkg/core.py"))
    assert result.files_in_patch == [] and result.localization_match is False


def test_localization_reads_the_final_patch_of_a_legacy_whole_reply():
    reply = f"Prose first.\n\n```diff\n{diff('pkg/core.py')}\n```\n\nDone."
    assert localize(reply, gold_patch=diff("pkg/core.py")).localization_match is True


# ---------------------------------------------------------------------------
# run_outcome / outcome_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "localization_match", "expected"),
    [
        ("success", True, SUCCESS),  # valid diff + right files
        ("success", False, FAILURE),  # valid diff, wrong or missing files
        ("no_patch", None, FAILURE),  # no valid diff extracted
        ("no_patch", False, FAILURE),
        ("failure", None, FAILURE),
        ("success", None, SUCCESS),  # no gold patch: valid diff only
    ],
)
def test_run_outcome(status, localization_match, expected):
    assert run_outcome(status, localization_match) == expected


@pytest.mark.parametrize(
    "status", ["timeout", "cost_exceeded", "error", "dry_run_skipped", "running"]
)
def test_runs_that_did_not_complete_normally_have_no_outcome(status):
    assert run_outcome(status, True) is None
    assert outcome_value({"status": status}) is None


def test_outcome_value_prefers_the_engine_outcome_over_the_status():
    assert outcome_value({"status": "success", "outcome": FAILURE}) == 0
    assert outcome_value({"status": "success"}) == 1
    assert outcome_value({"status": "no_patch"}) == 0
    assert outcome_value({"status": "success", "outcome": None}) is None


# ---------------------------------------------------------------------------
# Reading the engine's results back
# ---------------------------------------------------------------------------

ROWS = [
    ("run", "r1", "outcome", 1.0),
    ("run", "r2", "outcome", 0.0),
    ("run", "r1", "localization_match", 1.0),
    ("experiment", "e", "excluded_runs_status", 2.0),
    ("experiment", "e", "excluded_runs_quality_warning", 3.0),
    ("agent", "llm_baseline|verbosity_reduction", "excluded_quality_warning", 3.0),
    ("agent", "llm_baseline|reordering", "excluded_quality_warning", 0.0),
    ("experiment", "e", "excluded_runs_noop", 1.0),
    ("agent", "llm_baseline|reordering", "excluded_noop", 1.0),
    ("agent", "llm_baseline|verbosity_reduction", "excluded_noop", 0.0),
    ("run", "r1", "file_overlap_jaccard", 0.5),
]


def test_recorded_and_displayed_outcomes():
    recorded = recorded_outcomes(ROWS)
    assert recorded == {"r1": SUCCESS, "r2": FAILURE}
    assert displayed_outcome("r2", "success", recorded) == FAILURE  # not the status
    assert displayed_outcome("r3", "timeout", recorded) == EXCLUDED  # left out by the engine


def test_displayed_outcome_for_experiments_scored_before_run_outcomes_existed():
    assert displayed_outcome("r1", "success", {}) == SUCCESS
    assert displayed_outcome("r1", "no_patch", {}) == FAILURE
    assert displayed_outcome("r1", "timeout", {}) == EXCLUDED


def test_exclusion_counts():
    assert exclusion_counts(ROWS) == {
        "status": 2,
        "quality_warning": 3,
        "quality_warning_by_transformation": {"verbosity_reduction": 3, "reordering": 0},
        "noop": 1,
        "noop_by_transformation": {"reordering": 1, "verbosity_reduction": 0},
    }


def test_recorded_run_values():
    assert recorded_run_values(ROWS, "file_overlap_jaccard") == {"r1": 0.5}
    assert recorded_run_values(ROWS, "localization_match") == {"r1": 1.0}
