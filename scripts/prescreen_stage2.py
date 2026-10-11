"""Stage 2 of the issue pre-screening: empirical stability pre-screen over the Stage 1 candidates.

Takes the 20 candidates written by scripts/prescreen_stage1.py (docs/SPEC.md section 18.3)
and measures how much the LLM Baseline's behaviour changes when an issue is reformulated,
so the ICSE pilot can mix unstable and stable issues instead of drawing an arbitrary sample.

Pipeline
1. Load scripts/output/stage1_candidates.json (the dataset is NOT reloaded) and insert the
   issues into the database (idempotent, keyed by SWE-bench instance id).
2. Produce two variants per candidate through the existing transformation engine and its
   cache: verbosity_reduction ({"target_ratio": 0.5}) and reordering ({"seed": 42}). The
   params equal those of configs/icse_pilot.json / SPEC Appendix B, so the pilot reuses these
   cached variants verbatim.
3. Run the LLM Baseline (real mode, through ExperimentRunner) on original + both variants:
   20 x 3 = 60 runs, persisted as experiment "prescreen_stage2".
4. Score each candidate (definitions below), write scripts/output/stage2_results.csv sorted by
   divergence (descending), print a Rich table of all candidates and a recommended selection.

Definitions
- outcome: the persisted run status (success | failure | timeout | ...). Same convention as
  metric A (SuccessConsistency): "success" means the agent returned a patch; the ICSE pilot has
  no test execution. A candidate is scored only if all three runs ended success/failure/timeout;
  an infrastructure `error` (or missing run) makes it "incomplete" and ineligible for selection.
- flip: a variant's success/non-success differs from the original's.
- C1: character-level diff similarity (stableagent.metrics.patch_similarity) of the two runs'
  final patches. The baseline ignores "output only the diff" and answers with prose plus several
  drafts of the same file, so each reply is first reduced to its diff blocks, last version per
  file (extract_final_patch); comparing whole replies would mostly measure rambling.
- divergence = 1.0 if any flip, else 1 - mean(C1(original, verbosity), C1(original, reordering)).

Selection (printed only; configs/icse_pilot.json is deliberately NOT written)
  top 6 by divergence + bottom 4 (most stable), with at most 4 issues per repo and at least 5
  repos represented. If the plain top-6/bottom-4 split violates a constraint, the lexicographically
  closest selection that satisfies it is used (top group takes priority over the stable group).

Cost guard (SPEC 12.4 ICSE defaults, tightened to this script)
  $0.50 per run, 60 s per request (the SDK retries a timeout twice, so ~3 x 60 s wall-clock for
  one run), $5.00 for the whole script, abort after 3 consecutive API errors. Before any spend the
  script proves a worst-case bound (every call at max_tokens) and refuses to start above the limit.

Re-running: if an experiment named "prescreen_stage2" already exists the script only re-analyses
it (free, read-only). Pass --rerun to execute the 60 runs again as a new experiment.

Usage:
    python scripts/prescreen_stage2.py              # full run (API spend, bounded by $5)
    python scripts/prescreen_stage2.py --dry-run    # key check, plan, worst-case budget only
    python scripts/prescreen_stage2.py --rerun      # execute again even if the experiment exists
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Settings read ".env" and the SQLite URL relative to the working directory, so pin it to the
# project root regardless of where the script is launched from (must precede the package imports).
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from stableagent.agents.llm_baseline import LLMBaselineAdapter  # noqa: E402
from stableagent.config.experiment_schema import (  # noqa: E402
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.config.settings import get_anthropic_api_key  # noqa: E402
from stableagent.data.database import build_engine, create_all  # noqa: E402
from stableagent.data.models import Experiment, Issue, Run, TransformedIssue  # noqa: E402
from stableagent.execution.runner import ExperimentRunner  # noqa: E402
from stableagent.metrics.patch_similarity import (  # noqa: E402
    c1_similarity,
    extract_final_patch,
    has_unified_diff,
)
from stableagent.transformations.base import IssueRecord  # noqa: E402
from stableagent.transformations.cache import TransformationCache  # noqa: E402
from stableagent.transformations.registry import transformation_registry  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "scripts" / "output"
CANDIDATES_PATH = OUTPUT_DIR / "stage1_candidates.json"
RESULTS_PATH = OUTPUT_DIR / "stage2_results.csv"

EXPERIMENT_NAME = "prescreen_stage2"
SEED = 42

VERBOSITY = "verbosity_reduction"
REORDERING = "reordering"
# (name, params) of the two variants. Params match configs/icse_pilot.json / SPEC Appendix B
# so the pilot hits the transformation cache instead of regenerating them.
TRANSFORMS: list[tuple[str, dict]] = [
    (VERBOSITY, {"target_ratio": 0.5}),
    (REORDERING, {"seed": SEED}),
]
VARIANT_LABELS = ("original", VERBOSITY, REORDERING)

# --- cost guard -------------------------------------------------------------------------
PER_RUN_CAP_USD = 0.50
TIMEOUT_SECONDS = 60
TOTAL_LIMIT_USD = 5.00
AGENT_MAX_TOKENS = 4096
CONSECUTIVE_ERROR_LIMIT = 3
# USD per million (input, output) tokens: Sonnet matches LLMBaselineAdapter's cost formula.
SONNET_PRICE = (3.0, 15.0)
HAIKU_PRICE = (1.0, 5.0)
HAIKU_MAX_TOKENS = 4096  # mirrors transformations/llm_backed/_api.py::call_haiku
# Conservative token upper bound for worst-case budgeting (real text is ~3.5-4 chars/token).
CHARS_PER_TOKEN_FLOOR = 2.5
PROMPT_OVERHEAD_TOKENS = 400

# --- selection --------------------------------------------------------------------------
N_TOP = 6
N_STABLE = 4
MAX_PER_REPO = 4
MIN_REPOS = 5
SEARCH_STEP_LIMIT = 1_000_000

# Adjacency below this marks a reordering as a line-level shuffle (fallback signal only).
LINE_SHUFFLE_BELOW = 0.5

# "no_patch" (adapter found no valid diff in the reply) is a genuine failure, not missing data.
GENUINE_OUTCOMES = frozenset({"success", "failure", "no_patch", "timeout"})
CSV_COLUMNS = [
    "issue_id",
    "repo",
    "outcome_original",
    "outcome_verbosity",
    "outcome_reorder",
    "c1_verbosity",
    "c1_reorder",
    "divergence",
]

_OUTCOME_CODES = {
    "success": "S",
    "failure": "F",
    "no_patch": "N",
    "timeout": "T",
    "error": "E",
    "cost_exceeded": "C",
}


# ======================================================================================
# Data
# ======================================================================================


@dataclass(frozen=True)
class Candidate:
    issue_id: str
    repo: str
    text: str


@dataclass(frozen=True)
class RunView:
    """The slice of a persisted Run that scoring needs."""

    status: str
    patch: str | None
    truncated: bool = False  # the reply hit max_tokens


@dataclass
class CandidateResult:
    issue_id: str
    repo: str
    outcome_original: str = "missing"
    outcome_verbosity: str = "missing"
    outcome_reorder: str = "missing"
    c1_verbosity: float | None = None
    c1_reorder: float | None = None
    flip_any: bool | None = None
    divergence: float | None = None  # None => incomplete (ineligible for selection)
    # Console-only diagnostics (not part of the CSV contract):
    line_shuffle: bool = False  # reordering shuffled single lines, not paragraphs
    reorder_intact: float | None = None  # share of adjacent line pairs the reordering kept
    verbosity_ratio: float | None = None  # reduced word count / original word count
    quality_warning: bool = False  # identifier-retention check failed on the verbosity variant
    json_fallback: bool = False  # verbosity variant came from the non-JSON fallback path
    no_diff: tuple[str, ...] = ()  # variants whose "successful" reply holds no unified diff
    truncated: tuple[str, ...] = ()  # variants whose reply was cut off at max_tokens

    @property
    def complete(self) -> bool:
        return self.divergence is not None

    @property
    def mean_c1(self) -> float | None:
        values = [v for v in (self.c1_verbosity, self.c1_reorder) if v is not None]
        return sum(values) / len(values) if values else None


@dataclass
class Selection:
    top: list[CandidateResult]  # most divergent first
    stable: list[CandidateResult]  # most stable first
    max_per_repo: int = 0
    n_repos: int = 0
    constraints_ok: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [r.issue_id for r in self.top + self.stable]


@dataclass(frozen=True)
class Budget:
    transform_worst_case: float
    run_worst_case_max: float
    runs_worst_case: float

    @property
    def total_worst_case(self) -> float:
        return self.transform_worst_case + self.runs_worst_case


# ======================================================================================
# Pure scoring / ranking / selection (no I/O)
# ======================================================================================


def is_success(outcome: str) -> bool:
    return outcome == "success"


def adjacency_preserved(original: str, variant: str) -> float:
    """Share of the original's adjacent (non-blank) line pairs still adjacent in `variant`.

    ~1.0 when whole paragraphs were moved; ~0.0 when individual lines were shuffled.
    """

    def pairs(text: str) -> list[tuple[str, str]]:
        lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
        return list(zip(lines, lines[1:]))

    original_pairs = pairs(original)
    if not original_pairs:
        return 1.0
    kept = set(pairs(variant))
    return sum(1 for p in original_pairs if p in kept) / len(original_pairs)


def _patch_c1(a: RunView, b: RunView) -> float:
    """C1 between the final patches of two runs (prose and superseded drafts removed)."""
    return c1_similarity(extract_final_patch(a.patch), extract_final_patch(b.patch))


def score_candidate(
    original: RunView | None, verbosity: RunView | None, reorder: RunView | None
) -> dict:
    """Compute flip/C1/divergence for one candidate; every value is None when it is incomplete."""
    runs = (original, verbosity, reorder)
    if any(r is None or r.status not in GENUINE_OUTCOMES for r in runs):
        return {"c1_verbosity": None, "c1_reorder": None, "flip_any": None, "divergence": None}

    c1_verbosity = _patch_c1(original, verbosity)
    c1_reorder = _patch_c1(original, reorder)
    flip_any = any(
        is_success(v.status) != is_success(original.status) for v in (verbosity, reorder)
    )
    divergence = 1.0 if flip_any else 1.0 - (c1_verbosity + c1_reorder) / 2.0
    return {
        "c1_verbosity": c1_verbosity,
        "c1_reorder": c1_reorder,
        "flip_any": flip_any,
        "divergence": divergence,
    }


def _rank_key(result: CandidateResult) -> tuple:
    mean_c1 = result.mean_c1
    return (-result.divergence, mean_c1 if mean_c1 is not None else 1.0, result.issue_id)


def rank_complete(results: list[CandidateResult]) -> list[CandidateResult]:
    """Complete candidates, most divergent first (ties: lower mean C1, then issue id)."""
    return sorted((r for r in results if r.complete), key=_rank_key)


def ordered_for_output(results: list[CandidateResult]) -> list[CandidateResult]:
    """Divergence descending; incomplete candidates last (by issue id)."""
    incomplete = sorted((r for r in results if not r.complete), key=lambda r: r.issue_id)
    return rank_complete(results) + incomplete


def _search_constrained(
    pool: list[CandidateResult], n_top: int, n_stable: int, max_per_repo: int, min_repos: int
) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Lexicographically best (top, stable) index selection satisfying the repo constraints.

    `pool` is ranked most divergent first. The top group is enumerated in rank order, and for
    each top group the stable group in most-stable-first order, so the first hit keeps the
    highest-ranked unstable picks and, among those, the most stable controls.
    """
    n = len(pool)
    repos = [r.repo for r in pool]
    if len(set(repos)) < min_repos or n_top + n_stable < min_repos:
        return None

    steps = 0
    for top in itertools.combinations(range(n), n_top):
        top_counts = Counter(repos[i] for i in top)
        if top_counts and max(top_counts.values()) > max_per_repo:
            continue
        if len(top_counts) + n_stable < min_repos:
            continue
        taken = set(top)
        remaining = [i for i in range(n - 1, -1, -1) if i not in taken]  # most stable first
        for stable in itertools.combinations(remaining, n_stable):
            steps += 1
            if steps > SEARCH_STEP_LIMIT:
                return None
            counts = top_counts + Counter(repos[i] for i in stable)
            if max(counts.values()) <= max_per_repo and len(counts) >= min_repos:
                return top, stable
    return None


