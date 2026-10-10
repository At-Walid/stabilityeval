"""Generate and quality-check an experiment's variants without running any agent.

``stabilityeval run --generate-only`` uses ``generate_variants``: every enabled transformation's
variant of every issue is taken from the cache, or generated and quality-checked (an LLM-backed
one with its code masked, SPEC section 11.7), then stored, so the experiment run that follows finds
them all cached. No agent is called and no experiment is recorded.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from stability_eval.config.experiment_schema import ExperimentConfig
from stability_eval.config.settings import get_anthropic_api_key
from stability_eval.data.models import TransformedIssue as TransformedIssueModel
from stability_eval.execution.plan import enabled_transformations, find_issue, variants_to_generate
from stability_eval.transformations.base import IssueRecord
from stability_eval.transformations.cache import (
    OFFLINE_MODES,
    TransformationCache,
    TransformationError,
    find_cached_variant,
)
from stability_eval.transformations.registry import transformation_registry

OK = "ok"
NOOP = "noop"
EXCLUDED = "excluded"
NOT_GENERATED = "not generated"


@dataclass(frozen=True)
class VariantStatus:
    issue_id: str  # the issue's external id, else its database id
    transformation: str
    status: str  # OK, NOOP, EXCLUDED or NOT_GENERATED
    reason: str | None  # why it is excluded, a no-op or not generated
    cost_usd: float  # API cost spent on it by this call: 0 for a cached variant
    cached: bool


def check_variants_can_be_generated(config: ExperimentConfig, db: Session) -> None:
    """Real mode: fail before anything runs if uncached LLM-backed variants need a missing key."""
    if config.execution_mode != "real" or get_anthropic_api_key():
        return
    needed = variants_to_generate(config, db)
    if needed:
        shown = ", ".join(needed[:5]) + (f" and {len(needed) - 5} more" if len(needed) > 5 else "")
        raise TransformationError(
            f"Real mode must generate {len(needed)} LLM-backed variant(s) ({shown}) but no "
            "Anthropic API key is configured (ANTHROPIC_API_KEY, or the key entered in the "
            "dashboard). Placeholders are only used in mock and dry-run modes. Nothing was run."
        )


def generate_variants(config: ExperimentConfig, db: Session) -> list[VariantStatus]:
    """The status of every (issue, enabled transformation) variant, generating the missing ones.

    Cached variants cost nothing. In real mode a missing variant is generated (an LLM-backed one
    with up to two Haiku calls) and stored; mock and dry-run modes never generate an LLM-backed
    variant and report it as not generated. Each variant is committed as soon as it is stored, so
    a failure keeps the ones already generated. Raises ValueError, before generating anything,
    when an issue is not in the database, and TransformationError like the runner.
    """
    issues = []
    for issue_id in config.issues.issue_ids:
        issue = find_issue(db, issue_id)
        if issue is None:
            raise ValueError(f"Issue '{issue_id}' not found in the database")
        issues.append(issue)
    check_variants_can_be_generated(config, db)

    mode = config.execution_mode
    cache = TransformationCache(db)
    statuses = []
    for issue in issues:
        label = issue.external_id or issue.id
        record = IssueRecord(
            issue_id=issue.id,
            repo_name=issue.repo_name,
            text=issue.issue_text,
            metadata={"external_id": label},
        )
        for transform_cfg in enabled_transformations(config):
            transformation = transformation_registry.get(transform_cfg.name)()
            row = find_cached_variant(db, issue.id, transformation, transform_cfg.params)
            cached = row is not None
            if row is None and transformation.category == "llm_backed" and mode in OFFLINE_MODES:
                statuses.append(VariantStatus(
                    label, transformation.name, NOT_GENERATED,
                    f"{mode} mode makes no API calls", 0.0, False,
                ))
                continue
            if row is None:
                row = cache.variant(transformation, record, transform_cfg.params, mode=mode)
                db.commit()
            statuses.append(VariantStatus(
                label, transformation.name, *_status(row),
                0.0 if cached else (row.generation_cost_usd or 0.0), cached,
            ))
    return statuses


def _status(row: TransformedIssueModel) -> tuple[str, str | None]:
    if row.quality_warning:
        return EXCLUDED, row.exclusion_reason or "quality warning"
    if row.noop:
        return NOOP, row.exclusion_reason
    return OK, None
