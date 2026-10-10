"""Record an experiment's runs as MockReplay fixtures (``stabilityeval record-fixtures``).

One fixture per (issue, variant), named as MockReplay looks it up
(``{issue_id}__{transformation}__mock_replay.json``), holding the run's AgentOutput exactly as
stored: status, patch, explanation, token usage, cost, runtime, error message, raw logs and
metadata. On top of that, so that mock mode replays the experiment exactly:

- the original's fixture lists the outputs of the issue's control runs, in order
  (``control_repeats``): the runner's control runs replay them, so the noise floor is replayed too;
- a variant's fixture records the variant the run used (``variant``: text, params, provenance,
  quality and no-op flags, exclusion reason). Offline modes restore it into the transformation
  cache when no generated variant is cached, so a fresh database runs on the same variants and
  skips the same excluded and no-op ones (TransformationCache.restore_recorded);
- a cell the runner skipped (status ``skipped_variant``: the agent was never called) is recorded
  too, so the issue counts as replayable for every transformation of the experiment;
- ``recorded_from`` names the experiment and run.

The gold patch is never written: fixtures hold agent outputs and issue variants only. The output is
deterministic (no timestamps), so recording the same experiment again rewrites identical files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from stability_eval.agents.mock_replay import fixture_filename
from stability_eval.data.models import Experiment, Issue, Run, TransformedIssue
from stability_eval.transformations.cache import recorded_variant


@dataclass(frozen=True)
class RecordedFixture:
    path: Path
    issue_id: str
    transformation_name: str
    status: str
    control_repeats: int
    changed: bool  # False when the file already held exactly this content


def record_experiment_fixtures(
    db: Session, experiment_id: str, fixtures_dir: str | Path
) -> list[RecordedFixture]:
    """Write one fixture per (issue, variant) of the experiment into ``fixtures_dir``.

    Raises ValueError, before writing anything, when the experiment cannot be replayed exactly:
    no runs, several agents (fixtures are per issue and variant, not per agent), or several
    replicas of a variant (``runs_per_variant`` > 1).
    """
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise ValueError(f"Experiment '{experiment_id}' not found.")
    rows = (
        db.query(Run, TransformedIssue, Issue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .join(Issue, TransformedIssue.issue_id == Issue.id)
        .filter(Run.experiment_id == experiment.id)
        .order_by(Run.run_index, Run.created_at)
        .all()
    )
    if not rows:
        raise ValueError(f"Experiment {experiment.id} has no runs to record.")
    agents = sorted({run.agent_name for run, _, _ in rows})
    if len(agents) > 1:
        raise ValueError(
            f"Experiment {experiment.id} ran {len(agents)} agents ({', '.join(agents)}); "
            "MockReplay fixtures are per issue and variant, so record a single-agent experiment."
        )

    cells: dict[tuple[str, str], tuple[Run, TransformedIssue, Issue]] = {}
    controls: dict[str, list[Run]] = {}
    for run, ti, issue in rows:
        label = issue.external_id or issue.id
        if run.control_repeat:
            controls.setdefault(label, []).append(run)
            continue
        key = (label, ti.transformation_name)
        if key in cells:
            raise ValueError(
                f"Experiment {experiment.id} has several runs of {label} / "
                f"{ti.transformation_name} (runs_per_variant > 1); a fixture replays one."
            )
        cells[key] = (run, ti, issue)

    directory = Path(fixtures_dir)
    directory.mkdir(parents=True, exist_ok=True)
    recorded: list[RecordedFixture] = []
    for (label, transformation_name), (run, ti, issue) in sorted(cells.items()):
        fixture = _agent_output(run)
        repeats = controls.get(label, []) if ti.is_original else []
        if repeats:
            fixture["control_repeats"] = [_agent_output(control) for control in repeats]
        if not ti.is_original:
            fixture["variant"] = recorded_variant(ti, issue.issue_text)
        fixture["recorded_from"] = {
            "experiment_id": experiment.id,
            "experiment_name": experiment.name,
            "run_id": run.id,
            "agent_name": run.agent_name,
            "execution_mode": run.execution_mode,
        }
        path = directory / fixture_filename(label, transformation_name)
        content = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
        changed = not path.is_file() or path.read_text(encoding="utf-8") != content
        if changed:
            path.write_text(content, encoding="utf-8")
        recorded.append(RecordedFixture(
            path=path, issue_id=label, transformation_name=transformation_name,
            status=run.status, control_repeats=len(repeats), changed=changed,
        ))
    return recorded


def _agent_output(run: Run) -> dict:
    """The run's AgentOutput fields, as MockReplayAdapter reads them back."""
    return {
        "status": run.status,
        "patch": run.patch,
        "explanation": run.explanation,
        "token_usage": {
            key: value
            for key, value in (("input", run.token_input), ("output", run.token_output))
            if value is not None
        },
        "cost_usd": run.cost_usd or 0.0,
        "runtime_seconds": run.runtime_seconds or 0.0,
        "error_message": run.error_message,
        "raw_logs": run.raw_logs or "",
        "metadata": json.loads(run.metadata_) if run.metadata_ else {},
    }
