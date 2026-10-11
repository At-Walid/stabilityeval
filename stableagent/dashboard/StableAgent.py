"""StableAgent — main experiment page.

The dashboard is the ONLY interface users need. Select an issue, choose an
agent and transformations, click Run — results appear on this same page.
"""
from __future__ import annotations

import sys
import uuid
from importlib.util import find_spec
from pathlib import Path

import streamlit as st

# Streamlit puts only this folder on sys.path: without an installed package (e.g. on Streamlit
# Community Cloud) the repository root has to be added for the imports below.
if find_spec("stableagent") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stableagent import REPOSITORY_URL
from stableagent.agents.llm_baseline import BASELINE_PRESETS, LLMBaselineAdapter
from stableagent.agents.mock_replay import (
    FixtureNotFoundError,
    MockReplayAdapter,
    fixture_index,
)
from stableagent.config.pricing import OPENAI
from stableagent.config.settings import get_anthropic_api_key, get_openai_api_key, settings
from stableagent.data.database import create_all
from stableagent.dashboard import _picker as picker
from stableagent.dashboard._db import (
    bundled_issue_ids,
    import_bundled_issues,
    load_experiments,
    load_issues,
    load_mean_real_run_cost,
    load_metrics_df,
    load_runs_df,
)
from stableagent.dashboard._results import render_results
from stableagent.execution.plan import expected_cost_per_run
from stableagent.dashboard._runner import (
    NotReplayableError,
    redact,
    run_mock_experiment,
    run_real_experiment,
)
from stableagent.transformations.cache import TransformationError
from stableagent.transformations.llm_backed._api import TRANSFORMATION_MODEL

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StableAgent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Ensure tables exist ────────────────────────────────────────────────────────
create_all()

# ── Session state ──────────────────────────────────────────────────────────────
if "show_results" not in st.session_state:
    st.session_state.show_results = False
if "result_exp_id" not in st.session_state:
    st.session_state.result_exp_id = None

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("StableAgent")
    st.caption("Behavioral Stability Evaluation\nof SE Agents")
    st.divider()
    st.page_link(
        "pages/1_Past_Experiments.py",
        label="Past Experiments ▸",
        icon="📋",
    )
    st.markdown(f"[GitHub ↗]({REPOSITORY_URL})")

# ── Page header ────────────────────────────────────────────────────────────────
st.title("StableAgent")
st.markdown(
    "Select an issue, choose an agent and transformations, then click "
    "**▶ Run Experiment**. Results appear below on this same page."
)
st.divider()

# MockReplay, then one LLM Baseline per model (agents/llm_baseline.py BASELINE_PRESETS): the
# label names the model, the caption under it gives the model id and where its key comes from.
_PRESETS = {preset.label: preset for preset in BASELINE_PRESETS}
_AGENT_OPTIONS = ["MockReplay (free, instant)", *_PRESETS]
_AGENT_CAPTIONS = ["Replays recorded fixtures: no API call, free"] + [
    f"model {preset.model} · key {preset.api_key_env_var}"
    + (" from .env" if preset.provider == OPENAI else "")
    for preset in BASELINE_PRESETS
]

_TRANSFORMS = [
    {
        "name": "paraphrase",
        "label": "Paraphrase",
        "description": "Rewrite in different words, preserving all technical content",
        "default": True,
        "type": "LLM-backed",
    },
    {
        "name": "verbosity_reduction",
        "label": "Verbosity Reduction",
        "description": "Compress to essential content (~50% shorter)",
        "default": True,
        "type": "LLM-backed",
    },
    {
        "name": "typo_injection",
        "label": "Typo / Noise Injection",
        "description": "Introduce random character-level errors (2% of words)",
        "default": False,
        "type": "Deterministic",
    },
    {
        "name": "reordering",
        "label": "Reordering",
        "description": "Shuffle the order of paragraphs (fixed seed)",
        "default": False,
        "type": "Deterministic",
    },
    {
        "name": "paragraph_to_structured",
        "label": "Paragraph → Structured Bug Report",
        "description": "Reformat as Summary / Steps / Expected / Actual / Environment",
        "default": False,
        "type": "LLM-backed",
    },
    {
        "name": "neutralize_emotional",
        "label": "Neutralize Emotional Language",
        "description": "Remove frustration/emotion, rewrite in professional tone",
        "default": False,
        "type": "LLM-backed",
    },
]

