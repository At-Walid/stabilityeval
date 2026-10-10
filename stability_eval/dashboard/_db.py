"""Data-loading helpers for the dashboard pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from stability_eval.data.database import build_engine, create_all
from stability_eval.data.loaders.swebench import ImportSummary, import_bundle, load_bundle
from stability_eval.data.models import (
    CUSTOM_SOURCE, Experiment, Issue, Metric, Run, TransformedIssue,
)
from stability_eval.export._metric_rows import provenance

_TRANSFORM_LABELS = {
    "original": "Original",
    "paraphrase": "Paraphrase",
    "verbosity_reduction": "Verbosity Red.",
    "typo_injection": "Typo / Noise",
    "reordering": "Reordering",
    "paragraph_to_structured": "Para→Struct.",
    "neutralize_emotional": "Neutralize",
}


def _session():
    engine = build_engine()
    return sessionmaker(bind=engine)()


@st.cache_data(ttl=60)
def load_issues() -> pd.DataFrame:
    """The dataset issues for the SWE-bench picker; ad-hoc custom issues are never listed."""
    db = _session()
    try:
        rows = (
            db.query(Issue)
            .filter(Issue.source != CUSTOM_SOURCE)
            .order_by(Issue.external_id)
            .all()
        )
        return pd.DataFrame([{
            "id": i.id,
            "external_id": i.external_id,
            "repo_name": i.repo_name,
            "source": i.source,
            "issue_text": i.issue_text,
            "created_at": i.created_at,
        } for i in rows])
    finally:
        db.close()


@st.cache_data(show_spinner=False)
def bundled_issue_ids() -> frozenset[str]:
    """Ids of the SWE-bench Lite issues bundled in data/swebench_lite_issues.json (offline)."""
    return frozenset(instance.instance_id for instance in load_bundle())


def import_bundled_issues() -> ImportSummary:
    """Import the bundled SWE-bench Lite issues into the issues table: offline, idempotent.

    Issues already present keep their text and gain the hidden gold patch.
    """
    engine = build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        summary = import_bundle(db)
        db.commit()
    load_issues.clear()
    return summary


@st.cache_data(ttl=60)
def load_mean_real_run_cost() -> tuple[float | None, int]:
    """Mean cost of the past real runs that recorded one, and how many such runs there are."""
    db = _session()
    try:
        mean, count = (
            db.query(func.avg(Run.cost_usd), func.count(Run.id))
            .filter(Run.execution_mode == "real", Run.cost_usd > 0)
            .one()
        )
        return (float(mean) if mean is not None else None), int(count)
    finally:
        db.close()


@st.cache_data(ttl=60)
def load_experiments() -> pd.DataFrame:
    db = _session()
    try:
        rows = db.query(Experiment).all()
        return pd.DataFrame([{
            "id": e.id,
            "name": e.name,
            "status": e.status,
            "created_at": e.created_at[:10] if e.created_at else "",
            "total_cost_usd": e.total_cost_usd,
            "description": e.description,
            "config": e.config,
        } for e in rows])
    finally:
        db.close()


@st.cache_data(ttl=60)
def load_runs_df(experiment_id: str) -> pd.DataFrame:
    db = _session()
    try:
        rows = (
            db.query(Run, TransformedIssue, Issue)
            .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
            .join(Issue, TransformedIssue.issue_id == Issue.id)
            .filter(Run.experiment_id == experiment_id)
            .all()
        )
        return pd.DataFrame([{
            "run_id": run.id,
            "run_index": run.run_index,
            "control_repeat": bool(run.control_repeat),
            "agent_name": run.agent_name,
            "agent_version": run.agent_version,
            "execution_mode": run.execution_mode,
            "issue_id": issue.external_id,
            "repo_name": issue.repo_name,
            "issue_text": issue.issue_text,
            "transformation_name": ti.transformation_name,
            "transform_label": _TRANSFORM_LABELS.get(ti.transformation_name, ti.transformation_name),
            "is_original": ti.is_original,
            "transformed_text": ti.transformed_text,
            "transformation_notes": ti.transformation_notes or "",
            "quality_warning": bool(ti.quality_warning),
            **provenance(ti),
            "status": run.status,
            "cost_usd": run.cost_usd or 0.0,
            "runtime_seconds": run.runtime_seconds or 0.0,
            "token_input": run.token_input or 0,
            "token_output": run.token_output or 0,
            "patch": run.patch,
            "explanation": run.explanation or "",
            "raw_logs": run.raw_logs or "",
            "metadata": run.metadata_ or "",
            "error_message": run.error_message or "",
            "created_at": run.created_at,
            "completed_at": run.completed_at,
        } for run, ti, issue in rows])
    finally:
        db.close()


_METRICS_COLUMNS = ["metric_name", "scope", "scope_key", "metric_value", "metric_metadata"]


@st.cache_data(ttl=60)
def load_metrics_df(experiment_id: str) -> pd.DataFrame:
    db = _session()
    try:
        rows = db.query(Metric).filter_by(experiment_id=experiment_id).all()
        # Always pass `columns=` so an experiment with zero computed metrics still
        # returns a DataFrame with the expected schema (pd.DataFrame([]) would
        # otherwise have no columns at all, breaking any metrics_df["metric_name"]
        # lookup downstream).
        return pd.DataFrame([{
            "metric_name": m.metric_name,
            "scope": m.scope,
            "scope_key": m.scope_key,
            "metric_value": m.metric_value,
            "metric_metadata": m.metric_metadata,  # JSON text: CIs, per-issue values, ...
        } for m in rows], columns=_METRICS_COLUMNS)
    finally:
        db.close()


@st.cache_data(ttl=60)
def load_experiment(experiment_id: str) -> dict | None:
    """Return one experiment's own DB record (name, status, config snapshot, ...).

    Used to derive which agent/model an experiment actually ran with from the
    persisted config, rather than from the current live UI selection — so
    Past Experiments shows the correct agent/model regardless of what's
    currently selected in Section B.
    """
    db = _session()
    try:
        exp = db.query(Experiment).filter_by(id=experiment_id).first()
        if exp is None:
            return None
        return {
            "id": exp.id,
            "name": exp.name,
            "status": exp.status,
            "config": exp.config,
            "created_at": exp.created_at,
        }
    finally:
        db.close()


# ── Demo issues (the ones the committed MockReplay fixtures cover) ─────────────

# Loaded verbatim from the bundled dataset file, never from hand-written texts.
DEMO_ISSUE_IDS = (
    "astropy__astropy-6938",
    "django__django-11099",
    "django__django-12125",
    "matplotlib__matplotlib-23299",
    "sympy__sympy-20590",
)


def insert_demo_issues() -> ImportSummary:
    """Insert the demo issues, verbatim with their hidden gold patches, from the bundle."""
    engine = build_engine()
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        summary = import_bundle(db, instance_ids=DEMO_ISSUE_IDS)
        db.commit()
    load_issues.clear()
    return summary
