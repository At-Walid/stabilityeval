"""Issue picker logic for the dashboard (Section A) and the Run guard (Section D).

Replayability, filters, the cost estimate and the reasons that keep Run disabled. Pure functions
with no Streamlit calls, so they are unit-tested directly (tests/unit/test_dashboard_picker.py).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd

from stability_eval.data.models import PILOT_SOURCE

ALL_REPOSITORIES = "All repositories"
# Issue sets: every loaded issue, or the ICSE pilot issues (source PILOT_SOURCE).
ALL_ISSUE_SETS = "All issues"
PILOT_SET = "ICSE pilot"
PILOT_TAG = "ICSE pilot"  # shown in the option label of every pilot issue
REPLAYABLE_BADGE = "✓ replayable"
# Estimated cost of one real run when no real run has recorded a cost yet.
FALLBACK_COST_PER_RUN = 0.03
_MAX_LISTED = 5  # issues named in a guard message before "and N more"


def issue_key(external_id, db_id) -> str:
    """The id runs and fixtures use for an issue: its external id, else its database id."""
    return external_id if isinstance(external_id, str) and external_id else db_id


def with_issue_keys(issues: pd.DataFrame) -> pd.DataFrame:
    """``issues`` (as loaded by _db.load_issues) with an ``issue_key`` column."""
    keyed = issues.copy()
    keyed["issue_key"] = [
        issue_key(external_id, db_id)
        for external_id, db_id in zip(issues["external_id"], issues["id"])
    ]
    return keyed


# ── Replayability ─────────────────────────────────────────────────────────────

def required_variants(transformations: Iterable[str]) -> list[str]:
    """The variants a run executes: the original, then each enabled transformation."""
    return ["original", *transformations]


def missing_fixtures(
    issue_id: str, transformations: Iterable[str], index: Mapping[str, set[str]]
) -> list[str]:
    """The variants MockReplay has no fixture for (``index`` from mock_replay.fixture_index)."""
    recorded = index.get(issue_id, set())
    return [variant for variant in required_variants(transformations) if variant not in recorded]


def is_replayable(
    issue_id: str, transformations: Iterable[str], index: Mapping[str, set[str]]
) -> bool:
    """True when fixtures exist for the original and every enabled transformation."""
    return not missing_fixtures(issue_id, transformations, index)


def replayable_ids(
    issue_ids: Iterable[str], transformations: Iterable[str], index: Mapping[str, set[str]]
) -> frozenset[str]:
    transformations = list(transformations)
    return frozenset(i for i in issue_ids if is_replayable(i, transformations, index))


def replay_gaps(
    issue_ids: Iterable[str], transformations: Iterable[str], index: Mapping[str, set[str]]
) -> dict[str, list[str]]:
    """The missing variants of each issue MockReplay cannot fully replay (others are left out)."""
    transformations = list(transformations)
    gaps = {i: missing_fixtures(i, transformations, index) for i in issue_ids}
    return {issue_id: variants for issue_id, variants in gaps.items() if variants}


def describe_replay_gaps(gaps: Mapping[str, list[str]]) -> str:
    """One sentence naming the issues without fixtures (at most five) and what each one lacks."""
    listed = "; ".join(
        f"{issue_id} (missing: {', '.join(variants)})"
        for issue_id, variants in list(gaps.items())[:_MAX_LISTED]
    )
    if len(gaps) > _MAX_LISTED:
        listed += f"; and {len(gaps) - _MAX_LISTED} more"
    return (
        f"MockReplay only replays recorded fixtures, and {len(gaps)} selected issue(s) have "
        f"none for the enabled transformations: {listed}."
    )


def badge(replayable: bool, cost_per_run: float) -> str:
    """REPLAYABLE_BADGE, or the real-mode cost of each variant."""
    if replayable:
        return REPLAYABLE_BADGE
    return f"real mode only (~${cost_per_run:.2f} per variant)"


# ── Filters ───────────────────────────────────────────────────────────────────

def n_pilot(issues: pd.DataFrame) -> int:
    """How many of the loaded issues belong to the ICSE pilot."""
    return int((issues["source"] == PILOT_SOURCE).sum()) if "source" in issues else 0


def issue_set_options(issues: pd.DataFrame) -> list[str]:
    """ALL_ISSUE_SETS, then PILOT_SET when pilot issues are loaded."""
    return [ALL_ISSUE_SETS, PILOT_SET] if n_pilot(issues) else [ALL_ISSUE_SETS]


def option_label(key: str, issue_text: str, source: str | None, mark: str) -> str:
    """A picker option: id, the pilot tag for a pilot issue, the badge and the first words."""
    snippet = " ".join(issue_text.split())[:70]
    tag = f" · {PILOT_TAG}" if source == PILOT_SOURCE else ""
    return f"{key}{tag} · {mark} — {snippet}…"


def repository_options(issues: pd.DataFrame) -> list[str]:
    """ALL_REPOSITORIES, then every repository of the loaded issues, sorted."""
    return [ALL_REPOSITORIES, *sorted(issues["repo_name"].dropna().unique().tolist())]


def filter_issues(
    issues: pd.DataFrame,
    *,
    issue_set: str = ALL_ISSUE_SETS,
    repo: str = ALL_REPOSITORIES,
    keyword: str = "",
    only_replayable: bool = False,
    replayable: Iterable[str] = (),
) -> pd.DataFrame:
    """The issues (with ``issue_key``) that pass every active filter, in their original order.

    ``keyword`` is case-insensitive and searches the issue text; every whitespace-separated term
    must occur in it.
    """
    mask = pd.Series(True, index=issues.index)
    if issue_set == PILOT_SET:
        mask &= issues["source"] == PILOT_SOURCE
    if repo and repo != ALL_REPOSITORIES:
        mask &= issues["repo_name"] == repo
    text = issues["issue_text"].str.lower()
    for term in keyword.lower().split():
        mask &= text.str.contains(term, regex=False, na=False)
    if only_replayable:
        mask &= issues["issue_key"].isin(set(replayable))
    return issues[mask]


def counter_text(
    n_loaded: int, n_replayable: int, n_shown: int | None = None, n_pilot: int = 0
) -> str:
    """E.g. "300 loaded, 5 replayable", plus ", 20 ICSE pilot" when pilot issues are loaded and
    "· 12 shown" when filters hide some issues."""
    text = f"{n_loaded} loaded, {n_replayable} replayable"
    if n_pilot:
        text += f", {n_pilot} {PILOT_TAG}"
    if n_shown is not None and n_shown != n_loaded:
        text += f" · {n_shown} shown"
    return text


def issue_payload(row: Mapping) -> dict:
    """What a run receives about an issue: its id, text and repository, nothing else.

    The hidden gold patch lives in the issue's metadata, which the picker never loads, so it
    cannot reach an agent through the dashboard.
    """
    return {
        "issue_id": row["issue_key"],
        "issue_text": row["issue_text"],
        "repo_name": row["repo_name"],
    }


# ── Cost estimate ─────────────────────────────────────────────────────────────

def cost_per_run(measured_mean: float | None) -> float:
    """The measured mean cost of past real runs, else FALLBACK_COST_PER_RUN."""
    if measured_mean is not None and measured_mean > 0:
        return measured_mean
    return FALLBACK_COST_PER_RUN


def n_runs(n_issues: int, n_transformations: int) -> int:
    """Runs in one experiment: each issue's original plus one run per transformation."""
    return n_issues * (1 + n_transformations)


