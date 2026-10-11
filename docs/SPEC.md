# StableAgent: Behavioral Stability Evaluation of Autonomous SE Agents
## Full Project Specification

**Version:** 2.11
**Target venue:** ICSE 2027 Tool Demonstration
**Last updated:** October 2026
**Changelog:**
- v2.11 (Oct 2026) — The tool is named StableAgent (package `stableagent`, CLI `stableagent`). This specification now states only what the code implements: six transformations (the other six of the catalogue are specified, not implemented), metrics A, F, G, the flip rates, the localization outcome, file overlap and changed-line similarity with their statistics (the other metric classes are interfaces), no test runner and no sandbox. Sections 5, 7, 18 and 19 describe the pilot as run: 20 issues selected by a structural rule, two models. The planning sections (example results, paper and video outlines, milestones, risks, follow-up study design) are removed.
- v2.10 (Oct 2026) — A second model for the ICSE pilot. The LLM Baseline takes a `provider` (`anthropic`, the default and unchanged, or `openai`), a `model` and an `api_key_env_var` (default `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`); the OpenAI path sends the same prompt text, temperature 0, 4096 tokens and 120 s, forces the `submit_patch` function and gives the same run record and statuses for the same reply (section 10.2). Run costs come from the model table `stableagent/config/pricing.py` (Claude Sonnet 4.6 $3/$15, Claude Haiku 4.5 $1/$5, GPT-4o $2.50/$10 per million tokens); a model without a price, a model of the other provider or a missing key stop a real run before anything is recorded. `reuse_variants_from` (section 12.1) runs an experiment on exactly the variants another experiment ran on, and fails before anything is recorded if one would have to be generated; `configs/icse_pilot_model2.json` (GPT-4o on the pilot's variants, $4 cap) uses it. `--estimate` counts the agent runs without the skipped variants and prices them from the model table (148 runs, ~$1.06 for GPT-4o; $1.42 for the pilot, its real cost). Agent names must be unique within an experiment. Every RQ1/RQ2 metric is computed per agent across experiments (`metrics/comparison.py`, section 13); `scripts/analyze_patch_similarity.py --experiments <ids>` writes the RQ2 figure `fig_results.pdf` (one IEEE column, one marker per model) and the combined table; the dashboard shows both on Past Experiments (section 16) and lists one LLM Baseline per model. A model other than the pilot's records and replays its MockReplay fixtures in a subdirectory of its own (`gpt-4o/`, section 10.3). `docs/paper/adapter_listing.py`: a 12-line excerpt of the adapter interface, checked against the code. A reply cut at the token limit without a usable diff gets the status `truncated` and is excluded from the outcome metrics like a timeout (section 13); runs recorded before as `no_patch` with stop reason `max_tokens` are scored the same way. The GPT-4o experiment (`9d27f3ef`, 148 agent runs, $0.72) is in the shipped pilot database with the Claude one; `scripts/build_pilot_db.py` exports each into `data/pilot/exports/<model>/`, and its 140 fixtures are recorded in `mock_responses/gpt-4o/`.
- v2.9 (Oct 2026) — Changed-line similarity (section 13): every non-original run's patch is compared with its issue's original run on the changed lines only (`+`/`-` lines without the `+++`/`---` headers, joined with newlines, `difflib.SequenceMatcher` over their characters); control runs get the same value, the noise floor. Per transformation: the mean, the mean paired difference to the control, 95% bootstrap CIs (5000 resamples, seed 42) and an exploratory Wilcoxon signed-rank p-value. `stableagent recompute-metrics` adds it to stored experiments. Dashboard (section 16): the RQ2 tab opens with the similarity table and a dot plot (one row per transformation and a grey "repeat of original" row, mean and CI, faint per-issue dots, dashed line at the control mean), above TS and the flip rate; the Patches tab becomes **Issue Detail**, both patches side by side with the differences highlighted, opening on psf__requests-2317 / Reordering. Fixtures (section 10.3): `record-fixtures` writes MockReplay's file names, records the control runs and the variant each run used, and skipped cells; mock mode restores a recorded variant instead of a placeholder, so the ICSE pilot (experiment bc6f1372, 20 issues, 160 runs) replays with identical runs and metrics, on the existing database or a fresh one.
- v2.8 (Oct 2026) — Retention check without markdown false positives (section 11.5): before technical tokens are taken, the prose loses HTML comments, formatting HTML tags (`<details>`, `</summary>`, ...), unanswered issue-form fields (`_No response_`), the standard section headings of issue templates, and emphasis markers (`_text_`, `*text*`, `**text**`), and its backslash escapes are undone (`\_\_repr\_\_` → `__repr__`); a closing tag is no longer read as a path and a lone `_` is not a token. Across the 300 SWE-bench Lite issues this drops 66 tokens, all formatting noise, and adds none. No `transform_version` bump: `scripts/requeue_retention_false_positives.py` removed the cache key of the 5 pilot variants excluded only for such tokens, so they are regenerated; every variant that passed stays cached.
- v2.7 (Oct 2026) — Code masking for every LLM-backed transformation (section 11.7): fenced and indented code blocks, `>>>` doctest blocks, tracebacks and inline code spans are replaced by numbered placeholders (`[[CODE_1]]`, ...) before the Haiku call and restored byte for byte after it, once every placeholder is checked to appear exactly once; only then is the retention check run. Two attempts at most: a failed first attempt is retried once with feedback naming the lost placeholders (or the missing tokens), then the variant is excluded (`placeholder_lost` when its code could not be restored; section 11.5). T01/T03/T11 → version 4, T10 → 5; variants of the previous version that passed the quality check stay cached (section 11.4). Each variant records its `generation_cost_usd`. The agent never runs on an excluded or no-op variant: the run is recorded as `skipped_variant`, at no cost (sections 12.1, 13). `run --generate-only` generates and quality-checks every variant, prints the status of each one with its generation cost, and stops before any agent call (section 12.1).
- v2.6 (Oct 2026) — Retention check protects technical content only: code verbatim (fenced blocks, `>>>` lines, indented code, backtick spans) and technical tokens (identifiers with `_ . /` or digits, CamelCase, paths, `*Error`/`*Exception`); missing items stored as each variant's `exclusion_reason`, shown in the Transformed Issues tab and every export (sections 11.5, 11.6). T11 rewrites only offending sentences and returns neutral text unchanged (a no-op). LLM-backed versions bumped (T01/T03/T11 → 3, T10 → 4). The LLM Baseline answers with a forced `submit_patch` tool call (`max_tokens` 4096; the text extractor is a fallback; section 10.2). `run --originals-only` / `originals_only` (section 12.1). Symmetric flip rate reported next to TS (section 13).
- v2.5 (Oct 2026) — Variant provenance and no-op variants (section 11.6): every variant records its generator (model id, `deterministic`, `placeholder`), transform_version, mode and a no-op flag, shown in the Transformed Issues tab and every export; the cache key includes the generator; placeholders only in mock/dry-run, invalidated on upgrade and once a real variant exists; real mode raises a clear error instead (sections 11.4, 12.2). No-op variants are excluded from SC/TS and counted per transformation (section 13). T10 uses only information from the original ("Not specified" sections, no invented versions; version 3). `file_overlap_jaccard` is exported next to the outcome (section 17). The dashboard's LLM Baseline path now runs the CLI's ExperimentRunner + LLMBaselineAdapter (section 16); custom issues are ad-hoc `custom_adhoc` records; hand-written sample issues removed; `scripts/seed_issues_from_stage1.py`.
- v2.4 (Oct 2026) — Dashboard issue picker (section 16): the 300 SWE-bench Lite test issues are bundled in `data/swebench_lite_issues.json` and imported on demand, offline and idempotently; per-issue "✓ replayable" / "real mode only" badges for the enabled transformations, repository / keyword / replayable-only filters and a loaded/replayable counter; a Run guard that explains every block (MockReplay without fixtures, missing API key, estimated cost over the limit); a real-mode cost preview from the measured mean cost per run; the API key stays in session state. Mock and dry-run modes never generate LLM-backed variants (section 12.2). `load-swebench` reads the bundle by default.
- v2.3 (Oct 2026) — Pre-pilot fixes: run outcome is "localization success" (valid diff + gold-patch files modified; gold patch hidden from agents), with timeouts/cost-capped/errored runs and quality-warning variants excluded and counted (section 13); LLM Baseline sends the repo name, demands one fenced diff, extracts the final patch, `no_patch` status, 8192 tokens / 120 s (sections 10.2, 12.3, 12.4); retry-then-exclude for LLM-backed transformations, CRLF/fence-aware reordering, versioned transformation cache (section 11).
- v2.2 — ICSE: 6 transformations (added T07 Reordering, T11 Neutralize Emotional), 70 pilot runs, GUI-first workflow (issue selection from SWE-bench sublist or custom text, transformation checklist, results in tabs). Follow-up study: full cost-reduced empirical design replaces Appendix C (calibration phase, primary/secondary metric hierarchy, revised statistics, conservative claims). Added companion file docs/CHECKPOINTS.md.
- v2.0 — Minimal ICSE configuration: 10 issues, 1 real agent (LLM Baseline) + 1 mock/replay agent, 2 RQs, 3 metrics

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Motivation and Research Gap](#2-motivation-and-research-gap)
3. [Target Users](#3-target-users)
4. [Core Contribution](#4-core-contribution)
5. [ICSE Demo Scope and Constraints](#5-icse-demo-scope-and-constraints)
6. [End-to-End User Workflow](#6-end-to-end-user-workflow)
7. [Example Demo Scenario](#7-example-demo-scenario)
8. [Full Architecture](#8-full-architecture)
9. [Module Decomposition](#9-module-decomposition)
10. [Agent Adapter Design](#10-agent-adapter-design)
11. [Transformation Engine Design](#11-transformation-engine-design)
12. [Execution Engine Design](#12-execution-engine-design)
13. [Metrics Engine Design](#13-metrics-engine-design)
14. [Data Model](#14-data-model)
15. [Database Schema](#15-database-schema)
16. [Dashboard Pages and Visualizations](#16-dashboard-pages-and-visualizations)
17. [Exported Artifacts and Reports](#17-exported-artifacts-and-reports)
18. [Validation Plan](#18-validation-plan)
19. [Research Questions](#19-research-questions)
- [Appendix A: Glossary](#appendix-a-glossary)
- [Appendix B: Configuration Schema (JSON)](#appendix-b-configuration-schema-json)

---

## 1. Problem Statement

Autonomous software engineering (SE) agents — systems that receive a natural-language issue description and autonomously produce a patch — are increasingly evaluated on benchmark datasets such as SWE-bench. Current evaluations measure whether an agent resolves a given issue, but they implicitly assume that agent behavior is stable with respect to the surface form of the issue description. This assumption has not been systematically validated.

In practice, the same software defect or feature request may be reported in multiple ways: as a terse one-liner, as a verbose structured bug report, with or without reproduction steps, with formal or colloquial language, and with varying degrees of completeness. If an autonomous SE agent resolves an issue when described in one form but fails when the same issue is described differently — despite identical semantic intent — then benchmark scores misrepresent the agent's true capability and reliability.

**StableAgent** addresses this gap by providing a systematic framework and tool for evaluating the *behavioral stability* of autonomous SE agents under semantically equivalent issue transformations. The tool applies a metamorphic testing philosophy to SE agent evaluation: if two inputs are semantically equivalent, a reliable agent should produce behaviorally equivalent outputs.

---

## 2. Motivation and Research Gap

### 2.1 The Promise and Limits of Current Benchmarks

SWE-bench and its variants have become the de facto standard for evaluating autonomous SE agents. These benchmarks provide curated issues from real GitHub repositories, along with gold-standard test suites that verify whether a proposed patch is correct. State-of-the-art agents now resolve between 20% and 50% of SWE-bench Lite issues.

However, SWE-bench evaluates each issue in exactly one form — the original GitHub issue text. This introduces a confound: benchmark performance reflects both the agent's software engineering capability and its sensitivity to the particular phrasing of the issue. An agent that scores 40% on SWE-bench may score substantially higher or lower on semantically equivalent reformulations of the same issues. This confound is currently invisible to researchers and practitioners.

### 2.2 Why Surface Form Sensitivity Matters

Surface form sensitivity in autonomous SE agents has direct practical consequences:

- **Deployment risk:** In production, issue descriptions come from diverse users with varying writing styles. An agent that is brittle to phrasing variation will produce inconsistent results in real-world use.
- **Benchmark validity:** If agent rankings on SWE-bench can be reversed by minor reformulations of the issue text, then the rankings do not faithfully measure relative capability.
- **LLM fragility inheritance:** Autonomous SE agents are built on large language models (LLMs), which are known to exhibit sensitivity to prompt phrasing. Agents inherit this fragility unless explicitly mitigated.
- **Fairness in empirical comparisons:** Comparative studies of SE agents that use a single issue phrasing may draw incorrect conclusions about relative performance.

### 2.3 Metamorphic Testing as a Foundation

Metamorphic testing (MT) is an established technique for testing software systems whose correct output is difficult to verify directly. MT defines *metamorphic relations* — properties that must hold between the outputs of related inputs — and checks whether a system satisfies those relations. For autonomous SE agents, the core metamorphic relation is: if two issue descriptions are semantically equivalent, the agent's repair behavior should be equivalent. StableAgent operationalizes this relation as a suite of issue transformations and a set of behavioral equivalence metrics.

### 2.4 Research Gap Summary

No existing tool or benchmark:
- systematically applies semantics-preserving transformations to SE issue descriptions,
- measures the consistency of agent behavior across those transformations,
- provides interpretable stability metrics at the transformation, agent, and issue level,
- supports multiple agents through a common adapter interface, or
- enables reproducible empirical studies of agent robustness.

StableAgent fills this gap.

---

## 3. Target Users

StableAgent is designed for three primary user groups.

**SE researchers** who evaluate autonomous SE agents and wish to study robustness properties beyond raw pass rates. These users will run experiments over SWE-bench issues or custom issue sets, and use the exported results in empirical studies.

**Practitioners and tool developers** who build or deploy autonomous SE agents and need assurance that their agent behaves reliably across realistic variation in issue descriptions. The mock/replay mode lets them validate agent behavior without API cost.

**Benchmark designers** who wish to construct more robust evaluation protocols by including surface-form variation as a first-class experimental variable.

---

## 4. Core Contribution

StableAgent makes the following contributions:

1. **A formal framework** for defining and measuring behavioral stability of autonomous SE agents under semantically equivalent issue transformations.
2. **A transformation engine** with six semantics-preserving issue transformations (a catalogue of twelve is specified in section 11.2), with code masking, quality checks and a variant cache.
3. **A pluggable agent adapter interface** with two implementations: an LLM Baseline agent (Anthropic or OpenAI models) and a MockReplay agent that replays recorded runs at no cost.
4. **A metrics suite**: Success Consistency, Stability Score and Transformation Sensitivity with the flip rates, a localization outcome, file overlap, and changed-line similarity with bootstrap CIs and Wilcoxon tests; further metrics of section 13 are specified as interfaces.
5. **An interactive dashboard** for visualizing experiment results at the issue, agent, and transformation level.
6. **A reproducible experiment format** enabling other researchers to replicate and extend studies.

---

## 5. ICSE Demo Scope and Constraints

The ICSE 2027 demo version is intentionally minimal. The goal is to demonstrate that the framework works, that behavioral instability is observable in practice, and that the tool provides useful diagnostic output. A large-scale empirical study is deferred to a follow-up study.

### 5.1 Agent Configuration

| Agent | Type | Cost/run (pilot) | Used for |
|-------|------|----------|----------|
| LLM Baseline (Claude Sonnet 4.6) | Real: one API call per issue variant | ~$0.010 | Pilot experiment 1 |
| LLM Baseline (GPT-4o) | Real: one API call per issue variant, same prompt | ~$0.005 | Pilot experiment 2, on the same variants |
| MockReplay | Replays recorded runs | $0.00 | Replay of both experiments, demo, tests |

The LLM Baseline is deliberately simple (no execution loop, no repository access), which keeps the pilot cheap and needs no sandbox; agentic systems plug into the same adapter interface (section 10).

### 5.2 Issue Configuration

| Parameter | Value |
|-----------|-------|
| Issues | 20 |
| Source | SWE-bench Lite test split (Python), problem statements verbatim |
| Selection | A structural rule that uses no agent outcome (`scripts/localizability.py`, `scripts/select_pilot_issues.py`): issues whose gold patch is localizable from the text, spread over repositories |
| Ground truth | The gold patch, hidden from the agent and used only for the localization outcome (section 13) |

### 5.3 Transformation Configuration

Six transformations are activated for the ICSE pilot, spanning semantic, length, noise, ordering, structural, and register dimensions of surface-form variation. The other six transformations of the catalogue (section 11.2) are specified but not implemented.

| ID | Name | Type | Why this one |
|----|------|------|--------------|
| T01 | Paraphrase | LLM-backed | Most natural transformation; baseline for semantic equivalence |
| T03 | Verbosity reduction | LLM-backed | Tests reliance on context: the same report in about half the words |
| T07 | Reordering | Deterministic | Free to generate; tests sensitivity to information order (fixed seed = 42 for reproducibility) |
| T08 | Typo/noise injection | Deterministic | Free to generate; shows robustness to noisy real-world input |
| T10 | Paragraph → structured bug report | LLM-backed | Represents the realistic case of a user reformatting an issue |
| T11 | Neutralize emotional language | LLM-backed | Tests register sensitivity; real users write issues with frustration and informal tone |

### 5.4 Research Questions (ICSE)

Only two RQs are addressed in the ICSE paper.

**RQ1 — Stability:** To what extent does an LLM-based SE agent exhibit consistent behavior across semantically equivalent reformulations of the same issue?

**RQ2 — Sensitivity:** Which transformation categories cause the largest behavioral change?

These two RQs are sufficient for a tool paper. They produce concrete, interpretable results and motivate the need for the tool without overclaiming.

### 5.5 Metrics (ICSE)

Three outcome metrics are reported, with the changed-line similarity of the patches (section 13).

| Metric | Symbol | Answers |
|--------|--------|---------|
| Success Consistency | A / SC | RQ1 — does the agent succeed or fail consistently? |
| Stability Score | F / SS | RQ1 — aggregate stability across all variants |
| Transformation Sensitivity | G / TS | RQ2 — which transformation is most disruptive? |


### 5.6 Pilot Cost

| Component | Runs | Observed cost (October 2026) |
|-----------|------|------|
| Claude Sonnet 4.6: 20 issues × (original + 6 variants + 1 repeat) | 148 agent runs (12 skipped variants) | $1.42 |
| GPT-4o on the same variants | 148 agent runs | $0.72 |
| Variant generation with Claude Haiku 4.5 (cached, shared by both) | 80 LLM-backed variants | ~$0.17 |

Infrastructure: Python 3.11 and the API keys of the providers used; no sandbox, no test execution.

### 5.7 What Is Implemented vs. What Is Piloted

| Component | Implemented | Used in the ICSE pilot |
|-----------|-------------|------------------------|
| Transformations | 6 of the 12 specified | 6 |
| Metrics | A, F, G, flip rates, localization outcome, file overlap, changed-line similarity and statistics; B, C1 summary, D, E, H, I as interfaces | A, F, G, flip rates, changed-line similarity |
| Agent adapters | LLM Baseline (Anthropic, OpenAI) and MockReplay; stubs for OpenHands, SWE-agent, Aider, AutoCodeRover | LLM Baseline (2 models), MockReplay |
| Test execution, sandbox | Not implemented | — |
| Dashboard | 2 pages: StableAgent and Past Experiments | Both |

---

## 6. End-to-End User Workflow

### Step 1: Issue Selection

The user selects one or more software issues via the dashboard or CLI. Sources:
- SWE-bench Lite (bundled dataset, 300 issues)
- Manual issue entry (free-form text, dashboard)

Each issue record stores: repository name, issue ID, issue text, reproduction steps (optional), expected behavior (optional), associated test names (optional).

### Step 2: Agent Selection

The user selects one or more agents from the registered adapter pool. Each agent displays its name, version, execution mode (real/mock), and estimated cost per run.

### Step 3: Transformation Selection

The user selects which transformations to apply and may preview any transformation on the selected issue before committing. Transformed texts are cached — generating them once costs ~$0.008 each and they are reused across all subsequent runs.

### Step 4: Experiment Configuration

The user defines:
- Number of repeated runs per variant (default: 1)
- Execution mode: mock, dry-run, or real
- Per-run cost cap and timeout
- Total experiment cost limit
- Output directory

The configuration is saved as a JSON file for full reproducibility.

### Step 5: Experiment Execution

For each (agent × issue × transformation × run) cell:
1. Transformation engine produces the transformed issue text (or returns cached version).
2. Agent adapter receives the transformed issue and executes.
3. Output (patch, explanation, status) is collected.
4. All results, logs, and costs are persisted to the database.

Progress is shown in real time on the dashboard.

### Step 6: Metrics Computation

After execution, the metrics engine computes all configured metrics. Results are stored in the database and surfaced on the dashboard.

### Step 7: Visualization and Export

Dashboard shows results across all pages. User exports CSV, JSON, or a human-readable Markdown report.

---

## 7. Example Demo Scenario

A 3–5 minute walkthrough in replay mode (no API key):

1. **Issue.** Select a pilot issue (e.g. `psf__requests-2317`) in section A; its text is shown below the picker.
2. **Agent.** Section B lists MockReplay and one LLM Baseline per model, with the model id and the expected cost per run. Keep MockReplay.
3. **Transformations.** Tick the six transformations in section C and click *Run Experiment*: the recorded runs are replayed in seconds.
4. **RQ1.** The RQ1 tab shows, per transformation, the outcome (localization success) and whether it matches the original's.
5. **RQ2.** The RQ2 tab shows the changed-line similarity of each variant's patch to the original's, against the repeat of the unchanged original (the noise floor), with CIs and exploratory tests.
6. **Patches.** The Issue Detail tab shows the original's patch and a variant's patch side by side, the differences highlighted.
7. **Two models.** *Past Experiments → Compare models* shows both pilot experiments in one figure and table.
8. **Export.** CSV, JSON and a Markdown report.

---

## 8. Full Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Interface Layer                        │
│          Dashboard (Streamlit)   CLI (Typer)             │
├──────────────────────────────────────────────────────────┤
│                  Orchestration Layer                      │
│               Experiment Runner / Scheduler               │
├────────────────┬───────────────┬─────────────────────────┤
│ Transformation │ Execution     │ Metrics                 │
│ Engine         │ Engine        │ Engine                  │
├────────────────┴──────┬────────┴─────────────────────────┤
│             Agent Adapter Layer                           │
│   LLM Baseline  |  MockReplay  |  [OpenHands stub]       │
│   [SWE-agent stub] | [Aider stub] | [AutoCodeRover stub] │
├───────────────────────┴──────────────────────────────────┤
│                      Data Layer                           │
│          SQLite (SQLAlchemy ORM)  +  File store           │
└──────────────────────────────────────────────────────────┘
```

### Key Design Principles

- **Adapter pattern** for agents: new agents are added without modifying core logic. Stubs for OpenHands, SWE-agent, Aider, and AutoCodeRover are present in code but not activated for the ICSE pilot.
- **Plugin pattern** for transformations: the six implemented transformations register themselves; a config selects the ones an experiment applies.
- **Immutable experiment records:** once a run is persisted its inputs and outputs are never overwritten. Re-runs create new records.
- **Mode isolation:** mock, dry-run, and real modes are enforced at the adapter level.
- **Transformation caching:** LLM-backed transformation outputs are cached by `(issue_id, transformation_name, params_hash)` and reused across all runs without additional API cost.
- **MockReplay isolation:** the MockReplay agent reads from a fixture directory; it never calls any external API, making it safe for CI and live demos.

---

## 9. Module Decomposition

```
stableagent/
├── config/
│   ├── settings.py              # Settings (env vars, .env), API keys as SecretStr
│   ├── pricing.py               # Model table: provider, display name, prices
│   └── experiment_schema.py     # Pydantic schema of the experiment JSON
├── data/
│   ├── models.py                # SQLAlchemy ORM models
│   ├── database.py              # Engine, sessions, seeding from the shipped pilot database
│   ├── migrations.py            # In-place upgrades of older databases
│   └── loaders/swebench.py      # SWE-bench Lite loader (gold patch kept as hidden ground truth)
├── transformations/
│   ├── base.py                  # AbstractTransformation, retention check, markdown normalization
│   ├── registry.py              # Registration and lookup
│   ├── cache.py                 # Variant cache, provenance, retry-then-exclude
│   ├── masking.py               # Code masking for LLM-backed transformations
│   ├── deterministic/
│   │   ├── noise.py             # T08 typo injection
│   │   └── reordering.py        # T07 reordering
│   └── llm_backed/
│       ├── base.py, _api.py     # Shared LLM call, masking and retry
│       ├── paraphrase.py        # T01
│       ├── verbosity.py         # T03
│       ├── structure.py         # T10
│       └── neutralize.py        # T11
├── agents/
│   ├── base.py                  # AbstractAgentAdapter, AgentInput, AgentOutput
│   ├── registry.py              # Agent registration
│   ├── llm_baseline.py          # LLM Baseline (Anthropic or OpenAI)
│   ├── mock_replay.py           # MockReplay (recorded runs)
│   └── openhands.py, swe_agent.py, aider.py, autocoderover.py   # Stubs
├── execution/
│   ├── runner.py                # Experiment orchestration
│   ├── plan.py                  # Run plan and estimate
│   ├── variants.py              # --generate-only
│   ├── reuse.py                 # reuse_variants_from
│   └── cost_guard.py            # Per-run and total cost limits
├── metrics/
│   ├── engine.py                # Metrics orchestrator
│   ├── outcome.py               # Run outcome: localization success
│   ├── success.py               # A
│   ├── stability_score.py       # F
│   ├── sensitivity.py           # G, flip rate, control flip rate
│   ├── changed_line_similarity.py, statistics.py   # Patch similarity, bootstrap CI, Wilcoxon
│   ├── patch_similarity.py      # Diff extraction, file overlap (C2), C1
│   ├── comparison.py            # Every RQ1/RQ2 metric per agent across experiments
│   ├── originals.py             # Originals-only summary
│   └── test_outcome.py, output_similarity.py, equivalence.py, ranking.py, cost.py   # Interfaces
├── fixtures/
│   ├── recorder.py              # record-fixtures
│   └── mock_responses/          # Recorded runs (gpt-4o/ for the second model)
├── dashboard/
│   ├── StableAgent.py           # Streamlit entry point
│   ├── pages/1_Past_Experiments.py
│   └── _db.py, _picker.py, _runner.py, _results.py, _similarity.py, _statistics.py, _compare.py
├── cli/main.py                  # Typer CLI (stableagent)
└── export/
    ├── csv_exporter.py, json_exporter.py, report_generator.py
    ├── figures.py               # The RQ2 figure (fig_results.pdf)
    └── comparison_table.py      # The combined table across models
```

---

## 10. Agent Adapter Design

### 10.1 Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

class ExecutionMode(Enum):
    MOCK    = "mock"
    DRY_RUN = "dry_run"
    REAL    = "real"

@dataclass
class AgentInput:
    issue_text:       str
    repo_name:        str
    repo_path:        Optional[str]   = None
    base_commit:      Optional[str]   = None
    relevant_tests:   list[str]       = field(default_factory=list)
    metadata:         dict            = field(default_factory=dict)

@dataclass
class AgentOutput:
    status:           str             # "success"|"failure"|"no_patch"|"timeout"|"error"|"cost_exceeded"
    patch:            Optional[str]   = None   # Unified diff string
    explanation:      Optional[str]   = None
    token_usage:      dict            = field(default_factory=dict)
    cost_usd:         float           = 0.0
    runtime_seconds:  float           = 0.0
    error_message:    Optional[str]   = None
    raw_logs:         str             = ""
    metadata:         dict            = field(default_factory=dict)

class AbstractAgentAdapter(ABC):
    name:             str
    version:          str
    supported_modes:  list[ExecutionMode]

    @abstractmethod
    def configure(self, params: dict) -> None: ...

    @abstractmethod
    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput: ...

    @abstractmethod
    def health_check(self) -> bool: ...
```

### 10.2 LLM Baseline Adapter (Real — ICSE pilot)

Sends the repository name and the issue text (user message `Repository: <repo>\n\nIssue:\n<text>`) to Claude Sonnet via the Anthropic API with a structured system prompt (prompt version `issue-to-unified-diff-v3-submit-patch-tool`, recorded in each run's metadata):

```
You are an expert software engineer. You will be given a GitHub issue description
and the repository name. Produce the patch that resolves the issue and submit it with
the submit_patch tool: exactly ONE unified diff (--- / +++ headers and @@ hunks) covering
every file you change. The diff string contains only the diff: no prose, no explanation,
no code fences, no alternative versions.
```

**Forced tool call.** The request defines one tool, `submit_patch`, with one string parameter `diff`, and sets `tool_choice` to that tool, so the answer is a structured call rather than prose. The tool's `diff` is stored as `patch` exactly as submitted, and the tool input (JSON) as `raw_logs`. The text extractor (diff blocks only, last version per file) is kept only as a fallback: for a diff the model still wrapped in fences or prose inside the string, and for a reply without the tool call (then the reply text is the raw log). Each run's metadata records `patch_source` (`tool`, `tool_extracted`, `text`). A reply with no valid unified diff gets status `no_patch`, a failure. A reply cut at `max_tokens` without a usable diff (a tool call is never used when cut: an incomplete diff is not a submission) gets status `truncated` (v2.10; before, `no_patch`): a budget limit, excluded from the outcome metrics like a timeout (section 13).

Defaults: `max_tokens` 4096 (the reply is only the diff), 120 s per-request timeout, $0.50 per-run cost cap. Records token usage, cost, runtime and `stop_reason`. No code execution, no repo cloning, no sandbox needed.

**Providers (v2.10).** The provider is a parameter: `provider` (`anthropic`, the default, or `openai`), `model`, and `api_key_env_var` (default `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` by provider). The Anthropic path is unchanged. The OpenAI path calls Chat Completions with the same text (the system prompt as the system message, the same user message), temperature 0, `max_completion_tokens` 4096 and the 120 s timeout (the SDK retries twice, like Anthropic's); it defines `submit_patch` as a function with the same name, description and parameters, forces it with `tool_choice` (`parallel_tool_calls` off), and reads the call's JSON arguments as the tool input. From there both paths are one: the same diff extraction and validation, statuses (`success`, `no_patch`, `truncated`, `timeout`, `cost_exceeded`, `error` when the SDK raises), messages and metadata. OpenAI finish reasons are recorded in the Anthropic vocabulary (`length` → `max_tokens`, a forced call → `tool_use`), so a reply cut at the token limit is `truncated` with the same message; arguments cut mid-JSON are kept as `{"unparsed_arguments": ...}` in the raw log. When OpenAI reports a dated snapshot for an alias (`gpt-4o` → `gpt-4o-2024-08-06`), it is recorded as `model_snapshot`. The same reply therefore gives the same run record whichever provider sent it. The OpenAI key comes only from `OPENAI_API_KEY` (`.env`, or the environment), a `SecretStr` that is never logged; the dashboard never asks for it, and error messages mask both keys.

**Cost from the model table.** A run's cost is its input tokens × the input price plus its output tokens × the output price, from `stableagent/config/pricing.py` (USD per million tokens: `claude-sonnet-4-6` 3 / 15, `claude-haiku-4-5-20251001` 1 / 5, `gpt-4o` 2.50 / 10, checked October 2026). Before a real experiment starts, the runner checks every agent: a model without a price (its cost cap could not be enforced), a model of the other provider, or a missing key raises an error naming the fix, and nothing is recorded.

### 10.3 MockReplay Adapter (Mock — ICSE demo)

Reads pre-recorded `AgentOutput` objects from JSON fixture files stored in `stableagent/fixtures/mock_responses/`. Fixture files are named `{issue_id}__{transformation_name}__mock_replay.json` (double underscores; SWE-bench issue ids contain `__` themselves, transformation names never do) and are committed to the repository. An issue is *replayable* for a set of transformations when a fixture exists for its original text and for each of them.

The MockReplay agent:
- Never calls any external API.
- Returns responses in under 100ms (instant for demo purposes).
- Raises `FixtureNotFoundError` if a requested combination has no fixture, preventing silent failures.
- Is used in all CI tests and the live ICSE demo.

Fixtures are populated by running the real LLM Baseline pilot once and recording all outputs. This is done once at M8 (pilot study).

**Fixture sets per model (v2.10).** The pilot's model (`claude-sonnet-4-6`) and agents without a model use the fixtures directory itself; the GPT-4o experiment (9d27f3ef) is recorded in `mock_responses/gpt-4o/` and replays identically (on a database holding the pilot, which `reuse_variants_from` needs; the shipped one does). Any other model has a subdirectory named after it (`mock_responses/gpt-4o/`): `record-fixtures` writes there for an experiment whose agent runs that model, and in mock mode MockReplay reads the set of the configured agent's model (an explicit `fixtures_dir` param wins). Recording a second model never overwrites the pilot's fixtures.

**Recording an experiment** (`stableagent record-fixtures --experiment-id <id>`, `stableagent/fixtures/recorder.py`): one fixture per issue and variant, holding the run's AgentOutput exactly as stored, plus:
- `control_repeats` in the original's fixture: the outputs of the issue's control runs (re-runs of the unchanged original), in order. The runner tells MockReplay which control run it is, so each replays its own recorded output (a fixture without them replays the original's output);
- `variant` in a variant's fixture: the text the run used, its params, provenance and flags (generator, transform_version, mode, quality warning, no-op, exclusion reason) and a hash of the original text;
- the cells the runner skipped (status `skipped_variant`), so every issue is replayable for all the experiment's transformations; and `recorded_from` (experiment and run).

The gold patch is never recorded. Recording is deterministic (the same experiment rewrites identical files) and refuses experiments it cannot replay exactly (several agents, `runs_per_variant` > 1). Replaying with the experiment's config and `--mode mock` reproduces every run and every metric. The ICSE pilot (experiment `bc6f1372-2088-45dd-907c-d741c0545d27`: 20 issues × (original + 6 transformations + 1 control run), real LLM Baseline) is recorded and checked to replay identically, also on a fresh database holding only its 20 bundled issues. The dashboard's MockReplay path replays recorded control runs when every selected issue has them.

### 10.4 Agent Stubs (follow-up study)

OpenHands, SWE-agent, Aider, and AutoCodeRover are present as stub classes:

```python
@agent_registry.register
class OpenHandsAdapter(AbstractAgentAdapter):
    name = "openhands"
    version = "stub"
    supported_modes = [ExecutionMode.MOCK]

    def run(self, agent_input, mode):
        raise NotImplementedError(
            "OpenHands adapter is not yet implemented. "
            "See CONTRIBUTING.md for integration instructions."
        )
```

Their presence in the codebase demonstrates the extensibility claim without incurring implementation cost for ICSE.

### 10.5 Adding a New Agent

1. Create `stableagent/agents/{name}.py`.
2. Subclass `AbstractAgentAdapter`, implement `configure`, `run`, `health_check`.
3. Apply `@agent_registry.register`.
4. Add fixture files under `stableagent/fixtures/mock_responses/` for mock mode.
5. No changes to the execution engine or metrics engine required.

---

## 11. Transformation Engine Design

### 11.1 Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class IssueRecord:
    issue_id:             str
    repo_name:            str
    text:                 str
    reproduction_steps:   Optional[str] = None
    expected_behavior:    Optional[str] = None
    metadata:             dict          = None

@dataclass
class TransformedIssue:
    original_issue_id:      str
    transformation_name:    str
    transformation_params:  dict
    transformed_text:       str
    transformation_notes:   str   # Human-readable explanation of changes

class AbstractTransformation(ABC):
    name:               str
    category:           str    # "deterministic" | "llm_backed"
    preserves_semantics: bool  = True
    transform_version:  str    = "1"   # part of the cache key; bump when outputs can change

    @abstractmethod
    def transform(self, issue: IssueRecord, params: dict) -> TransformedIssue: ...

    def preview(self, issue: IssueRecord, params: dict) -> str:
        return self.transform(issue, params).transformed_text
```

### 11.2 Full Transformation Catalogue

Six transformations are implemented and used in the ICSE pilot (marked ✓); the other six are specified for future work and not implemented.

| ID | Name | Category | ICSE | Description |
|----|------|----------|------|-------------|
| T01 | Paraphrase | LLM-backed | ✓ | Rewrite in different words; preserve all technical identifiers, error messages, and reproduction steps |
| T02 | Verbosity increase | LLM-backed | — | Expand with elaboration; target 1.5–2× word count |
| T03 | Verbosity reduction | LLM-backed | ✓ | Compress the prose to ~0.5× word count; identifiers, file paths, error messages, code and version numbers verbatim; never drop the described symptom |
| T04 | Markdown restructuring | Deterministic | — | Convert headings/bold/lists between markdown styles |
| T05 | Formatting change | Deterministic | — | Strip all markdown; produce plain prose |
| T06 | Synonym replacement | LLM-backed | — | Replace verbs/nouns with synonyms; preserve identifiers |
| T07 | Reordering | Deterministic | ✓ | Shuffle paragraph order (random seed 42); CRLF normalised to LF, split on blank lines only, never inside fenced code; fewer than 2 paragraphs → unchanged (lines are never shuffled) |
| T08 | Typo/noise injection | Deterministic | ✓ | Inject character-level errors at 2% word rate; prose only |
| T09 | Bullet → paragraph | Deterministic | — | Convert bullet lists to flowing prose |
| T10 | Paragraph → structured | LLM-backed | ✓ | Reformat as: Summary / Steps / Expected / Actual / Environment, using only information present in the original; a section the original does not cover reads "Not specified"; versions, steps and environment details are never invented (an output naming a version the original does not mention fails the quality check) |
| T11 | Neutralize emotional language | LLM-backed | ✓ | Rewrite only the sentences with emotional or informal language (emphatic exclamation marks, judgemental words, frustration, insults, slang); ordinary contractions are kept; a report without such language is returned unchanged and its variant is a no-op (section 11.6) |
| T12 | Add irrelevant context | LLM-backed | — | Append plausible but irrelevant context; must not contradict technical content |

### 11.3 LLM-Backed Transformation Prompt Structure

Each LLM-backed transformation uses:
- System prompt defining the task and semantic preservation constraints.
- Hard constraint: all identifiers, error messages, test names, and version numbers must appear verbatim in the output.
- The code of the issue never reaches the model: it sees numbered placeholders instead, and the prompt ends with the placeholder rules (section 11.7).
- One few-shot example pair (original → transformed).
- Output format: JSON `{"transformed_text": "...", "transformation_notes": "..."}`.

### 11.4 Transformation Caching

Results are cached in the database keyed by `(issue_id, transformation_name, sha256(params + transform_version + generator))`, where the generator is the model an LLM-backed transformation calls (`claude-haiku-4-5-20251001`), `deterministic`, or `placeholder` (section 11.6). On cache hit, the stored result is returned with zero API cost. Every change that can alter a transformation's output (prompt, algorithm, quality rule) bumps its `transform_version`, and a different model is a different generator, so variants produced by an older version or another model are never reused; they stay stored for the experiments that ran on them. The v2.3 changes bumped T01, T03, T07, T10 and T11 to version 2, v2.5 bumped T10 to version 3, and v2.6 (technical-token retention check; new T11 prompt) bumped T01, T03 and T11 to version 3 and T10 to version 4, so pre-screen variants (old prompt, line-shuffled reorderings) are regenerated for the pilot. v2.7 (code masking, section 11.7) bumped T01, T03 and T11 to version 4 and T10 to version 5. A transformation may declare earlier versions whose variants stay valid when they passed the quality check (`reuses_passed_versions`): each v2.7 version keeps the passed variants of the version before it (no-ops included), so they are not paid for twice, while its failed variants are regenerated with masking. Every other older version is never reused. Variants stored before the generator joined the key (v2.5) are never reused either. Variant generation is paid once (about $0.17 for the 80 LLM-backed variants of the pilot), however many times or with however many models the experiment is run.

### 11.5 Identifier Retention Check

After each LLM-backed transformation, an automated check verifies that the original's technical content survives. Only technical content is protected; plain English words may change freely:

- **Code, as verbatim substrings:** the content of fenced code blocks, `>>>` lines, indented code lines (markdown: 4 spaces or a tab after a blank line; list items excluded) and backtick spans.
- **Technical tokens of the prose, which must appear:** identifiers containing `_`, `.`, `/` or a digit (snake_case, dotted names, file names, versions such as `3.2`, `psycopg2`), CamelCase names (`GenericRelation`, `IOError`), file paths (`django/db/models/deletion.py`, `/tmp/out`) and `*Error` / `*Exception` names. Not protected: ordinary words, all-caps words (`NOT`, `AFAIK`), plain numbers, abbreviations such as `e.g.`, and `and/or`.

**Markdown and template noise is not technical.** Before tokens are taken, the prose is normalized (`normalize_markdown`): HTML comments, formatting HTML tags (`<details>`, `</summary>`, `<br/>`, ...), `_No response_` lines (an empty issue-form field) and the standard section headings of GitHub issue templates (`### Additional information`, `### Steps/Code to Reproduce`, ...; a heading naming something specific such as `### example.py` is kept) are removed; emphasis markers around words are stripped (`_text_`, `*text*`, `**text**`, only at word boundaries and never `__`, so `_sparse_fit` and `__init__` stay intact); then markdown backslash escapes are undone (`\_\_repr\_\_` → `__repr__`), except inside Windows paths. A `/` right after `<` (a closing tag such as `</module>`) never makes a path, and a token without a letter or digit (`_`) is never technical. A token counts as present when it appears in the variant as written or in its normalized form.

Comparisons ignore CRLF vs LF and spaces at line ends. A transformation may also reject invented details: T10 rejects any version number the original does not mention. The check runs on the output with its code restored (section 11.7). **Retry-then-exclude** (all LLM-backed transformations): two attempts at most. A failing first attempt is retried once, and the model is shown its previous answer with feedback naming what went wrong (the lost placeholders, the missing tokens or the invented details); if both attempts fail, the better one (restorable first, then fewest problems) is stored with `quality_warning = True`, its problems are stored as the variant's `exclusion_reason` (`placeholder_lost: [[CODE_3]] missing`, or the missing code and tokens and invented details), the failure is logged, and the variant is excluded from metrics A, F and G. The agent is never run on it (section 12.1). Exclusion counts are reported per transformation (section 13).

### 11.6 Variant Provenance and No-op Variants

Every stored variant records what produced it, and every export and the dashboard's Transformed Issues tab show it:

| Field | Values |
|-------|--------|
| `generator` | the model id of an LLM-backed variant; `deterministic`; `placeholder` (an offline stand-in from mock or dry-run mode, never a transformation); `original`; `unknown` (stored before provenance existed) |
| `transform_version` | the transformation's version when the variant was produced |
| `generation_mode` | the execution mode it was produced in (`real`, `mock`, `dry_run`; `unknown` for older rows) |
| `noop` | the text equals the original after whitespace normalization (every whitespace run, newlines included, collapsed to one space) |
| `exclusion_reason` | why the variant is excluded from the metrics, when it is: the lost placeholders (`placeholder_lost: ...`, section 11.7) or the missing code and technical tokens (and invented details) of a quality-warning variant, or "no-op: identical to the original after whitespace normalization" |
| `generation_cost_usd` | the API cost of generating the variant, every attempt included (0 for deterministic variants and placeholders; empty for variants stored before v2.7) |

Placeholders exist only in mock and dry-run modes. In real mode an LLM-backed variant is generated or the experiment fails with a clear error (missing API key, API failure); it never falls back to a placeholder, and a placeholder can never be served in real mode because its cache key has its own generator. A placeholder is invalidated (its cache key removed) as soon as the real variant is generated, and the v2.5 database upgrade invalidated every placeholder stored before it.

A no-op variant did not transform anything, so its runs are excluded from SC/TS (metrics A, F and G) like quality-warning variants, and counted per transformation. The upgrade flags no-op variants among older rows too: in the existing database, 8 of the 20 Stage 2 pre-screen reordering variants differ from the original only by line endings.

Databases created by earlier versions are upgraded in place on first use (`stableagent/data/migrations.py`): the columns are added and backfilled (`exclusion_reason` from each quality-warning note, or the no-op note; `generation_cost_usd` stays empty); nothing else changes.

### 11.7 Code Masking for LLM-Backed Transformations

The pilot showed that a model asked to paraphrase, shorten or restructure an issue also rewrites its code (doctest sessions, shell sessions, IPython transcripts), which fails the retention check on every attempt. So the model never sees the code (`stableagent/transformations/masking.py`, used by every LLM-backed transformation through `llm_backed/base.py`):

1. **Mask.** Before the call, each piece of code is replaced by a numbered placeholder (`[[CODE_1]]`, `[[CODE_2]]`, ... in order of appearance): fenced code blocks (fence lines included; closed by the next fence line, as in the retention check), indented code blocks (4 spaces or a tab after a blank line, list items excluded), `>>>` doctest blocks and tracebacks (`Traceback (most recent call last):`), each up to the next blank line, and inline code spans (backticks included). A block placeholder stands on a line of its own. Text that already looks like a placeholder is masked too. Everything the retention check protects as code lies inside a masked block (checked on all 300 SWE-bench Lite issues).
2. **Prompt.** The system prompt ends with the placeholder rules: every placeholder must appear exactly once, written exactly as given; it may be moved but never edited, split, merged, dropped, wrapped in backticks or a fence, or replaced by the code; a block placeholder stays on a line of its own. The few-shot examples use placeholders.
3. **Check, then restore.** Each placeholder must appear exactly once in the answer (missing, repeated and unknown placeholders are reported). Then every placeholder is replaced by its original code, byte for byte (line endings included), in one pass; backticks or a fence the model put around a placeholder are dropped, and a block placeholder ends up on lines of its own.
4. **Retention check** on the restored text (section 11.5).
5. **Retry once, then exclude.** A lost placeholder is retried once with feedback naming it; if the second answer still breaks the contract the variant is excluded with reason `placeholder_lost: ...`. Two attempts in total.

Masking leaves the model only the prose to transform, so an issue that is mostly code (a title and a traceback) more often gives a no-op variant, which is excluded like before (section 11.6).

---

## 12. Execution Engine Design

### 12.1 Experiment Runner

Orchestrates the full experiment. Iterates over (agents × issues × transformations × runs). Responsibilities:
- Validate experiment configuration before any run.
- Check transformation cache before generating.
- Dispatch runs to the async scheduler.
- Enforce cost and timeout limits via the cost guard.
- Persist all results to the database after every run (no batching — results survive partial failures).
- Emit progress events consumed by the dashboard.

**Excluded and no-op variants are never run.** When a variant is flagged `quality_warning` or `noop`, the runner records each of its cells as a run with status `skipped_variant`, cost 0 and the variant's exclusion reason, without calling the agent: such runs would be excluded from the metrics anyway (section 13).

**Generate-only mode.** `stableagent run --generate-only` takes every variant of the experiment from the cache, or generates and quality-checks it (in real mode an LLM-backed variant costs one or two Haiku calls; mock and dry-run modes never generate one), stores it, prints a table with one row per issue and transformation (status `ok`, `noop` or `excluded` with its reason, generation cost, cached or not) and a per-transformation summary with the total generation cost, then stops: no agent is called and no experiment is recorded. The experiment run that follows finds every variant cached.

**Reusing another experiment's variants (v2.10).** With `"reuse_variants_from": "<experiment id>"` every issue's variant of every enabled transformation is the stored variant that experiment's run used (`execution/reuse.py`): nothing is looked up in the transformation cache and nothing is generated, so a second model sees exactly the texts the first one saw, typo injection without a seed included, and skips the same excluded and no-op variants. Before anything is recorded the runner checks that the reference experiment is in the database and ran exactly one variant of each (issue, transformation) with the configured params; otherwise it fails, naming every variant that would have to be generated. `--estimate` reports the reused variants and "0 variants to generate", and `--generate-only` lists them as cached. The real-mode key check for variant generation is skipped (nothing is generated), so the second model needs only its own key.

**Originals-only mode.** `stableagent run --originals-only` (or `"originals_only": true` in the config) runs only the original variant of every issue: no transformation is applied or generated. After the metrics are computed it prints, per issue, the status, the outcome (localization success), the files the gold patch modifies and the files the patch modifies, then the overall success count. A cheap check of the agent and of the outcome before a full run.

### 12.2 Execution Modes

| Mode | Agent invocation | API calls | Cost | Used for |
|------|-----------------|-----------|------|----------|
| Mock | MockReplay replays fixtures | None | $0 | Live demo, CI, development |
| Dry-run | Skipped entirely | None | $0 | Config validation |
| Real | Actual agent called | Yes | Actual | Pilot study results |

"No API calls" covers the transformations too: in mock and dry-run modes an LLM-backed variant is never generated. The runner uses the generated variant if one is cached (current `transform_version` and model), else the variant a recorded MockReplay fixture holds when the cache itself would serve it (same original text, params and model; current version, or a passed variant of a reused version; section 10.3), stored with its recorded provenance; else a placeholder: the original text under a note saying the variant was not generated, stored with generator `placeholder` and reused by later offline runs. Recorded deterministic variants are restored the same way, because typo injection without a `seed` param differs from one computation to the next. MockReplay replays its fixture by issue id and transformation name, so the variant text does not change a mock result. Deterministic transformations are computed as usual.

Real mode is the opposite: LLM-backed variants are generated, never replaced by placeholders. Before anything runs, the runner checks that a key is configured if some LLM-backed variant still has to be generated; an API failure during generation stops the experiment (status `failed`) with an error naming the issue, the transformation and the model (section 11.6).

### 12.3 Run Lifecycle

```
PENDING → DISPATCHED → RUNNING → COMPLETED   (status "success": a valid diff was extracted)
                               → NO_PATCH    (reply without a valid unified diff; a failure)
                               → TRUNCATED   (reply cut at max_tokens, no usable diff; excluded)
                               → FAILED
                               → TIMEOUT
                               → COST_EXCEEDED
                               → DRY_RUN_SKIPPED
```

### 12.4 Cost Guard (ICSE defaults)

| Parameter | ICSE default | Follow-up default |
|-----------|-------------|---------------|
| Per-run cost cap | $0.50 | $10.00 |
| Per-run timeout | 120 seconds (per request; the SDK retries up to 2×) | 600 seconds |
| Max output tokens (LLM Baseline) | 4096 (forced tool call: the diff only) | 8192 |
| Total experiment cost limit | $20.00 | $5,000.00 |
| Runs per variant | 1 | 3 |

The per-run cap is checked after each call: a run that cost more than the cap is recorded as `cost_exceeded` (and excluded from the metrics). With `max_tokens` = 4096 a single LLM Baseline call cannot exceed about $0.07 plus input, so the cap acts as a safety net rather than a mid-generation stop.

### 12.5 Transformation Caching in the Runner

Before calling the transformation engine, the runner checks the cache. On a hit, no API call is made and the run proceeds immediately. This means:
- First pilot run: transformations generated (costs ~$0.30 total).
- All subsequent runs with the same issue/transformation: zero transformation cost.
- Re-running the full experiment after a bug fix: costs only agent API calls.

### 12.6 MockReplay Integration

The runner treats the MockReplay adapter exactly like any real adapter. The difference is entirely inside the adapter: instead of calling an API, it reads a fixture file. This design means:
- The full pipeline (runner → adapter → metrics → dashboard) is exercised identically in mock and real modes.
- Mock mode is a reliable test of the entire system, not a simplified version.
- Fixture files are committed to the repository, so any collaborator can run the full demo with no API key.

### 12.7 Test Execution (not implemented)

Patches are not executed: the outcome is localization success (section 13), not test-based resolution. Running the SWE-bench tests would need repository checkouts and a sandbox per run; Metric B (Test Outcome Consistency) is left to future work.

---

## 13. Metrics Engine Design

The metrics engine reads completed run records from the database and computes metrics at three granularities: per-run, per-(agent, issue), and per-experiment.

### Run Outcome: Localization Success (ICSE pilot)

Metrics A, F and G are computed from a binary per-run outcome, **localization success**:

```
outcome(run) = success   iff  a valid unified diff was extracted from the reply  (status "success")
                         and  files_in_gold ⊆ files_in_patch                       (localization_match)
               failure   otherwise, including status "no_patch"
```

- `files_in_patch` (P): files modified by the run's extracted diff; `files_in_gold` (G): files modified by the issue's gold patch (the SWE-bench `patch` field).
- Stored per run as run-scope metrics: `outcome` (1/0), `localization_match` (1/0) and `file_overlap_jaccard` = |P ∩ G| / |P ∪ G|, with P and G in the metric metadata. Extra files in the patch lower the Jaccard overlap but do not break the match.
- The gold patch is hidden ground truth: the loader stores it in the issue record's metadata and only the metrics engine reads it. It never appears in `AgentInput`, the prompt, or `raw_logs`, and it is not exported.
- Issues without a gold patch (custom issues, synthetic demo fixtures) cannot be localized. Their runs fall back to "a valid diff was extracted", are marked `basis = valid_diff_only` in the outcome metric's metadata, and are listed in a logged warning. Load gold patches (`stableagent load-swebench --ids …`) before the pilot.
- **Excluded runs.** Runs whose status is `timeout`, `truncated` (a reply cut at the token limit without a usable diff; also a `no_patch` run recorded before v2.10 whose `stop_reason` is `max_tokens`, read as truncated without rewriting it), `cost_exceeded` or `error` (or that never ran: `dry_run_skipped`, `running`) stay distinct statuses and are excluded from SC/TS rather than counted as failures; so are runs on transformed variants flagged `quality_warning` (section 11.5) and runs on no-op variants (`noop`, section 11.6). Since v2.7 the agent is not called on such variants (status `skipped_variant`, section 12.1); whatever their status, runs on them are counted under the variant's reason, not as runs that did not complete. A warning lists every excluded run, and the counts are stored as `excluded_runs_status`, `excluded_runs_quality_warning`, `excluded_runs_noop` (experiment scope) and `excluded_quality_warning`, `excluded_noop` per transformation, which every export reports. An issue whose original run is excluded contributes no SC value and no TS term.
- **Exports.** Every per-run export (runs CSV, JSON, Markdown report, dashboard downloads) puts `file_overlap_jaccard` right next to the binary outcome (blank when the run has no outcome or the issue no gold patch).
- The dashboard (RQ1 table and colours, statistical tests, exports) and the CLI exports display this same recorded outcome, never `run.status`, so the GUI and the metrics cannot disagree.

**Limitation.** Localization success is weaker than test-based resolution: modifying the right files says nothing about whether the change is correct, so it over-estimates success. Test-based resolution (Metric B, section 12.7) is deferred to the larger study.

### Metric A: Success Consistency (ICSE pilot)

For a given (agent, issue) pair across all transformation variants, the fraction that share the same success/failure outcome as the original.

```
SC(agent, issue) = |{v : outcome(v) = outcome(original)}| / |variants|
```

Range [0, 1]. A score of 1 means the agent always produces the same outcome regardless of phrasing.

### Metric F: Stability Score (ICSE pilot)

For the ICSE pilot (no test execution, patch similarity optional), the Stability Score simplifies to:

```
SS(agent, issue) = w_A × SC + w_C × PatchSim_C1
```

With default weights w_A = 0.7, w_C = 0.3 (or w_A = 1.0 if patch similarity is not computed).

Agent-level Stability Score: mean of SS across all issues.

Range [0, 1]. Interpretation: 1.0 = fully stable; < 0.5 = unstable.

### Metric G: Transformation Sensitivity (ICSE pilot)

For each transformation t, the mean drop in success rate when that transformation is applied:

```
TS(agent, t) = mean_{issues} [ outcome(original) - outcome(t) ]
```

where outcome is 1 for success and 0 for failure. A high TS value means the transformation frequently causes the agent to fail when it succeeded on the original.

TS is a drop rate: a success→failure flip counts +1 and a failure→success flip −1, so opposite flips cancel out. Every report therefore also gives the **symmetric flip rate**, the fraction of issues whose outcome changes in either direction:

```
FR(agent, t) = mean_{issues} | outcome(original) - outcome(t) |
```

Same exclusions as TS. Stored as the metric `flip_rate` (scope `agent`, key `agent|transformation`), shown next to TS in the dashboard's RQ2 tab, the CLI summary, the Markdown reports and the metrics exports.

### Changed-Line Similarity (patch content, v2.9)

The binary outcome hides most of what a transformation changes: the agent can localize the same files with a different edit. So every non-original run's patch is also compared with the patch of its issue's original run (same agent), on the **changed lines** only: the `+` and `-` lines of the unified diff, prefix included, without the `+++`/`---` file headers, joined with newlines and compared character by character with `difflib.SequenceMatcher` (`autojunk` off):

```
CLS(run) = SequenceMatcher("\n".join(changed_lines(original patch)),
                          "\n".join(changed_lines(run patch))).ratio()   ∈ [0, 1]
```

1 = the same changed lines in the same order; context lines, hunk headers and line numbers do not count. Two runs without a diff score 1, one without a diff against one with a diff 0. Patches go through the same extraction as localization (a no-op on a tool-submitted diff). Same exclusions as TS: only runs with an outcome, and an issue whose original run has none contributes nothing.

**Control runs and noise floor.** With `control_repeats` (config; the runner re-runs each issue's unchanged original after its variants, `Run.control_repeat`), each control run gets the same similarity to the original run. Their mean is the noise floor: what two runs of the very same text reach. Control runs never enter A, F or G; their outcome flips give `control_flip_rate`.

**Per transformation** (one value per issue: the mean of its runs): the mean similarity over issues; the mean paired difference to the control (by issue, variant − control, issues that have both); a 95% percentile bootstrap CI for both (5000 resamples of the issues, `numpy.random.default_rng(42)`); and the two-sided Wilcoxon signed-rank p-value of the paired differences (zero differences dropped; exact null distribution without zeros or ties and n ≤ 50, else the normal approximation with tie correction; SciPy's defaults, reimplemented in `metrics/statistics.py`). With 20 issues and no correction for multiple comparisons, **the tests are exploratory** and labelled so wherever they are shown.

Stored metrics: `changed_line_similarity` (scope `run`, every compared run, control runs included; the original run's id in the metadata), `changed_line_similarity_mean` and `changed_line_similarity_vs_control` (scope `agent`, key `agent|transformation`; CI, per-issue values, Wilcoxon p, `"analysis": "exploratory"` in the metadata), `control_changed_line_similarity` (scope `agent`, key the agent). Experiments recorded before v2.9 get them from `stableagent recompute-metrics --experiment-id <id>`, which deletes the experiment's metric rows and recomputes them from its runs (runs are never touched). The Stability Score (F) still uses SC alone.

**Per agent across experiments (v2.10).** `stableagent/metrics/comparison.py` compares the agents of several experiments run on the same issues (e.g. two models with `reuse_variants_from`). Each agent of each experiment is one compared agent, labelled after its model ("LLM Baseline (GPT-4o)"); its runs are scored exactly as the engine scores them (the engine's `score_runs`), and every RQ1/RQ2 metric is computed within that agent: originals localized, variants that kept the original's outcome, SC, SS, TS, flip rate, control flip rate, and the changed-line similarity per transformation with its CI, the paired difference to that agent's repeat of the original and the exploratory Wilcoxon p. A variant's or a repeat's patch is only ever compared with the same agent's own original patch, even when two experiments recorded the same `agent_name`. Nothing is stored. Within one experiment the engine groups by `agent_name`, so agent names must be unique in a config. `scripts/analyze_patch_similarity.py --experiments <ids>` (unique id prefixes accepted; `--runs` still reads CSV exports) prints the comparison and writes to `results/paper/`: `fig_results.pdf` and `.png`, the RQ2 figure (one row per transformation plus the repeat row on top, one marker per model offset vertically, models told apart by colour, marker shape and fill so the figure reads in grayscale, mean and 95% bootstrap CI, a dashed or dotted line per model at its repeat mean; 3.5 in wide, TrueType fonts, `export/figures.py`), and `table_results.csv`/`.md`/`.tex`, the combined table (per model and transformation: n, outcome kept, mean similarity [95% CI], difference to the repeat [95% CI], Wilcoxon p; `export/comparison_table.py`).

ICSE pilot (experiment bc6f1372, 20 issues, LLM Baseline): repeat of the original 0.75 [0.61, 0.88], paraphrase 0.54 [0.39, 0.70]; every transformation lower than the repeat, by −0.05 (Neutralize Emotional, p = 0.59) to −0.21 (Paraphrase, p = 0.008), while TS is 0 for five of the six transformations. (Comparing whole lines instead of characters gives lower values, repeat 0.635 and paraphrase 0.400; the paper reports the character-level values.)

Second model (experiment 9d27f3ef, GPT-4o on the same variants, v2.10): originals localized 17/20; 97 of the 105 scored variants keep the original's outcome (3 replies cut at 4096 tokens excluded; Claude Sonnet 4.6: 20/20 and 107/108); repeat of the original 0.76 [0.65, 0.86] (Claude 0.75); paraphrase 0.59 [0.47, 0.71], −0.18 vs the repeat (p = 0.02).

### Full Metric Suite

| Metric | Name | Status |
|--------|------|--------|
| A | Success Consistency | implemented, reported |
| B | Test Outcome Consistency | interface only (needs test execution) |
| C1 | Patch Similarity (character diff) | function implemented; the changed-line similarity above is reported instead |
| C2 | File overlap (Jaccard) | implemented, exported per run |
| C3, C4 | Line overlap, AST similarity | not implemented |
| D | Output similarity | interface only |
| E | Behavioral Equivalence Rate | interface only |
| F | Stability Score | implemented, reported |
| G | Transformation Sensitivity (and flip rate) | implemented, reported |
| H | Agent Robustness Ranking | interface only |
| I1–I6 | Cost and Runtime | recorded per run; summary metrics are an interface |

---

## 14. Data Model

### Core Entities

**Issue** — immutable record of a software issue from SWE-bench Lite or other source.

**TransformedIssue** — result of applying one transformation to one issue. Cached; never re-generated if already present.

**Experiment** — full configuration snapshot (agents, issues, transformations, parameters, mode). Created at experiment launch; immutable thereafter.

**Run** — single execution of one agent on one transformed issue. Contains output, status, cost, runtime.

**Metric** — computed metric value at any scope (run, agent-issue, agent, experiment).

**ExportArtifact** — generated export file (CSV, JSON, report) linked to an experiment.

**MockFixture** — pre-recorded AgentOutput for a given (issue, transformation, agent) triple. Committed to the repository. Used by MockReplay adapter.

### Relationships

```
Issue          1──* TransformedIssue
Issue          1──* MockFixture
Experiment     1──* Run
TransformedIssue 1──* Run
Run            1──* Metric
Experiment     1──* Metric
Experiment     1──* ExportArtifact
```

---

## 15. Database Schema

SQLite for ICSE (single-file, zero-configuration); PostgreSQL upgrade path for the follow-up study.

```sql
CREATE TABLE issues (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,        -- "swebench_lite" | "github" | "manual"
    external_id         TEXT,
    repo_name           TEXT NOT NULL,
    issue_text          TEXT NOT NULL,
    reproduction_steps  TEXT,
    expected_behavior   TEXT,
    relevant_tests      TEXT,                 -- JSON array
    metadata            TEXT,                 -- JSON blob
    created_at          TEXT NOT NULL
);

CREATE TABLE transformed_issues (
    id                      TEXT PRIMARY KEY,
    issue_id                TEXT NOT NULL REFERENCES issues(id),
    transformation_name     TEXT NOT NULL,
    transformation_params   TEXT,
    transformed_text        TEXT NOT NULL,
    transformation_notes    TEXT,
    quality_warning         INTEGER NOT NULL DEFAULT 0,  -- 1 if identifier retention check failed
    is_original             INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL
);

CREATE TABLE experiments (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    config          TEXT NOT NULL,   -- Full JSON config snapshot
    status          TEXT NOT NULL,   -- "pending"|"running"|"completed"|"failed"|"partially_complete"
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    total_cost_usd  REAL DEFAULT 0.0
);

CREATE TABLE runs (
    id                      TEXT PRIMARY KEY,
    experiment_id           TEXT NOT NULL REFERENCES experiments(id),
    transformed_issue_id    TEXT NOT NULL REFERENCES transformed_issues(id),
    agent_name              TEXT NOT NULL,
    agent_version           TEXT,
    run_index               INTEGER NOT NULL DEFAULT 0,
    execution_mode          TEXT NOT NULL,
    status                  TEXT NOT NULL,
    patch                   TEXT,
    explanation             TEXT,
    raw_logs                TEXT,
    token_input             INTEGER,
    token_output            INTEGER,
    cost_usd                REAL,
    runtime_seconds         REAL,
    error_message           TEXT,
    metadata                TEXT,
    created_at              TEXT NOT NULL,
    started_at              TEXT,
    completed_at            TEXT
);

CREATE TABLE metrics (
    id              TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES experiments(id),
    scope           TEXT NOT NULL,   -- "run"|"agent_issue"|"agent"|"experiment"
    scope_key       TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    metric_value    REAL,
    metric_metadata TEXT,
    computed_at     TEXT NOT NULL
);

CREATE TABLE export_artifacts (
    id              TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES experiments(id),
    artifact_type   TEXT NOT NULL,   -- "csv"|"json"|"report_md"
    file_path       TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_runs_experiment        ON runs(experiment_id);
CREATE INDEX idx_runs_agent             ON runs(agent_name);
CREATE INDEX idx_runs_status            ON runs(status);
CREATE INDEX idx_metrics_experiment     ON metrics(experiment_id);
CREATE INDEX idx_metrics_scope          ON metrics(scope, scope_key);
CREATE INDEX idx_transformed_issue      ON transformed_issues(issue_id);
CREATE INDEX idx_transformed_cache      ON transformed_issues(issue_id, transformation_name);
```

---

## 16. Dashboard (GUI-First Workflow)

The dashboard is the primary interface; the CLI remains available for scripted/batch use. The GUI has two navigation pages: StableAgent and Past Experiments. Experiment results and exports appear in tabs within StableAgent.

### Main Page: StableAgent

**Section A — Issue Input.** Radio choice at the top: **Select from SWE-bench Lite** (default) or **Write my own issue**.
- *SWE-bench mode:*
  - **Data.** The 300 SWE-bench Lite test issues are bundled in `data/swebench_lite_issues.json`: id, repository, verbatim problem statement, base commit and gold patch, with the source (dataset, revision, paper) and a license note (the dataset card declares no license; the issue texts and patches remain under their projects' terms). The file is built offline from a local copy of the dataset by `scripts/build_swebench_bundle.py`. While some bundled issues are missing from the database, a "Load SWE-bench Lite (300 issues, offline)" button imports them: no network access, idempotent (a second import writes nothing), issues already present keep their text and only gain the hidden gold patch (section 13). The CLI equivalent is `stableagent load-swebench --ids …`, which reads the same file unless `--from-huggingface` is given.
  - **Picker.** A multiselect over every loaded issue. Each option shows the issue id, a badge and the first words of the text. The badge reads **✓ replayable** when MockReplay fixtures exist for the issue's original and every transformation enabled in Section C (section 10.3), otherwise **real mode only (~$X per variant)**, where X is the per-run cost estimate of Section D.
  - **Filters.** A repository dropdown (with issue counts), a keyword search over the issue text (case-insensitive; every word must occur) and a **Show only replayable** toggle, ON by default with MockReplay and OFF with LLM Baseline (it resets to that default when the agent changes). Filters narrow the options; they never drop an issue that is already selected.
  - **Counter.** A caption such as "300 loaded, 5 replayable · 12 shown". Below the picker, a read-only Issue Preview.
  - **No gold patch in the payload.** The picker never loads issue metadata: a run receives only the issue id, text and repository, so the gold patch cannot reach an agent.
  - **Verbatim records only.** The picker lists dataset records (bundled SWE-bench Lite issues, `scripts/seed_issues_from_stage1.py`, `load-swebench`), never hand-written texts. `scripts/seed_issues.py` loads the 5 demo issues the fixtures cover, verbatim from the bundle. `scripts/seed_pilot_issues.py` loads the 20 ICSE pilot issues (`scripts/output/pilot_issue_ids.json`) verbatim from the bundle with their hidden gold patches, as source `swebench_lite_pilot` (a pilot issue already present keeps its row and text and is relabelled).
- *Custom mode:* a free-text Issue Description area plus optional Repository name and Issue ID inputs. A custom issue is stored as an ad-hoc record (source `custom_adhoc`, a new row per run): never listed in the SWE-bench picker, never reused, and never resolved in place of a dataset issue even when its label equals a dataset id. Custom issues have no fixtures, so MockReplay cannot run them (see the Run guard).

**Section B — Agent Selection.** Radio group: **MockReplay** (free, instant — default), **LLM Baseline (Claude Sonnet 4.6)** and **LLM Baseline (GPT-4o)** (v2.10: one entry per model, `BASELINE_PRESETS`; the caption under each gives the model id and its key variable, and the info panel names the model id, the provider and the per-variant cost estimate: the mean cost of that model's past real runs, else its expected cost from the model table). Claude needs the Anthropic key (a password input appears when selected). GPT-4o reads `OPENAI_API_KEY` from `.env` only: the panel says whether it is set and Run stays disabled until it is; the Anthropic field remains, needed only to generate LLM-backed variants that are not cached yet. The key is kept in the browser session's state only: it is handed to the Anthropic client and never written to disk, the database, or the logs; error messages are stored and shown with the key masked.

**Section C — Transformation Selection.** A checklist of the 6 activated transformations, each with a bold label, a one-line grey description, and a type badge (LLM-backed / Deterministic): Paraphrase (default on), Verbosity Reduction (default on), Typo/Noise Injection, Reordering, Paragraph → Structured Bug Report, Neutralize Emotional Language. Validation: minimum 2 selected, otherwise Run is disabled with a warning.

**Section D — Run.** A large "▶ Run Experiment" button. On click: validate inputs → create Experiment record → call ExperimentRunner synchronously with st.spinner/progress → results appear below on the same page. Both agents go through the same ExperimentRunner as the CLI: MockReplay replays fixtures; LLM Baseline runs the LLMBaselineAdapter with the pilot's parameters (`configs/icse_pilot.json`: model, temperature 0, 4096 tokens, 120 s, per-run cost cap; the forced submit_patch tool call) under the cost guard, and its LLM-backed variants are generated by the transformation model (a failure stops the run with a clear error, never a placeholder). The session's key reaches the agent and the transformations through a per-run override, not the environment.

**Cost preview (LLM Baseline).** Before Run, the estimated cost: runs × cost per run, where runs = issues × (1 + transformations) and the cost per run is the mean cost of the chosen model's past real runs that recorded one, else (v2.10) the model's expected cost: the ICSE pilot's mean tokens per run (1516 in, 337 out) at its prices from the model table, as `run --estimate` computes it.

**Run guard.** Run stays disabled, with one warning per reason shown above the button, when: no issue is selected; fewer than 2 transformations are selected; MockReplay is selected and some selected issue is not replayable (the warning names each such issue, at most five, and the variants it lacks) or the issue is a custom one; LLM Baseline is selected without an API key; or the estimated cost exceeds the configured total limit (`DEFAULT_TOTAL_COST_LIMIT_USD`, $20 by default). The guard is re-checked at click time, and the mock runner checks fixtures before creating anything, so a missing fixture is always reported as a plain explanation, never as a raw fixture-not-found error.

### Results (same page, below Run, organized in tabs)

- **Tab 1 — RQ1: Stability.** Summary sentence; per-transformation table (Transformation | Outcome | Patch produced | Consistent with original? with 🟢/🔴/🟡 status); Stability Score (F) as a large color-coded number (green ≥ 0.7, amber 0.4–0.7, red < 0.4); Success Consistency (A) shown similarly.
- **Tab 2 — RQ2: Transformation Sensitivity.** First the changed-line similarity (section 13): a table (variant, issues, mean [95% CI], Δ vs the repeat of the original [95% CI], Wilcoxon p labelled exploratory) with a grey **Repeat of original** row first, then the transformations from least to most similar; below it a dot plot with one row per table row: each issue as a faint dot, the mean with its CI bar, a dashed vertical line at the control mean, and a caption explaining the plot. Experiments whose metrics predate v2.9 show the `recompute-metrics` command instead. Then, unchanged: horizontal plotly bar chart of metric G per selected transformation, sorted most→least disruptive; summary sentence naming the most disruptive transformation; table with the symmetric flip rate next to G and an interpretation column; the noise floor (control flip rate).
- **Tab 3 — Transformed Issues.** Dropdown to pick a transformation; original and transformed issue text side by side for user verification, with the variant's provenance below (generator, transform_version, mode; section 11.6), a notice when it is a placeholder, a no-op or quality-flagged, and its exclusion reason (e.g. the missing technical tokens).
- **Tab 4 — Issue Detail.** An issue dropdown and a dropdown for what to compare the original's patch with (each transformation, then each repeat of the original), opening on psf__requests-2317 / Reordering when the experiment has them. A line gives both outcomes and the pair's changed-line similarity (with the repeat of the original on that issue). The two patches are shown side by side, line-aligned (`difflib`): lines only in the original's patch on red, only in the other on green, the differing characters darker when two paired lines are alike; a toggle shows only the changed lines (what the similarity compares). A skipped variant shows its exclusion reason instead; the raw patches are in an expander.
- **Tab 5 — Export.** Download buttons: CSV, JSON, Markdown report (via the existing exporters).

### Sidebar
App title and subtitle, link to Past Experiments, GitHub link.

### Past Experiments Page
Table of all previous experiments (date, issue snippet, agent, transformations, stability score); clicking a row reloads that experiment's results into the main view.

**Compare models (v2.10).** Above the table, an expander picks up to four experiments (preselected: the newest completed experiment that reused another one's variants, with that experiment first) and shows the RQ2 figure of section 13 (the same figure as `fig_results.pdf`, with a download button) and the combined table, from the per-agent comparison of the metrics code.

### Technical Requirements
Results held in st.session_state across reruns; runner called synchronously from the button callback; all metrics computed by the existing MetricsEngine (never inside the dashboard); plotly for charts; must work fully in mock mode with no API key set and no network access (loading the bundled issues included).

---

## 17. Exported Artifacts and Reports

### runs.csv
One row per run: run_id, experiment_id, agent_name, issue_id, transformation_name, status, outcome, file_overlap_jaccard (next to the outcome), patch, cost_usd, runtime_seconds, token_input, token_output, and the variant's quality_warning, provenance (generator, transform_version, generation_mode, noop) and exclusion_reason (section 11.6).

### metrics.csv
One row per metric: metric_name, scope, scope_key, metric_value.

### experiment_results.json
Full experiment record: config, all runs (with patches, explanations, outcome, file_overlap_jaccard and the variant provenance), all metrics, and the exclusion counts (status, quality warning, no-op; per transformation).

### experiment_report.md
```
# Experiment Report: [name]
## Summary
Date · Agents · Issues · Transformations · Total cost · Total runtime

## RQ1 — Stability Results
Stability Score by issue (table) · Mean agent stability score

## RQ2 — Transformation Sensitivity
Sensitivity ranking (table, TS with the flip rate next to it) · Most and least disruptive transformation

## Issue-Level Results
Per-run table: status · outcome · file overlap (Jaccard) · cost

## Variant Provenance
Per variant: generator · transform_version · mode · no-op · quality warning · exclusion reason

## Methodology
Transformation descriptions · Metric definitions · Config snapshot
```

### Replication Package (for submission)
Zenodo-archived ZIP containing: experiment config JSON, issues dataset, all run results (no raw logs), all metrics, Markdown report. Enables full result reproduction by running the tool in MockReplay mode against the committed fixtures.

---

## 18. Validation Plan

### 18.1 Unit Tests

- **Transformation engine:** For each of the 12 transformations, verify output is non-empty, differs from input, and passes the identifier retention check on 3 synthetic issues.
- **Metrics engine:** Verify A, F, G against hand-computed expected values on a 2-issue, 3-transformation synthetic dataset.
- **MockReplay adapter:** Verify it returns correctly structured `AgentOutput` for all committed fixtures; verify `FixtureNotFoundError` on missing fixture.
- **Transformation cache:** Verify second call for same (issue, transform) returns cached result without calling the LLM API.
- **Database layer:** Verify CRUD operations and that re-runs create new records rather than overwriting.

### 18.2 Integration Tests (Mock Mode)

End-to-end test: 2 issues × 1 agent (MockReplay) × 3 transformations × 1 run = 6 runs. Verify:
- All 6 runs persisted with correct status.
- Metrics A, F, G computed and stored.
- CSV and JSON exports generated and parseable.
- Markdown report generated with correct structure.

This test runs in CI on every push at zero API cost.

### 18.3 Pre-Screen Run (exploratory)

Before the pilot, an exploratory pre-screen (`scripts/prescreen_stage1.py`, `scripts/prescreen_stage2.py`: 20 candidate issues, the original and two variants each) checked the pipeline on real runs. It was not used to choose the pilot issues: those come from the structural rule of section 5.2, which uses no agent outcome.

### 18.4 Pilot Study

Two real-mode experiments on the same 20 issues: per issue the original, six variants and one repeat of the original (160 cells; excluded and no-op variants are recorded without calling the agent), first with Claude Sonnet 4.6 (`configs/icse_pilot.json`), then with GPT-4o on exactly the same variants (`configs/icse_pilot_model2.json`, `reuse_variants_from`). Both are recorded as MockReplay fixtures and replay to identical runs and metrics.

### 18.5 Transformation Quality Check

Every LLM-backed variant (80: 20 issues × 4 transformations) passes the code-masking and identifier-retention checks or is excluded with its reason (section 11.5); the exclusion counts are reported per transformation. A human validation of semantic equivalence (two raters, Cohen's κ) is future work.

### 18.6 Threats to Validity

- **Construct validity:** the outcome is localization success (the patch modifies the gold-patch files), weaker than test-based resolution; the changed-line similarity complements it at the patch level, and per-issue results are exported.
- **External validity:** results are limited to 20 Python issues from SWE-bench Lite and two models behind a single-call baseline. Generalization is not claimed; the pilot is preliminary.
- **Internal validity:** LLM-backed transformations may introduce subtle semantic shifts despite the identifier retention check. This is acknowledged as a limitation and motivates a human validation in future work.

---

## 19. Research Questions

### ICSE (2 RQs)

**RQ1 — Stability:** To what extent does an LLM-based SE agent exhibit consistent behavior across semantically equivalent reformulations of the same software issue?

*Method:* For each model, compute SC (metric A) and SS (metric F) over the 20 issues and six transformations; report the originals localized, the variants that keep the original's outcome and the control flip rate.

**RQ2 — Sensitivity:** Which transformation categories cause the largest reduction in agent behavioral consistency?

*Method:* For each model and transformation, compute TS (metric G), the flip rate and the changed-line similarity to that model's original patch, against the repeat of the original (95% bootstrap CIs, exploratory Wilcoxon tests); inspect example pairs in the Issue Detail tab.

### Future work

**RQ3 — Agent comparison:** Do different autonomous SE agents differ significantly in behavioral stability?

**RQ4 — Stability vs. performance:** Is there a correlation between an agent's SWE-bench pass rate and its behavioral stability?

**RQ5 — Cost of instability:** How does instability affect cost-efficiency (cost per successful repair)?

**RQ6 — Issue characteristics:** Do issue-level properties (length, presence of reproduction steps) predict stability?

**RQ7 — Stochastic instability:** How consistent is an agent's behavior across repeated runs of the same issue at non-zero temperature?

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| Autonomous SE agent | A system that receives a natural-language issue and autonomously produces a code patch without step-by-step human guidance. |
| Behavioral stability | The property that an agent produces equivalent behavior across semantically equivalent inputs. |
| LLM Baseline | The real agent of the ICSE pilot: a single API call (Claude Sonnet 4.6 or GPT-4o) that receives an issue and returns a unified diff patch. |
| MockReplay agent | An agent adapter that replays pre-recorded LLM Baseline responses from fixture files. Used for demos, CI, and development. Costs $0. |
| Metamorphic relation | A property that must hold between the outputs of a program when applied to semantically related inputs. |
| Stability Score (F) | Aggregate metric in [0, 1] measuring behavioral consistency across transformation variants. |
| Transformation Sensitivity (G) | The mean drop in success rate caused by a specific transformation category. |
| SWE-bench Lite | 300 GitHub issues from Python repositories with associated test suites, used to evaluate SE agents. |
| Unified diff | Standard text format for code changes, showing added and removed lines in context. |
| Fixture | A JSON file containing a pre-recorded AgentOutput for a specific (issue, transformation, agent) triple. |

---

## Appendix B: Configuration Schema (JSON)

```json
{
  "experiment_name": "icse_pilot_v1",
  "description": "ICSE 2027 pilot: 10 SWE-bench Lite issues, LLM Baseline, 6 transforms",
  "execution_mode": "real",
  "agents": [
    {
      "name": "llm_baseline",
      "version": "1.0",
      "params": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.0,
        "max_tokens": 4096,
        "timeout_seconds": 120,
        "cost_cap_usd": 0.50,
        "api_key_env_var": "ANTHROPIC_API_KEY"
      }
      // v2.10: "provider": "anthropic" (default) or "openai"; "model" must be in the model
      // table (stableagent/config/pricing.py); agent names are unique within a config
    }
  ],
  "issues": {
    "source": "swebench_lite",
    "issue_ids": [
      "django__django-XXXX",
      "astropy__astropy-XXXX"
    ]
  },
  "transformations": [
    { "name": "paraphrase",   "enabled": true, "params": {} },
    { "name": "verbosity_reduction", "enabled": true, "params": { "target_ratio": 0.5 } },
    { "name": "typo_injection", "enabled": true, "params": { "error_rate": 0.02 } },
    { "name": "reordering", "enabled": true, "params": { "seed": 42 } },
    { "name": "paragraph_to_structured", "enabled": true, "params": {} },
    { "name": "neutralize_emotional", "enabled": true, "params": {} }
  ],
  "runs_per_variant": 1,
  "cost_limit_usd": 20.0,
  "output_dir": "./results/icse_pilot_v1"
  // v2.10: "reuse_variants_from": "<experiment id>" runs on that experiment's variants only
}
```

---

*End of specification. Version 2.11. All section numbers stable. Commit this file as `docs/SPEC.md`.*
