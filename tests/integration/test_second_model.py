"""A second model on the ICSE pilot: same variants, per-agent analysis, fixtures, dashboard.

On a copy of the shipped pilot database (it holds experiment bc6f1372), configs/
icse_pilot_model2.json runs in real mode against a fake OpenAI client (no network, no key):

- every variant is the very row the pilot ran on (never looked up in the cache or generated),
  the 12 excluded / no-op variants are skipped, 148 calls reach the model, and the estimate says
  so beforehand (148 agent runs, 0 variants to generate);
- a variant the pilot lacks, a missing reference experiment or other params stop the run before
  anything is recorded;
- the per-agent comparison compares each model with its own original only; the RQ2 figure
  (fig_results.pdf, 3.5 in wide) and the combined table come out of it, also through
  scripts/analyze_patch_similarity.py and the Past Experiments page;
- recording the model-2 runs writes a fixture set of their own (gpt-4o/), and mock mode replays
  them to identical runs and metrics.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

import stableagent
from stableagent.agents.llm_baseline import build_user_message
from stableagent.agents.base import AgentInput
from stableagent.config.experiment_schema import ExperimentConfig
from stableagent.config.pricing import model_info
from stableagent.config.settings import settings
from stableagent.data import database
from stableagent.data.models import Experiment, Issue, Metric, Run, TransformedIssue
from stableagent.execution.plan import plan_runs, preflight
from stableagent.execution.reuse import VariantReuseError
from stableagent.execution.runner import ExperimentRunner
from stableagent.export.comparison_table import table_rows
from stableagent.export.figures import rq2_figure, save_rq2_figure
from stableagent.fixtures.recorder import record_experiment_fixtures
from stableagent.metrics.changed_line_similarity import changed_line_similarity
from stableagent.metrics.comparison import CONTROL, compare_experiments
from stableagent.metrics.engine import MetricsEngine
from stableagent.transformations.cache import TransformationCache
from stableagent.transformations.registry import transformation_registry
from tests.llm_fakes import FakeOpenAI, Reply

REPO = Path(__file__).resolve().parents[2]
PILOT = "bc6f1372-2088-45dd-907c-d741c0545d27"
SHIPPED_DB = REPO / "data" / "pilot" / "stableagent_pilot.db"
CONFIG = REPO / "configs" / "icse_pilot_model2.json"
MAIN_PAGE = str(Path(stableagent.__file__).parent / "dashboard" / "StableAgent.py")


def _config(**changes) -> ExperimentConfig:
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw.update(changes)
    return ExperimentConfig.model_validate(raw)


def original_patch(issue_id: str) -> str:
    return f"--- a/pkg/{issue_id}.py\n+++ b/pkg/{issue_id}.py\n@@ -1 +1 @@\n-old\n+fixed()\n"


def variant_patch(issue_id: str, text: str) -> str:
    return original_patch(issue_id) + f"@@ -9 +9 @@\n-keep\n+variant_{len(text) % 97}()\n"


class Model2:
    """The fake GPT-4o: the original's text (original and control runs) gets one patch per issue,
    a variant's text another, so a repeat is identical to its own original."""

    def __init__(self, originals: dict[str, str]):
        self.by_message = {
            build_user_message(AgentInput(issue_text=text, repo_name=repo)): issue_id
            for issue_id, (text, repo) in originals.items()
        }
        self.fake = FakeOpenAI(respond=self.respond)

    def respond(self, request: dict) -> Reply:
        message = request["messages"][1]["content"]
        issue_id = self.by_message.get(message)
        if issue_id is not None:
            return Reply(diff=original_patch(issue_id), input_tokens=1500, output_tokens=300)
        issue_id = message.split("\n", 1)[0].removeprefix("Repository: ").replace("/", "__")
        return Reply(diff=variant_patch(issue_id, message), input_tokens=1500, output_tokens=300)


