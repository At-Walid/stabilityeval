from __future__ import annotations

import csv
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from stableagent.data.models import Base, Experiment, Issue, Run, TransformedIssue
from stableagent.export.csv_exporter import CSVExporter
from stableagent.export.json_exporter import JSONExporter


def test_exports_keep_raw_run_inputs_outputs_and_experiment_config(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'exports.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        issue = Issue(
            id="issue-1", source="manual", external_id="issue-1",
            repo_name="example/project", issue_text="Original issue body",
        )
        experiment = Experiment(
            id="experiment-1", name="export-check", config='{"seed": 42}', status="completed",
        )
        db.add_all([issue, experiment])
        db.flush()
        transformed = TransformedIssue(
            id="variant-1", issue_id=issue.id, transformation_name="typo_injection",
            transformed_text="Transformed issue body", is_original=False,
            transformation_params='{"error_rate": 0.02}',
        )
        db.add(transformed)
        db.flush()
        db.add(Run(
            id="run-1", experiment_id=experiment.id, transformed_issue_id=transformed.id,
            agent_name="LLM Baseline", agent_version="1.0", run_index=0,
            execution_mode="real", status="success", patch="unified diff",
            explanation="candidate", raw_logs="raw response", cost_usd=0.012,
            runtime_seconds=1.2, token_input=100, token_output=20,
            metadata_='{"model":"test-model"}',
        ))
        db.commit()

        json_path = JSONExporter().export(experiment, tmp_path, db)
        csv_path, _ = CSVExporter().export(experiment, tmp_path, db)

    exported = json.loads(json_path.read_text(encoding="utf-8"))
    run = exported["runs"][0]
    assert exported["experiment"]["config"] == {"seed": 42}
    assert run["issue_text"] == "Original issue body"
    assert run["transformed_text"] == "Transformed issue body"
    assert run["patch"] == "unified diff"
    assert run["raw_logs"] == "raw response"
    assert run["metadata"] == {"model": "test-model"}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["issue_text"] == "Original issue body"
    assert row["transformed_text"] == "Transformed issue body"
    assert row["patch"] == "unified diff"
    assert row["raw_logs"] == "raw response"

    engine.dispose()