def recommend_selection(
    results: list[CandidateResult],
    n_top: int = N_TOP,
    n_stable: int = N_STABLE,
    max_per_repo: int = MAX_PER_REPO,
    min_repos: int = MIN_REPOS,
) -> Selection:
    """Top `n_top` by divergence + `n_stable` most stable, under the per-repo constraints."""
    pool = rank_complete(results)
    n = len(pool)
    notes: list[str] = []

    n_top_eff, n_stable_eff = n_top, n_stable
    if n < n_top + n_stable:
        notes.append(f"only {n} complete candidates - cannot fill {n_top}+{n_stable} slots")
        n_top_eff = min(n_top, n)
        n_stable_eff = min(n_stable, n - n_top_eff)

    naive_top = tuple(range(n_top_eff))
    naive_stable = tuple(range(n - 1, n - 1 - n_stable_eff, -1))

    found = _search_constrained(pool, n_top_eff, n_stable_eff, max_per_repo, min_repos)
    if found is None:
        notes.append(
            f"no selection satisfies (<= {max_per_repo} per repo, >= {min_repos} repos) - "
            "showing the plain top/bottom split instead"
        )
        top_idx, stable_idx = naive_top, naive_stable
    else:
        top_idx, stable_idx = found
        if (set(top_idx), set(stable_idx)) != (set(naive_top), set(naive_stable)):
            chosen = {pool[i].issue_id for i in top_idx + stable_idx}
            naive = {pool[i].issue_id for i in naive_top + naive_stable}
            notes.append(
                "repo constraints changed the plain top/bottom split: "
                f"dropped {sorted(naive - chosen)}, added {sorted(chosen - naive)}"
            )

    top = [pool[i] for i in top_idx]
    stable = [pool[i] for i in stable_idx]
    repo_counts = Counter(r.repo for r in top + stable)
    most_in_one_repo = max(repo_counts.values(), default=0)
    return Selection(
        top=top,
        stable=stable,
        max_per_repo=most_in_one_repo,
        n_repos=len(repo_counts),
        constraints_ok=most_in_one_repo <= max_per_repo and len(repo_counts) >= min_repos,
        notes=notes,
    )


