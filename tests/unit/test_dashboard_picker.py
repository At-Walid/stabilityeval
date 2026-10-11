"""Dashboard issue picker: fixture index, badges, filters, counter, cost estimate and Run guard."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import stableagent
from stableagent.agents.mock_replay import fixture_filename, fixture_index
from stableagent.dashboard import _picker as picker

REAL_FIXTURES = Path(stableagent.__file__).parent / "fixtures" / "mock_responses"
DEMO_SAMPLES = [
    "astropy__astropy-6938", "django__django-11099", "django__django-12125",
    "matplotlib__matplotlib-23299", "sympy__sympy-20590",
]
ALL_TRANSFORMS = [
    "paraphrase", "verbosity_reduction", "typo_injection", "reordering",
    "paragraph_to_structured", "neutralize_emotional",
]

INDEX = {
    "org__a-1": {"original", "paraphrase", "verbosity_reduction"},
    "org__a-2": {"original", "paraphrase"},
    "org__b-3": {"paraphrase", "verbosity_reduction"},  # no original fixture
}


# ── Fixture index ─────────────────────────────────────────────────────────────

def test_fixture_index_parses_ids_that_contain_double_underscores(tmp_path):
    for issue_id, variant in [
        ("django__django-11099", "original"),
        ("django__django-11099", "verbosity_reduction"),
        ("I01", "paraphrase"),
    ]:
        (tmp_path / fixture_filename(issue_id, variant)).write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a fixture", encoding="utf-8")
    (tmp_path / "broken__mock_replay.json").write_text("{}", encoding="utf-8")

    assert fixture_index(tmp_path) == {
        "django__django-11099": {"original", "verbosity_reduction"},
        "I01": {"paraphrase"},
    }
    assert fixture_index(tmp_path / "missing") == {}


def test_the_demo_samples_are_replayable_with_every_transformation():
    index = fixture_index(REAL_FIXTURES)
    assert picker.replayable_ids(DEMO_SAMPLES, ALL_TRANSFORMS, index) == set(DEMO_SAMPLES)
    assert not picker.is_replayable("astropy__astropy-14182", [], index)


def test_the_icse_pilot_issues_are_replayable_with_every_transformation():
    """Recorded from the real pilot run (experiment bc6f1372, `stableagent record-fixtures`)."""
    pilot = json.loads((Path(__file__).parents[2] / "scripts" / "output" / "pilot_issue_ids.json")
                       .read_text(encoding="utf-8"))
    index = fixture_index(REAL_FIXTURES)
    assert picker.replayable_ids(pilot, ALL_TRANSFORMS, index) == set(pilot)


# ── Replayability and badges ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("issue_id", "transformations", "missing"),
    [
        ("org__a-1", ["paraphrase", "verbosity_reduction"], []),
        ("org__a-1", ["paraphrase", "reordering"], ["reordering"]),
        ("org__a-2", ["paraphrase", "verbosity_reduction"], ["verbosity_reduction"]),
        ("org__a-2", [], []),  # the original alone
        ("org__b-3", ["paraphrase"], ["original"]),  # the original is always required
        ("unknown__x-9", ["paraphrase"], ["original", "paraphrase"]),
    ],
)
def test_replayability_follows_the_enabled_transformations(issue_id, transformations, missing):
    assert picker.missing_fixtures(issue_id, transformations, INDEX) == missing
    assert picker.is_replayable(issue_id, transformations, INDEX) is (not missing)


def test_badges():
    assert picker.badge(True, 0.03) == "✓ replayable"
    assert picker.badge(False, picker.cost_per_run(None)) == "real mode only (~$0.03 per variant)"
    assert picker.badge(False, 0.0242) == "real mode only (~$0.02 per variant)"


def test_badges_change_when_a_transformation_without_fixtures_is_enabled():
    ids = list(INDEX)
    assert picker.replayable_ids(ids, ["paraphrase"], INDEX) == {"org__a-1", "org__a-2"}
    assert picker.replayable_ids(ids, ["paraphrase", "verbosity_reduction"], INDEX) == {
        "org__a-1"
    }
    assert picker.replayable_ids(ids, ["reordering"], INDEX) == set()


# ── Filters ───────────────────────────────────────────────────────────────────

ISSUES = picker.with_issue_keys(pd.DataFrame([
    {"id": "db-1", "external_id": "org__a-1", "repo_name": "org/a",
     "issue_text": "Migration crashes with ImportError on startup"},
    {"id": "db-2", "external_id": "org__a-2", "repo_name": "org/a",
     "issue_text": "Docs typo in the tutorial"},
    {"id": "db-3", "external_id": "org__b-3", "repo_name": "org/b",
     "issue_text": "ImportError when calling foo(bar) twice"},
    {"id": "db-4", "external_id": "other__c-4", "repo_name": "other/c",
     "issue_text": "migration is slow"},
    {"id": "db-5", "external_id": None, "repo_name": "other/c",
     "issue_text": "custom issue without an external id"},
]))
REPLAYABLE = {"org__a-1", "org__a-2"}


@pytest.mark.parametrize(
    ("repo", "keyword", "only_replayable", "expected"),
    [
        (picker.ALL_REPOSITORIES, "", False, list(ISSUES["issue_key"])),
        ("org/a", "", False, ["org__a-1", "org__a-2"]),
        ("other/c", "", False, ["other__c-4", "db-5"]),
        (picker.ALL_REPOSITORIES, "importerror", False, ["org__a-1", "org__b-3"]),  # any case
        (picker.ALL_REPOSITORIES, "MIGRATION", False, ["org__a-1", "other__c-4"]),
        (picker.ALL_REPOSITORIES, "migration importerror", False, ["org__a-1"]),  # all terms
        (picker.ALL_REPOSITORIES, "  migration   slow ", False, ["other__c-4"]),
        (picker.ALL_REPOSITORIES, "foo(bar)", False, ["org__b-3"]),  # literal, not a regex
        (picker.ALL_REPOSITORIES, "nothing-matches", False, []),
        (picker.ALL_REPOSITORIES, "", True, ["org__a-1", "org__a-2"]),
        ("org/a", "importerror", False, ["org__a-1"]),
        ("org/b", "", True, []),
        (picker.ALL_REPOSITORIES, "docs", True, ["org__a-2"]),
        (picker.ALL_REPOSITORIES, "importerror", True, ["org__a-1"]),
        ("org/a", "migration", True, ["org__a-1"]),
        ("other/c", "migration", True, []),
    ],
)
def test_filter_combinations(repo, keyword, only_replayable, expected):
    shown = picker.filter_issues(
        ISSUES, repo=repo, keyword=keyword, only_replayable=only_replayable, replayable=REPLAYABLE
    )
    assert list(shown["issue_key"]) == expected


def test_issue_key_falls_back_to_the_database_id():
    assert list(ISSUES["issue_key"]) == ["org__a-1", "org__a-2", "org__b-3", "other__c-4", "db-5"]
    assert picker.issue_key(float("nan"), "db-9") == "db-9"
    assert picker.issue_key("", "db-9") == "db-9"


def test_repository_options_and_counter():
    assert picker.repository_options(ISSUES) == [
        picker.ALL_REPOSITORIES, "org/a", "org/b", "other/c"
    ]
    assert picker.counter_text(300, 20) == "300 loaded, 20 replayable"
    assert picker.counter_text(300, 20, 300) == "300 loaded, 20 replayable"
    assert picker.counter_text(300, 5, 12) == "300 loaded, 5 replayable · 12 shown"


def test_the_payload_carries_only_id_text_and_repository():
    row = dict(ISSUES.iloc[0]) | {"metadata": '{"gold_patch": "SECRET"}', "gold_patch": "SECRET"}
    assert picker.issue_payload(row) == {
        "issue_id": "org__a-1",
        "issue_text": "Migration crashes with ImportError on startup",
        "repo_name": "org/a",
    }


# ── Cost estimate ─────────────────────────────────────────────────────────────

def test_cost_estimate_uses_the_measured_mean_or_the_fallback():
    assert picker.cost_per_run(None) == picker.FALLBACK_COST_PER_RUN == 0.03
    assert picker.cost_per_run(0.0) == 0.03
    assert picker.cost_per_run(0.0242) == 0.0242
    assert picker.n_runs(2, 3) == 8  # each issue: original + 3 variants
    assert picker.estimate_cost(2, 3, 0.025) == pytest.approx(0.20)


# ── Run guard ─────────────────────────────────────────────────────────────────

def _guard(**overrides):
    args = {
        "issues": [{"issue_id": "org__a-1"}],
        "transformations": ["paraphrase", "verbosity_reduction"],
        "use_mock": True,
        "custom_issue": False,
        "api_key": None,
        "index": INDEX,
        "per_run": 0.03,
        "cost_limit": 20.0,
    }
    return picker.run_blockers(**(args | overrides))


def test_mock_run_allowed_when_every_issue_is_replayable():
    assert _guard() == []


def test_mock_run_blocked_for_a_non_replayable_issue_with_the_reason():
    (reason,) = _guard(issues=[{"issue_id": "org__a-1"}, {"issue_id": "org__a-2"}])
    assert "org__a-2 (missing: verbosity_reduction)" in reason
    assert "org__a-1" not in reason
    assert "LLM Baseline" in reason


def test_mock_guard_lists_five_issues_then_counts_the_rest():
    issues = [{"issue_id": f"none__x-{i}"} for i in range(7)]
    (reason,) = _guard(issues=issues)
    assert "7 selected issue(s)" in reason
    assert "none__x-4" in reason and "none__x-5" not in reason
    assert "and 2 more" in reason


def test_mock_run_blocked_for_a_custom_issue_even_with_a_matching_fixture_id():
    (reason,) = _guard(custom_issue=True)
    assert "custom issue" in reason


def test_selection_and_transformation_minimums():
    assert _guard(issues=[]) == ["Select at least 1 issue."]
    assert _guard(transformations=["paraphrase"]) == ["Select at least 2 transformations."]


def test_real_run_needs_a_key_but_no_fixtures():
    assert _guard(use_mock=False, issues=[{"issue_id": "unknown__x-9"}]) == [
        "Enter an Anthropic API key to run LLM Baseline."
    ]
    assert _guard(use_mock=False, api_key="k", issues=[{"issue_id": "unknown__x-9"}]) == []


def test_real_run_blocked_when_the_estimate_exceeds_the_limit():
    issues = [{"issue_id": f"i-{n}"} for n in range(10)]
    # 10 issues x (1 + 2) variants x $0.03 = $0.90
    (reason,) = _guard(use_mock=False, api_key="k", issues=issues, cost_limit=0.5)
    assert "Estimated cost $0.90 exceeds the configured limit of $0.50" in reason
    assert _guard(use_mock=False, api_key="k", issues=issues, cost_limit=1.0) == []


def test_an_estimate_equal_to_the_limit_is_allowed():
    issues = [{"issue_id": "i-1"}, {"issue_id": "i-2"}]  # 6 runs x $0.25 = $1.50 exactly
    real = {"use_mock": False, "api_key": "k", "issues": issues, "per_run": 0.25}
    assert _guard(**real, cost_limit=1.5) == []
    assert len(_guard(**real, cost_limit=1.49)) == 1
