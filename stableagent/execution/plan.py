"""What an experiment will run, counted before anything runs (``stableagent run --estimate``).

``plan_runs`` counts the runs from the config alone; the runner executes exactly these cells and
its progress bar uses the same total, so the estimate cannot drift from what runs. ``preflight``
adds what the database knows (read-only): which issues are loaded, which have a gold patch, which
LLM-backed variants are not cached yet and would be generated in real mode, which variants are
known to be excluded or no-ops (their cells are recorded without calling the agent), and, with
``reuse_variants_from``, whether every variant can be reused. ``agent_estimates`` gives each
agent's expected cost per run from the model table. Nothing here calls an API or writes to the
database.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from stableagent.config.experiment_schema import ExperimentConfig, TransformationConfig
from stableagent.config.pricing import MODELS, UnknownModelError, model_info
from stableagent.data.loaders.swebench import gold_patch_of
from stableagent.data.models import CUSTOM_SOURCE, Issue
from stableagent.transformations.cache import TransformationError, find_cached_variant
from stableagent.transformations.registry import transformation_registry

# Expected tokens of one LLM Baseline run: the means over the 148 agent runs of the ICSE pilot
# (experiment bc6f1372, claude-sonnet-4-6, prompt issue-to-unified-diff-v3-submit-patch-tool,
# forced submit_patch call): 1516 input and 337 output tokens, i.e. $0.0096 per run at Sonnet 4.6
# prices, the measured mean. Another model's expected cost applies its own prices (config/
# pricing.py) to these counts; its tokenizer and answer length make the real cost differ a little.
ESTIMATED_INPUT_TOKENS_PER_RUN = 1516
ESTIMATED_OUTPUT_TOKENS_PER_RUN = 337
# Expected cost of generating one LLM-backed variant (one Haiku call; SPEC section 6, step 3).
# Retry-then-exclude can add 1 more call for a variant that fails the placeholder or quality check.
ESTIMATED_COST_PER_VARIANT_USD = 0.008


def enabled_transformations(config: ExperimentConfig) -> list[TransformationConfig]:
    """The transformations an experiment applies: the enabled ones, none in originals-only mode."""
    if config.originals_only:
        return []
    return [t for t in config.transformations if t.enabled]


@dataclass(frozen=True)
class RunPlan:
    """The runs of an experiment: per agent and issue, the original, each variant, the controls."""

    agents: int
    issues: int
    transformations: int  # applied per issue (0 in originals-only mode)
    runs_per_variant: int
    control_repeats: int  # per agent and issue (0 in originals-only mode)

    @property
    def originals(self) -> int:
        return self.agents * self.issues * self.runs_per_variant

    @property
    def variants(self) -> int:
        return self.agents * self.issues * self.transformations * self.runs_per_variant

    @property
    def controls(self) -> int:
        return self.agents * self.issues * self.control_repeats

    @property
    def total(self) -> int:
        return self.originals + self.variants + self.controls


def plan_runs(config: ExperimentConfig) -> RunPlan:
    return RunPlan(
        agents=len(config.agents),
        issues=len(config.issues.issue_ids),
        transformations=len(enabled_transformations(config)),
        runs_per_variant=config.runs_per_variant,
        control_repeats=0 if config.originals_only else config.control_repeats,
    )


def find_issue(db: Session, issue_id: str) -> Issue | None:
    """By database id, else by external id (a dataset record wins over an ad-hoc custom one)."""
    return db.get(Issue, issue_id) or (
        db.query(Issue)
        .filter(Issue.external_id == issue_id)
        .order_by(Issue.source == CUSTOM_SOURCE)
        .first()
    )


def expected_cost_per_run(model: str) -> float:
    """Expected cost of one LLM Baseline run on ``model``: the pilot's mean token counts at the
    model's prices. Raises UnknownModelError for a model without a price."""
    return model_info(model).cost(ESTIMATED_INPUT_TOKENS_PER_RUN, ESTIMATED_OUTPUT_TOKENS_PER_RUN)