def estimate_budget(candidates: list[Candidate], max_tokens: int = AGENT_MAX_TOKENS) -> Budget:
    """Worst-case spend if every call used all of max_tokens (inputs bounded by chars/2.5)."""

    def input_tokens(text: str) -> float:
        return len(text) / CHARS_PER_TOKEN_FLOOR + PROMPT_OVERHEAD_TOKENS

    transform = (
        sum(
            input_tokens(c.text) * HAIKU_PRICE[0] + HAIKU_MAX_TOKENS * HAIKU_PRICE[1]
            for c in candidates
        )
        / 1e6
    )
    # A variant can come back longer than its source, so allow 2x input on agent calls.
    per_run = [
        2 * input_tokens(c.text) * SONNET_PRICE[0] + max_tokens * SONNET_PRICE[1]
        for c in candidates
    ]
    run_max = max(per_run, default=0.0) / 1e6
    runs = len(VARIANT_LABELS) * sum(per_run) / 1e6
    return Budget(transform_worst_case=transform, run_worst_case_max=run_max, runs_worst_case=runs)


# ======================================================================================
# CSV / presentation
# ======================================================================================


def write_results_csv(results: list[CandidateResult], path: Path = RESULTS_PATH) -> None:
    def fmt(value: float | None) -> str:
        return "" if value is None else f"{value:.4f}"

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for r in ordered_for_output(results):
            writer.writerow(
                [
                    r.issue_id,
                    r.repo,
                    r.outcome_original,
                    r.outcome_verbosity,
                    r.outcome_reorder,
                    fmt(r.c1_verbosity),
                    fmt(r.c1_reorder),
                    fmt(r.divergence),
                ]
            )


