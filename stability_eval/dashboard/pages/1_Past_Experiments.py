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
if find_spec("stability_eval") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from stability_eval import REPOSITORY_URL
from stability_eval.data.database import create_all
from stability_eval.dashboard._db import load_experiments, load_runs_df, load_metrics_df
from stability_eval.dashboard._results import render_results

st.set_page_config(
    page_title="Past Experiments · StabilityEval",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

create_all()

with st.sidebar:
    st.title("StabilityEval")
    st.caption("Behavioral Stability Evaluation\nof SE Agents")
    st.divider()
    st.page_link("StabilityEval.py", label="StabilityEval", icon="⚡")
    st.markdown(f"[GitHub ↗]({REPOSITORY_URL})")

st.title("Past Experiments")
st.markdown("All recorded experiments, most recent first. Select a row to load its results.")

# ── Load experiments ───────────────────────────────────────────────────────────
exps_df = load_experiments()

if exps_df.empty:
    st.info(
        "No experiments found. Run your first experiment on the "
        "[StabilityEval](/) page."
    )
    st.stop()

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
if st.button("🔁  Load this experiment in StabilityEval", type="secondary"):
    st.session_state["show_results"] = True
    st.session_state["result_exp_id"] = exp_id
    try:
        st.switch_page("StabilityEval.py")
    except Exception:
        st.info("Navigate to **StabilityEval** in the sidebar — the results will be pre-loaded.")