# Section A marks each issue replayable or not for the transformations enabled in Section C, and
# its "show only replayable" default follows the agent chosen in Section B. Those widgets render
# below Section A, so their current values are read from session state: Streamlit stores a keyed
# widget's new value there before the rerun its change triggers, and the defaults apply until then.
_mode_is_mock = st.session_state.get("agent_radio", _AGENT_OPTIONS[0]) == _AGENT_OPTIONS[0]
# The LLM Baseline chosen in Section B (the first one while MockReplay is chosen): cost estimates.
_preset = _PRESETS.get(st.session_state.get("agent_radio"), BASELINE_PRESETS[0])
_enabled_transforms = [
    t["name"] for t in _TRANSFORMS if st.session_state.get(f"transform_ck_{t['name']}", t["default"])
]
def _md(text: str) -> str:
    """``text`` for st.markdown and alerts: two "$" would otherwise render as LaTeX math."""
    return text.replace("$", r"\$")


_fixtures = fixture_index()
# Per model: the mean cost of its past real runs, else its expected cost from the model table
# (the ICSE pilot's mean tokens per run at the model's prices), as `run --estimate` computes it.
_mean_cost, _n_cost_runs = load_mean_real_run_cost(_preset.model)
_per_run = picker.cost_per_run(_mean_cost, expected_cost_per_run(_preset.model))
_cost_basis = (
    f"mean of {_n_cost_runs} past real {_preset.model} run(s)"
    if _mean_cost
    else f"no real {_preset.model} run recorded yet: expected cost at its prices"
)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION A — Issue Input
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("A — Issue Input")

issue_source = st.radio(
    "Issue source:",
    ["Select from SWE-bench Lite", "Write my own issue"],
    horizontal=True,
    key="issue_source_radio",
)

issues_to_run: list[dict] = []  # [{"issue_id": ..., "issue_text": ..., "repo_name": ...}, ...]

