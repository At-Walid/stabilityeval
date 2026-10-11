"""Recording an experiment as MockReplay fixtures and replaying it in mock mode.

- A synthetic experiment (control run, a generated variant, an excluded variant, a no-op variant)
  is recorded, then replayed on a fresh database: every run and every metric comes back identical,
  and the variants are restored from the fixtures instead of placeholders.
- The committed fixtures of the ICSE pilot (experiment bc6f1372, 20 issues, real LLM Baseline runs)
  replay to the very metrics the real experiment produced.

No network, no API key needed: everything runs on MockReplay fixtures and the bundled issues.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import stableagent
from stableagent.agents.mock_replay import fixture_index, recorded_control_repeats
from stableagent.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.data.loaders.swebench import SWEBenchInstance, load_bundle, store_instances
from stableagent.data.models import Base, Issue, Metric, Run, TransformedIssue
from stableagent.execution.runner import ExperimentRunner
from stableagent.fixtures.recorder import record_experiment_fixtures
from stableagent.metrics.engine import MetricsEngine
from stableagent.transformations.base import IssueRecord
from stableagent.transformations.cache import TransformationCache
from stableagent.transformations.registry import transformation_registry

PILOT_EXPERIMENT = "bc6f1372-2088-45dd-907c-d741c0545d27"
COMMITTED_FIXTURES = Path(stableagent.__file__).parent / "fixtures" / "mock_responses"


GOLD_LINE = "+fixed_by_the_gold_patch()"  # only in the hidden gold patches


def diff(path: str, *changes: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n" + "".join(f"{c}\n" for c in changes)


ISSUES = {
    # one paragraph: reordering is a no-op (skipped, never run)
    "org__a-1": ("Crash in pkg.core when the input is empty.", "pkg/core.py"),
    # two paragraphs: reordering really reorders
    "org__b-2": ("The api module drops headers.\n\nSteps: call api.send() twice.", "pkg/api.py"),
}


def _session(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _store_issues(Session) -> None:
    with Session() as db:
        store_instances(db, [
            SWEBenchInstance(issue_id, "org/x", text, gold_patch=diff(gold, "-a", GOLD_LINE))
            for issue_id, (text, gold) in ISSUES.items()
        ])
        db.commit()


def _config(fixtures: Path) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_name="recorded",
        execution_mode="mock",
        agents=[AgentConfig(name="mock_replay", params={"fixtures_dir": str(fixtures)})],
        issues=IssueConfig(issue_ids=list(ISSUES)),
        transformations=[TransformationConfig(name="paraphrase"),
                         TransformationConfig(name="reordering", params={"seed": 42})],
        control_repeats=1,
    )


def _write(fixtures: Path, issue_id: str, variant: str, data: dict) -> None:
    (fixtures / f"{issue_id}__{variant}__mock_replay.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _output(patch: str, cost: float) -> dict:
    return {"status": "success", "patch": patch, "token_usage": {"input": 100, "output": 20},
            "cost_usd": cost, "runtime_seconds": 1.5, "metadata": {"model": "m"}}


@pytest.fixture()
def recorded(tmp_path):
    """Experiment 1 run from hand-written fixtures and recorded into a second directory."""
    source = tmp_path / "source"
    source.mkdir()
    for issue_id, (_text, gold) in ISSUES.items():
        original = _output(diff(gold, "-a", "+b"), 0.01)
        original["control_repeats"] = [_output(diff(gold, "-a", "+c"), 0.02)]
        _write(source, issue_id, "original", original)
        _write(source, issue_id, "paraphrase", _output(diff(gold, "-a", "+b", "+d"), 0.03))
        _write(source, issue_id, "reordering", _output(diff("other.py", "+e"), 0.04))

    engine, Session = _session(tmp_path / "first.db")
    _store_issues(Session)
    paraphrase = transformation_registry.get("paraphrase")()
    with Session() as db:
        cache = TransformationCache(db)
        for issue_id, (text, _gold) in ISSUES.items():
            issue = db.query(Issue).filter_by(external_id=issue_id).one()
            # A generated paraphrase of a-1, and an excluded one for b-2 (never run).
            cache._store(
                paraphrase, IssueRecord(issue.id, "org/x", text), {},
                text=f"Reworded: {text}", notes="generated", generator=paraphrase.generator,
                mode="real", quality_warning=issue_id == "org__b-2",
                exclusion_reason="identifier retention failed" if issue_id == "org__b-2" else None,
                generation_cost_usd=0.001,
            )
        db.commit()
        experiment = ExperimentRunner(_config(source), db).run()
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        target = tmp_path / "recorded"
        files = record_experiment_fixtures(db, experiment.id, target)
        experiment_id = experiment.id
    yield Session, experiment_id, target, files, tmp_path
    engine.dispose()


def test_one_fixture_per_issue_and_variant_with_control_runs_and_variants(recorded):
    _Session, experiment_id, target, files, _ = recorded
    assert len(files) == 6
    assert fixture_index(target) == {
        "org__a-1": {"original", "paraphrase", "reordering"},
        "org__b-2": {"original", "paraphrase", "reordering"},
    }
    original = json.loads((target / "org__a-1__original__mock_replay.json").read_text("utf-8"))
    assert original["patch"] == diff("pkg/core.py", "-a", "+b")
    assert [r["patch"] for r in original["control_repeats"]] == [diff("pkg/core.py", "-a", "+c")]
    assert original["recorded_from"]["experiment_id"] == experiment_id
    assert "variant" not in original
    assert recorded_control_repeats("org__a-1", target) == 1

    skipped = json.loads((target / "org__a-1__reordering__mock_replay.json").read_text("utf-8"))
    assert skipped["status"] == "skipped_variant" and skipped["patch"] is None
    assert skipped["variant"]["noop"] is True
    excluded = json.loads((target / "org__b-2__paraphrase__mock_replay.json").read_text("utf-8"))
    assert excluded["variant"]["quality_warning"] is True
    generated = json.loads((target / "org__a-1__paraphrase__mock_replay.json").read_text("utf-8"))
    assert generated["variant"]["transformed_text"].startswith("Reworded: ")
    assert generated["token_usage"] == {"input": 100, "output": 20}
    for path in target.iterdir():  # the gold patch is hidden ground truth: never recorded
        assert GOLD_LINE not in path.read_text("utf-8")


def test_recording_again_rewrites_identical_files(recorded):
    Session, experiment_id, target, _files, _ = recorded
    with Session() as db:
        again = record_experiment_fixtures(db, experiment_id, target)
    assert not any(fixture.changed for fixture in again)


def _snapshot(db, experiment_id: str) -> tuple[dict, dict]:
    """Runs and metrics with run ids replaced by their cell, for comparing two experiments."""
    runs = (
        db.query(Run, TransformedIssue, Issue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .join(Issue, TransformedIssue.issue_id == Issue.id)
        .filter(Run.experiment_id == experiment_id)
        .all()
    )
    cell = {
        run.id: (issue.external_id, ti.transformation_name, run.control_repeat, run.run_index)
        for run, ti, issue in runs
    }

    def norm(value):
        if isinstance(value, str):
            if value in cell:
                return repr(cell[value])
            return "EXP" if value == experiment_id else value
        if isinstance(value, list):
            return sorted((norm(v) for v in value), key=repr)
        if isinstance(value, dict):
            return {k: norm(v) for k, v in value.items()}
        return value

    run_view = {
        cell[run.id]: (run.status, run.patch, run.cost_usd, run.token_input, run.token_output,
                       run.error_message, run.metadata_, ti.transformed_text, ti.generator,
                       ti.transform_version, ti.quality_warning, ti.noop, ti.exclusion_reason)
        for run, ti, issue in runs
    }
    metrics = {
        (m.scope, norm(m.scope_key), m.metric_name): (
            m.metric_value, norm(json.loads(m.metric_metadata)) if m.metric_metadata else None
        )
        for m in db.query(Metric).filter_by(experiment_id=experiment_id)
    }
    return run_view, metrics


def test_replay_on_a_fresh_database_reproduces_every_run_and_metric(recorded, no_network):
    Session, experiment_id, target, _files, tmp_path = recorded
    with Session() as db:
        runs_before, metrics_before = _snapshot(db, experiment_id)

    engine, Fresh = _session(tmp_path / "fresh.db")
    _store_issues(Fresh)
    with Fresh() as db:
        replay = ExperimentRunner(_config(target), db).run()
        MetricsEngine().compute(replay.id, db)
        db.commit()
        runs_after, metrics_after = _snapshot(db, replay.id)
        restored = db.query(TransformedIssue).filter(
            TransformedIssue.transformation_params.like("%restored_from%")
        ).count()
    engine.dispose()

    assert runs_after == runs_before
    assert metrics_after == metrics_before
    assert restored == 4  # both paraphrases (one excluded) and both reorderings (one no-op)
    names = {name for _scope, _key, name in metrics_before}
    assert {"changed_line_similarity", "control_changed_line_similarity",
            "changed_line_similarity_vs_control"} <= names
    # the control run replayed its own recorded output, not the original's
    control = runs_after[("org__a-1", "original", True, 1)]
    assert control[1] == diff("pkg/core.py", "-a", "+c")


def test_a_recorded_variant_is_not_restored_over_a_cached_one(recorded):
    Session, _experiment_id, target, _files, _ = recorded
    with Session() as db:
        before = db.query(TransformedIssue).count()
        ExperimentRunner(_config(target), db).run()
        assert db.query(TransformedIssue).count() == before  # every variant was a cache hit


# ── The committed ICSE pilot fixtures ─────────────────────────────────────────


def _pilot_issue_ids() -> list[str]:
    ids = []
    for path in sorted(COMMITTED_FIXTURES.glob("*__original__mock_replay.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("recorded_from") or {}).get("experiment_id") == PILOT_EXPERIMENT:
            ids.append(path.name[: -len("__original__mock_replay.json")])
    return ids


def test_the_pilot_fixtures_replay_to_the_metrics_of_the_real_experiment(tmp_path, no_network):
    issue_ids = _pilot_issue_ids()
    assert len(issue_ids) == 20
    engine, Session = _session(tmp_path / "pilot.db")
    with Session() as db:
        store_instances(db, load_bundle(issue_ids))  # verbatim issues and hidden gold patches
        db.commit()
        config = ExperimentConfig(
            experiment_name="icse_pilot_v1",
            execution_mode="mock",
            agents=[AgentConfig(name="llm_baseline", params={"model": "claude-sonnet-4-6"})],
            issues=IssueConfig(issue_ids=issue_ids),
            transformations=[
                TransformationConfig(name="paraphrase"),
                TransformationConfig(name="verbosity_reduction", params={"target_ratio": 0.5}),
                TransformationConfig(name="typo_injection", params={"error_rate": 0.02}),
                TransformationConfig(name="reordering", params={"seed": 42}),
                TransformationConfig(name="paragraph_to_structured"),
                TransformationConfig(name="neutralize_emotional"),
            ],
            control_repeats=1,
            cost_limit_usd=5.0,
        )
        experiment = ExperimentRunner(config, db).run()
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        statuses = [run.status for run in db.query(Run).filter_by(experiment_id=experiment.id)]
        metrics = {
            (m.scope_key.replace(experiment.id, "EXP"), m.metric_name): (
                m.metric_value, json.loads(m.metric_metadata) if m.metric_metadata else {}
            )
            for m in db.query(Metric).filter_by(experiment_id=experiment.id)
            if m.scope != "run"
        }
        total_cost = experiment.total_cost_usd
    engine.dispose()

    assert len(statuses) == 160
    assert statuses.count("skipped_variant") == 12 and statuses.count("success") == 148
    assert total_cost == pytest.approx(1.421307, abs=1e-9)

    def value(key, name):
        return metrics[(key, name)][0]

    agent = "llm_baseline"
    assert value(f"{agent}|reordering", "transformation_sensitivity") == pytest.approx(1 / 19)
    assert value(f"{agent}|reordering", "flip_rate") == pytest.approx(1 / 19)
    for name in ("paraphrase", "verbosity_reduction", "typo_injection",
                 "paragraph_to_structured", "neutralize_emotional"):
        assert value(f"{agent}|{name}", "transformation_sensitivity") == 0.0
    assert value(agent, "control_flip_rate") == 0.0
    assert value(agent, "stability_score_mean") == pytest.approx(0.99)
    assert value("EXP", "excluded_runs_noop") == 8
    assert value("EXP", "excluded_runs_quality_warning") == 4
    assert value("EXP", "excluded_runs_status") == 0

    # Changed-line similarity: (mean, vs-control difference, exploratory Wilcoxon p), as the real
    # experiment's metrics were recomputed from its stored runs.
    expected = {
        "paraphrase": (0.5407067581808555, -0.2137340003456582, 0.007630414739245618),
        "verbosity_reduction": (0.5769261434818561, -0.13391070312525327, 0.05933611988090865),
        "typo_injection": (0.6713317458400639, -0.08310901268644977, 0.21322298815094956),
        "reordering": (0.569515095694252, -0.18246883706106393, 0.02770784935807986),
        "paragraph_to_structured": (0.5584709525006101, -0.1994174626937644, 0.025842854459788924),
        "neutralize_emotional": (0.6763882507156861, -0.05491246797485863, 0.5939546753269146),
    }
    for name, (mean, delta, p_value) in expected.items():
        mean_value = value(f"{agent}|{name}", "changed_line_similarity_mean")
        assert mean_value == pytest.approx(mean, abs=1e-12)
        vs, meta = metrics[(f"{agent}|{name}", "changed_line_similarity_vs_control")]
        assert vs == pytest.approx(delta, abs=1e-12)
        assert meta["wilcoxon_p"] == pytest.approx(p_value, abs=1e-12)
        assert meta["analysis"] == "exploratory"
    control, meta = metrics[(agent, "control_changed_line_similarity")]
    assert control == pytest.approx(0.7544407585265137, abs=1e-12)
    assert (meta["ci_low"], meta["ci_high"]) == pytest.approx(
        (0.6071825226796256, 0.8806830615555319), abs=1e-12
    )


# ── The committed GPT-4o fixtures (experiment 9d27f3ef, on the pilot's variants) ──────────────


def test_the_gpt4o_fixtures_replay_to_the_metrics_of_the_real_experiment(tmp_path, no_network):
    import shutil

    from stableagent.metrics.comparison import compare_experiments

    model2 = "9d27f3ef-397a-41b7-b1b2-e09729288a40"
    shipped = Path(stableagent.__file__).parents[1] / "data" / "pilot" / "stableagent_pilot.db"
    config_path = Path(stableagent.__file__).parents[1] / "configs" / "icse_pilot_model2.json"
    assert len(list((COMMITTED_FIXTURES / "gpt-4o").glob("*__mock_replay.json"))) == 140
    db_path = tmp_path / "pilot.db"
    shutil.copy(shipped, db_path)  # holds both experiments: reuse_variants_from needs the pilot
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    config = ExperimentConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    with Session() as db:
        replay = ExperimentRunner(config.model_copy(update={"execution_mode": "mock"}), db).run()
        MetricsEngine().compute(replay.id, db)
        db.commit()
        real_cmp, replay_cmp = compare_experiments([model2, replay.id], db)
        statuses = [run.status for run in db.query(Run).filter_by(experiment_id=replay.id)]
        total_cost = replay.total_cost_usd
    engine.dispose()

    assert len(statuses) == 160 and statuses.count("skipped_variant") == 12
    assert total_cost == pytest.approx(0.719365, abs=1e-9)
    # The paper's GPT-4o numbers (cut replies excluded, SPEC section 13).
    assert (replay_cmp.originals_localized, replay_cmp.originals_scored) == (17, 20)
    assert (replay_cmp.variants_kept, replay_cmp.variants_scored) == (97, 105)
    assert round(replay_cmp.control.similarity.mean, 2) == 0.76
    # ... and every row equals the real experiment's.
    assert replay_cmp.rows == real_cmp.rows
    assert replay_cmp.stability_score_mean == real_cmp.stability_score_mean
