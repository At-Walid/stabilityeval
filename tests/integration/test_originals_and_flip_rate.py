"""Originals-only mode (`stabilityeval run --originals-only` / "originals_only": true) and the
symmetric flip rate reported next to TS. No network: MockReplay fixtures in a temp directory."""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from stability_eval.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stability_eval.data.loaders.swebench import SWEBenchInstance, store_instances
from stability_eval.data.models import Base, Issue, Metric, Run, TransformedIssue
from stability_eval.execution.runner import ExperimentRunner
from stability_eval.export.report_generator import ReportGenerator
from stability_eval.metrics.engine import MetricsEngine
from stability_eval.metrics.originals import original_results, success_count
from stability_eval.metrics.sensitivity import FlipRate, TransformationSensitivity


def diff(*paths: str) -> str:
    return "\n".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new" for p in paths)


# issue -> (gold files, original patch files, paraphrase patch files)
ISSUES = {
    "org__a-1": (["pkg/core.py"], ["pkg/core.py"], ["pkg/other.py"]),  # success -> failure
    "org__b-2": (["pkg/api.py"], ["pkg/util.py"], ["pkg/api.py"]),  # failure -> success
    "org__c-3": (["pkg/x.py", "pkg/y.py"], ["pkg/x.py"], ["pkg/x.py"]),  # failure, partial
}


@pytest.fixture()
def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'originals.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        store_instances(db, [
            SWEBenchInstance(issue_id, "org/x", f"Bug number {n} in pkg.", gold_patch=diff(*gold))
            for n, (issue_id, (gold, _o, _p)) in enumerate(ISSUES.items())
        ])
        db.add(Issue(external_id="custom-1", repo_name="o/r", source="manual",
                     issue_text="No gold patch here."))
        db.commit()
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for issue_id, (_gold, original, paraphrase) in ISSUES.items():
        for variant, files in (("original", original), ("paraphrase", paraphrase)):
            (fixtures / f"{issue_id}__{variant}__mock_replay.json").write_text(
                json.dumps({"status": "success", "patch": diff(*files)}), encoding="utf-8"
            )
    (fixtures / "custom-1__original__mock_replay.json").write_text(
        json.dumps({"status": "timeout", "patch": None}), encoding="utf-8"
    )
    yield Session, fixtures
    engine.dispose()


def _config(fixtures, *, originals_only, issue_ids=None):
    return ExperimentConfig(
        experiment_name="originals",
        execution_mode="mock",
        agents=[AgentConfig(name="mock_replay", params={"fixtures_dir": str(fixtures)})],
        issues=IssueConfig(issue_ids=issue_ids or list(ISSUES)),
        transformations=[TransformationConfig(name="paraphrase"),
                         TransformationConfig(name="reordering")],
        originals_only=originals_only,
    )


# ── Originals-only mode ───────────────────────────────────────────────────────

def test_originals_only_runs_no_variant_at_all(setup, no_network):
    Session, fixtures = setup
    with Session() as db:
        experiment = ExperimentRunner(_config(fixtures, originals_only=True), db).run()
        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
        assert len(runs) == 3
        assert {run.transformed_issue.transformation_name for run in runs} == {"original"}
        assert db.query(TransformedIssue).filter_by(is_original=False).count() == 0


def test_original_results_list_outcome_and_files(setup):
    Session, fixtures = setup
    with Session() as db:
        experiment = ExperimentRunner(
            _config(fixtures, originals_only=True, issue_ids=[*ISSUES, "custom-1"]), db
        ).run()
        MetricsEngine().compute(experiment.id, db)
        results = {r.issue_id: r for r in original_results(db, experiment.id)}

    assert results["org__a-1"].outcome == "success"
    assert results["org__a-1"].files_in_gold == ["pkg/core.py"]
    assert results["org__a-1"].files_in_patch == ["pkg/core.py"]
    assert (results["org__b-2"].outcome, results["org__b-2"].files_in_patch) == (
        "failure", ["pkg/util.py"]
    )
    assert results["org__c-3"].outcome == "failure"  # partial localization
    assert results["custom-1"].outcome == "excluded"  # timeout: no outcome
    assert results["custom-1"].files_in_gold is None  # no gold patch
    assert success_count(list(results.values())) == 1


def test_the_cli_flag_and_the_config_flag_print_the_per_issue_table(
    setup, tmp_path, monkeypatch, no_network
):
    from stability_eval.cli import main as cli

    Session, fixtures = setup

    @contextmanager
    def temp_db():
        session = Session()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(cli, "get_db", temp_db)
    monkeypatch.setattr(cli, "create_all", lambda *a, **k: None)
    config = _config(fixtures, originals_only=False).model_dump()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["run", "--config", str(path), "--originals-only"],
                                terminal_width=200)

    assert result.exit_code == 0, result.output
    assert "originals only" in result.output
    for issue_id in ISSUES:
        assert issue_id in result.output
    assert "pkg/core.py" in result.output and "pkg/util.py" in result.output
    assert "Success: 1 of 3 original run(s)" in result.output
    with Session() as db:
        assert db.query(TransformedIssue).filter_by(is_original=False).count() == 0

    config["originals_only"] = True  # the same through the config file
    path.write_text(json.dumps(config), encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["run", "--config", str(path)], terminal_width=200)
    assert result.exit_code == 0 and "Success: 1 of 3 original run(s)" in result.output


# ── Flip rate next to TS ──────────────────────────────────────────────────────

def test_opposite_flips_cancel_in_ts_but_not_in_the_flip_rate():
    rows = [
        {"agent_name": "a", "issue_id": i, "is_original": orig, "transformation_name": t,
         "outcome": outcome}
        for i, orig, t, outcome in [
            ("1", True, "original", "success"), ("1", False, "p", "failure"),  # drop
            ("2", True, "original", "failure"), ("2", False, "p", "success"),  # gain
            ("3", True, "original", "failure"), ("3", False, "p", "failure"),  # same
        ]
    ]
    assert TransformationSensitivity().compute(rows) == {("a", "p"): 0.0}
    assert FlipRate().compute(rows) == {("a", "p"): pytest.approx(2 / 3)}


def test_the_engine_stores_and_the_report_shows_the_flip_rate(setup, tmp_path):
    Session, fixtures = setup
    with Session() as db:
        experiment = ExperimentRunner(
            _config(fixtures, originals_only=False).model_copy(
                update={"transformations": [TransformationConfig(name="paraphrase")]}
            ),
            db,
        ).run()
        MetricsEngine().compute(experiment.id, db)
        metrics = {
            (m.metric_name, m.scope_key): m.metric_value
            for m in db.query(Metric).filter_by(experiment_id=experiment.id)
        }
        report = ReportGenerator().export(experiment, tmp_path, db).read_text(encoding="utf-8")

    # a-1: success -> failure, b-2: failure -> success, c-3: failure -> failure
    assert metrics[("transformation_sensitivity", "mock_replay|paraphrase")] == 0.0
    assert metrics[("flip_rate", "mock_replay|paraphrase")] == pytest.approx(2 / 3)
    assert "| Agent | Transformation | Sensitivity (G) | Flip rate |" in report
    assert "| mock_replay | paraphrase | 0.000 | 0.667 |" in report
