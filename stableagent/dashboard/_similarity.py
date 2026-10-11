"""Changed-line similarity views: the RQ2 table and dot plot, and the issue detail patch diff.

Everything shown here was computed by the MetricsEngine (stableagent.metrics.
changed_line_similarity) and read back from its metric rows: the dashboard never recomputes a
metric. The patch diff is a display aid only (what differs between two patches), not a metric.
"""
from __future__ import annotations

import html
import json
from difflib import SequenceMatcher

import pandas as pd
import plotly.graph_objects as go

from stableagent.metrics.changed_line_similarity import changed_lines

CONTROL = "repeat_of_original"
CONTROL_LABEL = "Repeat of original"

# One series (palette slot 1); the control row is neutral grey, the reference line darker grey.
_SERIES = "#2a78d6"
_CONTROL = "#8b8a85"
_REFERENCE = "#52514e"
_GRID = "#e9e8e4"
_TEXT = "#0b0b0b"
_TEXT_MUTED = "#52514e"


def _metadata(value) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def similarity_rows(metrics_df: pd.DataFrame, agent: str, labels: dict[str, str]) -> list[dict]:
    """The control row (when the experiment has control runs), then one row per transformation,
    least similar to the original first. Empty when the engine stored no similarity."""
    if metrics_df.empty or "metric_metadata" not in metrics_df:
        return []
    frame = metrics_df[metrics_df["scope"] == "agent"]

    def metric(name: str) -> dict[str, tuple[float, dict]]:
        rows = frame[frame["metric_name"] == name]
        return {
            key: (float(value), _metadata(meta))
            for key, value, meta in zip(rows["scope_key"], rows["metric_value"],
                                        rows["metric_metadata"])
            if value is not None and not pd.isna(value)
        }

    means = metric("changed_line_similarity_mean")
    versus = metric("changed_line_similarity_vs_control")
    control = metric("control_changed_line_similarity").get(agent)

    rows: list[dict] = []
    if control is not None:
        value, meta = control
        rows.append(_row(CONTROL, CONTROL_LABEL, value, meta, None, is_control=True))
    transformations = []
    for key, (value, meta) in means.items():
        row_agent, _, transformation = key.partition("|")
        if row_agent != agent:
            continue
        transformations.append(_row(
            transformation, labels.get(transformation, transformation), value, meta,
            versus.get(key), is_control=False,
        ))
    rows += sorted(transformations, key=lambda row: (row["mean"], row["label"]))
    return rows


def _row(key, label, mean, meta, versus, *, is_control) -> dict:
    row = {
        "key": key,
        "label": label,
        "is_control": is_control,
        "mean": mean,
        "ci_low": meta.get("ci_low"),
        "ci_high": meta.get("ci_high"),
        "n": int(meta.get("n") or len(meta.get("per_issue") or {})),
        "per_issue": {str(k): float(v) for k, v in (meta.get("per_issue") or {}).items()},
        "delta": None, "delta_ci_low": None, "delta_ci_high": None,
        "wilcoxon_p": None, "n_pairs": None,
    }
    if versus is not None:
        delta, vmeta = versus
        row.update(
            delta=delta, delta_ci_low=vmeta.get("ci_low"), delta_ci_high=vmeta.get("ci_high"),
            wilcoxon_p=vmeta.get("wilcoxon_p"), n_pairs=vmeta.get("n_pairs"),
        )
    return row


def similarity_table(rows: list[dict]) -> pd.DataFrame:
    """The table shown above the dot plot."""

    def interval(value, low, high, signed=False) -> str:
        if value is None:
            return "—"
        fmt = "{:+.3f}" if signed else "{:.3f}"
        if low is None or high is None:
            return fmt.format(value)
        return f"{fmt.format(value)} [{fmt.format(low)}, {fmt.format(high)}]"

    return pd.DataFrame([
        {
            "Variant": row["label"],
            "Issues": row["n"],
            "Mean [95% CI]": interval(row["mean"], row["ci_low"], row["ci_high"]),
            "Δ vs repeat [95% CI]": (
                "reference" if row["is_control"] else
                interval(row["delta"], row["delta_ci_low"], row["delta_ci_high"], signed=True)
            ),
            "Wilcoxon p (exploratory)": (
                "—" if row["wilcoxon_p"] is None else f"{row['wilcoxon_p']:.4f}"
            ),
        }
        for row in rows
    ])