def _outcome_code(outcome: str, *, no_diff: bool = False) -> str:
    code = _OUTCOME_CODES.get(outcome, "-" if outcome == "missing" else outcome[:1].upper())
    return code + ("!" if no_diff else "")


def _flags(r: CandidateResult) -> str:
    flags = []
    if r.line_shuffle:
        flags.append("T07:line-shuffle")
    if r.quality_warning:
        flags.append("QW")
    if r.json_fallback:
        flags.append("non-JSON")
    flags.extend(f"no-diff:{label}" for label in r.no_diff)
    flags.extend(f"trunc:{label}" for label in r.truncated)
    return " ".join(flags)


def print_results_table(
    console: Console, results: list[CandidateResult], selection: Selection
) -> None:
    top_ids = {r.issue_id for r in selection.top}
    stable_ids = {r.issue_id for r in selection.stable}
    n_complete = sum(1 for r in results if r.complete)

    table = Table(
        title=(
            "Stage 2 pre-screen: divergence ranking "
            f"({n_complete}/{len(results)} candidates scored)"
        ),
        header_style="bold",
    )
    table.add_column("#", justify="right")
    table.add_column("Issue", no_wrap=True)
    table.add_column("Repo")
    table.add_column("O/V/R", justify="center")
    table.add_column("C1 verb", justify="right")
    table.add_column("C1 reord", justify="right")
    table.add_column("Flip", justify="center")
    table.add_column("Divergence", justify="right")
    table.add_column("V len", justify="right")
    table.add_column("T07 kept", justify="right")
    table.add_column("Flags")
    table.add_column("Pick")

    def num(value: float | None, spec: str = ".3f") -> str:
        return "-" if value is None else format(value, spec)

    for rank, r in enumerate(ordered_for_output(results), start=1):
        if r.issue_id in top_ids:
            pick, style = ">> TOP", "bold green"
        elif r.issue_id in stable_ids:
            pick, style = ">> STABLE", "bold cyan"
        elif not r.complete:
            pick, style = "incomplete", "dim red"
        else:
            pick, style = "", None
        outcomes = "/".join(
            (
                _outcome_code(r.outcome_original, no_diff="original" in r.no_diff),
                _outcome_code(r.outcome_verbosity, no_diff="verbosity" in r.no_diff),
                _outcome_code(r.outcome_reorder, no_diff="reorder" in r.no_diff),
            )
        )
        flip = "-" if r.flip_any is None else ("yes" if r.flip_any else "no")
        table.add_row(
            str(rank),
            r.issue_id,
            r.repo.split("/")[-1],
            outcomes,
            num(r.c1_verbosity),
            num(r.c1_reorder),
            flip,
            num(r.divergence),
            num(r.verbosity_ratio, ".2f"),
            "-" if r.reorder_intact is None else f"{r.reorder_intact:.0%}",
            _flags(r),
            pick,
            style=style,
        )
    console.print(table)
    console.print(
        "[dim]O/V/R = outcome of original / verbosity_reduction / reordering "
        "(S success, F failure, N no_patch, T timeout, E error; "
        "'!' = reply without a unified diff). "
        "V len = reduced/original word count (target 0.5). T07 kept = share of original adjacent "
        "lines still adjacent after reordering; T07:line-shuffle = no blank-line paragraphs were "
        "found, so single lines were shuffled. QW = identifier-retention check failed. "
        "trunc:X = reply of variant X was cut off at max_tokens.[/dim]",
        highlight=False,
    )


