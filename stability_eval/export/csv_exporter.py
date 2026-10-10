from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from stability_eval.data.models import Experiment, Issue, Metric, Run, TransformedIssue
from stability_eval.export._metric_rows import PROVENANCE_FIELDS, metric_rows, provenance
from stability_eval.metrics.outcome import (
    displayed_outcome,
    recorded_outcomes,
    recorded_run_values,
)


class CSVExporter:
    def export(self, experiment: Experiment, output_dir: Path, db: Session) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            self._export_runs(experiment, output_dir, db),
            self._export_metrics(experiment, output_dir, db),
        ]

    def _export_runs(self, experiment: Experiment, output_dir: Path, db: Session) -> Path:
        rows = (
            db.query(Run, TransformedIssue, Issue)
            .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
            .join(Issue, TransformedIssue.issue_id == Issue.id)
            .filter(Run.experiment_id == experiment.id)
            .all()
        )
        rows_metrics = metric_rows(db, experiment.id)
        recorded = recorded_outcomes(rows_metrics)
        jaccard = recorded_run_values(rows_metrics, "file_overlap_jaccard")
        path = output_dir / "runs.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "run_id", "experiment_id", "agent_name", "agent_version", "issue_id",
                    "repo_name", "issue_text", "transformation_name", "is_original",
                    "transformed_text", "run_index", "control_repeat", "execution_mode", "status",
                    "outcome",
                    "file_overlap_jaccard", "patch",
                    "explanation", "raw_logs", "error_message", "cost_usd",
                    "runtime_seconds", "token_input", "token_output", "created_at",
                    "started_at", "completed_at", "transformation_params",
                    "transformation_notes", "quality_warning", *PROVENANCE_FIELDS,
                ],
            )
            writer.writeheader()
            for run, ti, issue in rows:
                writer.writerow({
                    "run_id": run.id,
                    "experiment_id": run.experiment_id,
                    "agent_name": run.agent_name,
                    "agent_version": run.agent_version,
                    "issue_id": issue.external_id or issue.id,
                    "repo_name": issue.repo_name,
                    "issue_text": issue.issue_text,
                    "transformation_name": ti.transformation_name,
                    "is_original": ti.is_original,
                    "transformed_text": ti.transformed_text,
                    "run_index": run.run_index,
                    "control_repeat": run.control_repeat,
                    "execution_mode": run.execution_mode,
                    "status": run.status,
                    "outcome": displayed_outcome(run.id, run.status, recorded),
                    # Empty when the run has no outcome or the issue no gold patch.
                    "file_overlap_jaccard": jaccard.get(run.id),
                    "patch": run.patch,
                    "explanation": run.explanation,
                    "raw_logs": run.raw_logs,
                    "error_message": run.error_message,
                    "cost_usd": run.cost_usd,
                    "runtime_seconds": run.runtime_seconds,
                    "token_input": run.token_input,
                    "token_output": run.token_output,
                    "created_at": run.created_at,
                    "started_at": run.started_at,
                    "completed_at": run.completed_at,
                    "transformation_params": ti.transformation_params,
                    "transformation_notes": ti.transformation_notes,
                    "quality_warning": ti.quality_warning,
                    **provenance(ti),
                })
        return path

    def _export_metrics(self, experiment: Experiment, output_dir: Path, db: Session) -> Path:
        metrics = db.query(Metric).filter(Metric.experiment_id == experiment.id).all()
        path = output_dir / "metrics.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["metric_name", "scope", "scope_key", "metric_value"],
            )
            writer.writeheader()
            for m in metrics:
                writer.writerow({
                    "metric_name": m.metric_name,
                    "scope": m.scope,
                    "scope_key": m.scope_key,
                    "metric_value": m.metric_value,
                })
        return path
