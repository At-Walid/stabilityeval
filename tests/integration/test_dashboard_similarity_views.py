"""The RQ2 changed-line similarity table and dot plot, and the issue detail view, rendered by
Streamlit's AppTest from an experiment replayed from the committed pilot fixtures. Offline."""
from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

import stableagent
from stableagent.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.dashboard import _db
from stableagent.data import database
from stableagent.data.loaders.swebench import load_bundle, store_instances
from stableagent.data.models import Base
from stableagent.execution.runner import ExperimentRunner
from stableagent.metrics.engine import MetricsEngine

FIXTURES = Path(stableagent.__file__).parent / "fixtures" / "mock_responses"
ISSUES = ["mwaskom__seaborn-3010", "psf__requests-2317"]


@pytest.fixture()
def experiment_id(tmp_path, monkeypatch, no_network):
    engine = database.build_engine(f"sqlite:///{tmp_path / 'views.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(_db, "build_engine", lambda *a, **k: engine)
    st.cache_data.clear()
    with sessionmaker(bind=engine)() as db:
        store_instances(db, load_bundle(ISSUES))
        db.commit()
        config = ExperimentConfig(
            experiment_name="views",
            execution_mode="mock",
            agents=[AgentConfig(name="mock_replay", params={"fixtures_dir": str(FIXTURES)})],
            issues=IssueConfig(issue_ids=ISSUES),
            transformations=[TransformationConfig(name="paraphrase"),
                             TransformationConfig(name="reordering", params={"seed": 42})],
            control_repeats=1,
        )
        experiment = ExperimentRunner(config, db).run()
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        yield experiment.id
    st.cache_data.clear()
    engine.dispose()


def test_a_dashboard_mock_run_replays_the_recorded_control_runs(tmp_path, monkeypatch, no_network):
    from stableagent.config.settings import settings
    from stableagent.dashboard import _runner
    from stableagent.data.models import Metric, Run

    engine = database.build_engine(f"sqlite:///{tmp_path / 'mock.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(_runner, "build_engine", lambda *a, **k: engine)
    monkeypatch.setattr(settings, "FIXTURES_DIR", str(FIXTURES))
    with sessionmaker(bind=engine)() as db:
        store_instances(db, load_bundle(ISSUES))
        db.commit()
    experiment_id = _runner.run_mock_experiment(
        issues=[{"issue_id": issue_id} for issue_id in ISSUES],
        selected_transforms=["paraphrase", "reordering"],
        experiment_name="dashboard replay",
    )
    with sessionmaker(bind=engine)() as db:
        controls = db.query(Run).filter_by(experiment_id=experiment_id, control_repeat=True).all()
        noise_floor = db.query(Metric).filter_by(
            experiment_id=experiment_id, metric_name="control_changed_line_similarity"
        ).one()
        assert len(controls) == 2
        assert noise_floor.metric_value is not None
    engine.dispose()


def _page(exp_id: str) -> None:
    from stableagent.dashboard._db import load_metrics_df, load_runs_df
    from stableagent.dashboard._results import render_results

    render_results(exp_id, load_runs_df(exp_id), load_metrics_df(exp_id))


def test_rq2_puts_the_similarity_table_and_plot_before_sensitivity(experiment_id):
    at = AppTest.from_function(_page, args=(experiment_id,), default_timeout=30).run()
    assert not at.exception

    headings = [m.value for m in at.markdown if m.value.startswith("#### ")]
    assert headings == ["#### Changed-line similarity to the original",
                        "#### Outcome sensitivity (G) and flip rate"]
    tables = [df.value for df in at.dataframe]
    similarity = next(t for t in tables if "Wilcoxon p (exploratory)" in t.columns)
    assert similarity["Variant"].tolist()[0] == "Repeat of original"
    assert set(similarity["Variant"]) == {"Repeat of original", "Paraphrase", "Reordering"}
    assert any("Flip rate" in t.columns for t in tables)  # TS and the flip rate stay on the page
    assert len(at.get("plotly_chart")) == 2  # the dot plot, then the TS bar chart
    assert any("noise floor" in c.value for c in at.caption)


def test_issue_detail_opens_on_requests_2317_reordering_with_the_differences_marked(experiment_id):
    at = AppTest.from_function(_page, args=(experiment_id,), default_timeout=30).run()
    assert not at.exception

    issue = next(s for s in at.selectbox if s.label == "Select issue"
                 and s.key.endswith("_tab_patches_issue_sel"))
    variant = next(s for s in at.selectbox if s.label == "Compare the original's patch with")
    assert issue.value == "psf__requests-2317"
    assert variant.value == "Reordering"
    assert "Repeat of original" in variant.options

    html = [element.proto.body for element in at.get("html")]
    table = next(body for body in html if "Original issue — patch" in body)
    assert "Reordering — patch" in table
    assert "<mark" in table or "rgba(220, 38, 38, 0.12)" in table  # a difference is highlighted
    assert any("changed-line similarity" in m.value for m in at.markdown)

    variant.set_value("Repeat of original").run()
    assert not at.exception
    html = [element.proto.body for element in at.get("html")]
    assert any("Repeat of original — patch" in body for body in html)