def estimate_cost(n_issues: int, n_transformations: int, per_run: float) -> float:
    return n_runs(n_issues, n_transformations) * per_run


# ── Run guard ─────────────────────────────────────────────────────────────────

def run_blockers(
    *,
    issues: list[dict],
    transformations: list[str],
    use_mock: bool,
    custom_issue: bool,
    api_key: str | None,
    index: Mapping[str, set[str]],
    per_run: float,
    cost_limit: float,
) -> list[str]:
    """Why Run must stay disabled, one message per reason; empty when the run may start."""
    reasons: list[str] = []
    if not issues:
        reasons.append("Select at least 1 issue.")
    if len(transformations) < 2:
        reasons.append("Select at least 2 transformations.")

    if use_mock:
        if custom_issue and issues:
            reasons.append(
                "MockReplay only replays recorded fixtures, and a custom issue has none. "
                "Switch to LLM Baseline to run it."
            )
        elif issues:
            gaps = replay_gaps([issue["issue_id"] for issue in issues], transformations, index)
            if gaps:
                reasons.append(
                    f"{describe_replay_gaps(gaps)} Deselect them, enable only transformations "
                    "they were recorded with, or switch to LLM Baseline."
                )
    else:
        if not api_key:
            reasons.append("Enter an Anthropic API key to run LLM Baseline.")
        estimate = estimate_cost(len(issues), len(transformations), per_run)
        if issues and estimate > cost_limit:
            reasons.append(
                f"Estimated cost ${estimate:.2f} exceeds the configured limit of "
                f"${cost_limit:.2f}. Select fewer issues or transformations."
            )
    return reasons