def _no_generation(monkeypatch) -> None:
    """Any cache lookup or generation of a variant fails the test."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a variant was looked up or generated")

    monkeypatch.setattr(TransformationCache, "variant", forbidden)
    for name in transformation_registry.list_names():
        monkeypatch.setattr(transformation_registry.get(name), "transform", forbidden)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """The shipped pilot database plus one model-2 experiment run against the fake OpenAI."""
    tmp = tmp_path_factory.mktemp("model2")
    db_path = tmp / "pilot.db"
    shutil.copy(SHIPPED_DB, db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    config = _config()
    with Session() as db:
        originals = {
            issue.external_id: (issue.issue_text, issue.repo_name)
            for issue in db.query(Issue).filter(Issue.external_id.in_(config.issues.issue_ids))
        }
        pinned_texts = [
            ti.transformed_text
            for run, ti in db.query(Run, TransformedIssue)
            .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
            .filter(Run.experiment_id == PILOT, Run.status != "skipped_variant")
        ]
    model2 = Model2(originals)
    with pytest.MonkeyPatch.context() as monkeypatch:
        model2.fake.install(monkeypatch)
        _no_generation(monkeypatch)
        with Session() as db:
            check = preflight(config, db)
            experiment = ExperimentRunner(config, db).run()
            MetricsEngine().compute(experiment.id, db)
            db.commit()
            experiment_id = experiment.id
    yield {
        "Session": Session, "engine": engine, "tmp": tmp, "db_path": db_path,
        "experiment_id": experiment_id, "requests": model2.fake.requests,
        "clients": model2.fake.clients, "preflight": check, "pinned_texts": pinned_texts,
        "config": config,
    }
    engine.dispose()


def _cells(db, experiment_id: str) -> dict[tuple, tuple[Run, TransformedIssue]]:
    rows = (
        db.query(Run, TransformedIssue, Issue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .join(Issue, TransformedIssue.issue_id == Issue.id)
        .filter(Run.experiment_id == experiment_id)
        .all()
    )
    return {
        (issue.external_id, ti.transformation_name, run.control_repeat): (run, ti)
        for run, ti, issue in rows
    }


# ── Same variants, no regeneration ────────────────────────────────────────────

def test_the_estimate_counts_148_agent_runs_and_no_variant_to_generate(world):
    check, config = world["preflight"], world["config"]
    plan = plan_runs(config)
    assert (plan.originals, plan.variants, plan.controls, plan.total) == (20, 120, 20, 160)
    assert check.agent_runs(plan) == 148
    assert len(check.skipped_variants) == 12
    assert check.variants_to_generate == [] and check.reused_variants == 120
    assert check.reuse_error is None and check.missing_issues == [] == check.without_gold


def test_the_second_model_runs_on_exactly_the_pilot_variants(world):
    with world["Session"]() as db:
        pilot, model2 = _cells(db, PILOT), _cells(db, world["experiment_id"])
        experiment = db.get(Experiment, world["experiment_id"])
        assert experiment.status == "completed"
        assert model2.keys() == pilot.keys() and len(model2) == 160
        for cell, (run, ti) in model2.items():
            assert ti.id == pilot[cell][1].id  # the very variant row, originals included
            assert run.status == pilot[cell][0].status  # skipped exactly where the pilot was
            assert run.agent_name == "llm_baseline"
        statuses = [run.status for run, _ti in model2.values()]
        assert statuses.count("skipped_variant") == 12 and statuses.count("success") == 148
        assert experiment.total_cost_usd == pytest.approx(
            148 * model_info("gpt-4o").cost(1500, 300)
        )

    # 148 calls, each with the pilot's text: 40 on the originals (20 + 20 repeats), 108 variants.
    requests = world["requests"]
    assert len(requests) == 148 and {r["model"] for r in requests} == {"gpt-4o"}
    variant_messages = sorted(
        r["messages"][1]["content"] for r in requests
        if r["messages"][1]["content"].split("Issue:\n", 1)[1] in set(world["pinned_texts"])
    )
    assert len(variant_messages) == 148  # every request text is one the pilot ran on
    assert all(r["tool_choice"] == {"type": "function", "function": {"name": "submit_patch"}}
               for r in requests)


def test_reuse_fails_before_anything_runs_when_a_variant_would_be_generated(
    world, monkeypatch
):
    fake = FakeOpenAI().install(monkeypatch)
    _no_generation(monkeypatch)
    extra = world["config"].issues.issue_ids + ["django__django-11099"]  # not in the pilot
    cases = {
        "an issue the pilot never ran": _config(issues={"source": "swebench_lite",
                                                        "issue_ids": extra}),
        "an unknown reference experiment": _config(reuse_variants_from="0000-not-there"),
        "other params": _config(transformations=[
            {"name": "typo_injection", "enabled": True, "params": {"error_rate": 0.03}},
        ]),
    }
    messages = {}
    with world["Session"]() as db:
        before = db.query(Experiment).count()
        for case, config in cases.items():
            with pytest.raises(VariantReuseError) as excinfo:
                ExperimentRunner(config, db).run()
            messages[case] = str(excinfo.value)
        assert db.query(Experiment).count() == before  # nothing was recorded
    assert fake.requests == []
    assert "django__django-11099/paraphrase: no run in bc6f1372" in messages[
        "an issue the pilot never ran"]
    assert "would have to be generated" in messages["an issue the pilot never ran"]
    assert "not in this database" in messages["an unknown reference experiment"]
    assert '{"error_rate": 0.02}' in messages["other params"]
    assert all(message.endswith("Nothing was run.") for message in messages.values())


def test_a_missing_openai_key_stops_the_run_before_anything_is_recorded(
    world, monkeypatch, no_openai_key
):
    from stableagent.agents.llm_baseline import MissingAPIKeyError

    fake = FakeOpenAI().install(monkeypatch)
    with world["Session"]() as db:
        before = db.query(Experiment).count()
        with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY"):
            ExperimentRunner(world["config"], db).run()
        assert db.query(Experiment).count() == before
    assert fake.requests == []


# ── Per-agent analysis ────────────────────────────────────────────────────────

def test_each_model_is_compared_with_its_own_original_only(world):
    with world["Session"]() as db:
        pilot, model2 = compare_experiments([PILOT, world["experiment_id"]], db)
        cells = _cells(db, world["experiment_id"])

    assert pilot.agent.label == "LLM Baseline (Claude Sonnet 4.6)"
    assert model2.agent.label == "LLM Baseline (GPT-4o)"
    # The pilot's numbers do not move when another model is analysed next to it.
    assert pilot.control.similarity.mean == pytest.approx(0.7544407585265137, abs=1e-12)
    assert pilot.row("paraphrase").similarity.mean == pytest.approx(0.5407067581808555, abs=1e-12)
    # The fake model repeats its own original exactly: 1.0 against its own original (against the
    # pilot's original patches it would be far lower).
    assert model2.control.similarity.mean == 1.0 and model2.control.n == 20
    run, ti = cells[("psf__requests-2317", "paraphrase", False)]
    expected = changed_line_similarity(original_patch("psf__requests-2317"), run.patch)
    assert model2.row("paraphrase").similarity.per_issue["psf__requests-2317"] == expected
    assert expected < 1.0
    # RQ1 per agent
    assert (model2.originals_localized, model2.originals_scored) == (0, 20)  # fake files
    assert model2.variants_scored == 108 and model2.variants_kept == 108
    assert (pilot.variants_kept, pilot.variants_scored) == (107, 108)


def test_the_metrics_engine_stores_the_second_models_metrics_per_agent(world):
    with world["Session"]() as db:
        metrics = {
            (m.scope_key, m.metric_name): m.metric_value
            for m in db.query(Metric).filter_by(experiment_id=world["experiment_id"])
            if m.scope != "run"
        }
    assert metrics[("llm_baseline", "control_changed_line_similarity")] == 1.0
    assert metrics[("llm_baseline|reordering", "excluded_noop")] == 1
    assert ("llm_baseline|paraphrase", "changed_line_similarity_vs_control") in metrics


def test_the_rq2_figure_is_one_ieee_column_with_one_marker_style_per_model(world):
    with world["Session"]() as db:
        comparisons = compare_experiments([PILOT, world["experiment_id"]], db)
    figure = rq2_figure(comparisons)
    assert tuple(figure.get_size_inches())[0] == 3.5
    ax = figure.axes[0]
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert labels[0] == "Repeat of original" and len(labels) == 7
    markers = {(line.get_marker(), line.get_color()) for line in ax.get_lines()
               if line.get_marker() not in (None, "None", "", "|")}  # "|": error-bar caps
    assert {m for m, _c in markers} == {"o", "s"} and len({c for _m, c in markers}) == 2
    dashed = [line for line in ax.get_lines() if line.get_xdata()[0] == line.get_xdata()[-1]
              and len(set(line.get_ydata())) > 1]
    assert len(dashed) == 2  # one repeat-mean line per model
    pdf = save_rq2_figure(figure, world["tmp"] / "fig_results.pdf").read_bytes()
    assert re.search(rb"/MediaBox \[ 0 0 252 ", pdf)  # 3.5 in = 252 pt
    assert b"/Type3" not in pdf  # TrueType fonts only

    rows = table_rows(comparisons)
    assert len(rows) == 14 and [r["model"] for r in rows[:1] + rows[7:8]] == [
        "Claude Sonnet 4.6", "GPT-4o"]
    assert rows[0]["transformation"] == rows[7]["transformation"] == CONTROL
    assert rows[7]["Diff vs repeat [95% CI]"] == "reference"
    paraphrase = next(r for r in rows if r["model"] == "GPT-4o"
                      and r["transformation"] == "paraphrase")
    assert paraphrase["n"] == 20 and paraphrase["Outcome kept"] == "20/20"
    assert paraphrase["wilcoxon_p"] is not None and paraphrase["diff_vs_repeat"] < 0


def test_the_analysis_script_writes_the_figure_and_the_tables(world, monkeypatch, capsys):
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import analyze_patch_similarity as script
    finally:
        sys.path.remove(str(REPO / "scripts"))
    out = world["tmp"] / "paper"
    monkeypatch.setattr(sys, "argv", [
        "analyze_patch_similarity.py", "--experiments", PILOT[:8], world["experiment_id"],
        "--db", f"sqlite:///{world['db_path']}", "--out-dir", str(out),
    ])
    script.main()
    printed = capsys.readouterr().out
    assert "LLM Baseline (Claude Sonnet 4.6)" in printed and "LLM Baseline (GPT-4o)" in printed
    assert "variants that kept the original's outcome: 107/108" in printed
    for name in ("fig_results.pdf", "fig_results.png", "table_results.csv",
                 "table_results.md", "table_results.tex"):
        assert (out / name).stat().st_size > 0
    csv_lines = (out / "table_results.csv").read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 15 and csv_lines[0].startswith("model,model_id,agent,")
    assert "GPT-4o" in (out / "table_results.tex").read_text(encoding="utf-8")


# ── Fixtures of the second model, and their replay ────────────────────────────

def test_recording_writes_a_fixture_set_of_its_own_and_mock_mode_replays_it(
    world, tmp_path, monkeypatch, no_network
):
    fixtures = tmp_path / "mock_responses"
    with world["Session"]() as db:
        recorded = record_experiment_fixtures(db, world["experiment_id"], fixtures)
    assert len(recorded) == 140  # 20 issues x (original + 6 variants)
    assert {fixture.path.parent for fixture in recorded} == {fixtures / "gpt-4o"}
    assert not list(fixtures.glob("*.json"))  # the pilot's set (the root) is untouched

    monkeypatch.setattr(settings, "FIXTURES_DIR", str(fixtures))
    with world["Session"]() as db:
        replay = ExperimentRunner(_config(execution_mode="mock"), db).run()
        MetricsEngine().compute(replay.id, db)
        db.commit()
        real, replayed = _cells(db, world["experiment_id"]), _cells(db, replay.id)

        def view(cells):
            return {
                cell: (run.status, run.patch, run.cost_usd, run.token_input, run.token_output,
                       run.error_message, run.metadata_, ti.id)
                for cell, (run, ti) in cells.items()
            }

        def metrics(experiment_id):
            return {
                (m.scope_key, m.metric_name): (m.metric_value, json.loads(m.metric_metadata or
                                                                          "null"))
                for m in db.query(Metric).filter_by(experiment_id=experiment_id)
                if m.scope != "run" and m.scope != "experiment"
            }

        assert view(replayed) == view(real)
        assert metrics(replay.id) == metrics(world["experiment_id"])


# ── The dashboard ─────────────────────────────────────────────────────────────

def test_past_experiments_shows_the_model_comparison(world, monkeypatch):
    from stableagent.dashboard import _db

    engine = world["engine"]
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(_db, "build_engine", lambda *a, **k: engine)
    st.cache_data.clear()
    at = AppTest.from_file(MAIN_PAGE, default_timeout=120)
    at.run()
    at.switch_page("pages/1_Past_Experiments.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # Preselected: the pilot and the newest experiment that reused its variants (the model-2
    # run, or its mock replay when that test ran first).
    with world["Session"]() as db:
        reusing = [
            e.id for e in db.query(Experiment).order_by(Experiment.created_at)
            if json.loads(e.config).get("reuse_variants_from") == PILOT
        ]
    assert world["experiment_id"] in reusing
    assert at.multiselect(key="compare_experiments").value == [PILOT, reusing[-1]]
    table = at.dataframe[0].value
    assert list(table["Model"].unique()) == ["Claude Sonnet 4.6", "GPT-4o"]
    assert len(table) == 14
    assert at.get("download_button")  # fig_results.pdf
    assert at.get("imgs")  # the figure itself
    st.cache_data.clear()


# ── The CLI ───────────────────────────────────────────────────────────────────

def _cli(world, monkeypatch, *args):
    from contextlib import contextmanager

    from rich.console import Console
    from typer.testing import CliRunner

    from stableagent.cli import main as cli

    @contextmanager
    def temp_db():
        session = world["Session"]()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(cli, "get_db", temp_db)
    monkeypatch.setattr(cli, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_inject_truststore", lambda: None)
    monkeypatch.setattr(cli, "console", Console(width=250))
    return CliRunner().invoke(cli.app, ["run", "--config", str(CONFIG), *args],
                              terminal_width=250)


def test_cli_estimate_shows_148_agent_runs_no_generation_and_the_expected_cost(
    world, monkeypatch
):
    fake = FakeOpenAI().install(monkeypatch)
    result = _cli(world, monkeypatch, "--mode", "real", "--estimate")
    assert result.exit_code == 0, result.output
    out = result.output
    assert re.search(r"Agent runs\s*│\s*148\s*│ 20 originals \+ 108 valid variants \+ 20 repeats",
                     out)
    assert re.search(r"skipped\s*│\s*-12", out)
    assert "provider=openai  model=gpt-4o  key OPENAI_API_KEY: set" in out
    # 148 x (1516 x $2.50 + 337 x $10.00) / 1M = $1.06
    assert "Expected cost: $1.06  (148 agent runs x $0.0072" in out
    assert "Hard cost cap: $4.00" in out
    assert f"all 120 variants from experiment {PILOT} (108 run, 12 skipped" in out
    assert "0 variants to generate" in out
    assert "Variant generation: none" in out
    assert fake.requests == []


def test_cli_generate_only_reuses_every_variant(world, monkeypatch):
    _no_generation(monkeypatch)
    result = _cli(world, monkeypatch, "--mode", "real", "--generate-only")
    assert result.exit_code == 0, result.output
    assert "Generation cost: $0.0000 for 0 variant(s) generated now; 120 from the cache" in (
        result.output
    )


def test_cli_run_without_the_openai_key_exits_with_a_clear_message(
    world, monkeypatch, no_openai_key
):
    fake = FakeOpenAI().install(monkeypatch)
    result = _cli(world, monkeypatch, "--mode", "real")
    assert result.exit_code == 1
    assert "needs an API key in OPENAI_API_KEY" in result.output
    assert "No API call was made" in result.output
    assert fake.requests == []