if issue_source == "Select from SWE-bench Lite":
    issues_df = load_issues()

    # ── Bundled SWE-bench Lite issues: imported on demand, offline ────────────
    try:
        _bundle_ids = bundled_issue_ids()
    except (OSError, ValueError):
        _bundle_ids = frozenset()
        st.warning("⚠️ The bundled issue file data/swebench_lite_issues.json could not be read.")
    _loaded_ids = set() if issues_df.empty else set(issues_df["external_id"].dropna())
    _n_missing = len(_bundle_ids - _loaded_ids)
    if _n_missing:
        st.info(
            f"{len(_bundle_ids) - _n_missing} of the {len(_bundle_ids)} bundled SWE-bench Lite "
            "issues are loaded. Loading reads the file shipped with the app: no network access."
        )
        if st.button(
            f"Load SWE-bench Lite ({len(_bundle_ids)} issues, offline)",
            type="primary" if issues_df.empty else "secondary",
            key="load_bundle_button",
        ):
            _summary = import_bundled_issues()
            st.session_state["bundle_import_message"] = (
                f"Loaded {_summary.inserted} new SWE-bench Lite issue(s); "
                f"{_summary.updated} already present kept their text."
            )
            st.rerun()
    _import_message = st.session_state.pop("bundle_import_message", None)
    if _import_message:
        st.success(_import_message)

    if not issues_df.empty:
        issues_df = picker.with_issue_keys(issues_df)
        _replayable = picker.replayable_ids(issues_df["issue_key"], _enabled_transforms, _fixtures)

        # ── Filters: repository, keyword, replayable only ─────────────────────
        # The repository and issue widgets get their value through session state on every run:
        # their labels carry counts and badges that change, and a value set this way is kept
        # across label changes.
        _f_set, _f_repo, _f_keyword, _f_toggle = st.columns([2, 2, 3, 2])
        with _f_set:
            _set_options = picker.issue_set_options(issues_df)
            if st.session_state.get("issue_set_filter") not in _set_options:
                st.session_state["issue_set_filter"] = picker.ALL_ISSUE_SETS
            _n_pilot = picker.n_pilot(issues_df)
            selected_set = st.selectbox(
                "Issue set",
                _set_options,
                key="issue_set_filter",
                format_func=lambda s: f"{s} ({_n_pilot})" if s == picker.PILOT_SET else s,
            )
        with _f_repo:
            _repo_options = picker.repository_options(issues_df)
            _current_repo = st.session_state.get("repo_filter")
            st.session_state["repo_filter"] = (
                _current_repo if _current_repo in _repo_options else picker.ALL_REPOSITORIES
            )
            _repo_counts = issues_df["repo_name"].value_counts()
            selected_repo = st.selectbox(
                "Repository",
                _repo_options,
                key="repo_filter",
                format_func=lambda r: (
                    r if r == picker.ALL_REPOSITORIES else f"{r} ({_repo_counts.get(r, 0)})"
                ),
            )
        with _f_keyword:
            keyword = st.text_input(
                "Search the issue text",
                placeholder="e.g. migration ImportError (all words must match)",
                key="issue_keyword",
            )
        with _f_toggle:
            # Defaults to ON with MockReplay and OFF with LLM Baseline; a change of agent resets it.
            if (
                "only_replayable" not in st.session_state
                or st.session_state.get("_only_replayable_mode") != _mode_is_mock
            ):
                st.session_state["only_replayable"] = _mode_is_mock
                st.session_state["_only_replayable_mode"] = _mode_is_mock
            only_replayable = st.toggle(
                "Show only replayable",
                key="only_replayable",
                help="Replayable issues have MockReplay fixtures for the original and for every "
                     "transformation enabled in Section C.",
            )

        shown_df = picker.filter_issues(
            issues_df,
            issue_set=selected_set,
            repo=selected_repo,
            keyword=keyword,
            only_replayable=only_replayable,
            replayable=_replayable,
        )
        st.caption(
            picker.counter_text(len(issues_df), len(_replayable), len(shown_df), _n_pilot)
        )

        # ── Issue selector (1 or more). Options are issue ids; labels carry the badge ──
        _rows_by_key: dict[str, dict] = {}
        for _row in issues_df.to_dict("records"):
            _rows_by_key.setdefault(_row["issue_key"], _row)
        _options = list(dict.fromkeys(shown_df["issue_key"]))
        # Filters narrow what can be added; they never drop an issue that is already selected.
        if "issue_selector" in st.session_state:
            _selected = [k for k in st.session_state["issue_selector"] if k in _rows_by_key]
        else:
            _selected = _options[:1]
        _options += [k for k in _selected if k not in _options]
        st.session_state["issue_selector"] = _selected

        def _issue_label(key: str) -> str:
            row = _rows_by_key[key]
            mark = picker.badge(key in _replayable, _per_run)
            return picker.option_label(key, row["issue_text"], row.get("source"), mark)

        if shown_df.empty:
            st.info("No issues match the filters.")
        selected_keys = st.multiselect(
            "Select issues (1 or more)",
            _options,
            format_func=_issue_label,
            key="issue_selector",
        )
        issues_to_run = [picker.issue_payload(_rows_by_key[k]) for k in selected_keys]

        if len(issues_to_run) == 1:
            st.text_area(
                "Issue Preview",
                value=issues_to_run[0]["issue_text"],
                height=180,
                disabled=True,
                key=f"issue_preview_{issues_to_run[0]['issue_id']}",
            )
        elif issues_to_run:
            with st.expander(f"Issue Previews ({len(issues_to_run)} selected)"):
                for d in issues_to_run:
                    st.markdown(f"**{d['issue_id']}** — {d['repo_name']}")
                    st.text_area(
                        "preview",
                        value=d["issue_text"],
                        height=120,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"issue_preview_multi_{d['issue_id']}",
                    )

else:  # Write my own issue
    issue_text = st.text_area(
        "Issue Description",
        placeholder="Paste or type the software issue you want to test…",
        height=200,
        key="custom_issue_text",
    )
    repo_name = st.text_input(
        "Repository name (optional)",
        placeholder="e.g. django/django",
        key="custom_repo",
    )
    _custom_id_input = st.text_input(
        "Issue ID (optional)",
        placeholder="e.g. my-issue-001",
        key="custom_issue_id",
    )
    issue_id = _custom_id_input if _custom_id_input.strip() else f"custom-{uuid.uuid4().hex[:8]}"
    if issue_text.strip():
        # Stored as an ad-hoc record (source "custom_adhoc"), hidden from the SWE-bench picker.
        issues_to_run.append({
            "issue_id": issue_id, "issue_text": issue_text, "repo_name": repo_name, "custom": True,
        })

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION B — Agent Selection
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("B — Agent Selection")

