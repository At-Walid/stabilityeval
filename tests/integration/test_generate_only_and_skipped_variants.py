"""`stableagent run --generate-only`, and no agent call on excluded or no-op variants.

Real mode with every API call faked (no network): Haiku answers per transformation, and the LLM
Baseline's ``run`` counts its calls. The issue is SWE-bench Lite astropy__astropy-12907, verbatim
from the bundled dataset file.
"""
from __future__ import annotations

import re
from contextlib import contextmanager

import pytest
from rich.console import Console
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from stableagent.agents.base import AgentOutput
from stableagent.agents.llm_baseline import LLMBaselineAdapter
from stableagent.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.data.database import create_all
from stableagent.data.loaders.swebench import load_bundle, store_instances
from stableagent.data.models import Base, Experiment, Metric, Run, TransformedIssue
from stableagent.execution.runner import SKIPPED_VARIANT, ExperimentRunner
from stableagent.metrics.engine import MetricsEngine
from stableagent.transformations.llm_backed._api import HaikuReply
from stableagent.transformations.masking import mask_code

ISSUE_ID = "astropy__astropy-12907"
INSTANCE = load_bundle([ISSUE_ID])[0]
MASKED = mask_code(INSTANCE.problem_statement)
GOLD_FILE = "astropy/modeling/separable.py"
PATCH = f"--- a/{GOLD_FILE}\n+++ b/{GOLD_FILE}\n@@ -1 +1 @@\n-a\n+b\n"
TRANSFORMATIONS = ["paraphrase", "verbosity_reduction", "neutralize_emotional", "reordering"]
COST = 0.0021  # per fake Haiku call


