"""Shared results rendering for StabilityEval and Past Experiments.

Both pages load (runs_df, metrics_df) for an experiment and call render_results().
Keeping this in one place means single-issue and multi-issue display logic — RQ1/RQ2
tables, Transformed Issues, Issue Detail, Export — can't drift between "just ran" and
"reloaded from Past Experiments" (see SPEC section 16).
"""
from __future__ import annotations

import csv
import io
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stability_eval.dashboard._db import load_experiment
from stability_eval.dashboard._similarity import (
    CONTROL_LABEL,
    default_index,
    diff_legend_html,
    patch_lines,
    side_by_side_html,
    similarity_dot_plot,
    similarity_rows,
    similarity_table,
)
from stability_eval.dashboard._statistics import paired_transformation_tests
from stability_eval.export._metric_rows import PROVENANCE_FIELDS
from stability_eval.metrics.outcome import (
    EXCLUDED,
    displayed_outcome,
    exclusion_counts,
    recorded_outcomes,
    recorded_run_values,
)
from stability_eval.transformations.base import PLACEHOLDER

_TLABELS = {
    "original":               "Original",
    "paraphrase":             "Paraphrase",
    "verbosity_reduction":    "Verbosity Reduction",
    "typo_injection":         "Typo / Noise Injection",
    "reordering":             "Reordering",
    "paragraph_to_structured": "Para → Structured",
    "neutralize_emotional":   "Neutralize Emotional",
}


def _score_color(v: float) -> str:
    return "green" if v >= 0.7 else "orange" if v >= 0.4 else "red"


def _interp(v: float) -> str:
    if v >= 0.5:
        return "Most disruptive"
    if v >= 0.15:
        return "Moderate"
    if v > 0.0:
        return "Minor"
    return "Minimal"


def _agent_display_name(raw_name: str) -> str:
    return "MockReplay" if "mock" in (raw_name or "").lower() else "LLM Baseline"


def _results_header(exp_id: str, runs_df: pd.DataFrame, raw_agent_name: str) -> str:
    """Build "Results — <Agent> (<model>), N runs", read from the experiment's
    persisted config snapshot rather than the current UI selection — this is
    what makes Past Experiments show the agent/model an experiment actually
    ran with, not whatever happens to be selected in Section B right now.
    """
    n_runs = len(runs_df)
    agent_display = _agent_display_name(raw_agent_name)
    model: str | None = None

    exp_meta = load_experiment(exp_id)
    if exp_meta and exp_meta.get("config"):
        try:
            cfg = json.loads(exp_meta["config"])
            agents = cfg.get("agents") or []
            if agents:
                agent_display = _agent_display_name(agents[0].get("name", raw_agent_name))
                model = (agents[0].get("params") or {}).get("model")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass  # fall back to the raw Run.agent_name-derived display above

    if model:
        return f"Results — {agent_display} ({model}), {n_runs} runs"
    return f"Results — {agent_display}, {n_runs} runs"


# ── Outcomes ──────────────────────────────────────────────────────────────────
# Every outcome on this page (RQ1 table and colours, consistency counts, statistical tests,
# exports) comes from the MetricsEngine's recorded run outcome — never from run.status — so the
# GUI cannot disagree with metrics A/F/G (see stability_eval.metrics.outcome).

_RUNS_CSV_COLUMNS = [
    "run_id", "run_index", "control_repeat", "agent_name", "agent_version", "execution_mode",
    "issue_id", "repo_name", "is_original", "transformation_name",
    "issue_text", "transformed_text", "status", "outcome", "file_overlap_jaccard",
    "patch", "explanation",
    "raw_logs", "error_message", "cost_usd", "runtime_seconds",
    "token_input", "token_output", "created_at", "completed_at",
    "transformation_notes", "quality_warning", *PROVENANCE_FIELDS,
]


def _metric_tuples(metrics_df: pd.DataFrame) -> list[tuple]:
    if metrics_df.empty:
        return []
    return list(
        metrics_df[["scope", "scope_key", "metric_name", "metric_value"]].itertuples(
            index=False, name=None
        )
    )


def attach_outcomes(runs_df: pd.DataFrame, metrics_df: pd.DataFrame) -> pd.DataFrame:
    """runs_df plus "outcome" (success | failure | excluded, as the metrics engine scored it) and
    "file_overlap_jaccard" (None without an outcome or a gold patch)."""
    tuples = _metric_tuples(metrics_df)
    recorded = recorded_outcomes(tuples)
    jaccard = recorded_run_values(tuples, "file_overlap_jaccard")
    frame = runs_df.copy()
    frame["outcome"] = [
        displayed_outcome(run_id, status, recorded)
        for run_id, status in zip(frame["run_id"], frame["status"])
    ]
    frame["file_overlap_jaccard"] = [jaccard.get(run_id) for run_id in frame["run_id"]]
    return frame


def exclusion_reason(run: pd.Series) -> str:
    """Why a run has no outcome: its variant (no-op, quality warning) or its status."""
    if not run.get("is_original", False):
        if run.get("noop", False):
            return "no-op variant"
        if run.get("quality_warning", False):
            return "quality warning"
    return str(run["status"])


