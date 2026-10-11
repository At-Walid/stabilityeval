from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from stableagent.data.models import Experiment, Issue, Metric, Run, TransformedIssue
from stableagent.export._metric_rows import metric_rows, provenance
from stableagent.metrics.outcome import (
    displayed_outcome,
    exclusion_counts,
    recorded_outcomes,
    recorded_run_values,
)


class JSONExporter:
    def export(self, experiment: Experiment, output_dir: Path, db: Session) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        rows = metric_rows(db, experiment.id)
        result = {
            "experiment": {
                "id": experiment.id,
                "name": experiment.name,
                "description": experiment.description,
                "status": experiment.status,
                "created_at": experiment.created_at,
                "started_at": experiment.started_at,
                "completed_at": experiment.completed_at,
                "total_cost_usd": experiment.total_cost_usd,
                "config": json.loads(experiment.config),
            },
            "runs": self._build_runs(
                experiment, db, recorded_outcomes(rows),
                recorded_run_values(rows, "file_overlap_jaccard"),
            ),
            "metrics": self._build_metrics(experiment, db),
            # Runs left out of metrics A/F/G (see SPEC section 13).
            "exclusions": exclusion_counts(rows),
        }
        path = output_dir / "experiment_results.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return path

    def _build_runs(
        self,
        experiment: Experiment,
        db: Session,
        recorded: dict[str, str],
        jaccard: dict[str, float],
    ) -> list[dict]:
        rows = (
            db.query(Run, TransformedIssue, Issue)
            .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
            .join(Issue, TransformedIssue.issue_id == Issue.id)
            .filter(Run.experiment_id == experiment.id)
            .all()
        )
        return [
            {
                "run_id": run.id,
                "agent_name": run.agent_name,
                "agent_version": run.agent_version,
                "issue_id": issue.external_id or issue.id,
                "repo_name": issue.repo_name,
                "issue_text": issue.issue_text,
                "transformation_name": ti.transformation_name,
                "is_original": ti.is_original,
                "transformed_text": ti.transformed_text,
                "transformation_params": json.loads(ti.transformation_params) if ti.transformation_params else None,
                "transformation_notes": ti.transformation_notes,
                "quality_warning": ti.quality_warning,
                **provenance(ti),
                "run_index": run.run_index,
                "control_repeat": run.control_repeat,
                "execution_mode": run.execution_mode,
                "status": run.status,
                "outcome": displayed_outcome(run.id, run.status, recorded),
                "file_overlap_jaccard": jaccard.get(run.id),
                "patch": run.patch,
                "explanation": run.explanation,
                "raw_logs": run.raw_logs,
                "metadata": json.loads(run.metadata_) if run.metadata_ else None,
                "cost_usd": run.cost_usd,
                "runtime_seconds": run.runtime_seconds,
                "token_input": run.token_input,
                "token_output": run.token_output,
                "error_message": run.error_message,
                "started_at": run.started_at,
                "created_at": run.created_at,
                "completed_at": run.completed_at,
            }
            for run, ti, issue in rows
        ]

    def _build_metrics(self, experiment: Experiment, db: Session) -> list[dict]:
        return [
            {
                "metric_name": m.metric_name,
                "scope": m.scope,
                "scope_key": m.scope_key,
                "metric_value": m.metric_value,
                "metadata": json.loads(m.metric_metadata) if m.metric_metadata else None,
                "computed_at": m.computed_at,
            }
            for m in db.query(Metric).filter(Metric.experiment_id == experiment.id).all()
        ]
