"""Requeue the variants excluded only because of identifier-retention false positives (offline).

The retention check now ignores markdown formatting and issue-template boilerplate (SPEC section
11.5): "_No response_", standard section headings, emphasis markers, "\\_" escapes, HTML tags.
A variant stored with quality_warning and an exclusion reason "identifier retention failed (...)"
(and nothing else: no invented details, no lost placeholder) is re-checked against its issue with
the current rules. If it passes now, every token it was missing was a false positive: its cache
key is removed so the next run (or ``stableagent run --generate-only``) regenerates it. Nothing
else changes: variants that passed stay cached, and the row stays for the runs that used it. No API
call is made.

Usage:
    python scripts/requeue_retention_false_positives.py --dry-run   # list only
    python scripts/requeue_retention_false_positives.py
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import stableagent.transformations  # noqa: E402,F401  (registers the transformations)
from stableagent.data.database import build_engine, create_all  # noqa: E402
from stableagent.data.models import TransformedIssue  # noqa: E402
from stableagent.transformations.base import check_identifier_retention  # noqa: E402
from stableagent.transformations.cache import (  # noqa: E402
    PLACEHOLDER_LOST,
    is_cached,
    uncache,
)
from stableagent.transformations.registry import transformation_registry  # noqa: E402

RETENTION_REASON = "identifier retention failed"
# The other reasons a variant can be excluded for (see transformations/cache.py::_describe).
OTHER_REASONS = ("invented details", PLACEHOLDER_LOST)
REQUEUE_NOTE = "requeued: its missing tokens are false positives of the old retention rules"


@dataclass(frozen=True)
class Candidate:
    row: TransformedIssue
    issue_id: str  # external id, else database id
    still_missing: list[str]  # under the current rules; empty: requeued


def retention_exclusions(db) -> list[Candidate]:
    """Every variant the cache serves (current transform_version, cache key kept) that is
    excluded for identifier retention only, re-checked with the current rules."""
    rows = (
        db.query(TransformedIssue)
        .filter(
            TransformedIssue.quality_warning.is_(True),
            TransformedIssue.exclusion_reason.like(f"{RETENTION_REASON}%"),
        )
        .order_by(TransformedIssue.created_at)
    )
    names = set(transformation_registry.list_names())
    candidates = []
    for row in rows:
        if (
            row.transformation_name not in names
            or row.transform_version
            != transformation_registry.get(row.transformation_name).transform_version
            or not is_cached(row)
            or any(other in row.exclusion_reason for other in OTHER_REASONS)
        ):
            continue  # not served by the cache, or excluded for something else as well
        _passed, missing = check_identifier_retention(row.issue.issue_text, row.transformed_text)
        candidates.append(Candidate(row, row.issue.external_id or row.issue.id, missing))
    return candidates


def main(argv: list[str] | None = None, *, engine=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list, change nothing")
    args = parser.parse_args(argv)

    engine = engine or build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        candidates = retention_exclusions(db)
        requeued = [c for c in candidates if not c.still_missing]
        for c in candidates:
            verdict = "requeue" if not c.still_missing else "keep   "
            print(
                f"  {verdict} {c.issue_id} / {c.row.transformation_name} "
                f"v{c.row.transform_version}: was {c.row.exclusion_reason}"
                + (f" | still missing: {', '.join(c.still_missing)}" if c.still_missing else "")
            )
        if not args.dry_run:
            for c in requeued:
                uncache(c.row, REQUEUE_NOTE)
            db.commit()
    print(
        f"{len(candidates)} cached variant(s) excluded for identifier retention only; "
        f"{len(requeued)} {'would be requeued' if args.dry_run else 'requeued'} (false positives), "
        f"{len(candidates) - len(requeued)} kept excluded."
        + (" Dry run: nothing changed." if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