def provenance_text(run: pd.Series) -> str:
    """One line: what produced the variant, under which version, in which mode."""
    version = run.get("transform_version") or "n/a"
    mode = run.get("generation_mode") or "unknown"
    return (
        f"Generator: {run.get('generator') or 'unknown'} · transform_version {version} · "
        f"produced in {mode} mode"
    )


def variant_consistency(runs_df: pd.DataFrame, issue_id: str) -> tuple[int, int] | None:
    """(variants sharing the original's outcome, scored variants) for one issue.

    Their ratio is exactly the issue's Success Consistency (A). None when the original run has no
    outcome (excluded or missing): the engine computes no SC for that issue either.
    """
    issue_runs = runs_df[runs_df["issue_id"] == issue_id]
    original = issue_runs[issue_runs["is_original"]]
    if original.empty or original["outcome"].iloc[0] == EXCLUDED:
        return None
    variants = issue_runs[~issue_runs["is_original"]]
    scored = variants[variants["outcome"] != EXCLUDED]
    return int((scored["outcome"] == original["outcome"].iloc[0]).sum()), len(scored)


def rq1_overview(runs_df: pd.DataFrame, issue_ids: list[str]) -> str:
    """One sentence over all issues: originals localized, and variants that kept the original's
    outcome (the sums of ``variant_consistency``; issues whose original has no outcome are left
    out of the variant count, as the engine leaves them out of SC)."""
    originals = runs_df[runs_df["is_original"] & runs_df["issue_id"].isin(issue_ids)]
    scored_originals = originals[originals["outcome"] != EXCLUDED]
    n_localized = int((scored_originals["outcome"] == "success").sum())
    counts = [c for c in (variant_consistency(runs_df, iid) for iid in issue_ids) if c is not None]
    kept, n_scored = sum(c[0] for c in counts), sum(c[1] for c in counts)
    return (
        f"Originals localized: **{n_localized} of {len(scored_originals)}**. "
        f"Variants that kept the original's outcome: **{kept} of {n_scored}** scored variants."
    )


def rq1_table_rows(runs_df: pd.DataFrame, issue_id: str) -> list[dict]:
    """The single-issue RQ1 table: one row per variant, coloured by outcome."""
    issue_runs = runs_df[runs_df["issue_id"] == issue_id]
    original = issue_runs[issue_runs["is_original"]]
    original_outcome = original["outcome"].iloc[0] if not original.empty else EXCLUDED
    rows = []
    for _, run in issue_runs[~issue_runs["is_original"]].iterrows():
        if run["outcome"] == EXCLUDED:
            icon, consistent = "⚪", "Excluded"
            outcome_label = f"Excluded ({exclusion_reason(run)})"
        else:
            same = original_outcome != EXCLUDED and run["outcome"] == original_outcome
            icon, consistent = ("🟢", "Yes") if same else ("🔴", "No")
            if original_outcome == EXCLUDED:
                icon, consistent = "⚪", "N/A (original excluded)"
            outcome_label = run["outcome"].capitalize()
        rows.append({
            "":                          icon,
            "Transformation":            _TLABELS.get(
                run["transformation_name"], run["transformation_name"]
            ),
            "Outcome":                   outcome_label,
            "Patch Produced":            "Yes" if run["patch"] else "No",
            "Consistent with Original?": consistent,
        })
    return rows


def exclusions_text(exclusions: dict) -> str:
    """One sentence on the runs left out of metrics A/F/G."""

    def by_transformation(counts: dict[str, int]) -> str:
        nonzero = {name: count for name, count in counts.items() if count}
        if not nonzero:
            return ""
        return " (" + ", ".join(
            f"{_TLABELS.get(name, name)}: {count}" for name, count in sorted(nonzero.items())
        ) + ")"

    return (
        f"Excluded from metrics: {exclusions['status']} run(s) that did not complete normally "
        f"(timeout, cost cap, error); {exclusions['quality_warning']} run(s) on quality-warning "
        f"variants{by_transformation(exclusions['quality_warning_by_transformation'])}; "
        f"{exclusions.get('noop', 0)} run(s) on no-op variants (identical to the original)"
        f"{by_transformation(exclusions.get('noop_by_transformation', {}))}."
    )


def provenance_rows(runs_df: pd.DataFrame) -> list[dict]:
    """One row per variant (issue × transformation) with its provenance, for the reports."""
    variants = runs_df[~runs_df["is_original"]].drop_duplicates(
        subset=["issue_id", "transformation_name"]
    )
    return [
        {
            "issue_id": run["issue_id"],
            "transformation_name": run["transformation_name"],
            "generator": run.get("generator") or "unknown",
            "transform_version": run.get("transform_version") or "n/a",
            "generation_mode": run.get("generation_mode") or "unknown",
            "noop": bool(run.get("noop", False)),
            "quality_warning": bool(run.get("quality_warning", False)),
            "exclusion_reason": _text(run.get("exclusion_reason")),
        }
        for _, run in variants.sort_values(["issue_id", "transformation_name"]).iterrows()
    ]


