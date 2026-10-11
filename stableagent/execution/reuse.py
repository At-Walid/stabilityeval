"""Run an experiment on exactly the variants an earlier one ran on (``reuse_variants_from``).

A second model must see the very texts the first one saw: same paraphrase, same typo injection
(which differs from one computation to the next without a seed), same skipped variants. So with
``reuse_variants_from`` set to an experiment id, each issue's variant of each enabled
transformation is the stored variant (TransformedIssue row) that experiment's run used. Nothing is
looked up in the transformation cache and nothing is generated: if the earlier experiment has no
run on some variant, that variant would have to be generated, and the experiment fails before
anything is recorded (SPEC section 12.1). Read-only: nothing here writes to the database.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from stableagent.config.experiment_schema import ExperimentConfig
from stableagent.data.models import Experiment, Run, TransformedIssue
from stableagent.transformations.cache import TransformationError

# At most this many missing variants are named in an error message.
_SHOWN = 10


class VariantReuseError(TransformationError):
    """``reuse_variants_from`` cannot supply some variant, which would then have to be generated."""


def reused_variants(
    config: ExperimentConfig, db: Session
) -> dict[tuple[str, str], TransformedIssue] | None:
    """(issue database id, transformation name) -> the variant the reference experiment ran on.

    None when the config sets no ``reuse_variants_from``. Raises VariantReuseError, naming every
    problem, when the reference experiment is not in the database, when it has no run on some
    (issue, enabled transformation) or runs on several variants of it, or when the stored
    variant was produced with other params than the config's. Issues missing from the database
    are named too.
    """
    reference_id = config.reuse_variants_from
    if not reference_id:
        return None
    from stableagent.execution.plan import enabled_transformations, find_issue

    if db.get(Experiment, reference_id) is None:
        raise VariantReuseError(
            f"reuse_variants_from: experiment {reference_id} is not in this database, so its "
            "variants cannot be reused and every variant would have to be generated. Use the "
            "database that holds it (the shipped data/pilot/stableagent_pilot.db does for the "
            "ICSE pilot). Nothing was run."
        )

    used: dict[tuple[str, str], dict[str, TransformedIssue]] = {}
    rows = (
        db.query(TransformedIssue)
        .join(Run, Run.transformed_issue_id == TransformedIssue.id)
        .filter(Run.experiment_id == reference_id)
        .all()
    )
    for row in rows:
        if row.is_original:
            continue
        used.setdefault((row.issue_id, row.transformation_name), {})[row.id] = row

    pinned: dict[tuple[str, str], TransformedIssue] = {}
    problems: list[str] = []
    for issue_id in config.issues.issue_ids:
        issue = find_issue(db, issue_id)
        if issue is None:
            problems.append(f"{issue_id}: issue not in the database")
            continue
        label = issue.external_id or issue.id
        for transform_cfg in enabled_transformations(config):
            name = transform_cfg.name
            candidates = used.get((issue.id, name), {})
            if not candidates:
                problems.append(f"{label}/{name}: no run in {reference_id[:8]}")
            elif len(candidates) > 1:
                problems.append(
                    f"{label}/{name}: {reference_id[:8]} ran on {len(candidates)} different "
                    "variants"
                )
            else:
                (row,) = candidates.values()
                stored = _stored_params(row)
                if stored != transform_cfg.params:
                    problems.append(
                        f"{label}/{name}: stored with params {json.dumps(stored, sort_keys=True)}"
                        f", configured {json.dumps(transform_cfg.params, sort_keys=True)}"
                    )
                else:
                    pinned[(issue.id, name)] = row
    if problems:
        shown = "; ".join(problems[:_SHOWN])
        more = f"; and {len(problems) - _SHOWN} more" if len(problems) > _SHOWN else ""
        raise VariantReuseError(
            f"reuse_variants_from {reference_id}: {len(problems)} variant(s) cannot be taken from "
            f"that experiment and would have to be generated, which reuse forbids: {shown}{more}. "
            "Nothing was run."
        )
    return pinned


def _stored_params(row: TransformedIssue) -> dict:
    try:
        stored = json.loads(row.transformation_params or "{}")
    except json.JSONDecodeError:
        return {}
    params = stored.get("params", {}) if isinstance(stored, dict) else {}
    return params if isinstance(params, dict) else {}