def print_selection(console: Console, selection: Selection) -> None:
    lines = [f"[bold]Most unstable (top {len(selection.top)} by divergence)[/bold]"]
    for i, r in enumerate(selection.top, start=1):
        lines.append(f"  {i:>2}. {r.issue_id:<34} {r.repo:<28} divergence {r.divergence:.3f}")
    lines.append(f"[bold]Most stable (bottom {len(selection.stable)})[/bold]")
    for i, r in enumerate(selection.stable, start=len(selection.top) + 1):
        lines.append(f"  {i:>2}. {r.issue_id:<34} {r.repo:<28} divergence {r.divergence:.3f}")
    status = "[green]OK[/green]" if selection.constraints_ok else "[red]VIOLATED[/red]"
    lines.append(
        f"Constraints: at most {selection.max_per_repo} per repo (limit {MAX_PER_REPO}), "
        f"{selection.n_repos} repos represented (min {MIN_REPOS}) -> {status}"
    )
    for note in selection.notes:
        lines.append(f"[yellow]Note: {note}[/yellow]")
    lines.append("")
    lines.append("IDs: " + json.dumps(selection.ids))
    console.print(
        Panel(
            "\n".join(lines),
            title=f"RECOMMENDED PILOT SELECTION ({len(selection.ids)} issues)",
            subtitle="configs/icse_pilot.json was NOT written",
            border_style="green",
        ),
        highlight=False,
    )


# ======================================================================================
# Preconditions
# ======================================================================================


def load_candidates(path: Path = CANDIDATES_PATH) -> list[Candidate]:
    if not path.exists():
        raise SystemExit(f"{path} not found - run scripts/prescreen_stage1.py first")
    records = json.loads(path.read_text(encoding="utf-8"))
    candidates = [Candidate(r["id"], r["repo"], r["problem_statement"]) for r in records]
    if len({c.issue_id for c in candidates}) != len(candidates):
        raise SystemExit(f"{path} contains duplicate issue ids")
    return candidates


def check_api_key(console: Console) -> None:
    """Abort (exit 2) unless ANTHROPIC_API_KEY loads. Reports only where it came from."""
    env_value = os.environ.get("ANTHROPIC_API_KEY") or None
    dotenv_value = dotenv_values(PROJECT_ROOT / ".env").get("ANTHROPIC_API_KEY") or None
    key = get_anthropic_api_key()

    problem = None
    if not key:
        problem = "ANTHROPIC_API_KEY is not set (not in the environment, not in .env)"
    elif key.endswith("...") or len(key) < 20:
        problem = "ANTHROPIC_API_KEY looks like a placeholder (see .env.example)"
    elif not LLMBaselineAdapter().health_check():
        problem = "LLMBaselineAdapter.health_check() failed (is the anthropic package installed?)"
    if problem:
        console.print(f"[bold red]ABORT:[/bold red] {problem}.", highlight=False)
        raise SystemExit(2)

    if env_value and dotenv_value and env_value != dotenv_value:
        console.print(
            "[yellow]WARNING: ANTHROPIC_API_KEY in the process environment differs from .env "
            "and takes precedence.[/yellow]"
        )
        source = "process environment (overrides .env)"
    elif env_value and not dotenv_value:
        source = "process environment (not in .env)"
    else:
        source = ".env"
    key_format = "format OK" if key.startswith("sk-ant-") else "unexpected format"
    console.print(
        f"ANTHROPIC_API_KEY: loaded from {source} ({key_format}); adapter health_check OK",
        highlight=False,
    )


def print_plan(console: Console, candidates: list[Candidate], budget: Budget) -> None:
    n_runs = len(candidates) * len(VARIANT_LABELS)
    per_run_ok = budget.run_worst_case_max <= PER_RUN_CAP_USD
    total_ok = budget.total_worst_case <= TOTAL_LIMIT_USD
    console.print(
        f"Plan: {len(candidates)} candidates x {len(VARIANT_LABELS)} variants "
        f"({', '.join(VARIANT_LABELS)}) = {n_runs} real LLM Baseline runs "
        f"({LLMBaselineAdapter.DEFAULT_MODEL}, T=0.0, max_tokens {AGENT_MAX_TOKENS}), "
        f"{len(candidates)} verbosity_reduction generations (cached, Haiku), "
        f"{len(candidates)} reorderings (free).",
        highlight=False,
    )
    console.print(
        f"Cost guard: ${PER_RUN_CAP_USD:.2f}/run cap | {TIMEOUT_SECONDS}s/request timeout "
        f"(SDK retries x2) | ${TOTAL_LIMIT_USD:.2f} total | abort after "
        f"{CONSECUTIVE_ERROR_LIMIT} consecutive API errors",
        highlight=False,
    )
    console.print(
        "Worst-case bound (every call at max_tokens): "
        f"variants <= ${budget.transform_worst_case:.2f}, "
        f"runs <= ${budget.runs_worst_case:.2f} (<= ${budget.run_worst_case_max:.3f}/run), "
        f"total <= ${budget.total_worst_case:.2f} of ${TOTAL_LIMIT_USD:.2f}",
        highlight=False,
    )
    if not per_run_ok or not total_ok:
        per_run_verdict = "OK" if per_run_ok else "TOO HIGH"
        total_verdict = "OK" if total_ok else "TOO HIGH"
        console.print(
            "[bold red]ABORT:[/bold red] the worst-case bound exceeds the cost guard "
            f"(per-run {per_run_verdict}, total {total_verdict}).",
            highlight=False,
        )
        raise SystemExit(2)