def similarity_dot_plot(rows: list[dict]) -> go.Figure:
    """One row per variant, top to bottom as in the table: faint dots for the issues, the mean
    with its 95% CI, a dashed line at the control mean."""
    count = len(rows)
    positions = {row["key"]: count - index for index, row in enumerate(rows)}  # top row first
    control = next((row for row in rows if row["is_control"]), None)
    fig = go.Figure()

    for row in rows:
        y = positions[row["key"]]
        color = _CONTROL if row["is_control"] else _SERIES
        issues = sorted(row["per_issue"])
        fig.add_trace(go.Scatter(
            x=[row["per_issue"][issue] for issue in issues],
            y=[y + _jitter(index) for index in range(len(issues))],
            mode="markers",
            marker=dict(size=7, color=color, opacity=0.3, line=dict(width=0)),
            customdata=[[issue, row["label"]] for issue in issues],
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                          "similarity %{x:.3f}<extra></extra>",
            showlegend=False,
        ))
        low, high = row["ci_low"], row["ci_high"]
        has_ci = low is not None and high is not None
        fig.add_trace(go.Scatter(
            x=[row["mean"]], y=[y], mode="markers",
            marker=dict(size=12, color=color, line=dict(width=2, color="white")),
            error_x=dict(
                type="data", symmetric=False,
                array=[high - row["mean"]] if has_ci else [0],
                arrayminus=[row["mean"] - low] if has_ci else [0],
                color=color, thickness=2, width=5,
            ),
            customdata=[[row["label"], low if has_ci else row["mean"],
                         high if has_ci else row["mean"], row["n"]]],
            hovertemplate="<b>%{customdata[0]}</b><br>mean %{x:.3f} "
                          "[%{customdata[1]:.3f}, %{customdata[2]:.3f}]<br>"
                          "%{customdata[3]} issues<extra></extra>",
            showlegend=False,
        ))

    if control is not None:
        fig.add_vline(
            x=control["mean"], line=dict(color=_REFERENCE, width=1.5, dash="dash"),
            annotation=dict(
                text=f"repeat of original {control['mean']:.2f}",
                font=dict(size=11, color=_TEXT_MUTED), yanchor="bottom",
            ),
            annotation_position="top",
        )
    fig.update_layout(
        height=90 + 44 * count,
        xaxis=dict(
            title=dict(text="Changed-line similarity to the original run",
                       font=dict(size=13, color=_TEXT)),
            range=[-0.02, 1.04], dtick=0.2, gridcolor=_GRID, gridwidth=1, zeroline=False,
            tickfont=dict(color=_TEXT_MUTED),
        ),
        yaxis=dict(
            tickvals=[positions[row["key"]] for row in rows],
            ticktext=[row["label"] for row in rows],
            range=[0.4, count + 0.6], showgrid=False, zeroline=False,
            tickfont=dict(size=13, color=_TEXT),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=180, r=30, t=34, b=50),
        font=dict(family="Arial, sans-serif"),
        hoverlabel=dict(bgcolor="white", font=dict(color=_TEXT)),
    )
    return fig


def _jitter(index: int) -> float:
    """A fixed vertical offset per issue, so equal values stay visible side by side."""
    return ((index * 7) % 11 - 5) * 0.045


# ── Issue detail: two patches side by side, the differences highlighted ─────────────────────

_REMOVED_BG = "rgba(220, 38, 38, 0.12)"
_REMOVED_SPAN = "rgba(220, 38, 38, 0.32)"
_ADDED_BG = "rgba(22, 163, 74, 0.14)"
_ADDED_SPAN = "rgba(22, 163, 74, 0.36)"
# Paired lines less alike than this are different lines, not an edit of one line: no char marks.
_INTRALINE_MIN_RATIO = 0.5


def patch_lines(patch: str | None, changed_only: bool = False) -> list[str]:
    """A patch as lines; with ``changed_only``, only what the similarity compares."""
    if changed_only:
        return changed_lines(patch)
    text = (patch or "").replace("\r\n", "\n").rstrip("\n")
    return text.split("\n") if text else []


