from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import typer
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stability_eval.config.experiment_schema import ExperimentConfig
from stability_eval.config.settings import settings
from stability_eval.data.database import create_all, get_db
from stability_eval.data.models import Experiment, ExportArtifact, Issue, Metric, Run
from stability_eval.execution.runner import ExperimentRunner
from stability_eval.export.csv_exporter import CSVExporter
from stability_eval.export.json_exporter import JSONExporter
from stability_eval.export.report_generator import ReportGenerator
from stability_eval.metrics.engine import MetricsEngine

app = typer.Typer(name="stabilityeval", add_completion=False, no_args_is_help=True)
console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_experiment(db, experiment_id: str) -> Experiment:
    """Return an Experiment by UUID or 1-indexed creation order."""
    try:
        idx = int(experiment_id)
        all_exps = db.query(Experiment).order_by(Experiment.created_at).all()
        if idx < 1 or idx > len(all_exps):
            console.print(
                f"[red]No experiment at position {idx} "
                f"(total: {len(all_exps)}).[/red]"
            )
            raise typer.Exit(1)
        return all_exps[idx - 1]
    except ValueError:
        pass

    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if exp is None:
        console.print(f"[red]Experiment '{experiment_id}' not found.[/red]")
        raise typer.Exit(1)
    return exp


def _safe_dirname(name: str) -> str:
    """Convert an experiment name to a filesystem-safe directory name."""
    return re.sub(r"[^\w\-]", "_", name)


