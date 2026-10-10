"""Per-issue results of the original runs (originals-only mode, `stabilityeval run --originals-only`).

For each original run: its status, the outcome the metrics engine recorded ("localization
success", SPEC section 13), the files the gold patch modifies and the files the run's patch
modifies. Reads the metrics, so call it after MetricsEngine.compute.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from stability_eval.data.loaders.swebench import gold_patch_of
from stability_eval.data.models import Issue, Metric, Run, TransformedIssue
from stability_eval.metrics.outcome import SUCCESS, displayed_outcome, recorded_outcomes
from stability_eval.metrics.patch_similarity import extract_final_patch, patch_files


@dataclass(frozen=True)
class OriginalResult:
    issue_id: str
    agent_name: str
    status: str
    outcome: str  # "success" | "failure" | "excluded"
    files_in_gold: list[str] | None  # None: the issue has no gold patch (valid-diff-only outcome)
    files_in_patch: list[str]


def original_results(db: Session, experiment_id: str) -> list[OriginalResult]:
    """One result per original run of the experiment, ordered by issue."""
    recorded = recorded_outcomes(
        (m.scope, m.scope_key, m.metric_name, m.metric_value)
        for m in db.query(Metric).filter_by(experiment_id=experiment_id)
    )
    rows = (
        db.query(Run, Issue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .join(Issue, TransformedIssue.issue_id == Issue.id)
        .filter(
            Run.experiment_id == experiment_id,
            TransformedIssue.is_original.is_(True),
            Run.control_repeat.is_(False),
        )
        .all()
    )
    results = []
    for run, issue in rows:
        gold = gold_patch_of(issue)
        results.append(OriginalResult(
            issue_id=issue.external_id or issue.id,
            agent_name=run.agent_name,
            status=run.status,
            outcome=displayed_outcome(run.id, run.status, recorded),
            files_in_gold=patch_files(gold) if gold else None,
            files_in_patch=patch_files(extract_final_patch(run.patch)),
        ))
    return sorted(results, key=lambda r: (r.issue_id, r.agent_name))


def success_count(results: list[OriginalResult]) -> int:
    return sum(1 for r in results if r.outcome == SUCCESS)
