"""Build the shipped pilot database and its exports from a database that holds the pilot runs (offline).

Copies the experiments (default: the two ICSE pilot experiments, bc6f1372 on Claude Sonnet 4.6 and
9d27f3ef on GPT-4o, which ran on the same variants) out of a source database into a new database:
each experiment, its runs, the issue variants they ran on and their issues, unchanged (a variant
shared by both is copied once). The other bundled SWE-bench Lite issues are then imported from
data/swebench_lite_issues.json, the metrics are computed again from the runs, and each experiment
is exported (CSV, JSON, Markdown) into a directory named after its model. Nothing else from the
source database is copied. No API call is made.

Outputs:
- data/pilot/stableagent_pilot.db  (a new database starts as a copy of it, see data/database.py)
- data/pilot/exports/<model>/        (runs.csv, metrics.csv, experiment_results.json,
                                      experiment_report.md), e.g. claude-sonnet-4-6/, gpt-4o/

Usage:
    python scripts/build_pilot_db.py --source stableagent.db
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from stableagent.config.experiment_schema import ExperimentConfig  # noqa: E402
from stableagent.data.database import build_engine, create_all  # noqa: E402
from stableagent.data.loaders.swebench import import_bundle  # noqa: E402
from stableagent.data.models import Experiment  # noqa: E402
from stableagent.export import CSVExporter, JSONExporter, ReportGenerator  # noqa: E402
from stableagent.metrics.engine import MetricsEngine  # noqa: E402

PILOT_EXPERIMENT_ID = "bc6f1372-2088-45dd-907c-d741c0545d27"  # claude-sonnet-4-6
MODEL2_EXPERIMENT_ID = "9d27f3ef-397a-41b7-b1b2-e09729288a40"  # gpt-4o, the pilot's variants
OUTPUT_DB = PROJECT_ROOT / "data" / "pilot" / "stableagent_pilot.db"
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
            # OR IGNORE: experiments that ran on the same variants share their issue rows.
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO main.{table} ({names}) "
                f"SELECT {names} FROM src.{table} WHERE {where}",
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


def export_dir(experiment: Experiment) -> Path:
    """data/pilot/exports/<model of its agent>/, e.g. claude-sonnet-4-6/ or gpt-4o/."""
    config = ExperimentConfig.model_validate_json(experiment.config)
    params = dict(config.agents[0].params) if len(config.agents) == 1 else {}
    model = params.get("model") or "claude-sonnet-4-6"
    return OUTPUT_EXPORTS / re.sub(r"[^A-Za-z0-9._-]", "_", model)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, required=True, help="database holding the pilot")
    parser.add_argument("--experiment-id", nargs="+", dest="experiment_ids",
                        default=[PILOT_EXPERIMENT_ID, MODEL2_EXPERIMENT_ID])
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
        counts: dict[str, int] = {}
        for experiment_id in args.experiment_ids:
            for table, n in copy_experiment(snapshot, work, experiment_id).items():
                counts[table] = counts.get(table, 0) + n

        engine = build_engine(f"sqlite:///{work.as_posix()}")
        exported = []
        with sessionmaker(bind=engine)() as db:
            summary = import_bundle(db)
            if OUTPUT_EXPORTS.exists():
                shutil.rmtree(OUTPUT_EXPORTS)
            for experiment_id in args.experiment_ids:
                MetricsEngine().compute(experiment_id, db)
                db.commit()
                experiment = db.get(Experiment, experiment_id)
                out = export_dir(experiment)
                exported += CSVExporter().export(experiment, out, db)
                exported.append(JSONExporter().export(experiment, out, db))
                exported.append(ReportGenerator().export(experiment, out, db))
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