def _text(value) -> str:
    """A string cell value, "" for None / NaN."""
    return value if isinstance(value, str) else ""


def _round(value) -> float | None:
    """A metric value rounded to 3 decimals, None when missing (None / NaN)."""
    return None if value is None or pd.isna(value) else round(float(value), 3)


def flip_rates(metrics_df: pd.DataFrame) -> dict[str, float]:
    """agent|transformation -> symmetric flip rate (any change of outcome), from the engine."""
    if metrics_df.empty:
        return {}
    rows = metrics_df[metrics_df["metric_name"] == "flip_rate"]
    return dict(zip(rows["scope_key"], rows["metric_value"]))


def without_control_runs(runs_df: pd.DataFrame) -> pd.DataFrame:
    """runs_df without its control runs (re-runs of the original measuring the noise floor).

    Every table, chart and test compares variants with THE original run; a control run is
    neither, so only the exports and the noise floor (control_flip_rate) report it.
    """
    if "control_repeat" not in runs_df:
        return runs_df
    return runs_df[~runs_df["control_repeat"].fillna(False).astype(bool)]


def noise_floor_text(metrics_df: pd.DataFrame) -> str | None:
    """The control flip rate of each agent as one sentence; None without control runs."""
    if metrics_df.empty:
        return None
    rows = metrics_df[metrics_df["metric_name"] == "control_flip_rate"]
    if rows.empty:
        return None
    rates = ", ".join(
        f"{value:.3f}" + (f" ({agent})" if len(rows) > 1 else "")
        for agent, value in zip(rows["scope_key"], rows["metric_value"])
    )
    return (
        f"Noise floor: control flip rate {rates}, from re-runs of the unchanged original. "
        "A flip rate at or below it is indistinguishable from run-to-run variance."
    )


# The issue detail view opens on this pair when the experiment has it (the pilot's showcase).
DETAIL_DEFAULT_ISSUE = "psf__requests-2317"
DETAIL_DEFAULT_VARIANT = "reordering"


def comparison_runs(all_runs_df: pd.DataFrame, issue_id: str | None) -> dict[str, pd.Series]:
    """label -> run, for the runs the issue's original patch can be compared with: one per
    transformation, then the control runs (repeats of the unchanged original)."""
    if issue_id is None:
        return {}
    issue_runs = all_runs_df[all_runs_df["issue_id"] == issue_id]
    is_control = (
        issue_runs["control_repeat"].fillna(False).astype(bool)
        if "control_repeat" in issue_runs else pd.Series(False, index=issue_runs.index)
    )
    candidates: dict[str, pd.Series] = {}
    for _, run in issue_runs[~issue_runs["is_original"] & ~is_control].iterrows():
        label = _TLABELS.get(run["transformation_name"], run["transformation_name"])
        candidates.setdefault(label, run)
    controls = issue_runs[is_control].sort_values("run_index")
    for number, (_, run) in enumerate(controls.iterrows(), start=1):
        candidates[CONTROL_LABEL if len(controls) == 1 else f"{CONTROL_LABEL} #{number}"] = run
    return candidates


def control_similarity(
    all_runs_df: pd.DataFrame, issue_id: str | None, similarity_by_run: dict[str, float]
) -> float | None:
    """The mean changed-line similarity of the issue's control runs to its original run."""
    if issue_id is None or "control_repeat" not in all_runs_df:
        return None
    controls = all_runs_df[
        (all_runs_df["issue_id"] == issue_id)
        & all_runs_df["control_repeat"].fillna(False).astype(bool)
    ]
    values = [similarity_by_run[r] for r in controls["run_id"] if r in similarity_by_run]
    return sum(values) / len(values) if values else None


def detail_summary(
    label: str,
    original_outcome: str,
    run: pd.Series,
    similarity_by_run: dict[str, float],
    control_value: float | None,
) -> str:
    """One line above the patches: both outcomes and the pair's changed-line similarity."""
    parts = [
        f"Original run: **{original_outcome}**",
        f"{label} run: **{run.get('outcome', EXCLUDED)}**",
    ]
    value = similarity_by_run.get(run["run_id"])
    if value is not None:
        text = f"changed-line similarity **{value:.3f}**"
        if control_value is not None and not str(label).startswith(CONTROL_LABEL):
            text += f" (repeat of the original on this issue: {control_value:.3f})"
        parts.append(text)
    return " · ".join(parts)


def similarity_caption(has_control: bool) -> str:
    """How to read the changed-line similarity table and dot plot."""
    text = (
        "Similarity of each run's changed lines (the + and − lines of its diff, without file "
        "headers, compared character by character) to those of the same issue's original run: "
        "1 = the same edit, 0 = nothing in "
        "common. Faint dots: issues; marker and bar: mean and 95% bootstrap CI (5000 resamples, "
        "fixed seed). "
    )
    if has_control:
        return text + (
            "Dashed line: the mean of the repeats of the unchanged original, the run-to-run "
            "noise floor. Δ is paired by issue (variant minus repeat). The Wilcoxon signed-rank "
            "tests are exploratory: few issues, no correction for multiple comparisons."
        )
    return text + "This experiment has no control runs, so there is no noise floor to compare with."


