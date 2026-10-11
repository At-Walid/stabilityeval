"""Past Experiments page.

Shows a table of all past experiments and their saved results.
"""
from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import streamlit as st

# Without an installed package (e.g. on Streamlit Community Cloud), add the repository root.
if find_spec("stableagent") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from stableagent import REPOSITORY_URL
from stableagent.data.database import create_all
from stableagent.dashboard._compare import default_comparison, experiment_option_label
from stableagent.dashboard._db import (
    load_agent_comparison,
    load_experiments,
    load_metrics_df,
    load_runs_df,
)
from stableagent.dashboard._results import render_results

st.set_page_config(
    page_title="Past Experiments · StableAgent",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

create_all()

with st.sidebar:
    st.title("StableAgent")
    st.caption("Behavioral Stability Evaluation\nof SE Agents")
    st.divider()
    st.page_link("StableAgent.py", label="StableAgent", icon="⚡")
    st.markdown(f"[GitHub ↗]({REPOSITORY_URL})")

st.title("Past Experiments")
st.markdown("All recorded experiments, most recent first. Select a row to load its results.")

# ── Load experiments ───────────────────────────────────────────────────────────
exps_df = load_experiments()

if exps_df.empty:
    st.info(
        "No experiments found. Run your first experiment on the "
        "[StableAgent](/) page."
    )
    st.stop()

# ── Compare models: the paper's RQ2 figure and table ───────────────────────────
_defaults = default_comparison(exps_df)
with st.expander("📊 Compare models — RQ2 figure and table", expanded=bool(_defaults)):
    st.caption(
        "Pick experiments run on the same issues and variants (e.g. a second model with "
        "reuse_variants_from). Each model's variants and repeats are compared with that model's "
        "own original patch. Mean and 95% bootstrap CI; dashed/dotted line: the model's repeat "
        "of the original; Wilcoxon tests are exploratory."
    )
    _rows = {row["id"]: row for row in exps_df.to_dict("records")}
    _compare_ids = st.multiselect(
        "Experiments to compare (one marker per model)",
        list(reversed(list(_rows))),
        default=_defaults,
        format_func=lambda exp_id: experiment_option_label(_rows[exp_id]),
        key="compare_experiments",
        max_selections=4,
    )
    if _compare_ids:
        from stableagent.export.comparison_table import DISPLAY_COLUMNS, table_rows
        from stableagent.export.figures import render_rq2_figure, rq2_figure

        _comparisons = load_agent_comparison(tuple(_compare_ids))
        if not any(c.rows for c in _comparisons):
            st.info("These experiments have no scored variant or repeat run to compare.")
        else:
            _figure = rq2_figure(_comparisons[:4])
            st.image(render_rq2_figure(_figure, dpi=220), width=560)
            st.download_button(
                "Download fig_results.pdf (one IEEE column, 3.5 in)",
                render_rq2_figure(_figure, fmt="pdf"),
                file_name="fig_results.pdf",
                mime="application/pdf",
                key="download_fig_results",
            )
            # Shorter headers than the exported tables, so every column fits the page width.
            _table = pd.DataFrame(table_rows(_comparisons))[DISPLAY_COLUMNS].rename(columns={
                "Mean similarity [95% CI]": "Similarity [95% CI]",
                "Diff vs repeat [95% CI]": "Δ vs repeat [95% CI]",
                "Outcome kept": "Kept",
            })
            st.dataframe(
                _table,
                use_container_width=True,
                hide_index=True,
                height=35 * (len(_table) + 1) + 3,  # every row, no inner scroll bar
                column_config={
                    "n": st.column_config.Column(width="small"),
                    "Kept": st.column_config.Column(
                        help="Compared runs whose outcome equals the original run's"
                    ),
                },
            )

# ── Build display table ────────────────────────────────────────────────────────
_STATUS_ICON = {
    "completed": "✅",
    "failed": "❌",
    "running": "⏳",
    "cost_exceeded": "⚠️",
    "pending": "⏸",
}

display_rows = []
for _, row in exps_df.sort_values("created_at", ascending=False).iterrows():
    display_rows.append({
        "Status": _STATUS_ICON.get(row["status"], row["status"]),
        "Name": row["name"],
        "Date": row["created_at"],
        "Cost (USD)": f"${row['total_cost_usd']:.4f}",
        "experiment_id": row["id"],
    })

disp_df = pd.DataFrame(display_rows)

selection = st.dataframe(
    disp_df[["Status", "Name", "Date", "Cost (USD)"]],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
)

selected_rows = selection.selection.rows if selection.selection else []

if not selected_rows:
    st.info("Click a row above to load that experiment's results.")
    st.stop()

# ── Show selected experiment results ───────────────────────────────────────────
sel_idx = selected_rows[0]
sel_exp = disp_df.iloc[sel_idx]
exp_id = sel_exp["experiment_id"]

st.divider()
st.subheader(f"Results: {sel_exp['Name']}")

runs_df = load_runs_df(exp_id)
metrics_df = load_metrics_df(exp_id)

if runs_df.empty:
    st.warning("No run data found for this experiment.")
    st.stop()

render_results(exp_id, runs_df, metrics_df)

# ── Load in main page ─────────────────────────────────────────────────────────
st.divider()
if st.button("🔁  Load this experiment in StableAgent", type="secondary"):
    st.session_state["show_results"] = True
    st.session_state["result_exp_id"] = exp_id
    try:
        st.switch_page("StableAgent.py")
    except Exception:
        st.info("Navigate to **StableAgent** in the sidebar — the results will be pre-loaded.")
