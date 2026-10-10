"""Insert the 20 Stage 1 candidate issues into the issues table, idempotently and offline.

Reads scripts/output/stage1_candidates.json (id, repo, problem_statement) and takes each issue's
hidden gold patch from the bundled dataset file data/swebench_lite_issues.json: no network. The
candidate's problem statement must be the dataset's verbatim text; a mismatch stops the script.

Issues already in the database are skipped (their text is never changed); one that has no gold
patch yet gets it attached, as hidden metadata only. Prints what happened and the issue counts
per source.

Usage:
    python scripts/seed_issues_from_stage1.py
    python scripts/seed_issues_from_stage1.py --candidates path/to/stage1_candidates.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stability_eval.data.database import build_engine, create_all  # noqa: E402
from stability_eval.data.loaders.swebench import (  # noqa: E402
    gold_patch_of,
    load_bundle,
    store_instances,
)
from stability_eval.data.models import Issue  # noqa: E402

CANDIDATES = PROJECT_ROOT / "scripts" / "output" / "stage1_candidates.json"


def seed(db, candidates: list[dict]) -> dict[str, list[str]]:
    """Insert missing candidates; returns ids per outcome: inserted, skipped, gold_attached."""
    ids = [c["id"] for c in candidates]
    instances = {i.instance_id: i for i in load_bundle(ids)}
    for candidate in candidates:
        if candidate["problem_statement"] != instances[candidate["id"]].problem_statement:
            raise ValueError(
                f"{candidate['id']}: the candidate's problem statement is not the dataset's "
                "verbatim text"
            )
    existing = {
        issue.external_id: issue
        for issue in db.query(Issue).filter(Issue.external_id.in_(ids))
    }
    report: dict[str, list[str]] = {"inserted": [], "skipped": [], "gold_attached": []}
    for issue_id in ids:
        issue = existing.get(issue_id)
        if issue is None:
            report["inserted"].append(issue_id)
        elif gold_patch_of(issue) is None:
            report["gold_attached"].append(issue_id)
        else:
            report["skipped"].append(issue_id)
    # Inserts the new ones (source "swebench_lite", verbatim text); for existing ones only the
    # hidden gold patch is attached, their text is never touched. A no-op when nothing changes.
    store_instances(db, [instances[i] for i in report["inserted"] + report["gold_attached"]])
    return report


def counts_per_source(db) -> dict[str, int]:
    return dict(db.query(Issue.source, func.count(Issue.id)).group_by(Issue.source).all())


def main(argv: list[str] | None = None, *, engine=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    args = parser.parse_args(argv)

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    engine = engine or build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        report = seed(db, candidates)
        db.commit()
        sources = counts_per_source(db)

    print(
        f"Stage 1 candidates: {len(candidates)} | inserted {len(report['inserted'])} | "
        f"already present {len(report['skipped']) + len(report['gold_attached'])} "
        f"(gold patch attached to {len(report['gold_attached'])})"
    )
    for issue_id in report["inserted"]:
        print(f"  inserted       {issue_id}")
    for issue_id in report["gold_attached"]:
        print(f"  gold attached  {issue_id}")
    print("Issues per source: " + ", ".join(f"{s}={n}" for s, n in sorted(sources.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
