"""The combined RQ1/RQ2 table across models: one row per model and transformation.

Columns: n (issues compared with that model's own original), outcome kept (compared runs whose
localization outcome equals the original's), mean changed-line similarity [95% bootstrap CI],
difference to the model's repeat of the original [95% CI] and the exploratory Wilcoxon p-value.
Each model's block opens with its repeat-of-the-original row (the noise floor), then the
transformations in the figure's order. Written as CSV (every number, for further analysis),
Markdown and LaTeX (booktabs).
"""
from __future__ import annotations

import csv
from pathlib import Path

from stableagent.export.figures import TRANSFORMATION_LABELS, figure_rows
from stableagent.metrics.comparison import CONTROL, AgentComparison

CSV_COLUMNS = [
    "model", "model_id", "agent", "experiment_id", "transformation", "n", "outcome_kept",
    "outcome_compared", "excluded_runs", "mean_similarity", "ci_low", "ci_high",
    "diff_vs_repeat", "diff_ci_low", "diff_ci_high", "wilcoxon_p", "wilcoxon_n",
    "sensitivity_ts", "flip_rate",
]
DISPLAY_COLUMNS = [
    "Model", "Variant", "n", "Outcome kept", "Mean similarity [95% CI]",
    "Diff vs repeat [95% CI]", "Wilcoxon p",
]


def table_rows(comparisons: list[AgentComparison]) -> list[dict]:
    """One dict per model and row of the figure, with CSV_COLUMNS and DISPLAY_COLUMNS keys."""
    order = figure_rows(comparisons)
    rows = []
    for comparison in comparisons:
        for name in order:
            row = comparison.row(name)
            if row is None:
                continue
            summary, versus = row.similarity, row.versus_control
            rows.append({
                "model": comparison.agent.short_label,
                "model_id": comparison.agent.model or "",
                "agent": comparison.agent.label,
                "experiment_id": comparison.agent.experiment_id,
                "transformation": name,
                "n": row.n,
                "outcome_kept": row.kept,
                "outcome_compared": row.compared_runs,
                "excluded_runs": row.excluded,
                "mean_similarity": summary.mean if summary else None,
                "ci_low": summary.ci_low if summary else None,
                "ci_high": summary.ci_high if summary else None,
                "diff_vs_repeat": versus.mean_difference if versus else None,
                "diff_ci_low": versus.ci_low if versus else None,
                "diff_ci_high": versus.ci_high if versus else None,
                "wilcoxon_p": versus.wilcoxon.p_value if versus else None,
                "wilcoxon_n": versus.wilcoxon.n if versus else None,
                "sensitivity_ts": row.sensitivity,
                "flip_rate": row.flip_rate,
                "Model": comparison.agent.short_label,
                "Variant": TRANSFORMATION_LABELS.get(name, name),
                "Outcome kept": f"{row.kept}/{row.compared_runs}",
                "Mean similarity [95% CI]": _interval(summary and summary.mean, summary),
                "Diff vs repeat [95% CI]": (
                    "reference" if name == CONTROL
                    else _interval(versus and versus.mean_difference, versus, signed=True)
                ),
                "Wilcoxon p": _p_value(versus.wilcoxon.p_value if versus else None),
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "| " + " | ".join(DISPLAY_COLUMNS) + " |",
        "|" + "|".join("---" if i < 2 else "---:" for i in range(len(DISPLAY_COLUMNS))) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[c]) for c in DISPLAY_COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def to_latex(rows: list[dict]) -> str:
    """A booktabs tabular; one block per model, separated by a rule."""
    header = (
        "Model & Variant & $n$ & Kept & Mean sim. [95\\% CI] & $\\Delta$ vs repeat [95\\% CI] "
        "& $p$ \\\\"
    )
    lines = ["\\begin{tabular}{llrrlll}", "\\toprule", header, "\\midrule"]
    previous = None
    for row in rows:
        if previous is not None and row["model"] != previous:
            lines.append("\\midrule")
        model = _tex(row["Model"]) if row["model"] != previous else ""
        previous = row["model"]
        diff = row["Diff vs repeat [95% CI]"]
        cells = [
            model, _tex(row["Variant"]), str(row["n"]), row["Outcome kept"],
            row["Mean similarity [95% CI]"],
            "---" if diff == "reference" else diff.replace("-", "$-$"),
            "---" if row["Wilcoxon p"] == "—" else row["Wilcoxon p"].replace("<", "$<$"),
        ]
        lines.append(" & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def _interval(value, stats, signed: bool = False) -> str:
    if value is None or stats is None:
        return "—"
    fmt = "{:+.3f}" if signed else "{:.3f}"
    return f"{fmt.format(value)} [{fmt.format(stats.ci_low)}, {fmt.format(stats.ci_high)}]"


def _p_value(p: float | None) -> str:
    if p is None:
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def _tex(text: str) -> str:
    return (
        text.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
        .replace("→", "$\\rightarrow$")
    )
