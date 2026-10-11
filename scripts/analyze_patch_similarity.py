"""RQ1/RQ2 per agent across experiments: outcome consistency and changed-line similarity (offline,
no API call, nothing written to the database).

Every agent of every given experiment is analysed on its own (stableagent/metrics/
comparison.py): its runs are scored as the metrics engine scores them, and a variant's patch, or
a repeat's, is only ever compared with that agent's own original patch. Printed per agent:

- RQ1: originals localized, variants that kept their original's outcome (excluded variants,
  i.e. no-op or quality-warning ones, are left out), mean Stability Score;
- RQ2: per transformation, the outcome kept, the mean changed-line similarity to the original
  with its 95% bootstrap CI, the mean paired difference to the repeat of the unchanged original
  (the noise floor) with its CI, and an exploratory Wilcoxon signed-rank p-value.

Written to --out-dir (default results/paper/): fig_results.pdf (the RQ2 figure, one IEEE column,
one marker per model), fig_results.png, and the combined table as table_results.csv /
table_results.md / table_results.tex.

The similarity is the one the metrics engine stores (stableagent/metrics/
changed_line_similarity.py): the + and - lines of each diff, without file headers, joined with
newlines and compared character by character with difflib.SequenceMatcher (autojunk off).

Usage:
    python scripts/analyze_patch_similarity.py --experiments <pilot id> <model2 id>
    python scripts/analyze_patch_similarity.py --experiments bc6f1372 --db sqlite:///other.db
    python scripts/analyze_patch_similarity.py                      # the shipped pilot exports
    python scripts/analyze_patch_similarity.py --runs results/<experiment>/runs.csv
Experiment ids may be given by a unique prefix.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from stableagent.export.comparison_table import (  # noqa: E402
    table_rows,
    to_latex,
    to_markdown,
    write_csv,
)
from stableagent.export.figures import (  # noqa: E402
    TRANSFORMATION_LABELS,
    figure_rows,
    render_rq2_figure,
    rq2_figure,
    save_rq2_figure,
)
from stableagent.metrics.comparison import (  # noqa: E402
    AgentComparison,
    agent_ref,
    compare_experiments,
    compare_rows,
)

# The shipped exports of both ICSE pilot experiments (Claude Sonnet 4.6, then GPT-4o).
DEFAULT_RUNS = [
    PROJECT_ROOT / "data" / "pilot" / "exports" / model / "runs.csv"
    for model in ("claude-sonnet-4-6", "gpt-4o")
]
DEFAULT_OUT_DIR = PROJECT_ROOT / "results" / "paper"


def load_rows(path: Path) -> tuple[list[dict], list[dict]]:
    """(scored non-control rows, control rows) of a runs.csv export, as the engine scores them."""
    df = pd.read_csv(path, keep_default_na=False)
    df["is_original"] = df["is_original"].astype(str) == "True"
    df["control_repeat"] = df["control_repeat"].astype(str) == "True"
    df["outcome"] = df["outcome"].replace("", "excluded")
    df["patch"] = df["patch"].where(df["patch"] != "", None)
    rows = df[["run_id", "experiment_id", "agent_name", "issue_id", "transformation_name",
               "is_original", "control_repeat", "outcome", "patch"]].to_dict(orient="records")
    return [r for r in rows if not r["control_repeat"]], [r for r in rows if r["control_repeat"]]


def agent_params(runs_csv: Path) -> dict[str, dict]:
    """agent name -> params, from the experiment_results.json exported next to runs.csv ({} when
    there is none): the model names the compared agent."""
    results = runs_csv.with_name("experiment_results.json")
    if not results.is_file():
        return {}
    config = json.loads(results.read_text(encoding="utf-8"))["experiment"].get("config") or "{}"
    config = json.loads(config) if isinstance(config, str) else config
    return {agent["name"]: agent.get("params") or {} for agent in config.get("agents") or []}


def compare_csv(paths: list[Path]) -> list[AgentComparison]:
    """The comparison from runs.csv exports: one compared agent per (experiment, agent name)."""
    run_data, control_data, refs, order = [], [], {}, []
    for path in paths:
        rows, controls = load_rows(path)
        params = agent_params(path)
        for row in rows + controls:
            ref = refs.setdefault(
                (row["experiment_id"], row["agent_name"]),
                agent_ref(row["experiment_id"], row["agent_name"],
                          params.get(row["agent_name"], {})),
            )
            row["agent_name"] = ref.key
            if not row["is_original"] and row["transformation_name"] not in order:
                order.append(row["transformation_name"])
        run_data += rows
        control_data += controls
    return compare_rows(list(refs.values()), run_data, control_data, order)


def resolve_ids(db, prefixes: list[str]) -> list[str]:
    from stableagent.data.models import Experiment

    ids = []
    for prefix in prefixes:
        matches = [
            exp_id for (exp_id,) in
            db.query(Experiment.id).filter(Experiment.id.like(f"{prefix}%")).all()
        ]
        if len(matches) != 1:
            found = "no experiment" if not matches else f"{len(matches)} experiments"
            raise SystemExit(f"'{prefix}' matches {found} in the database.")
        ids.append(matches[0])
    return ids


def print_report(comparisons: list[AgentComparison]) -> None:
    order = figure_rows(comparisons)
    for comparison in comparisons:
        agent = comparison.agent
        print(f"\n{agent.label}  (experiment {agent.experiment_id}, agent {agent.agent_name})")
        ss = comparison.stability_score_mean
        print(f"RQ1  originals localized: {comparison.originals_localized}/"
              f"{comparison.originals_scored}; variants that kept the original's outcome: "
              f"{comparison.variants_kept}/{comparison.variants_scored}; mean SS "
              f"{'-' if ss is None else f'{ss:.3f}'}")
        print("RQ2  changed-line similarity to this model's own original "
              "(95% bootstrap CI; tests exploratory)")
        print(f"     {'variant':<24}{'n':>3} {'kept':>6}  {'mean [95% CI]':<22}"
              f"{'vs repeat [95% CI]':<26}{'p':>7}  {'TS':>6} {'flip':>6}")
        for name in order:
            row = comparison.row(name)
            if row is None:
                continue
            s, v = row.similarity, row.versus_control
            mean = f"{s.mean:.3f} [{s.ci_low:.3f}, {s.ci_high:.3f}]" if s else "-"
            delta = (f"{v.mean_difference:+.3f} [{v.ci_low:+.3f}, {v.ci_high:+.3f}]"
                     if v else "-")
            p_value = f"{v.wilcoxon.p_value:.4f}" if v else "-"
            ts = "-" if row.sensitivity is None else f"{row.sensitivity:.3f}"
            flip = "-" if row.flip_rate is None else f"{row.flip_rate:.3f}"
            print(f"     {TRANSFORMATION_LABELS.get(name, name):<24}{row.n:>3} "
                  f"{f'{row.kept}/{row.compared_runs}':>6}  {mean:<22}{delta:<26}{p_value:>7}  "
                  f"{ts:>6} {flip:>6}")


def write_outputs(comparisons: list[AgentComparison], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = table_rows(comparisons)
    figure = rq2_figure(comparisons)
    written = [
        save_rq2_figure(figure, out_dir / "fig_results.pdf"),
        out_dir / "fig_results.png",
        write_csv(rows, out_dir / "table_results.csv"),
        out_dir / "table_results.md",
        out_dir / "table_results.tex",
    ]
    written[1].write_bytes(render_rq2_figure(figure, dpi=300))
    written[3].write_text(to_markdown(rows), encoding="utf-8")
    written[4].write_text(to_latex(rows), encoding="utf-8")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--experiments", nargs="+", metavar="ID",
                        help="experiment ids (or unique prefixes) in the database")
    source.add_argument("--runs", type=Path, nargs="+", help="runs.csv export(s)")
    parser.add_argument("--db", help="database URL (default: DATABASE_URL, ./stableagent.db)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="where the figure and the tables go (default: results/paper)")
    args = parser.parse_args()

    if args.experiments:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from stableagent.config.settings import settings

        url = args.db or settings.DATABASE_URL
        engine = create_engine(url)
        with Session(engine) as db:  # read only: nothing is added or committed
            ids = resolve_ids(db, args.experiments)
            comparisons = compare_experiments(ids, db)
        engine.dispose()
        print(f"Database: {url}")
    else:
        paths = args.runs or DEFAULT_RUNS
        comparisons = compare_csv(paths)
        print("Runs: " + ", ".join(str(path) for path in paths))

    print_report(comparisons)
    written = write_outputs(comparisons, args.out_dir)
    print("\nCombined table (also in table_results.csv / .md / .tex):\n")
    print(to_markdown(table_rows(comparisons)))
    print("Written: " + ", ".join(str(path) for path in written))


if __name__ == "__main__":
    main()
