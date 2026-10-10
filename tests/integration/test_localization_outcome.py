"""Localization-success outcome end to end: metrics engine, dashboard and exports must agree.

One experiment covers every case:

  issue org__proj-1 (gold patch modifies pkg/core.py)
    original      success, modifies core.py + util.py -> success (match; extra file is fine)
    paraphrase    success, modifies other.py           -> FAILURE although status is "success"
    verbosity     no_patch                             -> failure
    reordering    timeout                              -> excluded (did not complete normally)
    typo          success, but variant quality_warning -> excluded (quality)
  issue org__proj-2 (gold patch modifies core.py + api.py)
    original      success, modifies core.py + api.py   -> success
    paraphrase    success, modifies core.py only       -> failure (partial localization)

The "paraphrase" run of org__proj-1 is the trap: by run.status it is consistent with the original,
by outcome it is not. Every view must say "not consistent".
"""
from __future__ import annotations

import csv
import io
import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.dashboard import _db as dashboard_db
from stability_eval.dashboard._results import (
    attach_outcomes,
    rq1_overview,
    rq1_table_rows,
    runs_csv_bytes,
    variant_consistency,
)
from stability_eval.dashboard._statistics import paired_transformation_tests
from stability_eval.data.loaders.swebench import SWEBenchInstance, store_instances
from stability_eval.data.models import Base, Experiment, Metric, Run, TransformedIssue
from stability_eval.export.csv_exporter import CSVExporter
from stability_eval.export.json_exporter import JSONExporter
from stability_eval.export.report_generator import ReportGenerator
from stability_eval.metrics.engine import MetricsEngine

AGENT = "llm_baseline"


def diff(*paths: str) -> str:
    return "\n".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new" for p in paths)


CELLS = [
    # issue, variant, status, patch, quality_warning
    ("org__proj-1", "original", "success", diff("pkg/core.py", "pkg/util.py"), False),
    ("org__proj-1", "paraphrase", "success", diff("pkg/other.py"), False),
    ("org__proj-1", "verbosity_reduction", "no_patch", None, False),
    ("org__proj-1", "reordering", "timeout", None, False),
    ("org__proj-1", "typo_injection", "success", diff("pkg/core.py"), True),
    ("org__proj-2", "original", "success", diff("pkg/core.py", "pkg/api.py"), False),
    ("org__proj-2", "paraphrase", "success", diff("pkg/core.py"), False),
]
EXPECTED_OUTCOME = {
    ("org__proj-1", "original"): "success",
    ("org__proj-1", "paraphrase"): "failure",
    ("org__proj-1", "verbosity_reduction"): "failure",
    ("org__proj-1", "reordering"): "excluded",
    ("org__proj-1", "typo_injection"): "excluded",
    ("org__proj-2", "original"): "success",
    ("org__proj-2", "paraphrase"): "failure",
}