# ======================================================================================
# Phase 1: seed issues + generate variants (cached)
# ======================================================================================


def seed_candidates(db: Session, candidates: list[Candidate]) -> dict[str, Issue]:
    """Insert the candidates as Issue rows (idempotent by SWE-bench instance id)."""
    issues: dict[str, Issue] = {}
    for c in candidates:
        issue = db.query(Issue).filter(Issue.external_id == c.issue_id).first()
        if issue is None:
            issue = Issue(
                external_id=c.issue_id,
                repo_name=c.repo,
                source="swebench_lite",
                issue_text=c.text,
                metadata_=json.dumps(
                    {"stage": "prescreen_stage2", "origin": "stage1_candidates.json"}
                ),
            )
            db.add(issue)
        elif issue.issue_text != c.text:
            raise RuntimeError(
                f"Issue {c.issue_id} already exists in the database with different text; "
                "refusing to overwrite an immutable issue record."
            )
        issues[c.issue_id] = issue
    db.commit()
    return issues


def _variant_row_count(db: Session, issue_db_id: str, name: str) -> int:
    return (
        db.query(TransformedIssue).filter_by(issue_id=issue_db_id, transformation_name=name).count()
    )


def estimate_haiku_cost(source_text: str, generated_text: str) -> float:
    """Rough spend of one verbosity_reduction call (the engine does not expose token usage)."""
    in_tokens = len(source_text) / 3.5 + 300
    out_tokens = len(generated_text) / 3.5 + 60
    return (in_tokens * HAIKU_PRICE[0] + out_tokens * HAIKU_PRICE[1]) / 1e6


def generate_variants(
    db: Session, issues: dict[str, Issue], console: Console
) -> tuple[float, Counter]:
    """Generate (or fetch from cache) both variants for every candidate.

    Returns (estimated Haiku spend in USD, Counter of 'generated'/'cached' per transformation).
    """
    cache = TransformationCache(db)
    spend = 0.0
    tally: Counter = Counter()
    total = len(issues)
    for i, (issue_id, issue) in enumerate(issues.items(), start=1):
        record = IssueRecord(issue_id=issue.id, repo_name=issue.repo_name, text=issue.issue_text)
        parts = []
        for name, params in TRANSFORMS:
            before = _variant_row_count(db, issue.id, name)
            result = cache.get_or_transform(transformation_registry.get(name)(), record, params)
            generated = _variant_row_count(db, issue.id, name) > before
            tally[(name, "generated" if generated else "cached")] += 1
            if generated and name == VERBOSITY:
                spend += estimate_haiku_cost(issue.issue_text, result.transformed_text)
            if name == VERBOSITY:
                ratio = len(result.transformed_text.split()) / max(len(issue.issue_text.split()), 1)
                parts.append(
                    f"{name} {'generated' if generated else 'cached'} ({ratio:.2f}x words)"
                )
            else:
                parts.append(f"{name} ok")
        db.commit()  # keep finished variants if a later call fails
        console.print(f"({i:>2}/{total}) {issue_id:<34} " + " | ".join(parts), highlight=False)
    return spend, tally


# ======================================================================================
# Phase 2: the experiment (real runs through ExperimentRunner)
# ======================================================================================


def build_config(issue_ids: list[str]) -> ExperimentConfig:
    n_runs = len(issue_ids) * len(VARIANT_LABELS)
    return ExperimentConfig(
        experiment_name=EXPERIMENT_NAME,
        description=(
            "Stage 2 empirical pre-screen (SPEC 18.3): "
            f"{len(issue_ids)} Stage 1 candidates x (original, verbosity_reduction, "
            f"reordering seed={SEED}) with the LLM Baseline in real mode = {n_runs} runs. "
            f"Cost guard: ${PER_RUN_CAP_USD:.2f}/run, {TIMEOUT_SECONDS}s timeout, "
            f"${TOTAL_LIMIT_USD:.2f} total."
        ),
        execution_mode="real",
        agents=[
            AgentConfig(
                name=LLMBaselineAdapter.name,
                version=LLMBaselineAdapter.version,
                params={
                    "model": LLMBaselineAdapter.DEFAULT_MODEL,
                    "temperature": 0.0,
                    "max_tokens": AGENT_MAX_TOKENS,
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "cost_cap_usd": PER_RUN_CAP_USD,
                    "api_key_env_var": "ANTHROPIC_API_KEY",
                },
            )
        ],
        issues=IssueConfig(source="swebench_lite", issue_ids=issue_ids),
        transformations=[TransformationConfig(name=n, params=p) for n, p in TRANSFORMS],
        runs_per_variant=1,
        cost_limit_usd=TOTAL_LIMIT_USD,
        output_dir="./scripts/output",
    )


