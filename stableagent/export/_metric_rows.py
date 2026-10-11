from __future__ import annotations

from sqlalchemy.orm import Session

from stableagent.data.models import Metric, TransformedIssue
from stableagent.transformations.base import UNKNOWN

# Variant provenance columns, in export order (SPEC section 11.6), then why the variant is
# excluded from the metrics, if it is (missing technical tokens, or no-op).
PROVENANCE_FIELDS = [
    "generator", "transform_version", "generation_mode", "noop", "exclusion_reason",
]


def metric_rows(db: Session, experiment_id: str) -> list[tuple]:
    """(scope, scope_key, metric_name, metric_value) for every metric of the experiment."""
    return [
        (m.scope, m.scope_key, m.metric_name, m.metric_value)
        for m in db.query(Metric).filter(Metric.experiment_id == experiment_id).all()
    ]


def provenance(ti: TransformedIssue) -> dict:
    """The variant's provenance (generator, transform_version, generation_mode, noop) and its
    exclusion_reason."""
    return {
        "generator": ti.generator or UNKNOWN,
        "transform_version": ti.transform_version,
        "generation_mode": ti.generation_mode,
        "noop": bool(ti.noop),
        "exclusion_reason": ti.exclusion_reason,
    }
