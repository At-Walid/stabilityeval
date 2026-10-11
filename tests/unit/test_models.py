"""Unit tests for SQLAlchemy ORM models and database layer."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.database import create_all
from stableagent.data.models import (
    Experiment,
    ExportArtifact,
    Issue,
    Metric,
    Run,
    TransformedIssue,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_issue(**kwargs) -> Issue:
    defaults = dict(
        source="swebench_lite",
        repo_name="django/django",
        issue_text="Something is broken.",
    )
    defaults.update(kwargs)
    return Issue(**defaults)


def make_transformed(issue: Issue, name: str = "paraphrase", is_original: bool = False) -> TransformedIssue:
    return TransformedIssue(
        issue_id=issue.id,
        transformation_name=name,
        transformed_text=f"Transformed by {name}.",
        is_original=is_original,
    )


def make_experiment(**kwargs) -> Experiment:
    defaults = dict(
        name="test_experiment",
        config=json.dumps({"execution_mode": "mock"}),
        status="pending",
    )
    defaults.update(kwargs)
    return Experiment(**defaults)


def make_run(experiment: Experiment, transformed_issue: TransformedIssue, **kwargs) -> Run:
    defaults = dict(
        experiment_id=experiment.id,
        transformed_issue_id=transformed_issue.id,
        agent_name="mock_replay",
        execution_mode="mock",
        status="completed",
    )
    defaults.update(kwargs)
    return Run(**defaults)


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------

class TestIssue:
    def test_create_minimal(self, session):
        issue = make_issue()
        session.add(issue)
        session.commit()

        fetched = session.get(Issue, issue.id)
        assert fetched is not None
        assert fetched.repo_name == "django/django"
        assert fetched.source == "swebench_lite"
        assert fetched.created_at is not None

    def test_optional_fields_default_none(self, session):
        issue = make_issue()
        session.add(issue)
        session.commit()

        fetched = session.get(Issue, issue.id)
        assert fetched.reproduction_steps is None
        assert fetched.expected_behavior is None
        assert fetched.relevant_tests is None
        assert fetched.metadata_ is None

    def test_metadata_stored_as_json_string(self, session):
        meta = json.dumps({"key": "value"})
        issue = make_issue(metadata_=meta)
        session.add(issue)
        session.commit()

        fetched = session.get(Issue, issue.id)
        assert json.loads(fetched.metadata_) == {"key": "value"}


# ---------------------------------------------------------------------------
# TransformedIssue
# ---------------------------------------------------------------------------

class TestTransformedIssue:
    def test_create_and_link_to_issue(self, session):
        issue = make_issue()
        session.add(issue)
        session.flush()

        ti = make_transformed(issue)
        session.add(ti)
        session.commit()

        fetched = session.get(TransformedIssue, ti.id)
        assert fetched.issue_id == issue.id
        assert fetched.transformation_name == "paraphrase"
        assert fetched.quality_warning is False
        assert fetched.is_original is False

    def test_is_original_flag(self, session):
        issue = make_issue()
        session.add(issue)
        session.flush()

        ti = make_transformed(issue, name="original", is_original=True)
        session.add(ti)
        session.commit()

        fetched = session.get(TransformedIssue, ti.id)
        assert fetched.is_original is True

    def test_relationship_issue_to_transformed(self, session):
        issue = make_issue()
        session.add(issue)
        session.flush()

        t1 = make_transformed(issue, name="paraphrase")
        t2 = make_transformed(issue, name="verbosity_reduction")
        session.add_all([t1, t2])
        session.commit()

        session.expire(issue)
        assert len(issue.transformed_issues) == 2


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

class TestExperiment:
    def test_create(self, session):
        exp = make_experiment()
        session.add(exp)
        session.commit()

        fetched = session.get(Experiment, exp.id)
        assert fetched.name == "test_experiment"
        assert fetched.status == "pending"
        assert fetched.total_cost_usd == 0.0

    def test_status_lifecycle(self, session):
        exp = make_experiment()
        session.add(exp)
        session.commit()

        exp.status = "running"
        session.commit()
        assert session.get(Experiment, exp.id).status == "running"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class TestRun:
    def _setup(self, session):
        issue = make_issue()
        session.add(issue)
        session.flush()
        ti = make_transformed(issue)
        session.add(ti)
        session.flush()
        exp = make_experiment()
        session.add(exp)
        session.flush()
        return exp, ti

    def test_create_run(self, session):
        exp, ti = self._setup(session)
        run = make_run(exp, ti)
        session.add(run)
        session.commit()

        fetched = session.get(Run, run.id)
        assert fetched.agent_name == "mock_replay"
        assert fetched.status == "completed"
        assert fetched.run_index == 0

    def test_reruns_create_new_records(self, session):
        """Re-running the same (experiment, transformed_issue, agent) must produce separate rows."""
        exp, ti = self._setup(session)

        run1 = make_run(exp, ti, run_index=0, patch="--- a\n+++ b")
        run2 = make_run(exp, ti, run_index=1, patch="--- a\n+++ c")
        session.add_all([run1, run2])
        session.commit()

        assert run1.id != run2.id

        runs = session.query(Run).filter_by(
            experiment_id=exp.id,
            transformed_issue_id=ti.id,
        ).all()
        assert len(runs) == 2
        patches = {r.patch for r in runs}
        assert "--- a\n+++ b" in patches
        assert "--- a\n+++ c" in patches

    def test_run_relationships(self, session):
        exp, ti = self._setup(session)
        run = make_run(exp, ti)
        session.add(run)
        session.commit()

        session.expire(exp)
        assert len(exp.runs) == 1
        assert exp.runs[0].id == run.id

        session.expire(run)
        assert run.experiment.id == exp.id
        assert run.transformed_issue.id == ti.id


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------

class TestMetric:
    def test_create_experiment_scoped_metric(self, session):
        exp = make_experiment()
        session.add(exp)
        session.flush()

        metric = Metric(
            experiment_id=exp.id,
            scope="experiment",
            scope_key=exp.id,
            metric_name="stability_score",
            metric_value=0.73,
        )
        session.add(metric)
        session.commit()

        fetched = session.get(Metric, metric.id)
        assert fetched.metric_value == pytest.approx(0.73)
        assert fetched.scope == "experiment"

    def test_create_run_scoped_metric(self, session):
        issue = make_issue()
        session.add(issue)
        session.flush()
        ti = make_transformed(issue)
        session.add(ti)
        session.flush()
        exp = make_experiment()
        session.add(exp)
        session.flush()
        run = make_run(exp, ti)
        session.add(run)
        session.flush()

        metric = Metric(
            experiment_id=exp.id,
            scope="run",
            scope_key=run.id,
            metric_name="cost_usd",
            metric_value=0.05,
        )
        session.add(metric)
        session.commit()

        fetched = session.get(Metric, metric.id)
        assert fetched.scope_key == run.id

    def test_experiment_has_metrics_relationship(self, session):
        exp = make_experiment()
        session.add(exp)
        session.flush()

        for name, val in [("stability_score", 0.7), ("sensitivity_t03", 0.6)]:
            session.add(Metric(
                experiment_id=exp.id, scope="experiment",
                scope_key=exp.id, metric_name=name, metric_value=val,
            ))
        session.commit()

        session.expire(exp)
        assert len(exp.metrics) == 2


# ---------------------------------------------------------------------------
# ExportArtifact
# ---------------------------------------------------------------------------

class TestExportArtifact:
    def test_create(self, session):
        exp = make_experiment()
        session.add(exp)
        session.flush()

        artifact = ExportArtifact(
            experiment_id=exp.id,
            artifact_type="csv",
            file_path="./results/runs.csv",
            file_size_bytes=4096,
        )
        session.add(artifact)
        session.commit()

        fetched = session.get(ExportArtifact, artifact.id)
        assert fetched.artifact_type == "csv"
        assert fetched.file_size_bytes == 4096

    def test_experiment_relationship(self, session):
        exp = make_experiment()
        session.add(exp)
        session.flush()

        for atype in ("csv", "json", "report_md"):
            session.add(ExportArtifact(
                experiment_id=exp.id,
                artifact_type=atype,
                file_path=f"./results/{atype}",
            ))
        session.commit()

        session.expire(exp)
        assert len(exp.export_artifacts) == 3