def side_by_side_rows(left: list[str], right: list[str]) -> list[tuple]:
    """Aligned rows (tag, left line no, left html, right line no, right html).

    tag is "equal", "replace", "delete" (only on the left) or "insert" (only on the right).
    Lines of a "replace" block are paired, and the characters that differ are wrapped in <mark>.
    """
    rows: list[tuple] = []
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                line = html.escape(left[i1 + offset])
                rows.append(("equal", i1 + offset + 1, line, j1 + offset + 1, line))
            continue
        width = max(i2 - i1, j2 - j1)
        for offset in range(width):
            i, j = i1 + offset, j1 + offset
            a = left[i] if i < i2 else None
            b = right[j] if j < j2 else None
            if a is not None and b is not None:
                a_html, b_html = _intraline(a, b)
                rows.append(("replace", i + 1, a_html, j + 1, b_html))
            elif a is not None:
                rows.append(("delete", i + 1, html.escape(a), None, None))
            else:
                rows.append(("insert", None, None, j + 1, html.escape(b)))
    return rows


def _intraline(a: str, b: str) -> tuple[str, str]:
    """Both lines escaped, with the differing characters wrapped in <mark> when the lines are
    alike; two unrelated lines are left unmarked (their background already says they differ)."""
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.ratio() < _INTRALINE_MIN_RATIO:
        return html.escape(a), html.escape(b)
    left, right = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        chunk_a, chunk_b = html.escape(a[i1:i2]), html.escape(b[j1:j2])
        if tag == "equal":
            left.append(chunk_a)
            right.append(chunk_b)
            continue
        if chunk_a:
            left.append(f'<mark style="background:{_REMOVED_SPAN};color:inherit">{chunk_a}</mark>')
        if chunk_b:
            right.append(f'<mark style="background:{_ADDED_SPAN};color:inherit">{chunk_b}</mark>')
    return "".join(left), "".join(right)


def side_by_side_html(
    left: list[str], right: list[str], left_title: str, right_title: str
) -> str:
    """An HTML table: the left patch and the right patch line by line, the differences
    highlighted (red: only on the left, green: only on the right, darker: changed characters)."""
    cell = (
        "padding:1px 8px;white-space:pre-wrap;word-break:break-all;vertical-align:top;"
        "font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px;"
        "line-height:1.45"
    )
    number = (
        "padding:1px 6px;text-align:right;vertical-align:top;user-select:none;opacity:0.45;"
        "font-family:ui-monospace,Consolas,monospace;font-size:11.5px;width:2.8em"
    )
    body = []
    divider = "border-left:1px solid rgba(128,128,128,0.35)"
    for tag, ln, left_html, rn, right_html in side_by_side_rows(left, right):
        left_bg = _REMOVED_BG if tag in ("replace", "delete") else "transparent"
        right_bg = _ADDED_BG if tag in ("replace", "insert") else "transparent"
        body.append(
            "<tr>"
            f'<td style="{number}">{ln or ""}</td>'
            f'<td style="{cell};background:{left_bg}">{left_html or ""}</td>'
            f'<td style="{number};{divider}">{rn or ""}</td>'
            f'<td style="{cell};background:{right_bg}">{right_html or ""}</td>'
            "</tr>"
        )
    if not body:
        empty = f'<td colspan="4" style="{cell};opacity:0.6">(both patches are empty)</td>'
        body.append(f"<tr>{empty}</tr>")
    header = (
        "padding:6px 8px;text-align:left;font-weight:600;font-size:13px;"
        "border-bottom:1px solid rgba(128,128,128,0.35)"
    )
    return (
        '<div style="overflow-x:auto;border:1px solid rgba(128,128,128,0.35);border-radius:6px">'
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed">'
        '<colgroup><col style="width:2.8em"><col><col style="width:2.8em"><col></colgroup>'
        f'<thead><tr><th colspan="2" style="{header}">{html.escape(left_title)}</th>'
        f'<th colspan="2" style="{header};border-left:1px solid rgba(128,128,128,0.35)">'
        f"{html.escape(right_title)}</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def diff_legend_html(variant_label: str) -> str:
    swatch = "display:inline-block;width:0.9em;height:0.9em;border-radius:2px;margin:0 4px -1px 0"
    return (
        '<div style="font-size:12.5px;opacity:0.85;margin:2px 0 6px 0">'
        f'<span style="{swatch};background:{_REMOVED_SPAN}"></span>only in the original\'s patch'
        f'&nbsp;&nbsp;&nbsp;<span style="{swatch};background:{_ADDED_SPAN}"></span>only in the '
        f"{html.escape(variant_label)} patch&nbsp;&nbsp;&nbsp;darker: the characters that differ "
        "within a line</div>"
    )


def default_index(options: list[str], preferred: str) -> int:
    """The position of ``preferred`` in ``options``, else 0."""
    return options.index(preferred) if preferred in options else 0
