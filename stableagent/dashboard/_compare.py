"""Past Experiments: compare models on the same issues (the paper's RQ2 figure and table).

The figure and the table are the ones ``scripts/analyze_patch_similarity.py`` writes
(stableagent/export/figures.py, export/comparison_table.py), from the per-agent comparison of
the metrics code (metrics/comparison.py): the dashboard computes nothing itself.
"""
from __future__ import annotations

import json

import pandas as pd

from stableagent.config.pricing import display_name


def experiment_option_label(row: dict) -> str:
    """"icse_pilot_model2 · GPT-4o · 2026-10-12 · 1a2b3c4d" for the experiment picker."""
    model = experiment_model(row.get("config"))
    parts = [row["name"]] + ([display_name(model)] if model else []) + [
        row.get("created_at") or "", row["id"][:8],
    ]
    return " · ".join(part for part in parts if part)


def experiment_model(config: str | None) -> str | None:
    """The model of the experiment's first agent, if its config names one."""
    try:
        agents = json.loads(config or "{}").get("agents") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    return ((agents[0].get("params") or {}).get("model")) if agents else None


def default_comparison(experiments: pd.DataFrame) -> list[str]:
    """The most recent completed experiment that reused another one's variants
    (``reuse_variants_from``), with that experiment first; [] when there is none."""
    if experiments.empty:
        return []
    ids = set(experiments["id"])
    # Newest first (rows come oldest first; dates may tie, so the stable sort keeps them newest)
    newest_first = experiments.iloc[::-1].sort_values("created_at", ascending=False, kind="stable")
    for _, row in newest_first.iterrows():
        if row["status"] != "completed":
            continue
        try:
            reference = json.loads(row["config"] or "{}").get("reuse_variants_from")
        except (json.JSONDecodeError, AttributeError):
            continue
        if reference in ids:
            return [reference, row["id"]]
    return []
