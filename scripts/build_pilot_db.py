"""Build the shipped pilot database and its exports from a database that holds the pilot run (offline).

Copies one experiment (default: the ICSE pilot, bc6f1372) out of a source database into a new
database: the experiment, its runs, the issue variants they ran on and their issues, unchanged.
The other bundled SWE-bench Lite issues are then imported from data/swebench_lite_issues.json, the
metrics are computed again from the runs, and the experiment is exported (CSV, JSON, Markdown).
Nothing else from the source database is copied. No API call is made.

Outputs:
- data/pilot/stabilityeval_pilot.db  (a new database starts as a copy of it, see data/database.py)
- data/pilot/exports/                (runs.csv, metrics.csv, experiment_results.json,
                                      experiment_report.md)

Usage:
    python scripts/build_pilot_db.py --source stabilityeval.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from stability_eval.data.database import build_engine, create_all  # noqa: E402
from stability_eval.data.loaders.swebench import import_bundle  # noqa: E402
from stability_eval.data.models import Experiment  # noqa: E402
from stability_eval.export import CSVExporter, JSONExporter, ReportGenerator  # noqa: E402
from stability_eval.metrics.engine import MetricsEngine  # noqa: E402

PILOT_EXPERIMENT_ID = "bc6f1372-2088-45dd-907c-d741c0545d27"
OUTPUT_DB = PROJECT_ROOT / "data" / "pilot" / "stabilityeval_pilot.db"
OUTPUT_EXPORTS = PROJECT_ROOT / "data" / "pilot" / "exports"

# (table, rows of the experiment to copy), in foreign-key order.
_SELECTIONS = [
    ("issues", "id IN (SELECT ti.issue_id FROM src.transformed_issues ti "
               "JOIN src.runs r ON r.transformed_issue_id = ti.id WHERE r.experiment_id = :eid)"),
    ("transformed_issues", "id IN (SELECT transformed_issue_id FROM src.runs "
                           "WHERE experiment_id = :eid)"),
    ("experiments", "id = :eid"),
    ("runs", "experiment_id = :eid"),
]


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def copy_experiment(source: Path, target: Path, experiment_id: str) -> dict[str, int]:
    """Copy the experiment's rows from ``source`` into the (schema-only) ``target``."""
    conn = sqlite3.connect(target)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        counts = {}
        for table, where in _SELECTIONS:
            target_columns = set(_columns(conn, "main", table))
            columns = [c for c in _columns(conn, "src", table) if c in target_columns]
            names = ", ".join(columns)
            cursor = conn.execute(
                f"INSERT INTO main.{table} ({names}) SELECT {names} FROM src.{table} WHERE {where}",
                {"eid": experiment_id},
            )
            counts[table] = cursor.rowcount
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    if not counts["experiments"]:
        raise SystemExit(f"Experiment {experiment_id} is not in {source}.")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, required=True, help="database holding the pilot")
    parser.add_argument("--experiment-id", default=PILOT_EXPERIMENT_ID)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        # Read the source through a consistent snapshot (it may be in WAL mode and in use).
        snapshot = Path(tmp) / "source.db"
        src = sqlite3.connect(f"file:{args.source.resolve().as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(snapshot)
        src.backup(dst)
        dst.close()
        src.close()

        work = Path(tmp) / "pilot.db"
        engine = build_engine(f"sqlite:///{work.as_posix()}")
        create_all(engine)
        engine.dispose()
        counts = copy_experiment(snapshot, work, args.experiment_id)

        engine = build_engine(f"sqlite:///{work.as_posix()}")
        with sessionmaker(bind=engine)() as db:
            summary = import_bundle(db)
            MetricsEngine().compute(args.experiment_id, db)
            db.commit()
            experiment = db.get(Experiment, args.experiment_id)
            if OUTPUT_EXPORTS.exists():
                shutil.rmtree(OUTPUT_EXPORTS)
            exported = CSVExporter().export(experiment, OUTPUT_EXPORTS, db)
            exported.append(JSONExporter().export(experiment, OUTPUT_EXPORTS, db))
            exported.append(ReportGenerator().export(experiment, OUTPUT_EXPORTS, db))
        engine.dispose()

        # One compact file in rollback-journal mode (no -wal/-shm companions to ship).
        OUTPUT_DB.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_DB.unlink(missing_ok=True)
        conn = sqlite3.connect(work)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM INTO ?", (str(OUTPUT_DB),))
        conn.close()

    print(f"Copied from {args.source}: " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    print(f"Bundled issues: {summary.inserted} inserted, {summary.updated} already present")
    print(f"Wrote {OUTPUT_DB.relative_to(PROJECT_ROOT)} ({OUTPUT_DB.stat().st_size:,} bytes)")
    for path in exported:
        print(f"Wrote {Path(path).relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