def _inject_truststore() -> None:
    """Trust the OS certificate store (needed behind a TLS-intercepting proxy)."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass


def _print_run_summary(experiment: Experiment, db) -> None:
    runs = db.query(Run).filter(Run.experiment_id == experiment.id).all()
    metrics = db.query(Metric).filter(Metric.experiment_id == experiment.id).all()

    status_counts: dict[str, int] = {}
    for r in runs:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    table = Table(title="Experiment Summary", show_header=True, header_style="bold cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Name", experiment.name)
    table.add_row("ID", experiment.id)
    table.add_row("Status", experiment.status)
    table.add_row("Total runs", str(len(runs)))
    for status, count in sorted(status_counts.items()):
        table.add_row(f"  {status}", str(count))
    table.add_row("Total cost", f"${experiment.total_cost_usd:.4f}")

    for m in metrics:
        if m.metric_name == "stability_score_mean":
            table.add_row(f"Mean SS ({m.scope_key})", f"{m.metric_value:.3f}")
    for m in metrics:
        if m.metric_name == "control_flip_rate":
            pairs = json.loads(m.metric_metadata or "{}").get("pairs", 0)
            table.add_row(
                f"Noise floor ({m.scope_key})",
                f"control flip rate {m.metric_value:.3f} over {pairs} control run(s)",
            )

    console.print(table)

    ts = sorted(
        [m for m in metrics if m.metric_name == "transformation_sensitivity"],
        key=lambda m: m.metric_value or 0.0,
        reverse=True,
    )
    flips = {m.scope_key: m.metric_value for m in metrics if m.metric_name == "flip_rate"}
    if ts:
        ts_table = Table(title="Transformation Sensitivity", show_header=True, header_style="bold cyan")
        ts_table.add_column("Agent")
        ts_table.add_column("Transformation")
        ts_table.add_column("Sensitivity (G)", justify="right")
        ts_table.add_column("Flip rate", justify="right")
        for m in ts:
            parts = m.scope_key.split("|", 1)
            agent = parts[0]
            transform = parts[1] if len(parts) > 1 else "N/A"
            flip = flips.get(m.scope_key)
            ts_table.add_row(
                agent, transform, f"{m.metric_value:.3f}",
                f"{flip:.3f}" if flip is not None else "N/A",
            )
        console.print(ts_table)
    _print_similarity(metrics)


def _print_similarity(metrics: list[Metric]) -> None:
    """Changed-line similarity to the original per transformation, against the control runs."""
    means = [m for m in metrics if m.metric_name == "changed_line_similarity_mean"]
    if not means:
        return
    versus = {
        m.scope_key: m for m in metrics if m.metric_name == "changed_line_similarity_vs_control"
    }
    controls = [m for m in metrics if m.metric_name == "control_changed_line_similarity"]
    table = Table(
        title="Changed-line similarity to the original (tests exploratory)",
        show_header=True, header_style="bold cyan",
    )
    columns = ("Agent", "Variant", "Mean [95% CI]", "Diff vs repeat [95% CI]", "Wilcoxon p", "n")
    for column in columns:
        table.add_column(column, justify="left" if column in ("Agent", "Variant") else "right")

    def interval(m: Metric) -> str:
        meta = json.loads(m.metric_metadata or "{}")
        return f"{m.metric_value:+.3f} [{meta['ci_low']:+.3f}, {meta['ci_high']:+.3f}]"

    def mean_interval(m: Metric) -> str:
        meta = json.loads(m.metric_metadata or "{}")
        return f"{m.metric_value:.3f} [{meta['ci_low']:.3f}, {meta['ci_high']:.3f}]"

    for m in controls:
        n = json.loads(m.metric_metadata or "{}").get("n", "")
        table.add_row(m.scope_key, "repeat of original", mean_interval(m), "-", "-", str(n))
    for m in sorted(means, key=lambda m: m.metric_value):
        agent, _, transformation = m.scope_key.partition("|")
        vs = versus.get(m.scope_key)
        p = json.loads(vs.metric_metadata or "{}").get("wilcoxon_p") if vs else None
        table.add_row(
            agent, transformation, mean_interval(m), interval(vs) if vs else "-",
            f"{p:.4f}" if p is not None else "-",
            str(json.loads(m.metric_metadata or "{}").get("n", "")),
        )
    console.print(table)


def _print_originals(experiment: Experiment, db) -> None:
    """Originals-only mode: outcome and the files in the gold patch and in the patch, per issue."""
    from stability_eval.metrics.originals import original_results, success_count

    results = original_results(db, experiment.id)
    table = Table(title="Original runs", show_header=True, header_style="bold cyan")
    for column in ("Issue", "Status", "Outcome", "Files in gold", "Files in patch"):
        table.add_column(column)
    for r in results:
        table.add_row(
            r.issue_id, r.status, r.outcome,
            "\n".join(r.files_in_gold) if r.files_in_gold is not None else "(no gold patch)",
            "\n".join(r.files_in_patch) or "-",
        )
    console.print(table)
    excluded = sum(1 for r in results if r.outcome == "excluded")
    console.print(
        f"[bold]Success:[/bold] {success_count(results)} of {len(results)} original run(s)"
        + (f" ({excluded} excluded: did not complete normally)" if excluded else "")
    )


def _print_estimate(exp_config: ExperimentConfig, cost_per_run: float) -> None:
    """The planned runs, their expected cost and the cost caps.

    No API call. The database is only read (after the usual in-place schema upgrade): no
    experiment, run or variant is created.
    """
    from rich.markup import escape

    from stability_eval.execution.plan import (
        ESTIMATED_COST_PER_VARIANT_USD,
        plan_runs,
        preflight,
    )
    from stability_eval.transformations.llm_backed._api import TRANSFORMATION_MODEL

    plan = plan_runs(exp_config)
    real = exp_config.execution_mode == "real"
    each = f"{plan.issues} issue(s) x {plan.agents} agent(s)"
    per_run_caps = sorted({
        float(agent.params.get("cost_cap_usd", settings.DEFAULT_COST_CAP_USD))
        for agent in exp_config.agents
    })

    console.print(
        f"[bold]Estimate:[/bold] {exp_config.experiment_name}  "
        f"[dim]mode={exp_config.execution_mode}"
        f"{'  originals only' if exp_config.originals_only else ''}  "
        "(nothing is run: no API call, no experiment record)[/dim]"
    )
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Planned runs", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("How")
    table.add_row(
        "Originals", str(plan.originals), f"{each} x {plan.runs_per_variant} run(s) per variant"
    )
    table.add_row(
        "Variants", str(plan.variants),
        f"{each} x {plan.transformations} transformation(s) x {plan.runs_per_variant} run(s)",
    )
    table.add_row(
        "Control repeats", str(plan.controls),
        f"{each} x {plan.control_repeats} re-run(s) of the original",
    )
    table.add_row("Total", f"[bold]{plan.total}[/bold]", "")
    console.print(table)

    if real:
        console.print(
            f"[bold]Expected cost:[/bold] ${plan.total * cost_per_run:.2f}  "
            f"({plan.total} runs x ${cost_per_run:.3f} per run, the measured mean of the LLM "
            "Baseline with the submit_patch tool)"
        )
    else:
        console.print(
            f"[bold]Expected cost:[/bold] $0.00  ({exp_config.execution_mode} mode makes no API call)"
        )
    console.print(
        f"[bold]Hard cost cap:[/bold] ${exp_config.cost_limit_usd:.2f} for the experiment "
        "(cost_limit_usd: once the runs' total reaches it the experiment stops, status "
        "cost_exceeded)"
    )
    console.print(
        "[bold]Per-run cap:[/bold] "
        + ", ".join(f"${cap:.2f}" for cap in per_run_caps)
        + " (cost_cap_usd: a run that costs more is recorded as cost_exceeded)"
    )

    create_all()
    with get_db() as db:
        check = preflight(exp_config, db)
    found = len(exp_config.issues.issue_ids) - len(check.missing_issues)
    console.print(
        f"[bold]Issues in the database:[/bold] {found} of {len(exp_config.issues.issue_ids)}, "
        f"{found - len(check.without_gold)} with a gold patch"
    )
    if check.missing_issues:
        console.print(
            "[red]Not in the database (seed them before running): "
            + escape(", ".join(check.missing_issues)) + "[/red]"
        )
    if check.without_gold:
        console.print(
            "[yellow]No gold patch (outcome falls back to 'valid diff only'): "
            + escape(", ".join(check.without_gold)) + "[/yellow]"
        )
    n_generate = len(check.variants_to_generate)
    if real and n_generate:
        console.print(
            f"[bold]Variant generation:[/bold] {n_generate} LLM-backed variant(s) not cached yet, "
            f"generated by {TRANSFORMATION_MODEL}: ~${n_generate * ESTIMATED_COST_PER_VARIANT_USD:.2f} "
            f"at ~${ESTIMATED_COST_PER_VARIANT_USD:.3f} each (more if quality retries are needed); "
            "not counted by the cost caps"
        )
    elif real:
        console.print("[bold]Variant generation:[/bold] none (every LLM-backed variant is cached)")


def _generate_only(exp_config: ExperimentConfig) -> None:
    """Generate and quality-check every variant, print their status, and stop before any agent."""
    from rich.markup import escape

    from stability_eval.execution.plan import enabled_transformations
    from stability_eval.execution.variants import (
        EXCLUDED,
        NOOP,
        NOT_GENERATED,
        OK,
        generate_variants,
    )
    from stability_eval.transformations.cache import TransformationError

    if not enabled_transformations(exp_config):
        console.print("No transformation is applied (originals only): no variant to generate.")
        return
    if exp_config.execution_mode == "real":
        _inject_truststore()
    console.print(
        f"[bold]Generating variants:[/bold] {exp_config.experiment_name}  "
        f"[dim]mode={exp_config.execution_mode}  (no agent call, no experiment record)[/dim]"
    )
    create_all()
    with get_db() as db:
        try:
            statuses = generate_variants(exp_config, db)
        except (TransformationError, ValueError) as exc:
            db.commit()  # keep the variants generated before the failure
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)

    colors = {OK: "green", NOOP: "yellow", EXCLUDED: "red"}
    table = Table(title="Variants", show_header=True, header_style="bold cyan")
    for column in ("Issue", "Transformation", "Status", "Reason", "Cost"):
        table.add_column(column, justify="right" if column == "Cost" else "left")
    for s in statuses:
        reason = s.reason or ""
        reason = reason if len(reason) <= 160 else reason[:160] + "…"
        table.add_row(
            s.issue_id, s.transformation,
            f"[{colors.get(s.status, 'dim')}]{s.status}[/]" + (" [dim](cached)[/dim]" if s.cached else ""),
            escape(reason),
            f"${s.cost_usd:.4f}",
        )
    console.print(table)

    summary = Table(title="Per transformation", show_header=True, header_style="bold cyan")
    for column in ("Transformation", OK, NOOP, EXCLUDED, NOT_GENERATED, "Cost"):
        summary.add_column(column, justify="left" if column == "Transformation" else "right")
    for name in dict.fromkeys(s.transformation for s in statuses):
        mine = [s for s in statuses if s.transformation == name]
        counts = [sum(1 for s in mine if s.status == status)
                  for status in (OK, NOOP, EXCLUDED, NOT_GENERATED)]
        summary.add_row(name, *map(str, counts), f"${sum(s.cost_usd for s in mine):.4f}")
    console.print(summary)

    generated = [s for s in statuses if not s.cached and s.status != NOT_GENERATED]
    console.print(
        f"[bold]Generation cost:[/bold] ${sum(s.cost_usd for s in statuses):.4f} for "
        f"{len(generated)} variant(s) generated now; {sum(s.cached for s in statuses)} from the "
        "cache. No agent was called."
    )


# ── Commands ─────────────────────────────────────────────────────────────────

@app.command()
def run(
    config: Path = typer.Option(..., "--config", help="Path to experiment config JSON"),
    mode: Optional[str] = typer.Option(
        None, "--mode", help="Override execution_mode: mock | dry_run | real"
    ),
    originals_only: bool = typer.Option(
        False, "--originals-only",
        help="Run only the original variant of every issue (also: originals_only in the config)",
    ),
    estimate: bool = typer.Option(
        False, "--estimate", "--dry-run",
        help="Print the planned runs, the expected cost and the cost caps, then stop: no API "
             "call, no experiment record (unlike --mode dry_run, which records skipped runs)",
    ),
    cost_per_run: Optional[float] = typer.Option(
        None, "--cost-per-run", min=0.0,
        help="Expected cost of one real run for --estimate (default: the measured $0.015)",
    ),
    generate_only: bool = typer.Option(
        False, "--generate-only",
        help="Generate and quality-check every variant (in real mode an uncached LLM-backed one "
             "costs Haiku calls), print each one's status and generation cost, then stop: no "
             "agent call, no experiment record",
    ),
) -> None:
    """Load config, run experiment, compute metrics, and print summary table.

    With --originals-only (or "originals_only": true in the config) no transformation is applied:
    each issue's original runs once per agent and replica, and the per-issue outcome, gold-patch
    files and patch files are printed with the overall success count. Control repeats are
    skipped in that mode.

    With --estimate (alias --dry-run) nothing runs: the planned originals, variants and control
    repeats are printed with the expected cost, the cost caps, and what the database is missing.

    With --generate-only every variant is taken from the cache or generated and quality-checked,
    then a table shows, per issue and transformation, ok / noop / excluded (with the reason) and
    the generation cost; no agent is called and no experiment is recorded.
    """
    if not config.exists():
        console.print(f"[red]Config file not found: {config}[/red]")
        raise typer.Exit(1)

    try:
        raw: dict = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON in config: {exc}[/red]")
        raise typer.Exit(1)

    if mode is not None:
        valid = {"mock", "dry_run", "real"}
        if mode not in valid:
            console.print(f"[red]Invalid mode '{mode}'. Choose from: {', '.join(sorted(valid))}[/red]")
            raise typer.Exit(1)
        raw["execution_mode"] = mode
    if originals_only:
        raw["originals_only"] = True

    try:
        exp_config = ExperimentConfig.model_validate(raw)
    except Exception as exc:
        console.print(f"[red]Invalid experiment config: {exc}[/red]")
        raise typer.Exit(1)

    if estimate and generate_only:
        console.print("[red]Use --estimate or --generate-only, not both.[/red]")
        raise typer.Exit(1)

    if estimate:
        from stability_eval.execution.plan import ESTIMATED_COST_PER_RUN_USD

        _print_estimate(
            exp_config, ESTIMATED_COST_PER_RUN_USD if cost_per_run is None else cost_per_run
        )
        return

    if generate_only:
        _generate_only(exp_config)
        return

    create_all()

    console.print(
        f"[bold]Running:[/bold] {exp_config.experiment_name}  "
        f"[dim]mode={exp_config.execution_mode}  "
        f"issues={len(exp_config.issues.issue_ids)}  "
        f"agents={len(exp_config.agents)}"
        f"{'  originals only' if exp_config.originals_only else ''}[/dim]"
    )

    from rich.markup import escape

    from stability_eval.transformations.cache import TransformationError

    with get_db() as db:
        runner = ExperimentRunner(exp_config, db)
        try:
            experiment = runner.run()
        except TransformationError as exc:
            # Real mode never substitutes a placeholder for a variant it could not generate.
            db.commit()  # keep the runs that completed and the experiment's "failed" status
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]OK[/green] status: {experiment.status}")

        MetricsEngine().compute(experiment.id, db)
        db.refresh(experiment)

        if exp_config.originals_only:
            _print_originals(experiment, db)
        else:
            _print_run_summary(experiment, db)


@app.command()
def preview(
    issue_id: str = typer.Option(..., "--issue", help="Issue ID (external_id or UUID)"),
    transform: str = typer.Option(..., "--transform", help="Transformation name to apply"),
) -> None:
    """Show original issue and transformed text side by side, with the variant's provenance.

    Uses the cached variant for the current transform_version and generator, else generates it
    (an LLM-backed one calls the API: real mode, never a placeholder).
    """
    from rich.markup import escape

    from stability_eval.transformations import transformation_registry
    from stability_eval.transformations.base import IssueRecord
    from stability_eval.transformations.cache import TransformationCache, TransformationError

    try:
        transform_cls = transformation_registry.get(transform)
    except KeyError:
        available = transformation_registry.list_names()
        console.print(
            f"[red]Unknown transformation '{transform}'. Available: {', '.join(available)}[/red]"
        )
        raise typer.Exit(1)

    create_all()
    with get_db() as db:
        issue = (
            db.query(Issue)
            .filter((Issue.external_id == issue_id) | (Issue.id == issue_id))
            .first()
        )
        if issue is None:
            console.print(f"[red]Issue '{issue_id}' not found.[/red]")
            raise typer.Exit(1)

        issue_record = IssueRecord(
            issue_id=issue.id,
            repo_name=issue.repo_name,
            text=issue.issue_text,
            metadata={"external_id": issue.external_id or issue.id},
        )
        try:
            ti = TransformationCache(db).variant(transform_cls(), issue_record, {}, mode="real")
        except TransformationError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)
        original_text = issue.issue_text
        transformed_text = ti.transformed_text
        provenance_line = (
            f"{ti.generator} · v{ti.transform_version} · {ti.generation_mode}"
            + (" · no-op" if ti.noop else "")
            + (" · quality warning" if ti.quality_warning else "")
        )

    original_panel = Panel(original_text, title="[blue]Original[/blue]", border_style="blue")
    transformed_panel = Panel(
        transformed_text,
        title=f"[green]Transformed ({transform})[/green]",
        subtitle=escape(provenance_line),
        border_style="green",
    )
    console.print(Columns([original_panel, transformed_panel]))


@app.command()
def export(
    experiment_id: str = typer.Option(..., "--experiment-id", help="Experiment UUID or 1-based index"),
    format: str = typer.Option(..., "--format", help="Output format: csv | json | md"),
) -> None:
    """Export results for the given experiment to the results/ directory."""
    valid_formats = {"csv", "json", "md"}
    if format not in valid_formats:
        console.print(f"[red]Invalid format '{format}'. Choose from: {', '.join(sorted(valid_formats))}[/red]")
        raise typer.Exit(1)

    create_all()

    with get_db() as db:
        experiment = _resolve_experiment(db, experiment_id)

        out_dir = Path("results") / _safe_dirname(experiment.name)
        out_dir.mkdir(parents=True, exist_ok=True)

        if format == "csv":
            paths = CSVExporter().export(experiment, out_dir, db)
            artifact_type = "csv"
        elif format == "json":
            paths = [JSONExporter().export(experiment, out_dir, db)]
            artifact_type = "json"
        else:  # md
            paths = [ReportGenerator().export(experiment, out_dir, db)]
            artifact_type = "report_md"

        for path in paths:
            artifact = ExportArtifact(
                experiment_id=experiment.id,
                artifact_type=artifact_type,
                file_path=str(path),
                file_size_bytes=path.stat().st_size,
            )
            db.add(artifact)
            console.print(f"[green]OK[/green] Exported: {path}")


@app.command("load-swebench")
def load_swebench(
    ids: str = typer.Option(..., "--ids", help="Comma-separated SWE-bench Lite instance ids"),
    from_huggingface: bool = typer.Option(
        False, "--from-huggingface",
        help="Download the dataset instead of reading the bundled data/swebench_lite_issues.json",
    ),
) -> None:
    """Load SWE-bench Lite issues and their gold patches (hidden ground truth, never shown to agents).

    Issues already in the database keep their text and only gain the gold patch, which the
    metrics engine needs to score localization success (SPEC section 13). Reads the bundled
    file by default (offline); --from-huggingface downloads the dataset instead.
    """
    from rich.markup import escape

    from stability_eval.data.loaders.swebench import (
        load_bundle,
        load_swebench_lite,
        store_instances,
    )
    from stability_eval.metrics.patch_similarity import patch_files

    instance_ids = [part.strip() for part in ids.split(",") if part.strip()]
    if not instance_ids:
        console.print("[red]No instance ids given.[/red]")
        raise typer.Exit(1)

    try:
        if from_huggingface:
            _inject_truststore()
            instances = load_swebench_lite(instance_ids)
        else:
            instances = load_bundle(instance_ids)
    except KeyError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(1)

    create_all()
    with get_db() as db:
        store_instances(db, instances)

    for instance in instances:
        n_files = len(patch_files(instance.gold_patch))
        console.print(
            f"[green]OK[/green] {instance.instance_id}: gold patch stored "
            f"({n_files} file(s); hidden from agents)"
        )


@app.command("record-fixtures")
def record_fixtures(
    experiment_id: str = typer.Option(..., "--experiment-id", help="Experiment UUID or 1-based index"),
) -> None:
    """Record every run of the experiment as a MockReplay fixture, so mock mode replays it exactly.

    One fixture per issue and variant: the run's output, the outputs of the original's control
    runs, and the variant each run used (see stability_eval/fixtures/recorder.py). Replay with
    the experiment's config and --mode mock.
    """
    from rich.markup import escape

    from stability_eval.fixtures.recorder import record_experiment_fixtures

    create_all()
    fixtures_dir = Path(settings.FIXTURES_DIR)

    with get_db() as db:
        experiment = _resolve_experiment(db, experiment_id)
        try:
            recorded = record_experiment_fixtures(db, experiment.id, fixtures_dir)
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(1)

    for fixture in recorded:
        repeats = f", {fixture.control_repeats} control run(s)" if fixture.control_repeats else ""
        state = "[green]written[/green]" if fixture.changed else "[dim]unchanged[/dim]"
        console.print(f"{state} {fixture.path.name} ({fixture.status}{repeats})")
    changed = sum(fixture.changed for fixture in recorded)
    console.print(
        f"Recorded {len(recorded)} fixture(s) in {fixtures_dir} "
        f"({changed} written, {len(recorded) - changed} unchanged)"
    )


@app.command("recompute-metrics")
def recompute_metrics(
    experiment_id: str = typer.Option(..., "--experiment-id", help="Experiment UUID or 1-based index"),
) -> None:
    """Delete the experiment's stored metrics and compute them again from its runs.

    Runs are never touched; metrics are derived from them, so this only adds metrics introduced
    after the experiment ran (e.g. the changed-line similarity) and refreshes the others.
    """
    create_all()
    with get_db() as db:
        experiment = _resolve_experiment(db, experiment_id)
        removed = db.query(Metric).filter(Metric.experiment_id == experiment.id).delete()
        stored = MetricsEngine().compute(experiment.id, db)
        db.refresh(experiment)
        console.print(
            f"[green]OK[/green] {experiment.id}: removed {removed} metric row(s), "
            f"stored {len(stored)}"
        )
        _print_run_summary(experiment, db)


@app.command("list-experiments")
def list_experiments() -> None:
    """Print a table of all experiments with id, name, status, cost, and date."""
    create_all()

    with get_db() as db:
        rows = db.query(Experiment).order_by(Experiment.created_at).all()
        # Snapshot all needed fields before the session closes.
        exp_rows = [
            (exp.id, exp.name, exp.status, exp.total_cost_usd, exp.created_at)
            for exp in rows
        ]

    if not exp_rows:
        console.print("[yellow]No experiments found.[/yellow]")
        return

    table = Table(title="Experiments", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Cost (USD)", justify="right")
    table.add_column("Date")

    for i, (eid, name, status, cost, created_at) in enumerate(exp_rows, start=1):
        date = (created_at or "")[:19].replace("T", " ")
        status_style = (
            "green" if status == "completed"
            else "red" if status in ("failed", "cost_exceeded")
            else "yellow"
        )
        table.add_row(
            str(i),
            eid[:8] + "...",
            name,
            f"[{status_style}]{status}[/{status_style}]",
            f"${cost:.4f}",
            date,
        )

    console.print(table)


if __name__ == "__main__":
    app()