class _ProgressRunner(ExperimentRunner):
    """ExperimentRunner that prints one line per finished run and stops on repeated API errors.

    Overrides the private per-cell hook only to observe results; persistence, the cost guard and
    the adapter calls are the unmodified runner's.
    """

    def __init__(self, config: ExperimentConfig, db: Session, console: Console, total: int) -> None:
        super().__init__(config, db)
        self._console = console
        self._total = total
        self._done = 0
        self._consecutive_errors = 0

    def _execute_cell(self, experiment, adapter, agent_cfg, issue, ti, run_index, **kwargs) -> None:
        run = None
        try:
            super()._execute_cell(experiment, adapter, agent_cfg, issue, ti, run_index, **kwargs)
        finally:
            run = (
                self._db.query(Run)
                .filter_by(experiment_id=experiment.id, transformed_issue_id=ti.id)
                .order_by(Run.created_at.desc())
                .first()
            )
            self._report(issue, ti, run)

        if run is not None and run.status == "error":
            self._consecutive_errors += 1
            if self._consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                raise RuntimeError(
                    f"{CONSECUTIVE_ERROR_LIMIT} consecutive API errors "
                    f"(last: {run.error_message}); aborting - "
                    "check the API key, credit balance and network."
                )
        else:
            self._consecutive_errors = 0

    def _report(self, issue: Issue, ti: TransformedIssue, run: Run | None) -> None:
        self._done += 1
        label = "original" if ti.is_original else ti.transformation_name
        if run is None:
            line, style = (
                f"({self._done:>2}/{self._total}) {issue.external_id:<34} "
                f"{label:<20} (no run recorded)",
                "red",
            )
        else:
            line = (
                f"({self._done:>2}/{self._total}) {issue.external_id:<34} {label:<20} "
                f"{run.status:<13} ${run.cost_usd or 0.0:.4f} {run.runtime_seconds or 0.0:5.1f}s  "
                f"total ${self._cost_guard.running_total:.4f}"
            )
            style = None if run.status in GENUINE_OUTCOMES else "red"
        self._console.print(line, style=style, markup=False, highlight=False)


def latest_experiment(db: Session, name: str = EXPERIMENT_NAME) -> Experiment | None:
    return (
        db.query(Experiment)
        .filter(Experiment.name == name)
        .order_by(Experiment.created_at.desc())
        .first()
    )


# ======================================================================================
# Phase 3: analysis (pure function of the database)
# ======================================================================================


def _was_truncated(run: Run) -> bool:
    """True if the model stopped because it hit max_tokens (recorded by the adapter)."""
    try:
        metadata = json.loads(run.metadata_) if run.metadata_ else {}
    except ValueError:
        return False
    return isinstance(metadata, dict) and metadata.get("stop_reason") == "max_tokens"


def analyze(
    db: Session, experiment: Experiment, candidates: list[Candidate]
) -> list[CandidateResult]:
    rows = (
        db.query(Run, TransformedIssue, Issue)
        .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
        .join(Issue, TransformedIssue.issue_id == Issue.id)
        .filter(Run.experiment_id == experiment.id)
        .order_by(Run.run_index, Run.created_at)
        .all()
    )
    slots: dict[str, dict[str, tuple[Run, TransformedIssue, Issue]]] = defaultdict(dict)
    for run, ti, issue in rows:
        label = "original" if ti.is_original else ti.transformation_name
        slots[issue.external_id].setdefault(label, (run, ti, issue))  # lowest run_index wins

    results: list[CandidateResult] = []
    for c in candidates:
        cell = slots.get(c.issue_id, {})

        def view(label: str) -> RunView | None:
            if label not in cell:
                return None
            run = cell[label][0]
            return RunView(run.status, run.patch, _was_truncated(run))

        original, verbosity, reorder = (view(label) for label in VARIANT_LABELS)
        result = CandidateResult(
            issue_id=c.issue_id,
            repo=c.repo,
            outcome_original=original.status if original else "missing",
            outcome_verbosity=verbosity.status if verbosity else "missing",
            outcome_reorder=reorder.status if reorder else "missing",
        )
        for key, value in score_candidate(original, verbosity, reorder).items():
            setattr(result, key, value)

        if VERBOSITY in cell:
            ti = cell[VERBOSITY][1]
            result.verbosity_ratio = len(ti.transformed_text.split()) / max(len(c.text.split()), 1)
            result.quality_warning = bool(ti.quality_warning)
            notes = ti.transformation_notes or ""
            result.json_fallback = notes.startswith("LLM returned non-JSON") or (
                '"transformed_text"' in ti.transformed_text[:200]
            )
        if REORDERING in cell:
            reordering_ti = cell[REORDERING][1]
            result.reorder_intact = adjacency_preserved(c.text, reordering_ti.transformed_text)
            # The transformation records how it split the text; fall back to the adjacency
            # measure if that wording ever changes.
            result.line_shuffle = (
                "single-newline" in (reordering_ti.transformation_notes or "")
                or result.reorder_intact < LINE_SHUFFLE_BELOW
            )

        named_runs = (("original", original), ("verbosity", verbosity), ("reorder", reorder))
        result.no_diff = tuple(
            name
            for name, v in named_runs
            if v is not None and v.status == "success" and not has_unified_diff(v.patch)
        )
        result.truncated = tuple(name for name, v in named_runs if v is not None and v.truncated)
        results.append(result)
    return results