@pytest.fixture()
def env(tmp_path, monkeypatch, no_network):
    engine = create_engine(f"sqlite:///{tmp_path / 'pilot.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        store_instances(db, [INSTANCE])
        db.commit()

    calls = {"haiku": [], "agent": []}

    def fake_haiku(system_prompt, user_content, api_key, model=None, *, expect_json=True,
                   retry=None):
        calls["haiku"].append(retry)
        if "Shorten" in system_prompt:  # verbosity_reduction: shorter prose, every placeholder
            reply = user_content.replace("This feels like a bug to me, but I might be missing "
                                         "something?", "Looks like a bug.")
        elif "emotional" in system_prompt:  # neutralize_emotional: nothing to neutralize
            reply = user_content
        else:  # paraphrase: always drops a code block
            reply = user_content.replace("[[CODE_3]]", "the matrix")
        return HaikuReply(reply, "fake", cost_usd=COST)

    def fake_run(self, agent_input, mode):
        calls["agent"].append(agent_input.metadata["transformation_name"])
        return AgentOutput(status="success", patch=PATCH, cost_usd=0.01, runtime_seconds=0.1)

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", fake_haiku)
    monkeypatch.setattr(LLMBaselineAdapter, "run", fake_run)
    yield Session, calls
    engine.dispose()


def _config(**overrides) -> ExperimentConfig:
    values = dict(
        experiment_name="pilot_test",
        execution_mode="real",
        agents=[AgentConfig(name="llm_baseline", params={"model": "claude-sonnet-4-6"})],
        issues=IssueConfig(issue_ids=[ISSUE_ID]),
        transformations=[TransformationConfig(name=name) for name in TRANSFORMATIONS],
        control_repeats=0,
    )
    return ExperimentConfig(**{**values, **overrides})


# ── The runner never pays for a run on an excluded or no-op variant ──────────

def test_excluded_and_no_op_variants_are_recorded_but_never_run(env):
    Session, calls = env
    with Session() as db:
        experiment = ExperimentRunner(_config(), db).run()
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        runs = {
            run.transformed_issue.transformation_name: run
            for run in db.query(Run).filter_by(experiment_id=experiment.id)
        }
        statuses = {name: run.status for name, run in runs.items()}
        skipped = runs["paraphrase"]
        metrics = {m.metric_name: m.metric_value for m in db.query(Metric)
                   .filter_by(experiment_id=experiment.id, scope="experiment")}

        assert experiment.status == "completed"
        assert statuses == {
            "original": "success",
            "verbosity_reduction": "success",
            "paraphrase": SKIPPED_VARIANT,  # placeholder lost twice: excluded
            "neutralize_emotional": SKIPPED_VARIANT,  # unchanged: a no-op
            "reordering": "success",
        }
        assert skipped.cost_usd == 0.0 and skipped.started_at is None
        assert skipped.error_message.startswith("Not run: variant excluded (placeholder_lost:")
        assert runs["neutralize_emotional"].error_message.startswith("Not run: no-op variant")
        assert experiment.total_cost_usd == pytest.approx(0.03)  # the three agent runs only
        # Counted under the variant's reason, not as runs that failed to complete.
        assert metrics["excluded_runs_quality_warning"] == 1
        assert metrics["excluded_runs_noop"] == 1
        assert metrics["excluded_runs_status"] == 0
    assert sorted(calls["agent"]) == ["original", "reordering", "verbosity_reduction"]


# ── --generate-only ───────────────────────────────────────────────────────────

def _invoke(Session, monkeypatch, tmp_path, *args):
    from stableagent.cli import main as cli

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
    monkeypatch.setattr(cli, "_inject_truststore", lambda: None)
    monkeypatch.setattr(cli, "console", Console(width=250))  # no wrapping of long table rows
    path = tmp_path / "config.json"
    path.write_text(_config().model_dump_json(), encoding="utf-8")
    return CliRunner().invoke(cli.app, ["run", "--config", str(path), *args], terminal_width=250)


def test_generate_only_prints_every_variant_and_calls_no_agent(env, monkeypatch, tmp_path):
    Session, calls = env
    result = _invoke(Session, monkeypatch, tmp_path, "--generate-only")

    assert result.exit_code == 0, result.output
    out = result.output
    assert "no agent call, no experiment record" in out
    rows = [re.split(r"[│|]", line) for line in out.splitlines() if ISSUE_ID in line]
    lines = {cells[2].strip(): "|".join(cells) for cells in rows if len(cells) >= 6}
    assert set(lines) == set(TRANSFORMATIONS)
    assert " ok " in lines["verbosity_reduction"] and f"${COST:.4f}" in lines["verbosity_reduction"]
    assert "excluded" in lines["paraphrase"]
    assert "placeholder_lost: [[CODE_3]] missing" in lines["paraphrase"]
    assert f"${2 * COST:.4f}" in lines["paraphrase"]  # two attempts, never three
    assert "noop" in lines["neutralize_emotional"]
    assert " ok " in lines["reordering"] and "$0.0000" in lines["reordering"]
    assert f"Generation cost: ${4 * COST:.4f} for 4 variant(s) generated now; 0 from the cache" in out
    assert "No agent was called." in out
    assert calls["agent"] == [] and len(calls["haiku"]) == 4
    with Session() as db:
        assert db.query(Experiment).count() == 0 and db.query(Run).count() == 0
        assert db.query(TransformedIssue).filter_by(is_original=False).count() == 4


def test_a_second_generate_only_serves_every_variant_from_the_cache(env, monkeypatch, tmp_path):
    Session, calls = env
    _invoke(Session, monkeypatch, tmp_path, "--generate-only")
    calls["haiku"].clear()

    result = _invoke(Session, monkeypatch, tmp_path, "--generate-only")

    assert result.exit_code == 0, result.output
    assert result.output.count("(cached)") == 4
    assert "Generation cost: $0.0000 for 0 variant(s) generated now; 4 from the cache" in (
        result.output
    )
    assert calls["haiku"] == [] and calls["agent"] == []


def test_generate_only_and_estimate_are_exclusive(env, monkeypatch, tmp_path):
    Session, calls = env
    result = _invoke(Session, monkeypatch, tmp_path, "--generate-only", "--estimate")
    assert result.exit_code == 1 and "not both" in result.output
    assert calls == {"haiku": [], "agent": []}


def test_generate_only_needs_no_variant_in_originals_only_mode(env, monkeypatch, tmp_path):
    Session, calls = env
    result = _invoke(Session, monkeypatch, tmp_path, "--generate-only", "--originals-only")
    assert result.exit_code == 0 and "no variant to generate" in result.output
    assert calls == {"haiku": [], "agent": []}


# ── The generation cost is recorded per variant ──────────────────────────────

def test_older_databases_gain_the_generation_cost_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transformed_issues DROP COLUMN generation_cost_usd"))

    create_all(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("transformed_issues")}
    assert "generation_cost_usd" in columns
    engine.dispose()


def test_the_model_never_sees_the_code_of_the_issue(env, monkeypatch):
    Session, _calls = env
    seen = []

    def spy(system_prompt, user_content, api_key, model=None, **_):
        seen.append(user_content)
        return HaikuReply(user_content.replace("Consider", "Take"), cost_usd=COST)

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", spy)
    with Session() as db:
        ExperimentRunner(_config(transformations=[TransformationConfig(name="paraphrase")]),
                         db).run()
        variant = db.query(TransformedIssue).filter_by(transformation_name="paraphrase").one()
        assert "Take the following model:" in variant.transformed_text
        for code in MASKED.originals.values():
            assert variant.transformed_text.count(code) == 1
    assert seen == [MASKED.text]
    assert "separability_matrix(" not in seen[0] and "```" not in seen[0]
