"""Insert the ICSE pilot issues into the issues table, verbatim from SWE-bench Lite, offline.

Reads the issue ids from scripts/output/pilot_issue_ids.json, and each issue's repository,
verbatim problem statement, base commit and gold patch from the bundled dataset file
data/swebench_lite_issues.json (princeton-nlp/SWE-bench_Lite, split test): no network. The gold
patch is stored as hidden metadata only and never reaches an agent (see
stableagent/data/loaders/swebench.py).

New issues get source "swebench_lite_pilot". An issue already in the database (e.g. from the
pre-screen) keeps its row and its text, which must be the dataset's verbatim text (a mismatch
stops the script before anything is written); it is relabelled as a pilot issue and gains a
missing gold patch. Idempotent: a second run changes nothing. Prints what happened and the issue
counts per source.

Usage:
    python scripts/seed_pilot_issues.py
    python scripts/seed_pilot_issues.py --ids path/to/pilot_issue_ids.json
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

from stableagent.data.database import build_engine, create_all  # noqa: E402
from stableagent.data.loaders.swebench import (  # noqa: E402
    gold_patch_of,
    load_bundle,
    store_instances,
)
from stableagent.data.models import PILOT_SOURCE, Issue  # noqa: E402

PILOT_IDS = PROJECT_ROOT / "scripts" / "output" / "pilot_issue_ids.json"


def seed(db, ids: list[str]) -> dict[str, list[str]]:
    """Insert missing pilot issues; returns ids per outcome.

    Outcomes: inserted, relabelled (an existing issue's source set to PILOT_SOURCE) and
    gold_attached; an existing issue can be both relabelled and gold_attached.
    """
    instances = {i.instance_id: i for i in load_bundle(ids)}
    existing = {
        issue.external_id: issue
        for issue in db.query(Issue).filter(Issue.external_id.in_(ids))
    }
    for issue_id, issue in existing.items():
        instance = instances[issue_id]
        if (issue.issue_text, issue.repo_name) != (instance.problem_statement, instance.repo):
            raise ValueError(
                f"{issue_id}: the database record is not the dataset's verbatim text; "
                "refusing to use or overwrite it"
            )
    report: dict[str, list[str]] = {"inserted": [], "relabelled": [], "gold_attached": []}
    for issue_id in ids:
        issue = existing.get(issue_id)
        if issue is None:
            report["inserted"].append(issue_id)
            continue
        if issue.source != PILOT_SOURCE:
            report["relabelled"].append(issue_id)
        if gold_patch_of(issue) is None:
            report["gold_attached"].append(issue_id)
    # Inserts the new ones (verbatim text, source PILOT_SOURCE) and attaches the hidden gold
    # patch to every one; existing texts are never touched. Write-free when nothing changes.
    store_instances(db, [instances[i] for i in ids], source=PILOT_SOURCE)
    for issue_id in report["relabelled"]:
        existing[issue_id].source = PILOT_SOURCE
    return report


def counts_per_source(db) -> dict[str, int]:
    return dict(db.query(Issue.source, func.count(Issue.id)).group_by(Issue.source).all())


def main(argv: list[str] | None = None, *, engine=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ids", type=Path, default=PILOT_IDS)
    args = parser.parse_args(argv)

    ids = json.loads(args.ids.read_text(encoding="utf-8"))
    engine = engine or build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        sources_before = {
            issue.external_id: issue.source
            for issue in db.query(Issue).filter(Issue.external_id.in_(ids))
        }
        report = seed(db, ids)
        db.commit()
        sources = counts_per_source(db)

    print(
        f"Pilot issues: {len(ids)} | inserted {len(report['inserted'])} | "
        f"already present {len(ids) - len(report['inserted'])} "
        f"(relabelled {len(report['relabelled'])}, "
        f"gold patch attached to {len(report['gold_attached'])})"
    )
    for issue_id in report["inserted"]:
        print(f"  inserted       {issue_id}")
    for issue_id in report["relabelled"]:
        print(f"  relabelled     {issue_id} (was {sources_before[issue_id]})")
    for issue_id in report["gold_attached"]:
        print(f"  gold attached  {issue_id}")
    print("Issues per source: " + ", ".join(f"{s}={n}" for s, n in sorted(sources.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
