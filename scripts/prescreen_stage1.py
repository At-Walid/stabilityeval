"""Stage 1 of the issue pre-screening: structural filter over SWE-bench Lite.

Selects 20 candidate issues for the empirical pre-screen (Stage 2, see
docs/SPEC.md section 18.3) using purely structural criteria computed from
the problem statement text. This script makes NO API calls and costs
nothing beyond the one-time HuggingFace dataset download.

Selection criteria (all must hold):
- 100 <= word_count <= 400, counted on prose only (fenced code blocks,
  inline code spans, and stack-trace-like lines removed)
- paragraph_count >= 2 (blank-line-separated segments of the original text)
- prose_ratio >= 0.60 (chars of prose text / chars of full text)

From the passing set, a seeded (seed=42) stratified sample of 20 issues is
drawn with at most 5 issues per repository, preferring repo diversity
(at least 4 distinct repos when available).

Outputs:
- scripts/output/stage1_candidates.csv   (features per candidate)
- scripts/output/stage1_candidates.json  (full issue records for Stage 2)

Usage:
    python scripts/prescreen_stage1.py
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    # Use the OS certificate store when available — required behind
    # TLS-intercepting proxies whose root CA is not in certifi's bundle.
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from datasets import load_dataset
from rich.console import Console
from rich.table import Table

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
SPLIT = "test"
SEED = 42
TARGET_COUNT = 20
MAX_PER_REPO = 5
MIN_REPOS_IN_SAMPLE = 4

OUTPUT_DIR = Path(__file__).parent / "output"

FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
UNCLOSED_FENCE_RE = re.compile(r"```.*\Z", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
STACK_TRACE_PREFIXES = ("  File ", "Traceback", ">>> ")


def extract_prose(text: str) -> str:
    """Issue body with code blocks, inline code, and stack-trace lines removed."""
    prose = FENCED_BLOCK_RE.sub("", text)
    prose = UNCLOSED_FENCE_RE.sub("", prose)
    prose = INLINE_CODE_RE.sub("", prose)
    lines = [
        line
        for line in prose.splitlines()
        if not line.startswith(STACK_TRACE_PREFIXES)
    ]
    return "\n".join(lines)


def count_paragraphs(text: str) -> int:
    """Blank-line-separated segments of the ORIGINAL text (code blocks included)."""
    segments = re.split(r"\n\s*\n", text.strip())
    return sum(1 for seg in segments if seg.strip())


def compute_features(issue: dict) -> dict:
    text = issue["problem_statement"]
    prose = extract_prose(text)
    return {
        "issue_id": issue["instance_id"],
        "repo": issue["repo"],
        "word_count": len(prose.split()),
        "paragraph_count": count_paragraphs(text),
        "prose_ratio": len(prose) / len(text) if text else 0.0,
        "has_code_block": "```" in text,
        "problem_statement": text,
    }


def passes_filter(feat: dict) -> bool:
    return (
        100 <= feat["word_count"] <= 400
        and feat["paragraph_count"] >= 2
        and feat["prose_ratio"] >= 0.60
    )


def stratified_sample(passing: list[dict], rng: random.Random) -> list[dict]:
    """Seeded stratified sample: max 5 per repo, round-robin across repos.

    Round-robin over shuffled repo groups maximizes repo diversity, so when
    more than 4 repos pass the filter the sample necessarily contains at
    least 4 distinct repos.
    """
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for feat in sorted(passing, key=lambda f: f["issue_id"]):
        by_repo[feat["repo"]].append(feat)

    repos = sorted(by_repo)
    rng.shuffle(repos)
    for repo in repos:
        rng.shuffle(by_repo[repo])

    selected: list[dict] = []
    taken_per_repo: Counter = Counter()
    while len(selected) < TARGET_COUNT:
        progressed = False
        for repo in repos:
            if len(selected) >= TARGET_COUNT:
                break
            if taken_per_repo[repo] < MAX_PER_REPO and by_repo[repo]:
                selected.append(by_repo[repo].pop())
                taken_per_repo[repo] += 1
                progressed = True
        if not progressed:
            break
    return selected


def main() -> None:
    console = Console()

    # Step 1: load
    dataset = load_dataset(DATASET_NAME, split=SPLIT)
    issues = list(dataset)
    console.print(f"Loaded [bold]{len(issues)}[/bold] issues from {DATASET_NAME} ({SPLIT} split)")

    # Step 2: features
    features = [compute_features(issue) for issue in issues]

    # Step 3: filter
    passing = [f for f in features if passes_filter(f)]
    console.print(
        f"\n[bold]{len(passing)}[/bold] / {len(features)} issues pass the structural filter"
    )
    repo_counts = Counter(f["repo"] for f in passing)
    breakdown = Table(title="Pass counts per repository")
    breakdown.add_column("Repository")
    breakdown.add_column("Passing", justify="right")
    for repo, count in repo_counts.most_common():
        breakdown.add_row(repo, str(count))
    console.print(breakdown)

    # Step 4: select 20 candidates
    rng = random.Random(SEED)
    candidates = stratified_sample(passing, rng)
    if len(candidates) < TARGET_COUNT:
        console.print(
            f"[bold yellow]WARNING:[/bold yellow] only {len(candidates)} candidates "
            f"selected (fewer than {TARGET_COUNT} issues pass the filter "
            f"under the per-repo cap of {MAX_PER_REPO})"
        )
    sample_repos = {c["repo"] for c in candidates}
    if len(repo_counts) > MIN_REPOS_IN_SAMPLE and len(sample_repos) < MIN_REPOS_IN_SAMPLE:
        console.print(
            f"[bold yellow]WARNING:[/bold yellow] sample contains only "
            f"{len(sample_repos)} repos despite {len(repo_counts)} passing repos"
        )

    # Step 5: outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "stage1_candidates.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "issue_id",
                "repo",
                "word_count",
                "paragraph_count",
                "prose_ratio",
                "has_code_block",
                "first_80_chars_of_issue",
            ]
        )
        for c in candidates:
            snippet = " ".join(c["problem_statement"].split())[:80]
            writer.writerow(
                [
                    c["issue_id"],
                    c["repo"],
                    c["word_count"],
                    c["paragraph_count"],
                    f"{c['prose_ratio']:.3f}",
                    c["has_code_block"],
                    snippet,
                ]
            )

    json_path = OUTPUT_DIR / "stage1_candidates.json"
    records = [
        {
            "id": c["issue_id"],
            "repo": c["repo"],
            "problem_statement": c["problem_statement"],
        }
        for c in candidates
    ]
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    summary = Table(title=f"Stage 1 candidates ({len(candidates)} selected)")
    summary.add_column("issue_id")
    summary.add_column("repo")
    summary.add_column("word_count", justify="right")
    summary.add_column("paragraph_count", justify="right")
    for c in sorted(candidates, key=lambda f: f["issue_id"]):
        summary.add_row(
            c["issue_id"], c["repo"], str(c["word_count"]), str(c["paragraph_count"])
        )
    console.print(summary)
    console.print(f"Wrote {csv_path}")
    console.print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
