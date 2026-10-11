from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from stableagent.data.models import Experiment, Issue, Metric, Run, TransformedIssue
from stableagent.export._metric_rows import provenance
from stableagent.metrics.outcome import (
    displayed_outcome,
    exclusion_counts,
    recorded_outcomes,
    recorded_run_values,
)


def _cell(text: str) -> str:
    """``text`` safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


class ReportGenerator:
    def export(self, experiment: Experiment, output_dir: Path, db: Session) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "experiment_report.md"
        path.write_text(self._build(experiment, db), encoding="utf-8")
        return path

    def _build(self, experiment: Experiment, db: Session) -> str:
        config = json.loads(experiment.config)
        runs = db.query(Run).filter(Run.experiment_id == experiment.id).all()
        metrics = db.query(Metric).filter(Metric.experiment_id == experiment.id).all()
        metric_tuples = [(m.scope, m.scope_key, m.metric_name, m.metric_value) for m in metrics]
        recorded = recorded_outcomes(metric_tuples)
        jaccard = recorded_run_values(metric_tuples, "file_overlap_jaccard")
        exclusions = exclusion_counts(metric_tuples)

        lines: list[str] = []

        # ── Header ──────────────────────────────────────────────────────────
        lines += [f"# Experiment Report: {experiment.name}", ""]

        # ── Summary ─────────────────────────────────────────────────────────
        agents = [a["name"] for a in config.get("agents", [])]
        transforms = [t["name"] for t in config.get("transformations", []) if t.get("enabled")]
        issue_ids = config.get("issues", {}).get("issue_ids", [])
        date = (experiment.created_at or "")[:10]

        lines += [
            "## Summary", "",
            f"- **Date:** {date or 'N/A'}",
            f"- **Status:** {experiment.status}",
            f"- **Agents:** {', '.join(agents) or 'None'}",
            f"- **Issues:** {len(issue_ids)}",
            f"- **Transformations:** {', '.join(transforms) or 'None'}",
            f"- **Total runs:** {len(runs)}",
            f"- **Total cost:** ${experiment.total_cost_usd:.4f}",
            "",
            "### Excluded from metrics A/F/G",
            "",
            f"- **Runs that did not complete normally** (timeout, cost cap, error): "
            f"{exclusions['status']}",
            f"- **Runs on quality-warning variants** (identifier retention failed after retries): "
            f"{exclusions['quality_warning']}",
        ]
        for transformation, count in sorted(exclusions["quality_warning_by_transformation"].items()):
            lines.append(f"  - {transformation}: {count}")
        lines.append(
            "- **Runs on no-op variants** (identical to the original after whitespace "
            f"normalization): {exclusions['noop']}"
        )
        for transformation, count in sorted(exclusions["noop_by_transformation"].items()):
            lines.append(f"  - {transformation}: {count}")
        lines.append("")

        # ── RQ1 — Stability ──────────────────────────────────────────────────
        lines += ["## RQ1 — Stability Results", ""]
        sc = {m.scope_key: m.metric_value for m in metrics if m.metric_name == "success_consistency"}
        ss = {m.scope_key: m.metric_value for m in metrics if m.metric_name == "stability_score"}
        mean_ss = [m for m in metrics if m.metric_name == "stability_score_mean"]

        if sc or ss:
            lines += [
                "| Scope | Success Consistency (A) | Stability Score (F) |",
                "|-------|------------------------|---------------------|",
            ]
            for key in sorted(set(list(sc) + list(ss))):
                sc_v = f"{sc[key]:.3f}" if key in sc else "N/A"
                ss_v = f"{ss[key]:.3f}" if key in ss else "N/A"
                lines.append(f"| {key} | {sc_v} | {ss_v} |")
            lines.append("")
            for m in mean_ss:
                lines.append(f"**Mean Stability Score ({m.scope_key}):** {m.metric_value:.3f}")
            lines.append("")
        else:
            lines += ["*No stability metrics computed (no eligible runs).*", ""]

        # ── RQ2 — Sensitivity ────────────────────────────────────────────────
        lines += ["## RQ2 — Transformation Sensitivity", ""]
        ts_metrics = sorted(
            [m for m in metrics if m.metric_name == "transformation_sensitivity"],
            key=lambda m: m.metric_value or 0.0,
            reverse=True,
        )
        flips = {m.scope_key: m.metric_value for m in metrics if m.metric_name == "flip_rate"}
        if ts_metrics:
            lines += [
                "TS is a drop rate (success → failure counts +1, failure → success −1); the flip "
                "rate counts any change of outcome between the original and the variant.",
                "",
                "| Agent | Transformation | Sensitivity (G) | Flip rate |",
                "|-------|---------------|-----------------|-----------|",
            ]
            for m in ts_metrics:
                parts = m.scope_key.split("|", 1)
                agent = parts[0]
                transform = parts[1] if len(parts) > 1 else "N/A"
                flip = flips.get(m.scope_key)
                flip_text = f"{flip:.3f}" if flip is not None else "N/A"
                lines.append(f"| {agent} | {transform} | {m.metric_value:.3f} | {flip_text} |")
            lines.append("")
            top = ts_metrics[0]
            top_parts = top.scope_key.split("|", 1)
            top_t = top_parts[1] if len(top_parts) > 1 else top.scope_key
            lines += [
                f"**Most disruptive transformation:** {top_t} "
                f"(sensitivity = {top.metric_value:.3f})",
                "",
            ]
        else:
            lines += ["*No transformation sensitivity metrics computed.*", ""]
        for m in metrics:
            if m.metric_name == "control_flip_rate":
                pairs = json.loads(m.metric_metadata or "{}").get("pairs", 0)
                lines += [
                    f"**Noise floor ({m.scope_key}):** control flip rate = {m.metric_value:.3f} "
                    f"over {pairs} control run(s), re-runs of the unchanged original. A flip "
                    "rate at or below it is indistinguishable from run-to-run variance.",
                    "",
                ]

        # ── Issue-Level Results ───────────────────────────────────────────────
        lines += ["## Issue-Level Results", ""]
        variants: dict[str, tuple[str, TransformedIssue]] = {}
        if runs:
            lines += [
                "| Issue | Transformation | Agent | Status | Outcome | File overlap (Jaccard) "
                "| Cost |",
                "|-------|----------------|-------|--------|---------|------------------------"
                "|------|",
            ]
            for run in runs:
                ti = db.query(TransformedIssue).filter_by(id=run.transformed_issue_id).first()
                issue = db.query(Issue).filter_by(id=ti.issue_id).first() if ti else None
                issue_label = (issue.external_id or issue.id) if issue else "unknown"
                transform_label = ti.transformation_name if ti else "unknown"
                if run.control_repeat:
                    transform_label += " (control)"
                cost = f"${run.cost_usd:.4f}" if run.cost_usd is not None else "N/A"
                outcome = displayed_outcome(run.id, run.status, recorded)
                overlap = f"{jaccard[run.id]:.3f}" if run.id in jaccard else "N/A"
                lines.append(
                    f"| {issue_label} | {transform_label} | "
                    f"{run.agent_name} | {run.status} | {outcome} | {overlap} | {cost} |"
                )
                if ti is not None:
                    variants.setdefault(ti.id, (issue_label, ti))
            lines.append("")
        else:
            lines += ["*No runs recorded for this experiment.*", ""]

        # ── Variant provenance ───────────────────────────────────────────────
        lines += [
            "## Variant Provenance", "",
            "What produced each issue text the agents saw (SPEC section 11.6). Placeholders are "
            "offline stand-ins from mock / dry-run mode, never generated variants.", "",
        ]
        if variants:
            lines += [
                "| Issue | Transformation | Generator | Transform version | Mode | No-op "
                "| Quality warning | Exclusion reason |",
                "|-------|----------------|-----------|-------------------|------|-------"
                "|-----------------|------------------|",
            ]
            for issue_label, ti in sorted(
                variants.values(), key=lambda item: (item[0], item[1].transformation_name)
            ):
                p = provenance(ti)
                reason = _cell(p["exclusion_reason"]) if p["exclusion_reason"] else ""
                lines.append(
                    f"| {issue_label} | {ti.transformation_name} | {p['generator']} | "
                    f"{p['transform_version'] or 'N/A'} | {p['generation_mode'] or 'N/A'} | "
                    f"{'yes' if p['noop'] else 'no'} | {'yes' if ti.quality_warning else 'no'} | "
                    f"{reason} |"
                )
            lines.append("")
        else:
            lines += ["*No variants.*", ""]

        # ── Methodology ───────────────────────────────────────────────────────
        lines += ["## Methodology", "", "### Transformations", ""]
        for t in config.get("transformations", []):
            flag = "enabled" if t.get("enabled") else "disabled"
            lines.append(f"- **{t['name']}** ({flag}): params = {json.dumps(t.get('params', {}))}")

        lines += [
            "",
            "### Metric Definitions",
            "",
            "- **Outcome (localization success):** success iff a valid unified diff was "
            "extracted and it modifies every file the gold patch modifies; otherwise failure. "
            "Without a gold patch, a valid diff counts as success. Weaker than test-based "
            "resolution, which is deferred to the larger study. The file overlap (Jaccard) "
            "between the patch's files and the gold patch's files is reported next to it.",
            "- **Excluded runs:** runs that did not complete normally, runs on quality-warning "
            "variants and runs on no-op variants have no outcome and do not enter A, F or G.",
            "- **A / Success Consistency (SC):** "
            "Fraction of variants sharing the same outcome as the original.",
            "- **F / Stability Score (SS):** "
            "Weighted aggregate of SC (and optionally patch similarity).",
            "- **G / Transformation Sensitivity (TS):** "
            "Mean drop in success rate caused by a transformation.",
            "- **Flip rate:** fraction of issues whose outcome changes, in either direction, "
            "between the original and the variant (TS lets opposite flips cancel out).",
            "- **Control flip rate (noise floor):** the same flip rate between the original run "
            "and its control runs, re-runs of the unchanged original; control runs never enter "
            "A, F or G.",
            "",
            "### Configuration Snapshot",
            "",
            "```json",
            json.dumps(config, indent=2),
            "```",
            "",
        ]

        return "\n".join(lines)