agent_choice = st.radio(
    "Select Agent:",
    _AGENT_OPTIONS,
    index=0,
    key="agent_radio",
    captions=_AGENT_CAPTIONS,
)
use_mock = agent_choice == _AGENT_OPTIONS[0]
uses_openai = not use_mock and _preset.provider == OPENAI

# Agent info panel — the model comes from the chosen preset (BASELINE_PRESETS), which is also
# what the run is configured with, so this display can't drift from what the agent calls.
if use_mock:
    st.info(
        f"**Agent:** MockReplay v{MockReplayAdapter.version}  \n"
        f"**Mode:** Replays recorded fixtures — no API calls  \n"
        f"**Cost:** $0.00"
    )
else:
    _key_line = (
        f"**API key:** {_preset.api_key_env_var} from .env — "
        + ("set" if get_openai_api_key() else "**not set**")
        + "  \n"
        if uses_openai else ""
    )
    st.info(_md(
        f"**Agent:** {_preset.label} — LLM Baseline v{LLMBaselineAdapter.version}  \n"
        f"**Model:** {_preset.model} (provider {_preset.provider})  \n"
        + _key_line
        + f"**Mode:** Real execution (one API call per variant, plus one {TRANSFORMATION_MODEL} "
        "call per LLM-backed variant not cached yet)  \n"
        f"**Est. cost:** ~${_per_run:.4f} per variant ({_cost_basis})"
    ))

