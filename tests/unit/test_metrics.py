"""Unit tests for metrics A, F, and G against a hand-computed synthetic dataset.

Synthetic dataset: 2 issues × 3 transforms + original, 1 agent.

  Issue I1:
    original → success
    T1       → success   (matches original)
    T2       → success   (matches original)
    T3       → success   (matches original)
  → SC(I1) = 3/3 = 1.0

  Issue I2:
    original → success
    T1       → failure   (does NOT match)
    T2       → failure   (does NOT match)
    T3       → success   (matches original)
  → SC(I2) = 1/3 ≈ 0.333

Expected values (hand-computed):
  SC(I1)  = 1.0
  SC(I2)  = 1/3

  SS(I1)  = 1.0  (w_A=1.0, no patch similarity)
  SS(I2)  = 1/3
  SS_mean = (1.0 + 1/3) / 2 = 2/3

  TS(T1)  = mean([ 1−1, 1−0 ]) = mean([0, 1]) = 0.5
  TS(T2)  = mean([ 1−1, 1−0 ]) = mean([0, 1]) = 0.5
  TS(T3)  = mean([ 1−1, 1−1 ]) = mean([0, 0]) = 0.0
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.database import create_all
from stableagent.data.models import Experiment, Issue, Metric, Run, TransformedIssue
from stableagent.metrics.engine import MetricsEngine
from stableagent.metrics.sensitivity import TransformationSensitivity
from stableagent.metrics.stability_score import StabilityScore
from stableagent.metrics.success import SuccessConsistency

AGENT = "test_agent"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _build_synthetic_experiment(session) -> tuple[Experiment, Issue, Issue]:
    """Populate the DB with the hand-computed 2×3 synthetic dataset.

    Returns (experiment, issue_I1, issue_I2) so callers can resolve scope_keys.
    """
    exp = Experiment(name="test_exp", config=json.dumps({}), status="completed")
    session.add(exp)
    session.flush()

    i1 = Issue(external_id="I1", source="test", repo_name="test/repo", issue_text="Issue I1")
    i2 = Issue(external_id="I2", source="test", repo_name="test/repo", issue_text="Issue I2")
    session.add_all([i1, i2])
    session.flush()

    # (issue object, transform_name, is_original, status)
    cells = [
        (i1, "original", True,  "success"),
        (i1, "T1",       False, "success"),
        (i1, "T2",       False, "success"),
        (i1, "T3",       False, "success"),
        (i2, "original", True,  "success"),
        (i2, "T1",       False, "failure"),
        (i2, "T2",       False, "failure"),
        (i2, "T3",       False, "success"),
    ]

    for issue, transform, is_orig, status in cells:
        ti = TransformedIssue(
            issue_id=issue.id,
            transformation_name=transform,
            transformed_text=f"Text {issue.external_id} {transform}",
            is_original=is_orig,
        )
        session.add(ti)
        session.flush()

        run = Run(
            experiment_id=exp.id,
            transformed_issue_id=ti.id,
            agent_name=AGENT,
            execution_mode="mock",
            status=status,
        )
        session.add(run)
        session.flush()

    return exp, i1, i2


# ---------------------------------------------------------------------------
# Direct metric class tests (no DB required)
# ---------------------------------------------------------------------------

RUN_DATA = [
    {"agent_name": AGENT, "issue_id": "I1", "is_original": True,  "transformation_name": "original", "status": "success", "patch": None},
    {"agent_name": AGENT, "issue_id": "I1", "is_original": False, "transformation_name": "T1",       "status": "success", "patch": None},
    {"agent_name": AGENT, "issue_id": "I1", "is_original": False, "transformation_name": "T2",       "status": "success", "patch": None},
    {"agent_name": AGENT, "issue_id": "I1", "is_original": False, "transformation_name": "T3",       "status": "success", "patch": None},
    {"agent_name": AGENT, "issue_id": "I2", "is_original": True,  "transformation_name": "original", "status": "success", "patch": None},
    {"agent_name": AGENT, "issue_id": "I2", "is_original": False, "transformation_name": "T1",       "status": "failure", "patch": None},
    {"agent_name": AGENT, "issue_id": "I2", "is_original": False, "transformation_name": "T2",       "status": "failure", "patch": None},
    {"agent_name": AGENT, "issue_id": "I2", "is_original": False, "transformation_name": "T3",       "status": "success", "patch": None},
]


class TestSuccessConsistency:
    def test_sc_i1(self):
        results = SuccessConsistency().compute(RUN_DATA)
        assert results[(AGENT, "I1")] == pytest.approx(1.0)

    def test_sc_i2(self):
        results = SuccessConsistency().compute(RUN_DATA)
        assert results[(AGENT, "I2")] == pytest.approx(1 / 3)

    def test_no_original_run_omitted(self):
        data = [r for r in RUN_DATA if not r["is_original"]]
        results = SuccessConsistency().compute(data)
        assert len(results) == 0

    def test_no_variants_omitted(self):
        data = [r for r in RUN_DATA if r["is_original"]]
        results = SuccessConsistency().compute(data)
        assert len(results) == 0

    def test_all_failure_original(self):
        data = [
            {"agent_name": AGENT, "issue_id": "X", "is_original": True,  "transformation_name": "original", "status": "failure", "patch": None},
            {"agent_name": AGENT, "issue_id": "X", "is_original": False, "transformation_name": "T1",       "status": "failure", "patch": None},
            {"agent_name": AGENT, "issue_id": "X", "is_original": False, "transformation_name": "T2",       "status": "success", "patch": None},
        ]
        results = SuccessConsistency().compute(data)
        # 1 of 2 variants matches the original "failure"
        assert results[(AGENT, "X")] == pytest.approx(0.5)


class TestStabilityScore:
    def test_ss_no_patch_sim_equals_sc(self):
        sc = SuccessConsistency().compute(RUN_DATA)
        ss = StabilityScore().compute(RUN_DATA, sc_results=sc)

        assert ss["per_issue"][(AGENT, "I1")] == pytest.approx(1.0)
        assert ss["per_issue"][(AGENT, "I2")] == pytest.approx(1 / 3)

    def test_ss_mean(self):
        sc = SuccessConsistency().compute(RUN_DATA)
        ss = StabilityScore().compute(RUN_DATA, sc_results=sc)

        assert ss["per_agent"][AGENT] == pytest.approx(2 / 3)

    def test_ss_with_patch_sim(self):
        sc = SuccessConsistency().compute(RUN_DATA)
        patch_sim = {(AGENT, "I1"): 0.9, (AGENT, "I2"): 0.6}
        ss = StabilityScore().compute(RUN_DATA, sc_results=sc, patch_sim_results=patch_sim)

        # I1: 0.7*1.0 + 0.3*0.9 = 0.97
        assert ss["per_issue"][(AGENT, "I1")] == pytest.approx(0.7 * 1.0 + 0.3 * 0.9)
        # I2: 0.7*(1/3) + 0.3*0.6
        assert ss["per_issue"][(AGENT, "I2")] == pytest.approx(0.7 * (1 / 3) + 0.3 * 0.6)


class TestTransformationSensitivity:
    def test_ts_T1(self):
        results = TransformationSensitivity().compute(RUN_DATA)
        # I1: 1−1=0; I2: 1−0=1 → mean=0.5
        assert results[(AGENT, "T1")] == pytest.approx(0.5)

    def test_ts_T2(self):
        results = TransformationSensitivity().compute(RUN_DATA)
        # I1: 1−1=0; I2: 1−0=1 → mean=0.5
        assert results[(AGENT, "T2")] == pytest.approx(0.5)

    def test_ts_T3(self):
        results = TransformationSensitivity().compute(RUN_DATA)
        # I1: 1−1=0; I2: 1−1=0 → mean=0.0
        assert results[(AGENT, "T3")] == pytest.approx(0.0)

    def test_no_original_returns_empty(self):
        data = [r for r in RUN_DATA if not r["is_original"]]
        results = TransformationSensitivity().compute(data)
        assert results == {}


# ---------------------------------------------------------------------------
# MetricsEngine integration tests (uses in-memory SQLite)
# ---------------------------------------------------------------------------


class TestMetricsEngineIntegration:
    def test_engine_stores_correct_number_of_metrics(self, session):
        exp, i1, i2 = _build_synthetic_experiment(session)
        stored = MetricsEngine().compute(exp.id, session)
        # A/F/G: 2 SC + 2 SS(per_issue) + 1 SS(per_agent) + 3 TS = 8, plus 3 flip rates
        # per run: 8 outcome rows (no gold patch here, so no localization rows)
        # exclusions: 3 experiment totals (status, quality warning, no-op) + 3 per-transformation
        # quality-warning counts + 3 per-transformation no-op counts
        # changed-line similarity: 6 variant runs + 3 per-transformation means (no control runs,
        # so no comparison with the control and no noise floor)
        assert len(stored) == 8 + 3 + 8 + 3 + 3 + 3 + 6 + 3

    def test_engine_sc_values(self, session):
        exp, i1, i2 = _build_synthetic_experiment(session)
        MetricsEngine().compute(exp.id, session)

        sc_metrics = (
            session.query(Metric)
            .filter_by(experiment_id=exp.id, metric_name="success_consistency")
            .all()
        )
        assert len(sc_metrics) == 2

        values_by_key = {m.scope_key: m.metric_value for m in sc_metrics}
        assert values_by_key[f"{AGENT}|{i1.external_id}"] == pytest.approx(1.0)
        assert values_by_key[f"{AGENT}|{i2.external_id}"] == pytest.approx(1 / 3)

    def test_engine_ss_mean(self, session):
        exp, i1, i2 = _build_synthetic_experiment(session)
        MetricsEngine().compute(exp.id, session)

        mean_metric = (
            session.query(Metric)
            .filter_by(
                experiment_id=exp.id,
                metric_name="stability_score_mean",
                scope="agent",
                scope_key=AGENT,
            )
            .one()
        )
        assert mean_metric.metric_value == pytest.approx(2 / 3)

    def test_engine_ts_values(self, session):
        exp, i1, i2 = _build_synthetic_experiment(session)
        MetricsEngine().compute(exp.id, session)

        ts_metrics = (
            session.query(Metric)
            .filter_by(experiment_id=exp.id, metric_name="transformation_sensitivity")
            .all()
        )
        assert len(ts_metrics) == 3

        by_key = {m.scope_key: m.metric_value for m in ts_metrics}
        assert by_key[f"{AGENT}|T1"] == pytest.approx(0.5)
        assert by_key[f"{AGENT}|T2"] == pytest.approx(0.5)
        assert by_key[f"{AGENT}|T3"] == pytest.approx(0.0)

    def test_engine_skips_dry_run_rows(self, session):
        exp, i1, _ = _build_synthetic_experiment(session)

        # Add a dry_run_skipped run for I1/T1 — should not affect any metric
        ti = (
            session.query(TransformedIssue)
            .filter_by(issue_id=i1.id, transformation_name="T1")
            .first()
        )
        run = Run(
            experiment_id=exp.id,
            transformed_issue_id=ti.id,
            agent_name=AGENT,
            execution_mode="dry_run",
            status="dry_run_skipped",
        )
        session.add(run)
        session.flush()

        MetricsEngine().compute(exp.id, session)

        sc_metrics = (
            session.query(Metric)
            .filter_by(experiment_id=exp.id, metric_name="success_consistency")
            .all()
        )
        by_key = {m.scope_key: m.metric_value for m in sc_metrics}
        # I1 SC should still be 1.0 — the skipped row must be ignored
        assert by_key[f"{AGENT}|{i1.external_id}"] == pytest.approx(1.0)

    def test_engine_empty_experiment_returns_no_metrics(self, session):
        exp = Experiment(name="empty", config=json.dumps({}), status="completed")
        session.add(exp)
        session.flush()

        stored = MetricsEngine().compute(exp.id, session)
        assert stored == []