@dataclass(frozen=True)
class AgentEstimate:
    name: str
    provider: str
    model: str
    api_key_env_var: str
    key_set: bool  # presence only: the estimate never shows the key
    cost_per_run: float | None  # None: the model has no price in the model table
    problem: str | None  # why this agent cannot run in real mode, if it cannot


def agent_estimates(config: ExperimentConfig) -> list[AgentEstimate]:
    """Per agent, what real mode runs (the LLM Baseline with the agent's params: provider, model,
    key variable), whether its key is set, and its expected cost per run."""
    from stableagent.agents.llm_baseline import LLMBaselineAdapter

    estimates = []
    for agent_cfg in config.agents:
        adapter = LLMBaselineAdapter()
        adapter.configure(agent_cfg.params)
        try:
            adapter.check_ready()
            problem = None
        except (UnknownModelError, ValueError, RuntimeError) as exc:
            problem = str(exc)
        estimates.append(AgentEstimate(
            name=agent_cfg.name,
            provider=adapter.provider,
            model=adapter.model,
            api_key_env_var=adapter.api_key_env_var,
            key_set=adapter.has_api_key(),
            cost_per_run=expected_cost_per_run(adapter.model) if adapter.model in MODELS else None,
            problem=problem,
        ))
    return estimates


def variants_to_generate(config: ExperimentConfig, db: Session) -> list[str]:
    """"issue/transformation" of every LLM-backed variant not cached yet (real mode generates it).

    Issues missing from the database are skipped (``preflight`` reports them). Empty with
    ``reuse_variants_from``: such an experiment never generates a variant.
    """
    if config.reuse_variants_from:
        return []
    needed = []
    for transform_cfg in enabled_transformations(config):
        transformation = transformation_registry.get(transform_cfg.name)()
        if transformation.category != "llm_backed":
            continue
        for issue_id in config.issues.issue_ids:
            issue = find_issue(db, issue_id)
            if issue is not None and find_cached_variant(
                db, issue.id, transformation, transform_cfg.params
            ) is None:
                needed.append(f"{issue.external_id or issue.id}/{transformation.name}")
    return needed


@dataclass(frozen=True)
class Preflight:
    missing_issues: list[str]  # configured ids not found in the database
    without_gold: list[str]  # found, but no gold patch: outcome falls back to "valid diff only"
    variants_to_generate: list[str]
    # "issue/transformation" of the variants known to be excluded or no-ops (cached or reused):
    # their cells are recorded as skipped_variant, without calling the agent
    skipped_variants: list[str]
    reused_variants: int | None = None  # with reuse_variants_from: how many variants it supplies
    reuse_error: str | None = None  # with reuse_variants_from: why it cannot supply them all

    def agent_runs(self, plan: RunPlan) -> int:
        """The runs that call an agent: the planned runs minus the known skipped cells."""
        return plan.total - len(self.skipped_variants) * plan.agents * plan.runs_per_variant


def preflight(config: ExperimentConfig, db: Session) -> Preflight:
    """What the database knows about the planned experiment. Read-only."""
    from stableagent.execution.reuse import reused_variants

    issues = {issue_id: find_issue(db, issue_id) for issue_id in config.issues.issue_ids}
    missing = [issue_id for issue_id, issue in issues.items() if issue is None]
    without_gold = [
        issue_id for issue_id, issue in issues.items()
        if issue is not None and gold_patch_of(issue) is None
    ]

    reused, reuse_error = None, None
    try:
        reused = reused_variants(config, db)
    except TransformationError as exc:
        reuse_error = str(exc)
    skipped = []
    for transform_cfg in enabled_transformations(config):
        transformation = transformation_registry.get(transform_cfg.name)()
        for issue in issues.values():
            if issue is None:
                continue
            if config.reuse_variants_from:
                row = (reused or {}).get((issue.id, transformation.name))
            else:
                row = find_cached_variant(db, issue.id, transformation, transform_cfg.params)
            if row is not None and (row.quality_warning or row.noop):
                skipped.append(f"{issue.external_id or issue.id}/{transformation.name}")
    return Preflight(
        missing, without_gold, variants_to_generate(config, db), skipped,
        reused_variants=len(reused) if reused is not None else None,
        reuse_error=reuse_error,
    )
