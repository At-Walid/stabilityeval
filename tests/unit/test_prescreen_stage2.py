"""Unit tests for the decision logic in scripts/prescreen_stage2.py (no network, no real DB)."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prescreen_stage2.py"


def _load_script():
    existing = sys.modules.get("prescreen_stage2")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("prescreen_stage2", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["prescreen_stage2"] = module
    spec.loader.exec_module(module)
    return module


ps = _load_script()

PATCH_A = (
    "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n"
    " def f(x):\n-    return x + 1\n+    return x + 2\n"
)
PATCH_B = (
    "--- a/bar.py\n+++ b/bar.py\n@@ -5,2 +5,2 @@\n"
    " class Bar:\n-    flag = False\n+    flag = True\n"
)


def view(status="success", patch=PATCH_A):
    return ps.RunView(status=status, patch=patch)


def result(issue_id, repo, divergence):
    """A complete, flip-free result whose divergence equals `divergence`."""
    c1 = 1.0 - divergence
    return ps.CandidateResult(
        issue_id=issue_id,
        repo=repo,
        outcome_original="success",
        outcome_verbosity="success",
        outcome_reorder="success",
        c1_verbosity=c1,
        c1_reorder=c1,
        flip_any=False,
        divergence=divergence,
    )


def incomplete(issue_id, repo="org/x"):
    return ps.CandidateResult(issue_id=issue_id, repo=repo, outcome_verbosity="error")


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


def test_identical_patches_give_zero_divergence():
    scored = ps.score_candidate(view(), view(), view())
    assert scored["flip_any"] is False
    assert scored["c1_verbosity"] == 1.0 and scored["c1_reorder"] == 1.0
    assert scored["divergence"] == 0.0


def test_divergence_is_one_minus_mean_c1_when_no_flip():
    scored = ps.score_candidate(view(), view(patch=PATCH_B), view())
    expected = 1.0 - (scored["c1_verbosity"] + scored["c1_reorder"]) / 2.0
    assert scored["flip_any"] is False
    assert scored["c1_verbosity"] < 1.0 and scored["c1_reorder"] == 1.0
    assert scored["divergence"] == pytest.approx(expected)


@pytest.mark.parametrize("flipped", ["verbosity", "reorder"])
def test_any_outcome_flip_forces_divergence_one(flipped):
    # Same patch text everywhere: C1 alone would say "perfectly stable"; the flip must win.
    variants = {"verbosity": view(), "reorder": view()}
    variants[flipped] = view(status="failure", patch=PATCH_A)
    scored = ps.score_candidate(view(), variants["verbosity"], variants["reorder"])
    assert scored["flip_any"] is True
    assert scored["divergence"] == 1.0


def test_timeout_is_a_distinct_failure_mode_and_counts_as_a_flip():
    scored = ps.score_candidate(view(), view(status="timeout", patch=None), view())
    assert scored["flip_any"] is True and scored["divergence"] == 1.0


def test_no_patch_is_a_scored_failure_not_missing_data():
    scored = ps.score_candidate(view(), view(status="no_patch", patch=None), view())
    assert scored["flip_any"] is True and scored["divergence"] == 1.0


def test_same_non_success_outcomes_do_not_flip():
    failing = view(status="failure", patch=None)
    scored = ps.score_candidate(failing, failing, failing)
    assert scored["flip_any"] is False
    assert scored["c1_verbosity"] == 1.0  # two empty patches are identical
    assert scored["divergence"] == 0.0


@pytest.mark.parametrize("bad_status", ["error", "cost_exceeded", "running", "dry_run_skipped"])
def test_infrastructure_statuses_make_the_candidate_incomplete(bad_status):
    scored = ps.score_candidate(view(), view(status=bad_status, patch=None), view())
    assert scored == {
        "c1_verbosity": None,
        "c1_reorder": None,
        "flip_any": None,
        "divergence": None,
    }


def test_missing_run_makes_the_candidate_incomplete():
    assert ps.score_candidate(view(), None, view())["divergence"] is None
    assert ps.score_candidate(None, view(), view())["divergence"] is None


def _reply(prose: str, *diffs: str) -> str:
    """A reply the way the baseline writes it: prose first, then one fenced diff per draft."""
    return (
        prose + "\n\n<br>\n\n" + "\n\nLet me try again:\n\n".join(f"```diff\n{d}```" for d in diffs)
    )


def test_c1_compares_final_patches_not_prose_or_superseded_drafts():
    # Different prose and a different first draft of the SAME file (foo.py), but the same final
    # patch -> perfectly stable.
    first_draft = PATCH_A.replace("x + 2", "x + 3")
    original = view(patch=_reply("Looking at the issue, it is in f.", first_draft, PATCH_A))
    variant = view(patch=_reply("The bug is clearly here, so:", PATCH_A))
    scored = ps.score_candidate(original, variant, variant)
    assert scored["c1_verbosity"] == 1.0 and scored["c1_reorder"] == 1.0
    assert scored["divergence"] == 0.0


def test_a_different_final_patch_is_still_detected_behind_identical_prose():
    original = view(patch=_reply("Same prose.", PATCH_A))
    variant = view(patch=_reply("Same prose.", PATCH_B))
    scored = ps.score_candidate(original, variant, original)
    assert scored["c1_verbosity"] < 0.6 and scored["divergence"] > 0.2


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


ISSUE = "Title line\nsecond line\nthird line\n\nParagraph two a\nParagraph two b\nParagraph two c"


def test_adjacency_is_full_for_identical_text_and_crlf():
    assert ps.adjacency_preserved(ISSUE, ISSUE) == 1.0
    assert ps.adjacency_preserved(ISSUE, ISSUE.replace("\n", "\r\n")) == 1.0


def test_adjacency_stays_high_when_whole_paragraphs_swap():
    first, second = ISSUE.split("\n\n")
    assert ps.adjacency_preserved(ISSUE, second + "\n\n" + first) >= 0.8


def test_adjacency_collapses_when_lines_are_shuffled():
    lines = ISSUE.replace("\n\n", "\n").split("\n")
    assert ps.adjacency_preserved(ISSUE, "\n".join(reversed(lines))) == 0.0


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------


def test_ordering_is_divergence_desc_ties_by_lower_mean_c1_then_id_incomplete_last():
    low = result("b-low", "org/a", 0.2)
    high = result("c-high", "org/a", 0.9)
    tie_a = result("a-tie", "org/a", 0.5)
    tie_b = result("b-tie", "org/a", 0.5)
    flipped = ps.CandidateResult(
        issue_id="d-flip",
        repo="org/a",
        outcome_original="success",
        outcome_verbosity="failure",
        outcome_reorder="success",
        c1_verbosity=0.1,
        c1_reorder=0.1,
        flip_any=True,
        divergence=1.0,
    )
    flipped_high_c1 = ps.CandidateResult(
        issue_id="e-flip",
        repo="org/a",
        outcome_original="success",
        outcome_verbosity="failure",
        outcome_reorder="success",
        c1_verbosity=0.9,
        c1_reorder=0.9,
        flip_any=True,
        divergence=1.0,
    )
    ordered = ps.ordered_for_output(
        [
            low,
            tie_b,
            incomplete("z-inc"),
            high,
            flipped_high_c1,
            tie_a,
            flipped,
            incomplete("y-inc"),
        ]
    )
    assert [r.issue_id for r in ordered] == [
        "d-flip",
        "e-flip",  # divergence 1.0; lower mean C1 first
        "c-high",
        "a-tie",
        "b-tie",
        "b-low",
        "y-inc",
        "z-inc",  # incomplete last, by id
    ]


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def spread_results(n=20):
    """r01 (most divergent) .. r20 (most stable), repos cycling over 8 organisations."""
    return [result(f"r{i:02d}", f"org/repo{i % 8}", 1.0 - i * 0.04) for i in range(1, n + 1)]


def test_plain_top_and_bottom_split_when_constraints_hold():
    selection = ps.recommend_selection(spread_results())
    assert [r.issue_id for r in selection.top] == [f"r{i:02d}" for i in range(1, 7)]
    assert [r.issue_id for r in selection.stable] == [
        "r20",
        "r19",
        "r18",
        "r17",
    ]  # most stable first
    assert selection.ids == [f"r{i:02d}" for i in range(1, 7)] + ["r20", "r19", "r18", "r17"]
    assert selection.constraints_ok and not selection.notes
    assert selection.n_repos >= 5 and selection.max_per_repo <= 4


def test_per_repo_cap_swaps_out_the_lowest_ranked_offender_first():
    results = []
    for rank in range(1, 21):
        repo = (
            "org/A"
            if rank <= 5
            else "org/B"
            if rank == 6
            else "org/C"
            if rank == 7
            else f"org/D{rank % 5}"
        )
        results.append(result(f"r{rank:02d}", repo, 1.0 - rank * 0.04))
    selection = ps.recommend_selection(results)

    top_ids = [r.issue_id for r in selection.top]
    assert top_ids == [
        "r01",
        "r02",
        "r03",
        "r04",
        "r06",
        "r07",
    ]  # r05 (5th repo-A issue) swapped out
    assert sum(1 for r in selection.top + selection.stable if r.repo == "org/A") == 4
    assert selection.constraints_ok
    assert any("repo constraints changed" in note for note in selection.notes)


def test_min_repos_is_repaired_in_the_stable_group_before_touching_the_top_group():
    repos = {
        1: "A",
        2: "B",
        3: "A",
        4: "B",
        5: "A",
        6: "B",
        20: "C",
        19: "D",
        18: "C",
        17: "D",
        16: "E",
    }
    results = [
        result(f"r{rank:02d}", f"org/{repos.get(rank, 'F')}", 1.0 - rank * 0.04)
        for rank in range(1, 21)
    ]
    selection = ps.recommend_selection(results)

    assert [r.issue_id for r in selection.top] == [
        f"r{i:02d}" for i in range(1, 7)
    ]  # top untouched
    assert [r.issue_id for r in selection.stable] == [
        "r20",
        "r19",
        "r18",
        "r16",
    ]  # 4th control swapped
    assert selection.n_repos == 5 and selection.constraints_ok


def test_infeasible_constraints_fall_back_to_the_plain_split_and_say_so():
    results = [
        result(f"r{i:02d}", f"org/repo{i % 3}", 1.0 - i * 0.04) for i in range(1, 21)
    ]  # 3 repos only
    selection = ps.recommend_selection(results)

    assert selection.ids == [f"r{i:02d}" for i in range(1, 7)] + ["r20", "r19", "r18", "r17"]
    assert not selection.constraints_ok
    assert any("no selection satisfies" in note for note in selection.notes)


def test_incomplete_candidates_are_never_selected_and_short_pools_are_flagged():
    results = spread_results(7) + [incomplete("bad1"), incomplete("bad2"), incomplete("bad3")]
    selection = ps.recommend_selection(results)

    assert len(selection.ids) == 7
    assert not {"bad1", "bad2", "bad3"} & set(selection.ids)
    assert any("only 7 complete candidates" in note for note in selection.notes)


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


def test_worst_case_budget_is_bounded_for_the_real_candidate_set():
    candidates = ps.load_candidates(ps.CANDIDATES_PATH)
    budget = ps.estimate_budget(candidates)
    assert len(candidates) == 20
    assert budget.run_worst_case_max <= ps.PER_RUN_CAP_USD
    assert budget.total_worst_case <= ps.TOTAL_LIMIT_USD


def test_budget_grows_with_max_tokens():
    candidates = [ps.Candidate("x", "org/x", "a" * 1000)]
    assert ps.estimate_budget(candidates, max_tokens=4096).run_worst_case_max < ps.PER_RUN_CAP_USD
    assert ps.estimate_budget(candidates, max_tokens=64000).run_worst_case_max > ps.PER_RUN_CAP_USD


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_has_exact_columns_sorted_by_divergence_with_incomplete_last(tmp_path):
    results = [result("low", "org/a", 0.1), incomplete("inc"), result("high", "org/b", 0.8)]
    out = tmp_path / "stage2_results.csv"
    ps.write_results_csv(results, out)

    with open(out, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert reader.fieldnames == [
        "issue_id",
        "repo",
        "outcome_original",
        "outcome_verbosity",
        "outcome_reorder",
        "c1_verbosity",
        "c1_reorder",
        "divergence",
    ]
    assert [r["issue_id"] for r in rows] == ["high", "low", "inc"]
    assert rows[0]["divergence"] == "0.8000" and rows[0]["c1_verbosity"] == "0.2000"
    assert rows[2]["outcome_verbosity"] == "error"
    assert rows[2]["divergence"] == "" and rows[2]["c1_verbosity"] == ""


# ---------------------------------------------------------------------------
# analyze(): database -> CandidateResult
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    engine = ps.build_engine(f"sqlite:///{tmp_path / 'analysis.db'}")
    ps.create_all(engine)
    session = ps.sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _add_issue_with_runs(
    db,
    experiment,
    issue_id,
    text,
    runs,
    verbosity_text="short",
    notes="ok",
    quality_warning=False,
    reordered=None,
    reorder_notes="n/a",
    stop_reasons=None,
):
    """runs: {"original"|"verbosity_reduction"|"reordering": (status, patch)}.

    reorder_notes: the reordering transformation's own record of how it split the text.
    stop_reasons: optional {label: stop_reason} stored as the run's adapter metadata.
    """
    stop_reasons = stop_reasons or {}
    issue = ps.Issue(
        external_id=issue_id, repo_name="org/x", source="swebench_lite", issue_text=text
    )
    db.add(issue)
    db.flush()
    texts = {
        "original": text,
        "verbosity_reduction": verbosity_text,
        "reordering": reordered or text,
    }
    for label, (status, patch) in runs.items():
        ti = ps.TransformedIssue(
            issue_id=issue.id,
            transformation_name=label,
            transformed_text=texts[label],
            transformation_notes={"verbosity_reduction": notes, "reordering": reorder_notes}.get(
                label, "n/a"
            ),
            quality_warning=quality_warning if label == "verbosity_reduction" else False,
            is_original=label == "original",
        )
        db.add(ti)
        db.flush()
        db.add(
            ps.Run(
                experiment_id=experiment.id,
                transformed_issue_id=ti.id,
                agent_name="llm_baseline",
                run_index=0,
                execution_mode="real",
                status=status,
                patch=patch,
                metadata_=(
                    json.dumps({"stop_reason": stop_reasons[label]})
                    if label in stop_reasons
                    else None
                ),
            )
        )
    db.flush()


def test_analyze_scores_complete_incomplete_and_missing_candidates(db):
    experiment = ps.Experiment(name=ps.EXPERIMENT_NAME, config="{}", status="completed")
    db.add(experiment)
    db.flush()
    text = "word " * 40 + "\n\n" + "other " * 10
    _add_issue_with_runs(
        db,
        experiment,
        "ok-1",
        text,
        {
            "original": ("success", PATCH_A),
            "verbosity_reduction": ("success", PATCH_B),
            "reordering": ("success", PATCH_A),
        },
        verbosity_text="word " * 20,
        notes="LLM returned non-JSON response; using raw output.",
        quality_warning=True,
        reorder_notes="Shuffled 3 paragraph(s) using single-newline split (seed=42).",
        stop_reasons={"verbosity_reduction": "max_tokens", "original": "end_turn"},
    )
    _add_issue_with_runs(
        db,
        experiment,
        "err-2",
        text,
        {
            "original": ("success", PATCH_A),
            "verbosity_reduction": ("error", None),
            "reordering": ("success", "just prose, no diff"),
        },
    )
    candidates = [
        ps.Candidate("ok-1", "org/x", text),
        ps.Candidate("err-2", "org/x", text),
        ps.Candidate("never-ran", "org/y", text),
    ]

    ok, err, never = ps.analyze(db, experiment, candidates)

    assert ok.complete and not ok.flip_any
    assert ok.c1_reorder == 1.0 and 0.0 <= ok.c1_verbosity < 1.0
    assert ok.divergence == pytest.approx(1.0 - (ok.c1_verbosity + 1.0) / 2.0)
    assert ok.quality_warning and ok.json_fallback
    assert ok.verbosity_ratio == pytest.approx(20 / 50)
    assert ok.reorder_intact == 1.0  # reordering left the text untouched here ...
    assert ok.line_shuffle  # ... but its recorded single-newline split still marks it
    assert ok.no_diff == ()
    assert ok.truncated == ("verbosity",)  # only the max_tokens run, not the end_turn one

    assert not err.complete and err.outcome_verbosity == "error" and err.divergence is None
    assert err.no_diff == ("reorder",)
    assert not err.line_shuffle  # unchanged text, no single-newline note

    assert not never.complete
    assert (never.outcome_original, never.outcome_verbosity, never.outcome_reorder) == (
        "missing",
    ) * 3


def test_line_shuffle_falls_back_to_adjacency_when_the_notes_are_uninformative(db):
    experiment = ps.Experiment(name=ps.EXPERIMENT_NAME, config="{}", status="completed")
    db.add(experiment)
    db.flush()
    lines = [f"line number {i}" for i in range(30)]
    text = "\n".join(lines)
    all_success = {
        "original": ("success", PATCH_A),
        "verbosity_reduction": ("success", PATCH_A),
        "reordering": ("success", PATCH_A),
    }
    _add_issue_with_runs(
        db, experiment, "shuffled", text, all_success, reordered="\n".join(reversed(lines))
    )
    _add_issue_with_runs(db, experiment, "intact", text, all_success)

    shuffled, intact = ps.analyze(
        db,
        experiment,
        [ps.Candidate("shuffled", "org/x", text), ps.Candidate("intact", "org/x", text)],
    )

    assert shuffled.reorder_intact == 0.0 and shuffled.line_shuffle
    assert intact.reorder_intact == 1.0 and not intact.line_shuffle
