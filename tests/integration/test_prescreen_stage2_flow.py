"""End-to-end flow of scripts/prescreen_stage2.py with both LLM calls faked.

No network and no real database: the Haiku variant generator and the LLM Baseline adapter's
run() are replaced, and every database lives in tmp_path. Exercises seeding, the transformation
cache, ExperimentRunner persistence, analysis, CSV output, re-run protection and the abort paths.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from rich.console import Console

from stability_eval.agents.base import AgentOutput
from stability_eval.agents.llm_baseline import LLMBaselineAdapter
from stability_eval.data.models import Experiment, Issue, Run, TransformedIssue
from stability_eval.transformations.llm_backed._api import HaikuReply

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prescreen_stage2.py"


def _load_script():
    existing = sys.modules.get("prescreen_stage2")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("prescreen_stage2", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["prescreen_stage2"] = module
    spec.loader.exec_module(module)
    return module


ps = _load_script()

N_CANDIDATES = 20


def _candidates() -> list[dict]:
    records = []
    for idx in range(1, N_CANDIDATES + 1):
        org = idx % 7
        body = (
            f"The function func_{idx} in module_{idx} raises ValueError "
            f"when called with ClassName{idx}.\n\n"
            + "It used to work in version 1.2.3 and nothing in the changelog explains the change. "
            * 3
            + f"\n\nReproduce with: call func_{idx}(None) and watch the traceback.\n\n"
            + "Expected behaviour is that the call returns normally. " * 2
        )
        records.append(
            {
                "id": f"org{org}__proj{org}-{idx}",
                "repo": f"org{org}/proj{org}",
                "problem_statement": body,
            }
        )
    return records


class Env:
    """Counters plus the temp engine shared by one test."""

    def __init__(self, engine):
        self.engine = engine
        self.haiku_calls = 0
        self.agent_calls = 0

    def session(self):
        return ps.sessionmaker(bind=self.engine)()

    def count(self, model, **filters) -> int:
        with self.session() as db:
            return db.query(model).filter_by(**filters).count()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = ps.build_engine(f"sqlite:///{tmp_path / 'flow.db'}")
    ps.create_all(engine)
    environment = Env(engine)

    candidates_file = tmp_path / "stage1_candidates.json"
    candidates_file.write_text(json.dumps(_candidates()), encoding="utf-8")

    monkeypatch.setattr(ps, "build_engine", lambda: engine)
    monkeypatch.setattr(ps, "CANDIDATES_PATH", candidates_file)
    monkeypatch.setattr(ps, "RESULTS_PATH", tmp_path / "stage2_results.csv")
    monkeypatch.setattr(ps, "_inject_truststore", lambda: None)
    monkeypatch.setattr(ps, "dotenv_values", lambda *_a, **_k: {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real-0123456789")

    def fake_haiku(system_prompt, user_content, api_key, model=None, **_):
        environment.haiku_calls += 1
        words = user_content.split()
        return HaikuReply(" ".join(words[: max(len(words) // 2, 1)]), "halved by the fake")

    monkeypatch.setattr("stability_eval.transformations.llm_backed._api.call_haiku", fake_haiku)

    def fake_run(self, agent_input, mode):
        environment.agent_calls += 1
        issue_id = agent_input.metadata["issue_id"]
        variant = agent_input.metadata["transformation_name"]
        idx = int(issue_id.rsplit("-", 1)[1])
        n_changed = {"original": 0, "verbosity_reduction": idx % 7 * 3, "reordering": idx % 5 * 2}[
            variant
        ]
        lines = [f"+    value_{k} = {k}" for k in range(40)]
        for k in range(n_changed):
            lines[k] = f"+    changed_{k} = {k * 7}"
        patch = f"--- a/mod_{idx}.py\n+++ b/mod_{idx}.py\n@@ -1,40 +1,40 @@\n" + "\n".join(lines)
        return AgentOutput(
            status="success",
            patch=patch,
            token_usage={"input": 500, "output": 400},
            cost_usd=0.01,
            runtime_seconds=0.1,
            raw_logs=patch,
            metadata={"fake": True},
        )

    monkeypatch.setattr(LLMBaselineAdapter, "run", fake_run)
    return environment


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_flow_persists_60_runs_and_writes_the_ranked_csv(env, capsys):
    assert ps.main([]) == 0
    out = capsys.readouterr().out

    with env.session() as db:
        experiments = db.query(Experiment).filter_by(name="prescreen_stage2").all()
        assert len(experiments) == 1
        experiment = experiments[0]
        assert experiment.status == "completed"
        assert experiment.total_cost_usd == pytest.approx(0.60)  # 60 fake runs x $0.01

        config = json.loads(experiment.config)
        assert config["execution_mode"] == "real"
        assert config["cost_limit_usd"] == 5.0
        assert config["agents"][0]["name"] == "llm_baseline"
        assert config["agents"][0]["params"]["timeout_seconds"] == 60
        assert config["agents"][0]["params"]["cost_cap_usd"] == 0.50
        assert [(t["name"], t["params"]) for t in config["transformations"]] == [
            ("verbosity_reduction", {"target_ratio": 0.5}),
            ("reordering", {"seed": 42}),
        ]

        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
        assert len(runs) == 60
        assert {r.execution_mode for r in runs} == {"real"}
        assert {r.status for r in runs} == {"success"}

    assert env.agent_calls == 60
    assert env.haiku_calls == 20  # one verbosity_reduction per candidate; reordering is free
    assert env.count(Issue) == 20
    assert env.count(TransformedIssue, transformation_name="verbosity_reduction") == 20
    assert env.count(TransformedIssue, transformation_name="reordering") == 20
    assert env.count(TransformedIssue, is_original=True) == 20

    rows = _read_csv(ps.RESULTS_PATH)
    assert len(rows) == N_CANDIDATES
    divergences = [float(r["divergence"]) for r in rows]
    assert divergences == sorted(divergences, reverse=True)
    assert len({r["issue_id"] for r in rows}) == N_CANDIDATES

    assert "RECOMMENDED PILOT SELECTION (10 issues)" in out
    assert "configs/icse_pilot.json was NOT written" in out
    assert ">> TOP" in out and ">> STABLE" in out


def test_main_never_writes_the_pilot_config(env, tmp_path):
    pilot = ps.PROJECT_ROOT / "configs" / "icse_pilot.json"
    before = pilot.read_bytes() if pilot.exists() else None
    ps.main([])
    assert (pilot.read_bytes() if pilot.exists() else None) == before


# ---------------------------------------------------------------------------
# Re-run protection / caching
# ---------------------------------------------------------------------------


def test_second_invocation_only_reanalyses_without_spending(env, capsys):
    ps.main([])
    capsys.readouterr()
    first_csv = ps.RESULTS_PATH.read_text(encoding="utf-8")

    assert ps.main([]) == 0
    out = capsys.readouterr().out

    assert "already exists" in out and "without any API calls" in out
    assert env.agent_calls == 60 and env.haiku_calls == 20  # unchanged
    assert env.count(Experiment, name="prescreen_stage2") == 1
    assert ps.RESULTS_PATH.read_text(encoding="utf-8") == first_csv


def test_rerun_creates_a_new_experiment_but_reuses_cached_variants(env):
    ps.main([])
    assert ps.main(["--rerun"]) == 0

    assert env.count(Experiment, name="prescreen_stage2") == 2
    assert env.count(Run) == 120
    assert env.agent_calls == 120
    assert env.haiku_calls == 20  # variants came from the cache the second time
    assert env.count(TransformedIssue, transformation_name="verbosity_reduction") == 20


def test_dry_run_checks_and_plans_but_writes_nothing(env, capsys):
    assert ps.main(["--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "ANTHROPIC_API_KEY: loaded" in out
    assert "60 real LLM Baseline runs" in out
    assert "Worst-case bound" in out
    assert env.count(Issue) == 0 and env.count(Experiment) == 0
    assert env.agent_calls == 0 and env.haiku_calls == 0
    assert not ps.RESULTS_PATH.exists()


# ---------------------------------------------------------------------------
# Guards and abort paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "sk-ant-..."])
def test_missing_or_placeholder_api_key_aborts_before_any_work(env, no_api_key, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)

    with pytest.raises(SystemExit) as exc:
        ps.main([])

    assert exc.value.code == 2
    assert env.count(Issue) == 0 and env.count(Experiment) == 0
    assert env.agent_calls == 0 and env.haiku_calls == 0


def test_the_api_key_value_is_never_printed(env, monkeypatch, capsys):
    secret = "sk-ant-SECRET-VALUE-THAT-MUST-NOT-APPEAR-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    ps.main([])
    captured = capsys.readouterr()
    assert secret not in captured.out and secret not in captured.err
    assert "SECRET-VALUE" not in captured.out


def test_variant_generation_failure_stops_before_any_agent_run(env, monkeypatch, capsys):
    def exploding_haiku(system_prompt, user_content, api_key, model=None, **_):
        raise RuntimeError("simulated API outage [503]")

    monkeypatch.setattr(
        "stability_eval.transformations.llm_backed._api.call_haiku", exploding_haiku
    )

    assert ps.main([]) == 1
    assert env.agent_calls == 0
    assert env.count(Experiment) == 0
    assert "Variant generation failed" in capsys.readouterr().out


def test_three_consecutive_api_errors_abort_the_experiment(env, monkeypatch, capsys):
    def failing_run(self, agent_input, mode):
        env.agent_calls += 1
        raise RuntimeError("simulated API error")

    monkeypatch.setattr(LLMBaselineAdapter, "run", failing_run)

    assert ps.main([]) == 1
    assert env.agent_calls == ps.CONSECUTIVE_ERROR_LIMIT
    with env.session() as db:
        experiment = db.query(Experiment).filter_by(name="prescreen_stage2").one()
        assert experiment.status == "failed"
        assert (
            db.query(Run).filter_by(experiment_id=experiment.id).count()
            == ps.CONSECUTIVE_ERROR_LIMIT
        )
    assert "Experiment aborted" in capsys.readouterr().out


def test_total_cost_limit_stops_the_run_and_leaves_candidates_incomplete(env, monkeypatch, capsys):
    def expensive_run(self, agent_input, mode):
        env.agent_calls += 1
        return AgentOutput(
            status="success", patch="--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y", cost_usd=2.5
        )

    monkeypatch.setattr(LLMBaselineAdapter, "run", expensive_run)

    assert ps.main([]) == 0
    out = capsys.readouterr().out

    assert env.agent_calls == 2  # $2.50 + $2.50 reaches the $5.00 limit
    with env.session() as db:
        assert (
            db.query(Experiment).filter_by(name="prescreen_stage2").one().status == "cost_exceeded"
        )
    assert "status is 'cost_exceeded'" in out
    assert "incomplete" in out
    rows = _read_csv(ps.RESULTS_PATH)
    assert len(rows) == N_CANDIDATES and all(r["divergence"] == "" for r in rows)


def test_timeout_outcome_is_scored_as_a_flip(env, monkeypatch):
    original_run = LLMBaselineAdapter.run

    def timing_out_on_reordering(self, agent_input, mode):
        if agent_input.metadata["transformation_name"] == "reordering":
            env.agent_calls += 1
            return AgentOutput(
                status="timeout", error_message="No response within 60s", runtime_seconds=60.0
            )
        return original_run(self, agent_input, mode)

    monkeypatch.setattr(LLMBaselineAdapter, "run", timing_out_on_reordering)
    ps.main([])

    rows = _read_csv(ps.RESULTS_PATH)
    assert {r["outcome_reorder"] for r in rows} == {"timeout"}
    assert {r["divergence"] for r in rows} == {"1.0000"}


def test_truncated_replies_are_flagged_via_the_persisted_stop_reason(env, monkeypatch, capsys):
    original_run = LLMBaselineAdapter.run

    def truncating_on_reordering(self, agent_input, mode):
        output = original_run(self, agent_input, mode)
        if agent_input.metadata["transformation_name"] == "reordering":
            output.metadata = {"model": "fake", "stop_reason": "max_tokens"}
        return output

    monkeypatch.setattr(LLMBaselineAdapter, "run", truncating_on_reordering)
    ps.main([])

    assert capsys.readouterr().out.count("trunc:reorder") == N_CANDIDATES


def test_existing_issue_with_different_text_is_refused(env):
    with env.session() as db:
        first = _candidates()[0]
        db.add(
            Issue(
                external_id=first["id"],
                repo_name=first["repo"],
                source="swebench_lite",
                issue_text="a different text",
            )
        )
        db.commit()

    with pytest.raises(RuntimeError, match="different text"):
        ps.main([])
    assert env.agent_calls == 0


def test_results_table_renders_every_candidate_with_markers():
    results = [
        ps.CandidateResult(
            issue_id=f"org{i % 6}__p-{i}",
            repo=f"org{i % 6}/p",
            outcome_original="success",
            outcome_verbosity="success",
            outcome_reorder="success",
            c1_verbosity=1 - i / 25,
            c1_reorder=1 - i / 30,
            flip_any=False,
            divergence=i / 30,
            reorder_intact=0.9 if i % 2 else 0.1,
            line_shuffle=i % 2 == 0,
            verbosity_ratio=0.5,
            quality_warning=bool(i % 3 == 0),
            truncated=("verbosity",) if i == 7 else (),
        )
        for i in range(1, 21)
    ]
    selection = ps.recommend_selection(results)
    console = Console(record=True, width=200, file=io.StringIO())
    ps.print_results_table(console, results, selection)
    ps.print_selection(console, selection)
    text = console.export_text()

    for r in results:
        assert r.issue_id in text
    assert text.count(">> TOP") == 6 and text.count(">> STABLE") == 4
    assert "T07:line-shuffle" in text and "QW" in text and "trunc:verbosity" in text
