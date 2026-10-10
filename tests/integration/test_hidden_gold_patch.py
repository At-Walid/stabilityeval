"""The gold patch is hidden ground truth: it must never reach the agent (AgentInput, the prompt,
raw_logs), yet the metrics engine must still use it to score localization.

Runs the real ExperimentRunner in real mode with the LLM Baseline, but anthropic.Anthropic is a
fake that records every request: no network, no cost.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.agents.llm_baseline import LLMBaselineAdapter
from stability_eval.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stability_eval.data.loaders.swebench import SWEBenchInstance, store_instances
from stability_eval.data.models import Base, Metric, Run
from stability_eval.execution.runner import ExperimentRunner
from stability_eval.export.csv_exporter import CSVExporter
from stability_eval.export.json_exporter import JSONExporter
from stability_eval.metrics.engine import MetricsEngine

MARKER = "GOLD-PATCH-SECRET-MARKER"
GOLD = f"--- a/pkg/core.py\n+++ b/pkg/core.py\n@@ -1 +1 @@\n-x = 1\n+x = 2  # {MARKER}"
DIFF = "--- a/pkg/core.py\n+++ b/pkg/core.py\n@@ -1 +1 @@\n-x = 1\n+x = 3\n"
# The agent answers with the forced submit_patch tool call.
REPLY = SimpleNamespace(type="tool_use", id="toolu_1", name="submit_patch", input={"diff": DIFF})
ISSUE_TEXT = "core.py breaks on empty input.\n\nIt should return an empty result instead."


def test_gold_patch_never_reaches_the_agent_but_scores_localization(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'gold.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    requests: list[dict] = []
    agent_inputs = []

    class FakeAnthropic:
        def __init__(self, **_kwargs):
            self.messages = SimpleNamespace(create=self._create)

        @staticmethod
        def _create(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                content=[REPLY],
                usage=SimpleNamespace(input_tokens=10, output_tokens=10),
                stop_reason="tool_use",
            )

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    real_run = LLMBaselineAdapter.run

    def spying_run(self, agent_input, mode):
        agent_inputs.append(agent_input)
        return real_run(self, agent_input, mode)

    monkeypatch.setattr(LLMBaselineAdapter, "run", spying_run)

    with Session() as db:
        store_instances(
            db, [SWEBenchInstance("org__proj-1", "org/proj", ISSUE_TEXT, gold_patch=GOLD)]
        )
        db.commit()
        config = ExperimentConfig(
            experiment_name="hidden-gold",
            execution_mode="real",
            agents=[AgentConfig(name="llm_baseline")],
            issues=IssueConfig(issue_ids=["org__proj-1"]),
            transformations=[
                TransformationConfig(name="reordering", params={"seed": 42}),
                TransformationConfig(name="typo_injection", params={"error_rate": 0.02}),
            ],
            cost_limit_usd=1.0,
        )
        experiment = ExperimentRunner(config, db).run()
        MetricsEngine().compute(experiment.id, db)
        db.commit()

        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
        localization = {
            m.scope_key: m.metric_value
            for m in db.query(Metric).filter_by(
                experiment_id=experiment.id, metric_name="localization_match"
            )
        }
        csv_paths = CSVExporter().export(experiment, tmp_path / "out", db)
        json_path = JSONExporter().export(experiment, tmp_path / "out", db)

    # Every cell ran through the real adapter and the (fake) API.
    assert len(runs) == 3 and len(agent_inputs) == 3 and len(requests) == 3

    # Never shown to the agent: not in its input, not in the prompt, not in what it returned.
    for agent_input in agent_inputs:
        assert MARKER not in repr(agent_input)
    for request in requests:
        assert MARKER not in json.dumps(request, default=str)
        assert request["messages"][0]["content"].startswith("Repository: org/proj\n")
        assert request["tool_choice"] == {"type": "tool", "name": "submit_patch"}
    for run in runs:
        assert MARKER not in (run.raw_logs or "") and MARKER not in (run.patch or "")
        assert run.patch == DIFF and json.loads(run.raw_logs) == {"diff": DIFF}

    # Not leaked by the exports either.
    for path in [*csv_paths, json_path]:
        assert MARKER not in path.read_text(encoding="utf-8")

    # ...but used for scoring: every run modified the gold file, so localization matches.
    assert sorted(localization) == sorted(run.id for run in runs)
    assert set(localization.values()) == {1.0}
