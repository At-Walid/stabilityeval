"""Integration test: ExperimentRunner in mock mode, end-to-end."""
from __future__ import annotations

import json
import uuid as uuid_module

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stability_eval.data.models import Base, Experiment, Issue, Run
from stability_eval.execution.cost_guard import CostGuard, CostLimitExceeded
from stability_eval.execution.runner import ExperimentRunner


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine(tmp_path):
    url = f"sqlite:///{tmp_path}/test_runner.db"
    eng = create_engine(url, echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def fixture_dir(tmp_path):
    """Create three fixture files (one per issue, original transformation, zero cost)."""
    fdir = tmp_path / "mock_fixtures"
    fdir.mkdir()

    for issue_id in ("test__issue-001", "test__issue-002", "test__issue-003"):
        data = {
            "status": "success",
            "patch": f"--- a/fix.py\n+++ b/fix.py\n@@ -1 +1 @@\n-old\n+new  # {issue_id}\n",
            "explanation": f"Mock fix for {issue_id}.",
            "token_usage": {"input": 80, "output": 40},
            "cost_usd": 0.0,
            "runtime_seconds": 0.001,
            "error_message": None,
            "raw_logs": "",
            "metadata": {"issue_id": issue_id, "transformation_name": "original"},
        }
        (fdir / f"{issue_id}__original__mock_replay.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    return fdir


@pytest.fixture()
def seeded_db(db_session):
    """Insert the three test issues into the database before the runner starts."""
    for i in range(1, 4):
        issue_id = f"test__issue-00{i}"
        issue = Issue(
            id=issue_id,
            source="manual",
            external_id=issue_id,
            repo_name=f"test/repo-{i}",
            issue_text=f"Issue number {i}: something is broken.",
        )
        db_session.add(issue)
    db_session.flush()
    return db_session


# ---------------------------------------------------------------------------
# Main integration test
# ---------------------------------------------------------------------------

def test_mock_run_produces_three_run_records(seeded_db, fixture_dir):
    """Run 3 cells in mock mode; verify records, status, and zero cost."""
    config = ExperimentConfig(
        experiment_name="integration_test_mock",
        description="3-cell mock run for CI",
        execution_mode="mock",
        agents=[
            AgentConfig(
                name="mock_replay",
                params={"fixtures_dir": str(fixture_dir)},
            )
        ],
        issues=IssueConfig(
            issue_ids=["test__issue-001", "test__issue-002", "test__issue-003"]
        ),
        transformations=[],   # only the 'original' variant per issue
        runs_per_variant=1,
        cost_limit_usd=5.0,
    )

    runner = ExperimentRunner(config, seeded_db)
    experiment = runner.run()

    # --- 3 Run records created ---
    runs = seeded_db.query(Run).filter_by(experiment_id=experiment.id).all()
    assert len(runs) == 3, f"Expected 3 runs, got {len(runs)}"

    # --- Each run completed successfully ---
    for run in runs:
        assert run.status == "success", f"Unexpected status {run.status!r} for run {run.id}"
        assert run.patch is not None
        assert run.execution_mode == "mock"

    # --- Experiment itself completed cleanly ---
    assert experiment.status == "completed"

    # --- Cost guard did not trigger (mock cost = 0) ---
    assert runner._cost_guard.running_total == 0.0
    assert experiment.total_cost_usd == 0.0


def test_mock_run_with_external_id_distinct_from_pk(db_session, fixture_dir):
    """Regression test: issue.id (UUID PK) must differ from issue.external_id.

    Previously the runner passed `issue.external_id or issue.id` into
    IssueRecord.issue_id, which the transformation cache writes straight into
    transformed_issues.issue_id — a foreign key to issues.id. Whenever
    external_id was set and differed from the real primary key (the normal
    case for real SWE-bench issues), this raised a FOREIGN KEY constraint
    IntegrityError. The other fixtures in this file mask the bug by setting
    id == external_id.
    """
    issue = Issue(
        id=str(uuid_module.uuid4()),
        source="manual",
        external_id="real__repo-12345",
        repo_name="real/repo",
        issue_text="Issue number 1: something is broken.",
    )
    db_session.add(issue)
    db_session.flush()

    fixture_data = {
        "status": "success",
        "patch": "--- a/fix.py\n+++ b/fix.py\n@@ -1 +1 @@\n-old\n+new\n",
        "explanation": "Mock fix.",
        "token_usage": {"input": 80, "output": 40},
        "cost_usd": 0.0,
        "runtime_seconds": 0.001,
        "error_message": None,
        "raw_logs": "",
        "metadata": {"issue_id": "real__repo-12345", "transformation_name": "typo_injection"},
    }
    (fixture_dir / "real__repo-12345__original__mock_replay.json").write_text(
        json.dumps(fixture_data), encoding="utf-8"
    )
    (fixture_dir / "real__repo-12345__typo_injection__mock_replay.json").write_text(
        json.dumps(fixture_data), encoding="utf-8"
    )

    config = ExperimentConfig(
        experiment_name="integration_test_external_id",
        execution_mode="mock",
        agents=[AgentConfig(name="mock_replay", params={"fixtures_dir": str(fixture_dir)})],
        issues=IssueConfig(issue_ids=["real__repo-12345"]),
        # Seeded: unseeded, one sentence sometimes gets no typo, and a no-op variant is not run.
        transformations=[
            TransformationConfig(name="typo_injection", enabled=True, params={"seed": 1})
        ],
        runs_per_variant=1,
        cost_limit_usd=5.0,
    )

    runner = ExperimentRunner(config, db_session)
    experiment = runner.run()

    assert experiment.status == "completed"
    runs = db_session.query(Run).filter_by(experiment_id=experiment.id).all()
    assert len(runs) == 2  # original + typo_injection
    assert all(r.status == "success" for r in runs)


def test_failed_experiment_keeps_completed_cells_committed(engine, db_session, fixture_dir):
    issue = Issue(
        id="durable-issue",
        source="manual",
        external_id="durable-issue",
        repo_name="test/durable",
        issue_text="A reproducible issue.",
    )
    db_session.add(issue)
    db_session.commit()
    fixture = {
        "status": "success",
        "patch": "--- a/fix.py\n+++ b/fix.py\n@@ -1 +1 @@\n-old\n+new\n",
        "cost_usd": 0.0,
        "runtime_seconds": 0.01,
    }
    (fixture_dir / "durable-issue__original__mock_replay.json").write_text(
        json.dumps(fixture), encoding="utf-8"
    )
    config = ExperimentConfig(
        experiment_name="durability_check",
        execution_mode="mock",
        agents=[AgentConfig(name="mock_replay", params={"fixtures_dir": str(fixture_dir)})],
        issues=IssueConfig(issue_ids=["durable-issue", "missing-issue"]),
    )

    with pytest.raises(ValueError, match="missing-issue"):
        ExperimentRunner(config, db_session).run()

    Session = sessionmaker(bind=engine)
    with Session() as verify_db:
        experiment = verify_db.query(Experiment).filter_by(name="durability_check").one()
        runs = verify_db.query(Run).filter_by(experiment_id=experiment.id).all()
        assert experiment.status == "failed"
        assert len(runs) == 1
        assert runs[0].status == "success"


# ---------------------------------------------------------------------------
# CostGuard unit-level checks (standalone, no DB)
# ---------------------------------------------------------------------------

def test_cost_guard_allows_run_below_limit():
    guard = CostGuard(per_run_cap=0.50, total_limit=10.0)
    assert guard.check_run(0.0, 0.50, 10.0) is True
    assert guard.check_run(9.99, 0.50, 10.0) is True


def test_cost_guard_blocks_run_at_limit():
    guard = CostGuard(per_run_cap=0.50, total_limit=10.0)
    assert guard.check_run(10.0, 0.50, 10.0) is False
    assert guard.check_run(15.0, 0.50, 10.0) is False


def test_cost_guard_record_run_accumulates():
    guard = CostGuard(per_run_cap=0.50, total_limit=10.0)
    guard.record_run(1.0)
    guard.record_run(2.0)
    assert guard.running_total == pytest.approx(3.0)


def test_cost_guard_raises_when_limit_hit():
    guard = CostGuard(per_run_cap=0.50, total_limit=2.0)
    guard.record_run(1.0)
    with pytest.raises(CostLimitExceeded):
        guard.record_run(1.5)
