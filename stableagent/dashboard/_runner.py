"""Dashboard experiment runner.

Two public functions, both on the same ExperimentRunner pipeline as `stableagent run` (SPEC
section 12.6), so the dashboard and the CLI cannot drift apart:
  run_mock_experiment()  — MockReplayAdapter, replaying committed fixtures
                           (see fixtures/mock_responses); no API calls.
  run_real_experiment()  — LLMBaselineAdapter with the pilot's parameters, on the chosen
                           provider and model (Claude Sonnet 4.6 or GPT-4o); LLM-backed variants
                           are generated with the transformation model, never replaced by
                           placeholders.

Both create full Experiment / Run / Metric records in the database and return
the experiment_id string so the dashboard can query results immediately.
"""
from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy.orm import Session, sessionmaker

from stableagent.agents.llm_baseline import PROMPT_VERSION, LLMBaselineAdapter
from stableagent.config.pricing import ANTHROPIC
from stableagent.agents.mock_replay import fixture_index, recorded_control_repeats
from stableagent.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.config.settings import api_key_override, redact_api_key, settings
from stableagent.dashboard._picker import describe_replay_gaps, replay_gaps
from stableagent.data.database import build_engine, create_all
from stableagent.data.models import CUSTOM_SOURCE, Issue
from stableagent.execution.runner import ExperimentRunner
from stableagent.metrics.engine import MetricsEngine

ProgressCallback = Callable[[float, str], None]

# The LLM Baseline exactly as the pilot runs it (configs/icse_pilot.json).
REAL_AGENT_PARAMS = {
    "model": LLMBaselineAdapter.DEFAULT_MODEL,
    "temperature": 0.0,
    "max_tokens": LLMBaselineAdapter.DEFAULT_MAX_TOKENS,
    "timeout_seconds": settings.DEFAULT_TIMEOUT_SECONDS,
    "cost_cap_usd": settings.DEFAULT_COST_CAP_USD,
    "prompt_version": PROMPT_VERSION,
}
# Transformation params as in configs/icse_pilot.json, so dashboard runs reuse the pilot's cached
# variants (the params are part of the cache key).
TRANSFORMATION_PARAMS = {
    "verbosity_reduction": {"target_ratio": 0.5},
    "typo_injection": {"error_rate": 0.02},
}


class NotReplayableError(ValueError):
    """MockReplay has no recorded fixture for some selected issue and variant; nothing ran."""


def redact(text: Optional[str], secret: Optional[str]) -> Optional[str]:
    """``text`` with ``secret`` masked. Error strings are stored in the database and shown."""
    return redact_api_key(text, secret) if secret else text


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_issues(db: Session, issues: list[dict]) -> tuple[list[str], list[str]]:
    """(references for the runner config, display labels) for the selected issues.

    A dataset issue must already be in the database (the picker only offers stored issues). A
    custom issue is stored as a new ad-hoc record (source "custom_adhoc"): never reused, never
    listed in the SWE-bench picker, never resolved in place of a dataset issue. Its database id is
    what the runner gets, so a label that happens to equal a dataset id cannot be confused with it.
    """
    refs, labels = [], []
    for data in issues:
        if data.get("custom"):
            issue = Issue(
                external_id=data["issue_id"],
                repo_name=data.get("repo_name") or "unknown/unknown",
                source=CUSTOM_SOURCE,
                issue_text=data["issue_text"],
            )
            db.add(issue)
            db.flush()
            refs.append(issue.id)
        else:
            issue = (
                db.query(Issue)
                .filter(
                    (Issue.external_id == data["issue_id"]) | (Issue.id == data["issue_id"]),
                    Issue.source != CUSTOM_SOURCE,
                )
                .first()
            )
            if issue is None:
                raise ValueError(f"Issue '{data['issue_id']}' is not in the database.")
            refs.append(issue.external_id or issue.id)
        labels.append(issue.external_id or issue.id)
    return refs, labels


def _description(labels: list[str]) -> str:
    if len(labels) == 1:
        return f"Dashboard experiment — issue: {labels[0]}"
    return f"Dashboard experiment — {len(labels)} issues: {', '.join(labels)}"


