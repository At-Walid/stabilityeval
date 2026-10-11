"""Every RQ1/RQ2 metric per agent, across experiments: several models on the same issues.

Each agent of each compared experiment is one compared agent, named after its model ("LLM
Baseline (GPT-4o)"). Its runs are scored exactly as the metrics engine scores them
(``MetricsEngine.scored_runs``: localization success, the same exclusions), and every metric is
computed within that agent:

- RQ1: originals localized, variants that kept their original's outcome, Success Consistency (A)
  and the Stability Score (F), the control flip rate;
- RQ2: per transformation, Transformation Sensitivity (G), the flip rate and the changed-line
  similarity with its bootstrap CI, its mean paired difference to the repeat of the original and
  the exploratory Wilcoxon p-value.

A variant's patch, and a repeat's, is only ever compared with the same agent's own original run:
the metric classes key everything by (agent, issue), and here each compared agent gets a key of
its own, even when two experiments recorded the same ``agent_name``. Nothing is stored; the
stored per-experiment metrics are unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from stableagent.config.experiment_schema import ExperimentConfig
from stableagent.config.pricing import display_name
from stableagent.data.models import Experiment
from stableagent.metrics.changed_line_similarity import (
    ChangedLineSimilarity,
    ControlComparison,
    SimilaritySummary,
)
from stableagent.metrics.engine import MetricsEngine
from stableagent.metrics.outcome import outcome_value
from stableagent.metrics.sensitivity import ControlFlipRate, FlipRate, TransformationSensitivity
from stableagent.metrics.stability_score import StabilityScore
from stableagent.metrics.success import SuccessConsistency

# The key of the repeat-of-the-original row, next to the transformation names.
CONTROL = "repeat_of_original"


@dataclass(frozen=True)
class AgentRef:
    key: str  # unique among the compared agents; the rows' agent_name
    label: str  # "LLM Baseline (GPT-4o)"
    short_label: str  # "GPT-4o": legends
    experiment_id: str
    agent_name: str  # Run.agent_name in that experiment
    model: str | None


@dataclass(frozen=True)
class VariantRow:
    """One transformation (or the repeat of the original, CONTROL) of one agent."""

    transformation: str
    n: int  # issues compared with the original (both runs scored)
    kept: int  # compared runs whose outcome equals the original's
    compared_runs: int
    similarity: SimilaritySummary | None
    versus_control: ControlComparison | None  # None for CONTROL
    sensitivity: float | None  # G (None for CONTROL)
    flip_rate: float | None  # the control flip rate on the CONTROL row
    excluded: int  # runs on excluded or no-op variants (never compared)


@dataclass(frozen=True)
class AgentComparison:
    agent: AgentRef
    originals_localized: int
    originals_scored: int
    variants_kept: int  # over every transformation (control runs not included)
    variants_scored: int
    stability_score_mean: float | None
    rows: list[VariantRow]  # CONTROL first when there are control runs, then the transformations

    def row(self, transformation: str) -> VariantRow | None:
        return next((r for r in self.rows if r.transformation == transformation), None)

    @property
    def control(self) -> VariantRow | None:
        return self.row(CONTROL)


def agent_ref(experiment_id: str, agent_name: str, params: dict) -> AgentRef:
    """The compared agent of an experiment, labelled after its model when it has one."""
    model = params.get("model")
    if model:
        short = display_name(model)
        label = f"LLM Baseline ({short})" if agent_name.startswith("llm_baseline") else (
            f"{agent_name} ({short})"
        )
    else:
        short = label = "MockReplay" if agent_name == "mock_replay" else agent_name
    return AgentRef(
        key=f"{experiment_id}|{agent_name}", label=label, short_label=short,
        experiment_id=experiment_id, agent_name=agent_name, model=model,
    )


def compare_experiments(experiment_ids: list[str], db: Session) -> list[AgentComparison]:
    """Score the runs of each experiment and compare every agent, in the order given.

    Raises ValueError for an experiment that is not in the database.
    """
    engine = MetricsEngine()
    refs: list[AgentRef] = []
    run_data: list[dict] = []
    control_data: list[dict] = []
    excluded: dict[tuple[str, str], int] = defaultdict(int)
    order: list[str] = []
    for experiment_id in experiment_ids:
        experiment = db.get(Experiment, experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment '{experiment_id}' not found.")
        params, transformations = _config(experiment)
        scored = engine.scored_runs(experiment_id, db)
        names = dict.fromkeys(
            ref["agent_name"]
            for ref in scored.run_data + scored.control_data + scored.excluded_status
            + scored.excluded_quality + scored.excluded_noop
        )
        mine = {name: agent_ref(experiment_id, name, params.get(name, {})) for name in names}
        refs.extend(mine.values())
        for target, rows in ((run_data, scored.run_data), (control_data, scored.control_data)):
            target.extend({**row, "agent_name": mine[row["agent_name"]].key} for row in rows)
        for ref in scored.excluded_quality + scored.excluded_noop:
            excluded[(mine[ref["agent_name"]].key, ref["transformation_name"])] += 1
        seen = transformations + [
            row["transformation_name"] for row in scored.run_data if not row["is_original"]
        ]
        order.extend(name for name in seen if name not in order)
    return compare_rows(_unique_labels(refs), run_data, control_data, order, excluded)


def compare_rows(
    refs: list[AgentRef],
    run_data: list[dict],
    control_data: list[dict],
    transformations: list[str],
    excluded: dict[tuple[str, str], int] | None = None,
) -> list[AgentComparison]:
    """The comparison from scored rows whose ``agent_name`` is the compared agent's key (the
    metrics engine's row format, see ``ScoredRuns``)."""
    excluded = excluded or {}
    sc = SuccessConsistency().compute(run_data)
    ss = StabilityScore().compute(run_data, sc_results=sc)["per_agent"]
    ts = TransformationSensitivity().compute(run_data)
    flips = FlipRate().compute(run_data)
    control_flips = ControlFlipRate().compute(run_data, control_data)
    similarity = ChangedLineSimilarity().compute(run_data, control_data)

    results = []
    for ref in refs:
        originals = {
            row["issue_id"]: outcome_value(row)
            for row in run_data
            if row["agent_name"] == ref.key and row["is_original"]
            and outcome_value(row) is not None
        }
        compared: dict[str, list[tuple[str, bool]]] = defaultdict(list)  # name -> (issue, kept)
        for row in run_data:
            if row["agent_name"] != ref.key or row["is_original"]:
                continue
            value = outcome_value(row)
            if value is not None and row["issue_id"] in originals:
                kept = value == originals[row["issue_id"]]
                compared[row["transformation_name"]].append((row["issue_id"], kept))
        for row in control_data:
            value = outcome_value(row)
            if row["agent_name"] == ref.key and value is not None and row["issue_id"] in originals:
                compared[CONTROL].append((row["issue_id"], value == originals[row["issue_id"]]))

        rows = []
        if compared.get(CONTROL):
            pairs = compared[CONTROL]
            rows.append(VariantRow(
                transformation=CONTROL, n=len({issue for issue, _ in pairs}),
                kept=sum(kept for _, kept in pairs), compared_runs=len(pairs),
                similarity=similarity.control.get(ref.key), versus_control=None,
                sensitivity=None,
                flip_rate=(control_flips.get(ref.key) or {}).get("value"),
                excluded=0,
            ))
        for name in transformations:
            pairs = compared.get(name, [])
            n_excluded = excluded.get((ref.key, name), 0)
            if not pairs and not n_excluded:
                continue
            rows.append(VariantRow(
                transformation=name, n=len({issue for issue, _ in pairs}),
                kept=sum(kept for _, kept in pairs), compared_runs=len(pairs),
                similarity=similarity.per_transformation.get((ref.key, name)),
                versus_control=similarity.versus_control.get((ref.key, name)),
                sensitivity=ts.get((ref.key, name)), flip_rate=flips.get((ref.key, name)),
                excluded=n_excluded,
            ))
        variant_pairs = [p for name, pairs in compared.items() if name != CONTROL for p in pairs]
        results.append(AgentComparison(
            agent=ref,
            originals_localized=sum(1 for value in originals.values() if value == 1),
            originals_scored=len(originals),
            variants_kept=sum(kept for _, kept in variant_pairs),
            variants_scored=len(variant_pairs),
            stability_score_mean=ss.get(ref.key),
            rows=rows,
        ))
    return results


def _config(experiment: Experiment) -> tuple[dict[str, dict], list[str]]:
    """(agent name -> params, enabled transformation names) of the experiment's config."""
    try:
        config = ExperimentConfig.model_validate_json(experiment.config)
    except ValueError:
        return {}, []
    params = {agent.name: dict(agent.params) for agent in config.agents}
    return params, [t.name for t in config.transformations if t.enabled]


def _unique_labels(refs: list[AgentRef]) -> list[AgentRef]:
    """Two compared agents with the same label (e.g. one model in two experiments) get the
    experiment's short id appended, so tables and legends never merge them."""
    counts: dict[str, int] = defaultdict(int)
    for ref in refs:
        counts[ref.label] += 1
    return [
        ref if counts[ref.label] == 1 else AgentRef(
            key=ref.key, label=f"{ref.label} [{ref.experiment_id[:8]}]",
            short_label=f"{ref.short_label} [{ref.experiment_id[:8]}]",
            experiment_id=ref.experiment_id, agent_name=ref.agent_name, model=ref.model,
        )
        for ref in refs
    ]