api_key: str | None = None
if not use_mock:
    # The key lives in this browser session's state only: it is handed to the Anthropic client
    # and never written to disk, the database, or the logs. With the field empty, the key from the
    # environment (e.g. docker run -e ANTHROPIC_API_KEY=...) is used.
    _env_key = get_anthropic_api_key()
    api_key = st.text_input(
        "Anthropic API Key" + (
            " (only to generate LLM-backed variants not cached yet)" if uses_openai else ""
        ),
        type="password",
        placeholder="Anthropic API key",
        key="api_key_input",
        help="Kept in this browser session only; never saved to disk, the database, or logs.",
    ) or _env_key
    if _env_key and not st.session_state.get("api_key_input"):
        st.caption("Using the key from the ANTHROPIC_API_KEY environment variable.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION C — Transformation Selection
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("C — Select Transformations (minimum 2)")

_BADGE_LLM = (
    "background:#ede9fe;color:#6d28d9;"
    "padding:1px 7px;border-radius:4px;"
    "font-size:0.72em;font-weight:600;white-space:nowrap"
)
_BADGE_DET = (
    "background:#dcfce7;color:#15803d;"
    "padding:1px 7px;border-radius:4px;"
    "font-size:0.72em;font-weight:600;white-space:nowrap"
)

selected_transforms: list[str] = []
t_cols = st.columns(2)
for i, t in enumerate(_TRANSFORMS):
    with t_cols[i % 2]:
        checked = st.checkbox(
            f"**{t['label']}**",
            value=t["default"],
            key=f"transform_ck_{t['name']}",
        )
        badge_style = _BADGE_LLM if t["type"] == "LLM-backed" else _BADGE_DET
        st.markdown(
            f'<div style="margin-top:-10px;margin-bottom:10px;line-height:1.4">'
            f'<span style="color:#6b7280;font-size:0.85em">{t["description"]}</span>'
            f'&nbsp;&nbsp;<span style="{badge_style}">{t["type"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if checked:
            selected_transforms.append(t["name"])

st.info(
    f"ℹ️ In real mode, LLM-backed variants are generated with {TRANSFORMATION_MODEL} (and "
    "cached); if one cannot be generated the run stops with an error, it never uses a "
    "placeholder. Mock mode makes no API calls: agent outputs are replayed from recorded "
    "fixtures, and an LLM-backed variant not generated yet is shown as a labelled placeholder."
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION D — Run
# ══════════════════════════════════════════════════════════════════════════════


def _run_blockers(index: dict[str, set[str]]) -> list[str]:
    return picker.run_blockers(
        issues=issues_to_run,
        transformations=selected_transforms,
        use_mock=use_mock,
        custom_issue=issue_source == "Write my own issue",
        api_key=api_key,
        index=index,
        per_run=_per_run,
        cost_limit=settings.DEFAULT_TOTAL_COST_LIMIT_USD,
        openai_agent=_preset.label if uses_openai else None,
        openai_key_set=get_openai_api_key() is not None,
    )


if not use_mock and issues_to_run:
    _n_runs = picker.n_runs(len(issues_to_run), len(selected_transforms))
    _estimate = picker.estimate_cost(len(issues_to_run), len(selected_transforms), _per_run)
    st.markdown(_md(
        f"**Estimated cost:** ${_estimate:.2f} = {_n_runs} run(s) × ${_per_run:.4f} per run "
        f"({_cost_basis}). Limit: ${settings.DEFAULT_TOTAL_COST_LIMIT_USD:.2f}."
    ))

# Shown before the click: a disabled button never fires, so these are the only explanation.
_blockers = _run_blockers(_fixtures)
for _reason in _blockers:
    st.warning(_md(f"⚠️ {_reason}"))
run_disabled = bool(_blockers)

_progress_slot = st.empty()
_status_slot = st.empty()

if st.button(
    "▶  Run Experiment",
    type="primary",
    disabled=run_disabled,
    use_container_width=False,
):
    # Click-time re-check: fixtures could have changed since the page was drawn.
    _blockers = _run_blockers(fixture_index())
    if _blockers:
        for _reason in _blockers:
            st.error(_md(f"❌ {_reason}"))
        st.stop()

    exp_name = (
        f"Dashboard — {issues_to_run[0]['issue_id']}"
        if len(issues_to_run) == 1
        else f"Dashboard — {len(issues_to_run)} issues"
    )

    def _progress(frac: float, msg: str) -> None:
        _progress_slot.progress(frac, text=msg)

    with st.spinner("Running experiment…"):
        try:
            if use_mock:
                new_exp_id = run_mock_experiment(
                    issues=issues_to_run,
                    selected_transforms=selected_transforms,
                    experiment_name=exp_name,
                    progress_callback=_progress,
                )
            else:
                new_exp_id = run_real_experiment(
                    issues=issues_to_run,
                    selected_transforms=selected_transforms,
                    experiment_name=exp_name,
                    api_key=api_key or "",
                    progress_callback=_progress,
                    provider=_preset.provider,
                    model=_preset.model,
                )

            st.session_state.result_exp_id = new_exp_id
            st.session_state.show_results = True
            # Clear caches so fresh data is visible
            load_runs_df.clear()
            load_metrics_df.clear()
            load_experiments.clear()
            load_issues.clear()
            load_mean_real_run_cost.clear()

        except NotReplayableError as exc:
            st.error(_md(f"❌ {exc}"))
            st.session_state.show_results = False
        except TransformationError as exc:
            st.error(_md(f"❌ {redact(str(exc), api_key)}"))
            st.session_state.show_results = False
        except FixtureNotFoundError:
            st.error(
                "❌ MockReplay has no recorded fixture for this selection, so nothing could be "
                "replayed. Pick issues marked ✓ replayable, or switch to LLM Baseline."
            )
            st.session_state.show_results = False
        except Exception as exc:
            st.error(_md(f"Experiment failed: {redact(str(exc), api_key)}"))
            st.session_state.show_results = False

    _progress_slot.empty()
    if st.session_state.show_results:
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# RESULTS — shown below Run button after experiment completes
# ══════════════════════════════════════════════════════════════════════════════
if not (st.session_state.show_results and st.session_state.result_exp_id):
    st.stop()

exp_id: str = st.session_state.result_exp_id
runs_df = load_runs_df(exp_id)
metrics_df = load_metrics_df(exp_id)

if runs_df.empty:
    st.warning("No run data found for this experiment.")
    st.stop()

st.success("✅ Experiment complete! Results are shown below.")
st.divider()

render_results(exp_id, runs_df, metrics_df)