def _transformations(selected: list[str]) -> list[TransformationConfig]:
    return [
        TransformationConfig(name=name, enabled=True, params=TRANSFORMATION_PARAMS.get(name, {}))
        for name in selected
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def run_mock_experiment(
    issues: list[dict],
    selected_transforms: list[str],
    experiment_name: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """Run a MockReplay experiment through the real ExperimentRunner + MockReplayAdapter
    pipeline, replaying committed fixtures from stableagent/fixtures/mock_responses —
    the same execution path used by `stableagent run --mode mock` (see SPEC section 12.6:
    the runner must treat MockReplay exactly like any other adapter).

    `issues` is a list of {"issue_id": ..., "issue_text": ..., "repo_name": ...} dicts —
    one per selected issue. All issues run against the same transformation set
    (issues × variants), matching how ExperimentRunner already handles multi-issue
    experiments for the CLI. LLM-backed variants are not generated (mock mode makes no API
    calls): a cached generated variant is reused, else the variant the fixture recorded, else a
    labelled placeholder stands in. When every selected issue's fixtures recorded control runs
    (re-runs of the original), that many are replayed as control runs.

    Creates Experiment, TransformedIssue, Run, and Metric records in the database, then
    returns the experiment_id. Raises NotReplayableError, before anything is created, if no
    fixture exists for some issue/variant combination or an issue is a custom one.
    """
    custom = [d["issue_id"] for d in issues if d.get("custom")]
    if custom:
        raise NotReplayableError(
            f"MockReplay only replays recorded fixtures, and a custom issue has none "
            f"({', '.join(custom)}). Switch to LLM Baseline to run it. Nothing was run."
        )
    gaps = replay_gaps([d["issue_id"] for d in issues], selected_transforms, fixture_index())
    if gaps:
        raise NotReplayableError(f"{describe_replay_gaps(gaps)} Nothing was run.")

    engine = build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        refs, labels = _resolve_issues(db, issues)
        if progress_callback:
            progress_callback(0.1, "Replaying fixtures…")
        config = ExperimentConfig(
            experiment_name=experiment_name,
            description=_description(labels),
            execution_mode="mock",
            agents=[AgentConfig(name="mock_replay", version="1.0")],
            issues=IssueConfig(issue_ids=refs),
            transformations=_transformations(selected_transforms),
            runs_per_variant=1,
            # Fixtures recorded from an experiment hold its control runs: replay them too, so the
            # noise floor comes back with the results (every selected issue must have them).
            control_repeats=min((recorded_control_repeats(ref) for ref in refs), default=0),
            cost_limit_usd=settings.DEFAULT_TOTAL_COST_LIMIT_USD,
        )
        experiment = ExperimentRunner(config, db).run()

        if progress_callback:
            progress_callback(0.9, "Computing metrics…")
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        return experiment.id


def run_real_experiment(
    issues: list[dict],
    selected_transforms: list[str],
    experiment_name: str,
    api_key: str,
    progress_callback: Optional[ProgressCallback] = None,
    *,
    provider: str = ANTHROPIC,
    model: str = LLMBaselineAdapter.DEFAULT_MODEL,
) -> str:
    """Run a real LLM Baseline experiment through ExperimentRunner + LLMBaselineAdapter.

    `issues` is a list of {"issue_id": ..., "issue_text": ..., "repo_name": ...} dicts (plus
    "custom": True for a custom issue) — one per selected issue; the agent is called once per
    (issue, variant) pair with the pilot's parameters on `provider` / `model`, under the cost
    guard. With provider "openai" the agent's key comes from OPENAI_API_KEY in .env only, and
    `api_key` (Anthropic) is needed only to generate LLM-backed variants not cached yet.

    LLM-backed variants are generated (or taken from the cache) with the transformation model;
    if one cannot be generated (no key, API failure) the experiment fails with a clear
    TransformationError: real mode never falls back to a placeholder. `api_key` is used for this
    call only (api_key_override): never written to the environment, disk, the database or logs.

    Creates Experiment, TransformedIssue, Run, and Metric records in the database with actual
    LLM outputs, then returns the experiment_id.
    """
    if not api_key and provider == ANTHROPIC:
        raise ValueError("An Anthropic API key is required for LLM Baseline mode.")

    engine = build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        refs, labels = _resolve_issues(db, issues)
        db.commit()
        config = ExperimentConfig(
            experiment_name=experiment_name,
            description=_description(labels),
            execution_mode="real",
            agents=[AgentConfig(
                name="llm_baseline", version=LLMBaselineAdapter.version,
                params={**REAL_AGENT_PARAMS, "provider": provider, "model": model},
            )],
            issues=IssueConfig(issue_ids=refs),
            transformations=_transformations(selected_transforms),
            runs_per_variant=1,
            cost_limit_usd=settings.DEFAULT_TOTAL_COST_LIMIT_USD,
        )
        with api_key_override(api_key):
            experiment = ExperimentRunner(
                config, db, progress_callback=progress_callback
            ).run()

        if progress_callback:
            progress_callback(0.95, "Computing metrics…")
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        return experiment.id