def variant_provenance_summary(runs_df: pd.DataFrame, transformation: str) -> dict:
    """The distinct generators and versions behind one transformation's variants."""
    variants = runs_df[
        (~runs_df["is_original"]) & (runs_df["transformation_name"] == transformation)
    ]

    def distinct(column: str) -> str:
        if column not in variants:
            return ""
        return ";".join(sorted({str(v) for v in variants[column].dropna() if v != ""}))

    return {"generators": distinct("generator"), "transform_versions": distinct("transform_version")}


def runs_csv_bytes(runs_df: pd.DataFrame) -> bytes:
    """The runs export, including each run's outcome."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_RUNS_CSV_COLUMNS)
    writer.writeheader()
    for record in _records(runs_df):
        writer.writerow({
            column: "" if record.get(column) is None else record[column]
            for column in _RUNS_CSV_COLUMNS
        })
    return buf.getvalue().encode()


def _records(frame: pd.DataFrame) -> list[dict]:
    """Rows as dicts with missing values (NaN) as None, so exports write blanks / null."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def render_results(exp_id: str, runs_df: pd.DataFrame, metrics_df: pd.DataFrame) -> None:
    """Render the RQ1 / RQ2 / Transformed Issues / Issue Detail / Export tabs for one experiment.

    Handles single-issue and multi-issue experiments: with exactly one issue the
    RQ1 tab renders the original per-transformation table (unchanged from before
    multi-issue support); with more than one, it renders a per-issue stability
    table plus the mean Stability Score. RQ2 sensitivity is already aggregated
    across all issues in the experiment by MetricsEngine, so its rendering does
    not depend on issue count.
    """
    if runs_df.empty:
        st.warning("No run data found for this experiment.")
        return

    all_runs_df = attach_outcomes(runs_df, metrics_df)  # control runs included: exports, detail
    runs_df = without_control_runs(all_runs_df)
    similarity_by_run = recorded_run_values(_metric_tuples(metrics_df), "changed_line_similarity")
    noise_floor = noise_floor_text(metrics_df)
    exclusions = exclusion_counts(_metric_tuples(metrics_df))
    variant_runs_all = runs_df[~runs_df["is_original"]].copy()
    variant_runs_all["transform_label"] = (
        variant_runs_all["transformation_name"].map(_TLABELS).fillna(variant_runs_all["transformation_name"])
    )

    issue_ids = sorted(i for i in runs_df["issue_id"].dropna().unique().tolist() if i)
    multi_issue = len(issue_ids) > 1
    agent_name = runs_df["agent_name"].iloc[0]
    statistical_tests, duplicate_pairs = paired_transformation_tests(
        runs_df.to_dict(orient="records")
    )

    st.header(_results_header(exp_id, all_runs_df, agent_name))

    orig_by_issue: dict[str, dict] = {}
    for iid in issue_ids:
        orig_rows = runs_df[(runs_df["issue_id"] == iid) & runs_df["is_original"]]
        orig_by_issue[iid] = {
            "patch": orig_rows["patch"].iloc[0] if not orig_rows.empty else None,
            "text": orig_rows["issue_text"].iloc[0] if not orig_rows.empty else "",
        }

    def _get_metric(name: str, scope_key: str | None = None) -> float | None:
        rows = metrics_df[metrics_df["metric_name"] == name]
        if scope_key is not None:
            rows = rows[rows["scope_key"] == scope_key]
        return float(rows["metric_value"].iloc[0]) if not rows.empty else None

    ss_mean = _get_metric("stability_score_mean", agent_name)

    ts_rows = metrics_df[metrics_df["metric_name"] == "transformation_sensitivity"].copy()
    flip_by_key = flip_rates(metrics_df)
    if not ts_rows.empty:
        ts_rows["transform"] = ts_rows["scope_key"].str.split("|").str[1]
        ts_rows["label"] = ts_rows["transform"].map(_TLABELS).fillna(ts_rows["transform"])
        ts_rows["flip_rate"] = [flip_by_key.get(key) for key in ts_rows["scope_key"]]

    tab_rq1, tab_rq2, tab_statistics, tab_issues, tab_patches, tab_export = st.tabs([
        "📊  RQ1: Stability",
        "📈  RQ2: Transformation Sensitivity",
        "🧪  Statistical Tests",
        "📝  Transformed Issues",
        "🔍  Issue Detail",
        "📥  Export",
    ])

    # ── TAB 1: RQ1 — Stability ───────────────────────────────────────────────
    with tab_rq1:
        if not multi_issue:
            iid = issue_ids[0] if issue_ids else None
            sc_val = _get_metric("success_consistency", f"{agent_name}|{iid}")
            ss_val = _get_metric("stability_score", f"{agent_name}|{iid}")
            ss_display = ss_val if ss_val is not None else (ss_mean if ss_mean is not None else 0.0)

            consistency = variant_consistency(runs_df, iid) if iid is not None else None
            if consistency is None:
                st.markdown(
                    "The original run has no outcome (it did not complete normally), so "
                    "consistency cannot be assessed for this issue."
                )
            else:
                n_consistent, n_scored = consistency
                st.markdown(
                    f"The agent showed consistent behavior on **{n_consistent} of {n_scored}** "
                    f"scored issue variants (Stability Score: **{ss_display:.2f}**)"
                )

            table_rows = rq1_table_rows(runs_df, iid) if iid is not None else []
            if table_rows:
                st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            st.divider()
            mc1, mc2 = st.columns(2)
            with mc1:
                col = _score_color(ss_display)
                st.markdown(f"**Stability Score (F):** :{col}[**{ss_display:.3f}**]")
                st.caption("Range [0,1] · ≥0.7 Stable · 0.4–0.7 Moderate · <0.4 Unstable")
            with mc2:
                if sc_val is not None:
                    col = _score_color(sc_val)
                    st.markdown(f"**Success Consistency (A):** :{col}[**{sc_val:.3f}**]")
                    st.caption(
                        "Fraction of variants with the same outcome as the original "
                        "(outcome = localization success)"
                    )
        else:
            st.markdown(f"Results aggregated across **{len(issue_ids)} issues**.")
            st.markdown(rq1_overview(runs_df, issue_ids))

            per_issue_rows = []
            for iid in issue_ids:
                consistency = variant_consistency(runs_df, iid)
                sc_val = _get_metric("success_consistency", f"{agent_name}|{iid}")
                ss_val = _get_metric("stability_score", f"{agent_name}|{iid}")
                per_issue_rows.append({
                    "Issue":                     iid,
                    "Consistent Variants":       (
                        f"{consistency[0]} / {consistency[1]}" if consistency else "N/A"
                    ),
                    "Success Consistency (A)":   round(sc_val, 3) if sc_val is not None else "N/A",
                    "Stability Score (F)":       round(ss_val, 3) if ss_val is not None else "N/A",
                })
            st.dataframe(pd.DataFrame(per_issue_rows), use_container_width=True, hide_index=True)

            st.divider()
            if ss_mean is not None:
                col = _score_color(ss_mean)
                st.markdown(f"**Mean Stability Score (F):** :{col}[**{ss_mean:.3f}**]")
                st.caption(
                    "Mean of per-issue Stability Score across all selected issues · "
                    "Range [0,1] · ≥0.7 Stable · 0.4–0.7 Moderate · <0.4 Unstable"
                )

        if exclusions["status"] or exclusions["quality_warning"] or exclusions["noop"]:
            st.caption(exclusions_text(exclusions))

    # ── TAB 2: RQ2 — Transformation Sensitivity ─────────────────────────────
    with tab_rq2:
        if multi_issue:
            st.caption(f"Sensitivity computed across all {len(issue_ids)} selected issues.")

        # Patch content first: the changed-line similarity against the repeat of the original.
        st.markdown("#### Changed-line similarity to the original")
        sim_rows = similarity_rows(metrics_df, agent_name, _TLABELS)
        if sim_rows:
            st.dataframe(similarity_table(sim_rows), use_container_width=True, hide_index=True)
            st.plotly_chart(
                similarity_dot_plot(sim_rows), use_container_width=True,
                key=f"{exp_id}_similarity_plot",
            )
            st.caption(similarity_caption(any(row["is_control"] for row in sim_rows)))
        else:
            st.info(
                "Changed-line similarity was not computed for this experiment (its metrics "
                "predate it). Recompute them from the stored runs, at no cost: "
                f"`stabilityeval recompute-metrics --experiment-id {exp_id}`"
            )

        st.divider()
        st.markdown("#### Outcome sensitivity (G) and flip rate")
        if not ts_rows.empty:
            ts_plot = ts_rows.sort_values("metric_value", ascending=True)

            max_val = ts_plot["metric_value"].max()
            norm_vals = ts_plot["metric_value"] / max(max_val, 0.01)
            bar_colors = [
                f"rgba({int(34 + 205 * n)},{int(197 - 129 * n)},{int(94 - 26 * n)},0.85)"
                for n in norm_vals
            ]

            fig = go.Figure(go.Bar(
                x=ts_plot["metric_value"],
                y=ts_plot["label"],
                orientation="h",
                marker_color=bar_colors,
                text=[f"{v:.2f}" for v in ts_plot["metric_value"]],
                textposition="outside",
                textfont=dict(size=13, family="Arial, sans-serif"),
                hovertemplate="<b>%{y}</b><br>Sensitivity (G) = %{x:.3f}<extra></extra>",
            ))
            fig.update_layout(
                height=260,
                xaxis=dict(
                    title=dict(text="Sensitivity Score (G)", font=dict(size=13)),
                    range=[0, max(max_val * 1.3, 0.1)],
                    gridcolor="#e5e7eb",
                    zeroline=True,
                    zerolinecolor="#94a3b8",
                ),
                yaxis=dict(tickfont=dict(size=13, family="Arial, sans-serif")),
                plot_bgcolor="white",
                paper_bgcolor="white",
                margin=dict(l=190, r=80, t=20, b=50),
                font=dict(family="Arial, sans-serif"),
            )
            st.plotly_chart(fig, use_container_width=True)

            top_row = ts_plot.iloc[-1]
            st.info(
                f"**Most disruptive transformation:** {top_row['label']} "
                f"(sensitivity score: {top_row['metric_value']:.2f})"
            )

            tbl_data = [
                {
                    "Transformation": r["label"],
                    "Sensitivity (G)": round(r["metric_value"], 3),
                    "Flip rate": _round(r["flip_rate"]),
                    "Interpretation": _interp(r["metric_value"]),
                }
                for _, r in ts_plot.sort_values("metric_value", ascending=False).iterrows()
            ]
            st.dataframe(pd.DataFrame(tbl_data), use_container_width=True, hide_index=True)
            st.caption(
                "Sensitivity (G) is a drop rate: success → failure counts +1 and failure → "
                "success −1, so opposite flips cancel out. The flip rate counts any change of "
                "outcome between the original and the variant."
            )
            if noise_floor:
                st.caption(noise_floor)
        else:
            st.info("No transformation sensitivity data available for this experiment.")

    # ── TAB 3: Paired statistical tests ──────────────────────────────────────
    with tab_statistics:
        stats_runs = runs_df
        stats_agents = sorted(runs_df["agent_name"].dropna().unique().tolist())
        if len(stats_agents) > 1:
            selected_agent = st.selectbox(
                "Agent", stats_agents, key=f"{exp_id}_stats_agent"
            )
            stats_runs = stats_runs[stats_runs["agent_name"] == selected_agent]
        statistical_tests, duplicate_pairs = paired_transformation_tests(
            stats_runs.to_dict(orient="records")
        )
        if "run_index" in stats_runs:
            replicate_ids = sorted(int(value) for value in stats_runs["run_index"].dropna().unique())
            if len(replicate_ids) > 1:
                selected_replicate = st.selectbox(
                    "Run replicate", replicate_ids, key=f"{exp_id}_stats_replicate"
                )
                stats_runs = runs_df[runs_df["run_index"] == selected_replicate]
                statistical_tests, duplicate_pairs = paired_transformation_tests(
                    stats_runs.to_dict(orient="records")
                )
        st.markdown("### Transformation vs. original")
        st.caption(
            "Exact two-sided McNemar tests use paired issues; Holm correction controls "
            "family-wise error across the displayed transformations. Effect is the "
            "transformed minus original success rate."
        )
        st.info(
            "Here, success means localization success: a valid unified diff was extracted "
            "and it modifies every file the gold patch modifies (without a gold patch, a "
            "valid diff counts as success). It does not mean the patch was applied or passed "
            "tests. Runs that did not complete normally, runs on quality-warning or no-op "
            "variants and incomplete issue pairs are excluded. Each issue must have one outcome "
            "per variant."
        )
        if duplicate_pairs:
            st.warning(
                f"Excluded {duplicate_pairs} issue/variant pairs with multiple runs. "
                "Select or aggregate a replicate before testing repeated-run experiments."
            )
        if not statistical_tests:
            st.warning("No complete original/transformation pairs have testable outcomes.")
        else:
            stats_df = pd.DataFrame(statistical_tests)
            stats_df["success_rate_delta"] = stats_df["success_rate_delta"].map(
                lambda value: f"{value:+.1%}"
            )
            stats_df["p_value"] = stats_df["p_value"].map(lambda value: f"{value:.4f}")
            stats_df["p_holm"] = stats_df["p_holm"].map(lambda value: f"{value:.4f}")
            stats_df = stats_df.rename(columns={
                "transformation": "Transformation",
                "n_pairs": "Paired issues",
                "original_successes": "Original successes",
                "transformed_successes": "Transformed successes",
                "regressions": "Success to failure",
                "improvements": "Failure to success",
                "success_rate_delta": "Rate change",
                "p_value": "Exact p",
                "p_holm": "Holm-adjusted p",
            })
            st.dataframe(stats_df, use_container_width=True, hide_index=True)
            max_pairs = max(row["n_pairs"] for row in statistical_tests)
            if max_pairs < 10:
                st.caption(
                    f"Small sample: at most {max_pairs} paired issues. Treat p-values as "
                    "exploratory; report issue-level counts and effect estimates too."
                )

    # ── TAB 4: Transformed Issues ────────────────────────────────────────────
    with tab_issues:
        if variant_runs_all.empty:
            st.info("No transformation variants found.")
        else:
            if multi_issue:
                sel_issue = st.selectbox(
                    "Select issue", issue_ids, key=f"{exp_id}_tab_issues_issue_sel"
                )
            else:
                sel_issue = issue_ids[0] if issue_ids else None

            issue_variant_runs = (
                variant_runs_all[variant_runs_all["issue_id"] == sel_issue]
                if sel_issue is not None else variant_runs_all
            )

            if issue_variant_runs.empty:
                st.info("No transformation variants found for this issue.")
            else:
                t_opts = issue_variant_runs["transform_label"].tolist()
                sel_t = st.selectbox(
                    "Select transformation to inspect", t_opts, key=f"{exp_id}_tab_issues_sel"
                )
                t_run = issue_variant_runs[issue_variant_runs["transform_label"] == sel_t].iloc[0]
                orig_text = orig_by_issue.get(sel_issue, {}).get("text", "")

                ic1, ic2 = st.columns(2)
                with ic1:
                    st.markdown("**Original Issue**")
                    st.text_area(
                        "orig_issue_text",
                        value=orig_text,
                        height=300,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"{exp_id}_{sel_issue}_orig_text",
                    )
                with ic2:
                    st.markdown(f"**Transformed Issue — {sel_t}**")
                    st.text_area(
                        "transformed_issue_text",
                        value=t_run["transformed_text"],
                        height=300,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"{exp_id}_{sel_issue}_{sel_t}_trans_text",
                    )
                # Provenance (SPEC section 11.6): what produced the text the agent saw.
                st.caption(provenance_text(t_run))
                if t_run.get("generator") == PLACEHOLDER:
                    st.warning(
                        "Placeholder: this variant was not generated (mock and dry-run modes "
                        "make no API calls). It is not a transformation of the issue."
                    )
                if t_run.get("noop", False):
                    st.info(
                        "No-op: identical to the original after whitespace normalization, so "
                        "this run is excluded from Success Consistency and Transformation "
                        "Sensitivity."
                    )
                if t_run.get("quality_warning", False):
                    st.warning(
                        "Quality warning: the variant failed the quality check after retries "
                        "and is excluded from the metrics."
                    )
                reason = _text(t_run.get("exclusion_reason"))
                if reason:
                    st.markdown("**Exclusion reason**")
                    st.code(reason, language=None)

    # ── TAB 5: Issue detail — original patch vs a variant's, differences highlighted ────────
    with tab_patches:
        if variant_runs_all.empty:
            st.info("No transformation variants found.")
        else:
            if multi_issue:
                sel_issue4 = st.selectbox(
                    "Select issue", issue_ids,
                    index=default_index(issue_ids, DETAIL_DEFAULT_ISSUE),
                    key=f"{exp_id}_tab_patches_issue_sel",
                )
            else:
                sel_issue4 = issue_ids[0] if issue_ids else None

            candidates = comparison_runs(all_runs_df, sel_issue4)
            if not candidates:
                st.info("No transformation variants found for this issue.")
            else:
                labels4 = list(candidates)
                sel_t4 = st.selectbox(
                    "Compare the original's patch with", labels4,
                    index=default_index(labels4, _TLABELS[DETAIL_DEFAULT_VARIANT]),
                    key=f"{exp_id}_tab_patches_sel",
                )
                changed_only = st.toggle(
                    "Changed lines only (what the similarity compares)",
                    key=f"{exp_id}_tab_patches_changed_only",
                )
                t_run4 = candidates[sel_t4]
                orig_patch = orig_by_issue.get(sel_issue4, {}).get("patch")
                original_run = runs_df[(runs_df["issue_id"] == sel_issue4) & runs_df["is_original"]]
                original_outcome = (
                    original_run["outcome"].iloc[0] if not original_run.empty else EXCLUDED
                )
                st.markdown(detail_summary(
                    sel_t4, original_outcome, t_run4, similarity_by_run,
                    control_similarity(all_runs_df, sel_issue4, similarity_by_run),
                ))

                if t_run4["status"] == "skipped_variant":
                    st.info(
                        f"{sel_t4} was not run on this issue: "
                        f"{_text(t_run4.get('error_message')) or exclusion_reason(t_run4)}"
                    )
                else:
                    st.html(diff_legend_html(sel_t4))
                    st.html(side_by_side_html(
                        patch_lines(orig_patch, changed_only),
                        patch_lines(t_run4["patch"], changed_only),
                        "Original issue — patch",
                        f"{sel_t4} — patch",
                    ))
                    with st.expander("Raw patches"):
                        pc1, pc2 = st.columns(2)
                        with pc1:
                            st.code(orig_patch or "(no patch)", language="diff")
                        with pc2:
                            st.code(t_run4["patch"] or "(no patch)", language="diff")

    # ── TAB 6: Export ────────────────────────────────────────────────────────
    with tab_export:
        def _json_export() -> bytes:
            safe_runs = _records(all_runs_df)
            exp_meta = load_experiment(exp_id) or {}
            data = {
                "experiment_id": exp_id,
                "experiment": exp_meta,
                "issues": issue_ids,
                "stability_score_mean": ss_mean,
                "runs": safe_runs,
                "metrics": metrics_df.to_dict(orient="records"),
                "exclusions": exclusions,
                "statistical_tests": statistical_tests,
            }
            return json.dumps(data, indent=2, default=str).encode()

        def _statistical_tests_csv() -> bytes:
            buf = io.StringIO()
            columns = [
                "transformation", "n_pairs", "original_successes",
                "transformed_successes", "regressions", "improvements",
                "success_rate_delta", "p_value", "p_holm", "generators", "transform_versions",
            ]
            writer = csv.DictWriter(buf, fieldnames=columns)
            writer.writeheader()
            for result in statistical_tests:
                writer.writerow({**result, **variant_provenance_summary(
                    runs_df, result["transformation"]
                )})
            return buf.getvalue().encode()

        def _md_report() -> bytes:
            lines = [
                "# StabilityEval Experiment Report",
                "",
                f"**Experiment ID:** `{exp_id}`",
                f"**Issues:** {', '.join(issue_ids) if issue_ids else 'N/A'}",
                "",
                "## RQ1 — Stability Results",
                "",
            ]
            if ss_mean is not None:
                lines.append(f"- **Mean Stability Score (F):** {ss_mean:.3f}")
            lines.append(f"- {exclusions_text(exclusions)}")
            lines += [
                "",
                "| Issue | Success Consistency (A) | Stability Score (F) |",
                "|-------|--------------------------|----------------------|",
            ]
            for iid in issue_ids:
                sc_val = _get_metric("success_consistency", f"{agent_name}|{iid}")
                ss_val = _get_metric("stability_score", f"{agent_name}|{iid}")
                sc_str = f"{sc_val:.3f}" if sc_val is not None else "N/A"
                ss_str = f"{ss_val:.3f}" if ss_val is not None else "N/A"
                lines.append(f"| {iid} | {sc_str} | {ss_str} |")
            lines += [
                "",
                "## RQ2 — Transformation Sensitivity",
                "",
                "Sensitivity (G) is a drop rate; the flip rate counts any change of outcome.",
                "",
                "| Transformation | Sensitivity (G) | Flip rate | Interpretation |",
                "|----------------|-----------------|-----------|----------------|",
            ]
            if not ts_rows.empty:
                for _, r in ts_rows.sort_values("metric_value", ascending=False).iterrows():
                    v = r["metric_value"]
                    flip = _round(r["flip_rate"])
                    flip_text = f"{flip:.3f}" if flip is not None else "N/A"
                    lines.append(f"| {r['label']} | {v:.3f} | {flip_text} | {_interp(v)} |")
            if noise_floor:
                lines += ["", noise_floor]
            lines += [
                "",
                "## Paired Tests — Transformation vs. Original",
                "",
                "Exact two-sided McNemar tests; Holm-adjusted p-values.",
                "",
                "| Transformation | Paired issues | Regressions | Improvements | Rate change | Exact p | Holm p |",
                "|----------------|---------------|-------------|--------------|-------------|---------|--------|",
            ]
            for result in statistical_tests:
                label = _TLABELS.get(result["transformation"], result["transformation"])
                lines.append(
                    f"| {label} | {result['n_pairs']} | {result['regressions']} | "
                    f"{result['improvements']} | {result['success_rate_delta']:+.1%} | "
                    f"{result['p_value']:.4f} | {result['p_holm']:.4f} |"
                )
            lines += [
                "",
                "## Variant Provenance",
                "",
                "What produced each issue text the agent saw. Placeholders are offline "
                "stand-ins (mock / dry-run mode), never generated variants.",
                "",
                "| Issue | Transformation | Generator | Transform version | Mode | No-op "
                "| Quality warning | Exclusion reason |",
                "|-------|----------------|-----------|-------------------|------|-------"
                "|-----------------|------------------|",
            ]
            for row in provenance_rows(runs_df):
                reason = row["exclusion_reason"].replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| {row['issue_id']} | {row['transformation_name']} | {row['generator']} | "
                    f"{row['transform_version']} | {row['generation_mode']} | "
                    f"{'yes' if row['noop'] else 'no'} | "
                    f"{'yes' if row['quality_warning'] else 'no'} | {reason} |"
                )
            lines.append("")
            return "\n".join(lines).encode()

        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            st.download_button(
                "⬇ Download CSV", data=runs_csv_bytes(all_runs_df), file_name="runs.csv",
                mime="text/csv", use_container_width=True, key=f"{exp_id}_dl_csv",
            )
        with ec2:
            st.download_button(
                "⬇ Download JSON", data=_json_export(), file_name="experiment_results.json",
                mime="application/json", use_container_width=True, key=f"{exp_id}_dl_json",
            )
        with ec3:
            st.download_button(
                "⬇ Download Report (Markdown)", data=_md_report(), file_name="experiment_report.md",
                mime="text/markdown", use_container_width=True, key=f"{exp_id}_dl_md",
            )
        with ec4:
            st.download_button(
                "⬇ Download Tests (CSV)", data=_statistical_tests_csv(),
                file_name="statistical_tests.csv", mime="text/csv",
                use_container_width=True, key=f"{exp_id}_dl_tests",
            )
