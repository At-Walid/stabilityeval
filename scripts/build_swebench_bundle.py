"""Build data/swebench_lite_issues.json from a local copy of SWE-bench Lite (offline).

Reads the test split (300 issues) from the Hugging Face cache, or from a parquet file given with
--parquet, and NEVER downloads. Each issue keeps its id, repository, verbatim problem statement,
base commit and gold patch; the gold patch is hidden ground truth that the app never shows to an
agent (see stableagent/data/loaders/swebench.py). The output also records where the data came
from and a license note.

Usage:
    python scripts/build_swebench_bundle.py
    python scripts/build_swebench_bundle.py --parquet path/to/test-00000-of-00001.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "data" / "swebench_lite_issues.json"
DATASET = "princeton-nlp/SWE-bench_Lite"
HF_SNAPSHOTS = (
    Path.home() / ".cache" / "huggingface" / "hub" / "datasets--princeton-nlp--SWE-bench_Lite"
    / "snapshots"
)

LICENSE_NOTE = (
    "The Hugging Face dataset card for princeton-nlp/SWE-bench_Lite (revision {revision}) "
    "declares no license. Problem statements are GitHub issue texts written by their original "
    "authors, and gold patches are code from the corresponding open-source repositories, which "
    "remain under those projects' own licenses. Bundled unmodified so the StableAgent tool can "
    "run offline for research reproducibility; check the upstream terms before redistributing."
)


def find_cached_parquet() -> Path:
    candidates = sorted(HF_SNAPSHOTS.glob("*/data/test-*.parquet"))
    if not candidates:
        raise SystemExit(
            f"No cached SWE-bench Lite test split under {HF_SNAPSHOTS}; pass --parquet explicitly."
        )
    return candidates[-1]


def build(parquet: Path) -> dict:
    frame = pd.read_parquet(parquet)
    revision = parquet.parent.parent.name if parquet.parent.name == "data" else "unknown"
    issues = [
        {
            "id": row.instance_id,
            "repo": row.repo,
            "problem_statement": row.problem_statement,
            "base_commit": row.base_commit,
            "gold_patch": row.patch,
        }
        for row in frame.sort_values("instance_id").itertuples(index=False)
    ]
    return {
        "source": {
            "dataset": DATASET,
            "url": f"https://huggingface.co/datasets/{DATASET}",
            "split": "test",
            "revision": revision,
            "paper": (
                "SWE-bench: Can Language Models Resolve Real-World GitHub Issues? "
                "(arXiv:2310.06770)"
            ),
            "fields": (
                "id = instance_id; repo, problem_statement and base_commit verbatim; "
                "gold_patch = the dataset's patch field (hidden ground truth, never shown to agents)"
            ),
            "generated_by": "scripts/build_swebench_bundle.py (offline, from a local copy)",
        },
        "license_note": LICENSE_NOTE.format(revision=revision),
        "count": len(issues),
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--parquet", type=Path, help="SWE-bench Lite test split parquet file")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    parquet = args.parquet or find_cached_parquet()
    bundle = build(parquet)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {bundle['count']} issues from {parquet} to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
