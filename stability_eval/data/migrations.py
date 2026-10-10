"""Additive upgrades for databases created by earlier versions (no Alembic: small, additive changes).

``upgrade(engine)`` runs from ``create_all`` and is idempotent: each step checks the live schema,
so a database that is already current is left alone.

Variant provenance (SPEC section 11.6) adds four columns to ``transformed_issues``. When they are
added, existing rows are backfilled:

- ``generator``: "original" for original texts, "placeholder" for offline placeholders, "unknown"
  for every other variant (nothing recorded which model or algorithm produced it);
- ``transform_version``: from the stored params when recorded there, else NULL;
- ``generation_mode``: "unknown" (not recorded);
- ``noop``: whether the text equals the original after whitespace normalization.

Placeholder variants are invalidated on this upgrade: their cache key is removed, so no lookup can
ever return them again. (Rows stored before provenance existed were keyed without a generator, so
no current cache key matches them either; they stay in the database for the runs that used them.)

``exclusion_reason`` (why a variant is left out of the metrics) is added next; excluded rows get the
reason from their quality-warning note, or the no-op note.

``transformed_issues.generation_cost_usd`` (the API cost of generating a variant) is added as NULL
for existing rows: their cost was never recorded.

``runs.control_repeat`` (a re-run of the original measuring run-to-run noise, SPEC section 13) is
added with default 0: no run stored before it existed was a control run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_PROVENANCE_COLUMNS = {
    "generator": "VARCHAR",
    "transform_version": "VARCHAR",
    "generation_mode": "VARCHAR",
    "noop": "BOOLEAN NOT NULL DEFAULT 0",
}
# Mirrors stability_eval.transformations.base (kept literal: the data layer does not import the
# transformation engine).
_ORIGINAL, _PLACEHOLDER, _UNKNOWN = "original", "placeholder", "unknown"


def upgrade(engine: Engine) -> list[str]:
    """Bring an existing database up to the current schema. Returns the steps taken."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "transformed_issues" not in tables:
        return []
    present = {column["name"] for column in inspector.get_columns("transformed_issues")}
    steps: list[str] = []

    missing = [name for name in _PROVENANCE_COLUMNS if name not in present]
    if missing:
        _add_columns(engine, {name: _PROVENANCE_COLUMNS[name] for name in missing})
        steps.append(f"added transformed_issues columns: {', '.join(missing)}")
        with Session(engine) as db:
            steps += _backfill_provenance(db)
            db.commit()

    if "exclusion_reason" not in present:
        _add_columns(engine, {"exclusion_reason": "TEXT"})
        steps.append("added transformed_issues column: exclusion_reason")
        with Session(engine) as db:
            steps += _backfill_exclusion_reason(db)
            db.commit()

    if "generation_cost_usd" not in present:
        _add_columns(engine, {"generation_cost_usd": "FLOAT"})
        steps.append(
            "added transformed_issues column: generation_cost_usd (NULL: not recorded before)"
        )

    if "runs" in tables and "control_repeat" not in {
        column["name"] for column in inspector.get_columns("runs")
    }:
        _add_columns(engine, {"control_repeat": "BOOLEAN NOT NULL DEFAULT 0"}, table="runs")
        steps.append("added runs column: control_repeat (0 for every existing run)")

    for step in steps:
        log.info("Database upgrade: %s", step)
    return steps


def _add_columns(engine: Engine, columns: dict[str, str], table: str = "transformed_issues") -> None:
    with engine.begin() as conn:
        for name, ddl in columns.items():
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


# Mirrors stability_eval.transformations.cache.NOOP_REASON.
_NOOP_REASON = "no-op: identical to the original after whitespace normalization"
_QUALITY_MARKER = "QUALITY WARNING:"


def _backfill_exclusion_reason(db: Session) -> list[str]:
    """The reason of every variant excluded so far: its quality-warning note, or the no-op note."""
    rows = db.execute(text(
        "SELECT id, transformation_notes, quality_warning, noop FROM transformed_issues "
        "WHERE is_original = 0 AND (quality_warning = 1 OR noop = 1)"
    )).all()
    for row_id, notes, quality_warning, noop in rows:
        if quality_warning:
            notes = notes or ""
            start = notes.find(_QUALITY_MARKER)
            reason = (
                notes[start + len(_QUALITY_MARKER):].strip().rstrip("]").strip()
                if start >= 0 else "quality warning (identifier retention failed)"
            )
        else:
            reason = _NOOP_REASON
        db.execute(
            text("UPDATE transformed_issues SET exclusion_reason = :reason WHERE id = :id"),
            {"reason": reason, "id": row_id},
        )
    return [f"backfilled exclusion_reason of {len(rows)} excluded variant row(s)"]


def _backfill_provenance(db: Session) -> list[str]:
    rows = db.execute(text(
        "SELECT t.id, t.transformation_params, t.transformed_text, t.is_original, i.issue_text "
        "FROM transformed_issues t JOIN issues i ON i.id = t.issue_id"
    )).all()
    note = f"invalidated by the provenance upgrade at {datetime.now(timezone.utc).isoformat()}"
    counts = {"original": 0, "placeholder": 0, "unknown": 0, "noop": 0}
    for row_id, params_json, transformed_text, is_original, issue_text in rows:
        params = _load(params_json)
        if is_original:
            generator, version, mode = _ORIGINAL, None, None
        elif params.get("offline_placeholder") or params.get("generator") == _PLACEHOLDER:
            generator, version, mode = _PLACEHOLDER, params.get("transform_version"), _UNKNOWN
            params.pop("_cache_key", None)
            params["invalidated"] = note
            params_json = json.dumps(params)
        else:
            generator, version, mode = _UNKNOWN, params.get("transform_version"), _UNKNOWN
        noop = not is_original and _normalized(transformed_text) == _normalized(issue_text)
        counts[generator] += 1
        counts["noop"] += int(noop)
        db.execute(
            text(
                "UPDATE transformed_issues SET generator = :generator, "
                "transform_version = :version, generation_mode = :mode, noop = :noop, "
                "transformation_params = :params WHERE id = :id"
            ),
            {"generator": generator, "version": version, "mode": mode, "noop": noop,
             "params": params_json, "id": row_id},
        )
    return [
        f"backfilled provenance of {len(rows)} variant row(s): {counts['original']} original, "
        f"{counts['placeholder']} placeholder (invalidated), {counts['unknown']} unknown "
        f"generator; {counts['noop']} no-op"
    ]


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _load(params_json: str | None) -> dict:
    try:
        value = json.loads(params_json) if params_json else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