# ======================================================================================
# Orchestration
# ======================================================================================


def run_experiment(db: Session, issues: dict[str, Issue], console: Console) -> Experiment:
    config = build_config(list(issues))
    runner = _ProgressRunner(config, db, console, total=len(issues) * len(VARIANT_LABELS))
    return runner.run()


def print_spend(
    console: Console, db: Session, experiment: Experiment, transform_spend: float | None
) -> None:
    runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
    agent_spend = sum(r.cost_usd or 0.0 for r in runs)
    statuses = Counter(r.status for r in runs)
    line = (
        f"Experiment {experiment.id} status={experiment.status}: {len(runs)} runs "
        f"({', '.join(f'{k}={v}' for k, v in sorted(statuses.items()))}); "
        f"agent spend ${agent_spend:.4f} (from API usage)"
    )
    if transform_spend is not None:
        line += (
            f"; variant generation ~${transform_spend:.4f} "
            "(estimate - token usage is not exposed); "
            f"script total ~${agent_spend + transform_spend:.4f} of ${TOTAL_LIMIT_USD:.2f}"
        )
    console.print(line, highlight=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 2 empirical pre-screen over the Stage 1 candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "check the API key, print the plan and worst-case budget, then exit "
            "(no API calls, no DB writes)"
        ),
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help=f"execute the runs again as a new '{EXPERIMENT_NAME}' experiment even if one exists",
    )
    return parser.parse_args(argv)


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _inject_truststore() -> None:
    """Trust the OS certificate store (needed behind a TLS-intercepting proxy; see stage 1)."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_streams()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    console = Console(width=None if sys.stdout.isatty() else 170)
    _inject_truststore()

    candidates = load_candidates(CANDIDATES_PATH)
    budget = estimate_budget(candidates)

    engine = build_engine()
    create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        existing = latest_experiment(db)
        will_execute = args.rerun or existing is None

        if args.dry_run:
            check_api_key(console)
            print_plan(console, candidates, budget)
            if will_execute:
                console.print("Dry run: a normal run would execute the experiment now.")
            else:
                console.print(
                    f"Dry run: experiment '{EXPERIMENT_NAME}' already exists ({existing.id}, "
                    f"status={existing.status}); a normal run would only re-analyse it."
                )
            return 0

        transform_spend: float | None = None
        if will_execute:
            console.rule("Preflight")
            check_api_key(console)
            print_plan(console, candidates, budget)

            console.rule("Phase 1: issues and variants (cached)")
            issues = seed_candidates(db, candidates)
            try:
                transform_spend, tally = generate_variants(db, issues, console)
                summary = "; ".join(
                    f"{name}: {tally[(name, 'generated')]} generated, "
                    f"{tally[(name, 'cached')]} cached"
                    for name, _ in TRANSFORMS
                )
                console.print(f"Variants: {summary}", highlight=False)
            except Exception as exc:  # noqa: BLE001 - report, keep finished variants, no agent spend
                db.rollback()
                console.print(
                    f"[bold red]Variant generation failed:[/bold red] {escape(repr(exc))}\n"
                    "No agent runs were started (no agent cost). Finished variants are cached; "
                    "re-run to resume.",
                    highlight=False,
                )
                return 1

            console.rule("Phase 2: LLM Baseline runs (real mode)")
            try:
                experiment = run_experiment(db, issues, console)
            except Exception as exc:  # noqa: BLE001
                console.print(
                    f"[bold red]Experiment aborted:[/bold red] {escape(str(exc))}", highlight=False
                )
                console.print(
                    "Completed runs are persisted; see 'stableagent' / Past Experiments."
                )
                return 1
        else:
            console.print(
                f"Experiment '{EXPERIMENT_NAME}' already exists ({existing.id}, status="
                f"{existing.status}); analysing it without any API calls. "
                "Pass --rerun to execute again."
            )
            experiment = existing

        console.rule("Phase 3: analysis")
        print_spend(console, db, experiment, transform_spend)
        if experiment.status != "completed":
            console.print(
                f"[yellow]WARNING: experiment status is '{experiment.status}' - "
                "results may be partial.[/yellow]"
            )
        results = analyze(db, experiment, candidates)

    write_results_csv(results, RESULTS_PATH)
    selection = recommend_selection(results)
    print_results_table(console, results, selection)
    print_selection(console, selection)
    incomplete = [r.issue_id for r in results if not r.complete]
    if incomplete:
        console.print(
            f"[yellow]{len(incomplete)} candidate(s) incomplete (excluded from selection): "
            f"{', '.join(incomplete)}[/yellow]",
            highlight=False,
        )
    console.print(f"Wrote {RESULTS_PATH}", highlight=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
