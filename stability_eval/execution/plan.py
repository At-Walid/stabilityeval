"""What an experiment will run, counted before anything runs (``stabilityeval run --estimate``).

``plan_runs`` counts the runs from the config alone; the runner executes exactly these cells and
its progress bar uses the same total, so the estimate cannot drift from what runs. ``preflight``
adds what the database knows (read-only): which issues are loaded, which have a gold patch, and
which LLM-backed variants are not cached yet and would be generated in real mode. Nothing here
calls an API or writes to the database.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from stability_eval.config.experiment_schema import ExperimentConfig, TransformationConfig
from stability_eval.data.loaders.swebench import gold_patch_of
from stability_eval.data.models import CUSTOM_SOURCE, Issue
from stability_eval.transformations.cache import find_cached_variant
from stability_eval.transformations.registry import transformation_registry

# Expected cost of one LLM Baseline run: the measured mean with the forced submit_patch tool call
# (prompt issue-to-unified-diff-v3-submit-patch-tool, max_tokens 4096) was $0.0133 over the 7 real
# runs recorded with it (2026-10-05), rounded up.
ESTIMATED_COST_PER_RUN_USD = 0.015
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


def variants_to_generate(config: ExperimentConfig, db: Session) -> list[str]:
    """"issue/transformation" of every LLM-backed variant not cached yet (real mode generates it).

    Issues missing from the database are skipped (``preflight`` reports them).
    """
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


def preflight(config: ExperimentConfig, db: Session) -> Preflight:
    """What the database knows about the planned experiment. Read-only."""
    missing, without_gold = [], []
    for issue_id in config.issues.issue_ids:
        issue = find_issue(db, issue_id)
        if issue is None:
            missing.append(issue_id)
        elif gold_patch_of(issue) is None:
            without_gold.append(issue_id)
    return Preflight(missing, without_gold, variants_to_generate(config, db))
