"""Changed-line similarity and outcome consistency of an exported experiment (offline, no API call).

Reads a runs.csv export (default: the ICSE pilot, data/pilot/exports/runs.csv) and prints the
numbers the paper reports:

- RQ1: originals localized, and variants that kept their original's outcome (excluded variants,
  i.e. no-op or quality-warning ones, are left out);
- RQ2: per transformation, the mean changed-line similarity of the variant's patch to the
  original's patch, with its 95% bootstrap CI, the mean paired difference to the repeat of the
  unchanged original (the noise floor) and an exploratory Wilcoxon signed-rank p-value.

The similarity is the one the metrics engine stores (stability_eval/metrics/
changed_line_similarity.py): the + and - lines of each diff, without file headers, joined with
newlines and compared character by character with difflib.SequenceMatcher (autojunk off).

Usage:
    python scripts/analyze_patch_similarity.py
    python scripts/analyze_patch_similarity.py --runs results/<experiment>/runs.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from stability_eval.metrics.changed_line_similarity import ChangedLineSimilarity  # noqa: E402

DEFAULT_RUNS = PROJECT_ROOT / "data" / "pilot" / "exports" / "runs.csv"


def load_rows(path: Path) -> tuple[list[dict], list[dict]]:
    """(scored non-control rows, control rows), as the metrics engine feeds the similarity."""
    df = pd.read_csv(path, keep_default_na=False)
    df["is_original"] = df["is_original"].astype(str) == "True"
    df["control_repeat"] = df["control_repeat"].astype(str) == "True"
    df["outcome"] = df["outcome"].replace("", "excluded")
    df["patch"] = df["patch"].where(df["patch"] != "", None)
    rows = df[["run_id", "agent_name", "issue_id", "transformation_name", "is_original",
               "control_repeat", "outcome", "patch"]].to_dict(orient="records")
    return [r for r in rows if not r["control_repeat"]], [r for r in rows if r["control_repeat"]]


def outcome_consistency(rows: list[dict]) -> tuple[int, int, int, int]:
    """(originals localized, scored originals, variants that kept the outcome, scored variants)."""
    originals = {r["issue_id"]: r["outcome"] for r in rows if r["is_original"]}
    scored_originals = {i: o for i, o in originals.items() if o != "excluded"}
    variants = [
        r for r in rows
        if not r["is_original"] and r["outcome"] != "excluded" and r["issue_id"] in scored_originals
    ]
    kept = sum(1 for r in variants if r["outcome"] == scored_originals[r["issue_id"]])
    localized = sum(1 for o in scored_originals.values() if o == "success")
    return localized, len(scored_originals), kept, len(variants)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS, help="runs.csv export")
    args = parser.parse_args()

    run_data, control_data = load_rows(args.runs)
    localized, n_originals, kept, n_variants = outcome_consistency(run_data)
    print(f"Runs: {args.runs}")
    print(f"RQ1  originals localized: {localized}/{n_originals}; "
          f"variants that kept the original's outcome: {kept}/{n_variants}")

    results = ChangedLineSimilarity().compute(run_data, control_data)
    print("RQ2  changed-line similarity to the original (95% bootstrap CI; tests exploratory)")
    print(f"     {'variant':<26}{'mean':>7}  {'95% CI':<16}{'vs repeat':>10}  {'p':>7}  {'n':>3}")
    for agent, control in sorted(results.control.items()):
        print(f"     {'repeat of original':<26}{control.mean:>7.3f}  "
              f"[{control.ci_low:.3f}, {control.ci_high:.3f}]{'-':>10}  {'-':>7}  {control.n:>3}")
        cells = sorted(
            (key, summary) for key, summary in results.per_transformation.items() if key[0] == agent
        )
        for (_, transformation), summary in cells:
            comparison = results.versus_control.get((agent, transformation))
            delta = f"{comparison.mean_difference:+.3f}" if comparison else "-"
            p_value = f"{comparison.wilcoxon.p_value:.4f}" if comparison else "-"
            print(f"     {transformation:<26}{summary.mean:>7.3f}  "
                  f"[{summary.ci_low:.3f}, {summary.ci_high:.3f}]{delta:>10}  {p_value:>7}  "
                  f"{summary.n:>3}")


if __name__ == "__main__":
    main()