@pytest.fixture()
def scored(tmp_path, monkeypatch):
    """The experiment above, scored by the MetricsEngine. Yields (Session, experiment_id)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'outcome.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(dashboard_db, "_session", lambda: Session())

    with Session() as db:
        issues = store_instances(db, [
            SWEBenchInstance("org__proj-1", "org/proj", "issue one", gold_patch=diff("pkg/core.py")),
            SWEBenchInstance("org__proj-2", "org/proj", "issue two",
                             gold_patch=diff("pkg/core.py", "pkg/api.py")),
        ])
        experiment = Experiment(name="outcome", config=json.dumps({"agents": []}), status="completed")
        db.add(experiment)
        db.flush()
        for issue_id, variant, status, patch, quality_warning in CELLS:
            ti = TransformedIssue(
                issue_id=issues[issue_id].id, transformation_name=variant,
                transformed_text=f"{issue_id} {variant}", is_original=variant == "original",
                quality_warning=quality_warning,
            )
            db.add(ti)
            db.flush()
            db.add(Run(experiment_id=experiment.id, transformed_issue_id=ti.id, agent_name=AGENT,
                       execution_mode="real", status=status, patch=patch))
        db.flush()
        MetricsEngine().compute(experiment.id, db)
        db.commit()
        experiment_id = experiment.id
    yield Session, experiment_id
    engine.dispose()


def metric(db, experiment_id, name, scope_key=None):
    query = db.query(Metric).filter_by(experiment_id=experiment_id, metric_name=name)
    if scope_key is not None:
        query = query.filter_by(scope_key=scope_key)
    rows = query.all()
    return {m.scope_key: m.metric_value for m in rows} if scope_key is None else rows[0].metric_value


def run_ids(db, experiment_id) -> dict[tuple[str, str], str]:
    rows = (
        db.query(Run, TransformedIssue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .filter(Run.experiment_id == experiment_id)
        .all()
    )
    # transformed_text is "<issue id> <variant>" in this fixture
    return {(ti.transformed_text.split(" ")[0], ti.transformation_name): run.id for run, ti in rows}


# ---------------------------------------------------------------------------
# Metrics engine
# ---------------------------------------------------------------------------


def test_engine_scores_localization_success(scored):
    Session, experiment_id = scored
    with Session() as db:
        sc = metric(db, experiment_id, "success_consistency")
        ts = metric(db, experiment_id, "transformation_sensitivity")
        assert sc == {f"{AGENT}|org__proj-1": 0.0, f"{AGENT}|org__proj-2": 0.0}
        assert ts == {f"{AGENT}|paraphrase": 1.0, f"{AGENT}|verbosity_reduction": 1.0}

        ids = run_ids(db, experiment_id)
        outcome = metric(db, experiment_id, "outcome")
        for cell, expected in EXPECTED_OUTCOME.items():
            if expected == "excluded":
                assert ids[cell] not in outcome, cell
            else:
                assert outcome[ids[cell]] == (1.0 if expected == "success" else 0.0), cell

        match = metric(db, experiment_id, "localization_match")
        jaccard = metric(db, experiment_id, "file_overlap_jaccard")
        assert match[ids[("org__proj-1", "original")]] == 1.0
        assert jaccard[ids[("org__proj-1", "original")]] == 0.5  # core+util vs core
        assert match[ids[("org__proj-1", "paraphrase")]] == 0.0
        assert jaccard[ids[("org__proj-1", "paraphrase")]] == 0.0
        assert match[ids[("org__proj-2", "paraphrase")]] == 0.0  # partial: api.py missing
        assert jaccard[ids[("org__proj-2", "paraphrase")]] == 0.5

        files = json.loads(
            db.query(Metric).filter_by(metric_name="localization_match",
                                       scope_key=ids[("org__proj-2", "paraphrase")]).one()
            .metric_metadata
        )
        assert files == {"files_in_patch": ["pkg/core.py"],
                         "files_in_gold": ["pkg/core.py", "pkg/api.py"]}


def test_exclusions_are_counted_per_reason_and_per_transformation(scored):
    Session, experiment_id = scored
    with Session() as db:
        assert metric(db, experiment_id, "excluded_runs_status", experiment_id) == 1.0
        assert metric(db, experiment_id, "excluded_runs_quality_warning", experiment_id) == 1.0
        assert metric(db, experiment_id, "excluded_quality_warning") == {
            f"{AGENT}|paraphrase": 0.0,
            f"{AGENT}|reordering": 0.0,
            f"{AGENT}|typo_injection": 1.0,
            f"{AGENT}|verbosity_reduction": 0.0,
        }


def test_excluded_runs_are_listed_in_a_logged_warning(scored, caplog):
    Session, experiment_id = scored
    caplog.set_level(logging.WARNING, logger="stability_eval.metrics.engine")
    with Session() as db:  # score again with log capture on (rows are not committed)
        ids = run_ids(db, experiment_id)
        MetricsEngine().compute(experiment_id, db)
    text = caplog.text
    assert "did not complete normally" in text and ids[("org__proj-1", "reordering")] in text
    assert "[timeout]" in text
    assert "quality-warning variants" in text and ids[("org__proj-1", "typo_injection")] in text


# ---------------------------------------------------------------------------
# Dashboard: same outcome as the metrics, never run.status
# ---------------------------------------------------------------------------


def dashboard_frames(experiment_id):
    runs_df = dashboard_db.load_runs_df(experiment_id)
    metrics_df = dashboard_db.load_metrics_df(experiment_id)
    return attach_outcomes(runs_df, metrics_df), metrics_df


def test_dashboard_outcomes_equal_the_engine_outcomes(scored):
    Session, experiment_id = scored
    runs_df, _ = dashboard_frames(experiment_id)
    shown = {
        (row.issue_id, row.transformation_name): row.outcome for row in runs_df.itertuples()
    }
    assert shown == EXPECTED_OUTCOME
    trap = runs_df[(runs_df.issue_id == "org__proj-1") & (runs_df.transformation_name == "paraphrase")]
    assert trap.status.iloc[0] == "success" and trap.outcome.iloc[0] == "failure"


def test_dashboard_consistency_is_exactly_the_success_consistency_metric(scored):
    Session, experiment_id = scored
    runs_df, metrics_df = dashboard_frames(experiment_id)
    for issue_id in ("org__proj-1", "org__proj-2"):
        consistent, scored_variants = variant_consistency(runs_df, issue_id)
        sc = metrics_df[(metrics_df.metric_name == "success_consistency")
                        & (metrics_df.scope_key == f"{AGENT}|{issue_id}")].metric_value.iloc[0]
        assert consistent / scored_variants == pytest.approx(sc)


def test_rq1_overview_sums_the_per_issue_consistency(scored):
    Session, experiment_id = scored
    runs_df, _ = dashboard_frames(experiment_id)
    text = rq1_overview(runs_df, ["org__proj-1", "org__proj-2"])
    # both originals succeed; 3 scored variants (2 + 1, the excluded ones left out), none kept it
    assert text == (
        "Originals localized: **2 of 2**. "
        "Variants that kept the original's outcome: **0 of 3** scored variants."
    )


def test_rq1_table_colours_follow_the_outcome(scored):
    Session, experiment_id = scored
    runs_df, _ = dashboard_frames(experiment_id)
    rows = {row["Transformation"]: row for row in rq1_table_rows(runs_df, "org__proj-1")}
    assert rows["Paraphrase"][""] == "🔴"  # status "success" like the original, outcome differs
    assert rows["Paraphrase"]["Consistent with Original?"] == "No"
    assert rows["Paraphrase"]["Outcome"] == "Failure"
    assert rows["Verbosity Reduction"][""] == "🔴"
    assert rows["Reordering"][""] == "⚪" and rows["Reordering"]["Outcome"] == "Excluded (timeout)"
    assert rows["Typo / Noise Injection"]["Consistent with Original?"] == "Excluded"


def test_statistical_tests_use_the_outcome(scored):
    Session, experiment_id = scored
    runs_df, _ = dashboard_frames(experiment_id)
    tests, _ = paired_transformation_tests(runs_df.to_dict(orient="records"))
    by_name = {t["transformation"]: t for t in tests}
    assert by_name["paraphrase"]["n_pairs"] == 2
    assert by_name["paraphrase"]["regressions"] == 2  # by status there would be 0
    assert "reordering" not in by_name and "typo_injection" not in by_name  # excluded only


def test_dashboard_runs_export_carries_the_same_outcome(scored):
    Session, experiment_id = scored
    runs_df, _ = dashboard_frames(experiment_id)
    exported = list(csv.DictReader(io.StringIO(runs_csv_bytes(runs_df).decode())))
    assert {(r["issue_id"], r["transformation_name"]): r["outcome"] for r in exported} == (
        EXPECTED_OUTCOME
    )


# ---------------------------------------------------------------------------
# CLI exports
# ---------------------------------------------------------------------------


def test_cli_exports_carry_the_outcome_and_the_exclusion_counts(scored, tmp_path):
    Session, experiment_id = scored
    with Session() as db:
        experiment = db.get(Experiment, experiment_id)
        runs_csv, metrics_csv = CSVExporter().export(experiment, tmp_path / "csv", db)
        json_path = JSONExporter().export(experiment, tmp_path / "json", db)
        report = ReportGenerator().export(experiment, tmp_path / "md", db).read_text(encoding="utf-8")

    with open(runs_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {(r["issue_id"], r["transformation_name"]): r["outcome"] for r in rows} == EXPECTED_OUTCOME

    with open(metrics_csv, newline="", encoding="utf-8") as fh:
        names = {r["metric_name"] for r in csv.DictReader(fh)}
    assert {"excluded_runs_status", "excluded_runs_quality_warning",
            "excluded_quality_warning"} <= names

    exported = json.loads(json_path.read_text(encoding="utf-8"))
    no_transformation = {
        "paraphrase": 0, "reordering": 0, "typo_injection": 0, "verbosity_reduction": 0,
    }
    assert exported["exclusions"] == {
        "status": 1,
        "quality_warning": 1,
        "quality_warning_by_transformation": {**no_transformation, "typo_injection": 1},
        "noop": 0,
        "noop_by_transformation": no_transformation,
    }
    assert {(r["issue_id"], r["transformation_name"]): r["outcome"]
            for r in exported["runs"]} == EXPECTED_OUTCOME

    assert "| Status | Outcome | File overlap (Jaccard) |" in report
    assert "did not complete normally** (timeout, cost cap, error): 1" in report
    assert "quality-warning variants** (identifier retention failed after retries): 1" in report
    assert "  - typo_injection: 1" in report
    assert "no-op variants** (identical to the original after whitespace normalization): 0" in (
        report
    )
    assert "| org__proj-1 | paraphrase | llm_baseline | success | failure | 0.000 |" in report
    assert "| org__proj-1 | original | llm_baseline | success | success | 0.500 |" in report
    assert "| org__proj-1 | reordering | llm_baseline | timeout | excluded | N/A |" in report


EXPECTED_JACCARD = {
    ("org__proj-1", "original"): 0.5,  # core+util vs core
    ("org__proj-1", "paraphrase"): 0.0,
    ("org__proj-1", "verbosity_reduction"): 0.0,  # no_patch: no files
    ("org__proj-2", "original"): 1.0,
    ("org__proj-2", "paraphrase"): 0.5,
}


def _jaccard(value) -> float | None:
    return None if value in ("", None) else float(value)


def test_every_export_puts_file_overlap_jaccard_next_to_the_outcome(scored, tmp_path):
    Session, experiment_id = scored
    with Session() as db:
        experiment = db.get(Experiment, experiment_id)
        runs_csv, _ = CSVExporter().export(experiment, tmp_path / "csv", db)
        json_path = JSONExporter().export(experiment, tmp_path / "json", db)
    runs_df, _ = dashboard_frames(experiment_id)
    dashboard_csv = runs_csv_bytes(runs_df).decode()

    with open(runs_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    for header in (reader.fieldnames, next(csv.reader(io.StringIO(dashboard_csv)))):
        assert header[header.index("outcome") + 1] == "file_overlap_jaccard"

    exported_json = json.loads(json_path.read_text(encoding="utf-8"))["runs"]
    dashboard_rows = list(csv.DictReader(io.StringIO(dashboard_csv)))
    for source in (rows, exported_json, dashboard_rows):
        values = {
            (r["issue_id"], r["transformation_name"]): _jaccard(r["file_overlap_jaccard"])
            for r in source
        }
        # Runs without an outcome (excluded) carry no overlap either.
        assert values == {
            cell: EXPECTED_JACCARD.get(cell) for cell in EXPECTED_OUTCOME
        }
