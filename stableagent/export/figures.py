"""The paper's RQ2 figure: changed-line similarity per transformation, one marker per model.

One row per transformation plus a "Repeat of original" row (the noise floor) on top; in each row
one marker per compared agent (model), offset vertically, at its mean similarity to that agent's
own original patch, with the 95% bootstrap CI as a horizontal bar; a vertical line per model at
its repeat mean. Models differ by colour AND by marker shape, marker fill and line style, so the
figure still reads in grayscale. Sized for one IEEE column (3.5 in wide) and saved as PDF with
TrueType fonts (no Type 3 fonts). The dashboard shows the same Figure object.

Built on ``matplotlib.figure.Figure`` (no pyplot state), so it is safe inside Streamlit.
"""
from __future__ import annotations

from pathlib import Path

from stableagent.metrics.comparison import CONTROL, AgentComparison

COLUMN_WIDTH_IN = 3.5  # one IEEE column

TRANSFORMATION_LABELS = {
    CONTROL: "Repeat of original",
    "paraphrase": "Paraphrase",
    "verbosity_reduction": "Verbosity reduction",
    "typo_injection": "Typo injection",
    "reordering": "Reordering",
    "paragraph_to_structured": "Paragraph → structured",
    "neutralize_emotional": "Neutralize emotional",
}

# Per model, in order: categorical slots 1 and 2 of the reference palette (blue, orange), then
# two more; a filled circle with a dashed line, a hollow square with a dotted line, ...
_STYLES = [
    {"color": "#2a78d6", "marker": "o", "filled": True, "linestyle": (0, (4, 2))},
    {"color": "#eb6834", "marker": "s", "filled": False, "linestyle": (0, (1, 1.5))},
    {"color": "#1baf7a", "marker": "D", "filled": True, "linestyle": (0, (6, 2, 1, 2))},
    {"color": "#4a3aa7", "marker": "^", "filled": False, "linestyle": (0, (2, 2))},
]
_TEXT = "#0b0b0b"
_MUTED = "#52514e"
_GRID = "#e9e8e4"
_RC = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "font.size": 7.5,
    "axes.labelsize": 7.5,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7,
    "pdf.fonttype": 42,  # TrueType: IEEE PDF eXpress rejects Type 3 fonts
    "ps.fonttype": 42,
}


def figure_rows(comparisons: list[AgentComparison]) -> list[str]:
    """Row order, top to bottom: the repeat of the original, then the transformations from least
    to most similar to the original (mean over the models that have the row)."""
    names: list[str] = []
    for comparison in comparisons:
        names.extend(r.transformation for r in comparison.rows if r.transformation not in names)
    transformations = [name for name in names if name != CONTROL]

    def mean_similarity(name: str) -> float:
        values = [
            row.similarity.mean
            for comparison in comparisons
            if (row := comparison.row(name)) is not None and row.similarity is not None
        ]
        return sum(values) / len(values) if values else float("inf")

    ordered = sorted(transformations, key=lambda name: (mean_similarity(name), name))
    return ([CONTROL] if CONTROL in names else []) + ordered


def rq2_figure(comparisons: list[AgentComparison], *, width_in: float = COLUMN_WIDTH_IN):
    """The figure (a matplotlib Figure) for the compared agents; at most four."""
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    if not comparisons:
        raise ValueError("No agent to plot.")
    if len(comparisons) > len(_STYLES):
        raise ValueError(f"At most {len(_STYLES)} models fit in one figure.")
    rows = figure_rows(comparisons)
    count = len(rows)
    positions = {name: count - index for index, name in enumerate(rows)}
    n_models = len(comparisons)
    spread = 0.36 if n_models > 1 else 0.0
    offsets = [spread / 2 - spread * i / max(n_models - 1, 1) for i in range(n_models)]

    with matplotlib.rc_context(_RC):
        fig = Figure(figsize=(width_in, 0.62 + 0.27 * count), layout="constrained")
        ax = fig.add_subplot()
        lows = []
        handles = []
        for comparison, style, offset in zip(comparisons, _STYLES, offsets):
            color = style["color"]
            face = color if style["filled"] else "white"
            control = comparison.control
            if control is not None and control.similarity is not None:
                ax.axvline(control.similarity.mean, color=color, linewidth=0.9,
                           linestyle=style["linestyle"], zorder=1)
            for name in rows:
                row = comparison.row(name)
                if row is None or row.similarity is None:
                    continue
                summary = row.similarity
                lows.append(summary.ci_low)
                ax.errorbar(
                    summary.mean, positions[name] + offset,
                    xerr=[[summary.mean - summary.ci_low], [summary.ci_high - summary.mean]],
                    fmt=style["marker"], color=color, ecolor=color, elinewidth=0.9,
                    capsize=1.8, capthick=0.9, markersize=4.2, markerfacecolor=face,
                    markeredgecolor=color, markeredgewidth=1.0, zorder=3,
                )
            handles.append(Line2D(
                [0], [0], color=color, linestyle=style["linestyle"], linewidth=0.9,
                marker=style["marker"], markersize=4.2, markerfacecolor=face,
                markeredgecolor=color, markeredgewidth=1.0, label=comparison.agent.short_label,
            ))

        low = min(lows) if lows else 0.0
        ax.set_xlim(max(0.0, int((low - 0.05) * 10) / 10), 1.0)
        ax.set_ylim(0.45, count + 0.55)
        ax.set_yticks([positions[name] for name in rows])
        ax.set_yticklabels([TRANSFORMATION_LABELS.get(name, name) for name in rows], color=_TEXT)
        if CONTROL in positions and count > 1:  # separate the noise floor from the variants
            ax.axhline(positions[CONTROL] - 0.5, color=_MUTED, linewidth=0.5, zorder=0)
        ax.set_xlabel("Changed-line similarity to the model’s own original", color=_TEXT)
        ax.grid(axis="x", color=_GRID, linewidth=0.5, zorder=0)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", colors=_MUTED, length=2, width=0.5)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(_MUTED)
        ax.spines["bottom"].set_linewidth(0.5)
        fig.legend(
            handles=handles, loc="outside upper center", ncol=n_models, frameon=False,
            handlelength=2.6, columnspacing=1.2, borderaxespad=0.1,
        )
    return fig


def save_rq2_figure(fig, path: str | Path) -> Path:
    """Save the figure (PDF for the paper; the format follows the suffix), page size unchanged.

    Always save or render through here (or ``render_rq2_figure``): tick labels are drawn at save
    time, so the fonts apply only inside the figure's style context. A PDF carries no creation
    date, so the same data writes the same file.
    """
    import matplotlib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with matplotlib.rc_context(_RC):
        fig.savefig(path, metadata={"CreationDate": None} if path.suffix == ".pdf" else None)
    return path


def render_rq2_figure(fig, fmt: str = "png", dpi: int = 200) -> bytes:
    """The figure as bytes (the dashboard shows the PNG and offers the PDF)."""
    import io

    import matplotlib

    buffer = io.BytesIO()
    with matplotlib.rc_context(_RC):
        fig.savefig(
            buffer, format=fmt, dpi=dpi,
            metadata={"CreationDate": None} if fmt == "pdf" else None,
        )
    return buffer.getvalue()
