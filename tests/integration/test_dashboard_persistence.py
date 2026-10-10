from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from stability_eval.data.models import Base, Experiment, Run
from stability_eval.dashboard import _runner


def test_real_dashboard_run_keeps_completed_rows_when_interrupted(tmp_path, monkeypatch, no_network):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(_runner, "build_engine", lambda: engine)

    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="```diff\n--- a/example.py\n+++ b/example.py\n"
                                                    "@@ -1 +1 @@\n-a\n+b\n```")],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
        stop_reason="end_turn",
    )
    monkeypatch.setattr(
        anthropic, "Anthropic",
        lambda **_: SimpleNamespace(messages=SimpleNamespace(create=lambda **__: response)),
    )

    callback_count = 0

    def interrupt_before_second_call(_fraction: float, _message: str) -> None:
        nonlocal callback_count
        callback_count += 1
        if callback_count == 3:  # 1: original run, 2: preparing the variant, 3: its run
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        _runner.run_real_experiment(
            issues=[{
                "issue_id": "persist-me",
                "issue_text": "A sample issue description.",
                "repo_name": "example/project",
                "custom": True,
            }],
            selected_transforms=["typo_injection"],
            experiment_name="dashboard_durability_check",
            api_key="test-key",
            progress_callback=interrupt_before_second_call,
        )

    with Session(engine) as db:
        experiment = db.query(Experiment).filter_by(
            name="dashboard_durability_check"
        ).one()
        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
        assert experiment.status == "failed"  # the runner records the interruption
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].token_input == 120
        assert runs[0].patch.startswith("--- a/example.py")

    engine.dispose()
