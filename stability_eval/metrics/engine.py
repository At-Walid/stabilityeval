from __future__ import annotations

import json
import logging
from collections import Counter

from sqlalchemy.orm import Session

from stability_eval.data.loaders.swebench import gold_patch_of
from stability_eval.data.models import Issue, Metric, Run, TransformedIssue
from stability_eval.metrics.changed_line_similarity import ChangedLineSimilarity
from stability_eval.metrics.outcome import (
    SCORED_STATUSES,
    SUCCESS,
    Localization,
    localize,
    run_outcome,
)
from stability_eval.metrics.sensitivity import (
    ControlFlipRate,
    FlipRate,
    TransformationSensitivity,
)
from stability_eval.metrics.stability_score import StabilityScore
from stability_eval.metrics.success import SuccessConsistency

log = logging.getLogger(__name__)


class MetricsEngine:
    """Compute and persist all active metrics for a completed experiment.

    Active metrics for the ICSE pilot: A (Success Consistency), F (Stability Score) and
    G (Transformation Sensitivity, a drop rate) with the symmetric ``flip_rate`` next to it, all
    computed from the per-run "localization success" outcome (stability_eval.metrics.outcome,
    SPEC section 13). Also stored:

    - ``control_flip_rate`` (scope "agent", key the agent): the run-to-run noise floor, from the
      control runs (``Run.control_repeat``, re-runs of the original). Control runs get an outcome
      like every run but never enter A, F or G;
    - changed-line similarity (stability_eval.metrics.changed_line_similarity): per compared run
      (scope "run", control runs included) ``changed_line_similarity`` to the issue's original
      run; per agent|transformation ``changed_line_similarity_mean`` (bootstrap CI and per-issue
      values in the metadata) and ``changed_line_similarity_vs_control`` (mean paired difference
      to the control runs, bootstrap CI, exploratory Wilcoxon p); per agent
      ``control_changed_line_similarity``, the noise floor;
    - per run (scope "run"): ``outcome`` (1/0) and, when the issue has a gold patch,
      ``localization_match`` (1/0) and ``file_overlap_jaccard``, with the files in the patch and
      in the gold patch as metadata;
    - exclusions: ``excluded_runs_status``, ``excluded_runs_quality_warning`` and
      ``excluded_runs_noop`` (scope "experiment"), and ``excluded_quality_warning`` and
      ``excluded_noop`` per agent|transformation (scope "agent"). Runs that did not complete
      normally (timeout, cost_exceeded, error, ...), runs on variants flagged ``quality_warning``
      and runs on no-op variants (identical to the original after whitespace normalization) get
      no outcome and do not enter A, F or G (SC/TS). A run on a flagged or no-op variant counts
      under the variant's reason whatever its status (the runner records it as
      "skipped_variant" without calling the agent).
    """

    def compute(self, experiment_id: str, db: Session) -> list[Metric]:
        """Run all active metrics and persist results to the Metric table.

        Args:
            experiment_id: Primary key of the Experiment to evaluate.
            db:            SQLAlchemy session (caller owns the transaction).

        Returns the list of Metric ORM objects added to the session.
        """
        rows = self._fetch_runs(experiment_id, db)
        if not rows:
            log.warning("No runs found for experiment %s", experiment_id)
            return []

        stored: list[Metric] = []
        run_data: list[dict] = []
        control_data: list[dict] = []  # control runs: scored, but kept out of A/F/G
        excluded_status: list[dict] = []
        excluded_quality: list[dict] = []
        excluded_noop: list[dict] = []
        without_gold: list[dict] = []
        variant_cells: set[tuple[str, str]] = set()

        for run, ti, issue in rows:
            ref = {
                "run_id": run.id,
                "agent_name": run.agent_name,
                "issue_id": issue.external_id or issue.id,
                "transformation_name": ti.transformation_name,
                "is_original": ti.is_original,
                "status": run.status,
            }
            if not ti.is_original:
                variant_cells.add((run.agent_name, ti.transformation_name))
            # The variant's own exclusion first: a run on an excluded or no-op variant (recorded
            # without calling the agent, status "skipped_variant") counts under that reason.
            if ti.quality_warning and not ti.is_original:
                excluded_quality.append(ref)
                continue
            if ti.noop and not ti.is_original:
                excluded_noop.append(ref)
                continue
            if run.status not in SCORED_STATUSES:
                excluded_status.append(ref)
                continue

            gold_patch = gold_patch_of(issue)
            localization = localize(run.patch, gold_patch) if gold_patch else None
            if localization is None:
                without_gold.append(ref)
            outcome = run_outcome(
                run.status, localization.localization_match if localization else None
            )
            stored.extend(self._store_run_metrics(db, experiment_id, run, outcome, localization))
            row = {**ref, "outcome": outcome, "patch": run.patch}
            (control_data if run.control_repeat else run_data).append(row)

        stored.extend(
            self._store_exclusions(
                db, experiment_id, excluded_status, excluded_quality, excluded_noop, variant_cells
            )
        )
        if without_gold:
            log.warning(
                "%d scored run(s) have no gold patch, so their outcome is 'valid diff extracted' "
                "only (localization not checked); issues: %s",
                len(without_gold),
                ", ".join(sorted({ref["issue_id"] for ref in without_gold})),
            )
        if not run_data:
            log.warning("No scorable runs for experiment %s", experiment_id)
            db.flush()
            return stored

        # --- Metric A: Success Consistency (per agent × issue) ---------------
        sc_results = SuccessConsistency().compute(run_data)

        for (agent, issue_id), sc_value in sc_results.items():
            stored.append(
                self._store(db, experiment_id, "agent_issue", f"{agent}|{issue_id}",
                            "success_consistency", sc_value)
            )

        # --- Metric F: Stability Score ----------------------------------------
        ss = StabilityScore().compute(run_data, sc_results=sc_results)

        for (agent, issue_id), ss_value in ss["per_issue"].items():
            stored.append(
                self._store(db, experiment_id, "agent_issue", f"{agent}|{issue_id}",
                            "stability_score", ss_value)
            )

        for agent, mean_ss in ss["per_agent"].items():
            stored.append(
                self._store(db, experiment_id, "agent", agent,
                            "stability_score_mean", mean_ss)
            )

        # --- Metric G: Transformation Sensitivity (per agent × transform) -----
        ts_results = TransformationSensitivity().compute(run_data)

        for (agent, transform), ts_value in ts_results.items():
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transform}",
                            "transformation_sensitivity", ts_value)
            )

        # --- Symmetric flip rate (next to G): any change of outcome, either way -----
        for (agent, transform), flip_value in FlipRate().compute(run_data).items():
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transform}",
                            "flip_rate", flip_value)
            )

        # --- Noise floor: control re-runs of the original against the original ----
        for agent, control in ControlFlipRate().compute(run_data, control_data).items():
            stored.append(
                self._store(db, experiment_id, "agent", agent, "control_flip_rate",
                            control["value"],
                            {"pairs": control["pairs"], "flipped": control["flipped"]})
            )

        # --- Changed-line similarity to the original run, against the control runs ----------
        stored.extend(self._store_similarity(db, experiment_id, run_data, control_data))

        db.flush()
        log.info(
            "MetricsEngine: stored %d metric rows for experiment %s",
            len(stored), experiment_id,
        )
        return stored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_runs(experiment_id: str, db: Session) -> list[tuple[Run, TransformedIssue, Issue]]:
        return (
            db.query(Run, TransformedIssue, Issue)
            .join(TransformedIssue, Run.transformed_issue_id == TransformedIssue.id)
            .join(Issue, TransformedIssue.issue_id == Issue.id)
            .filter(Run.experiment_id == experiment_id)
            .order_by(Run.created_at)
            .all()
        )

    def _store_run_metrics(
        self,
        db: Session,
        experiment_id: str,
        run: Run,
        outcome: str | None,
        localization: Localization | None,
    ) -> list[Metric]:
        basis = "localization" if localization is not None else "valid_diff_only"
        metrics = [
            self._store(db, experiment_id, "run", run.id, "outcome",
                        1.0 if outcome == SUCCESS else 0.0,
                        {"status": run.status, "basis": basis})
        ]
        if localization is not None:
            files = {
                "files_in_patch": localization.files_in_patch,
                "files_in_gold": localization.files_in_gold,
            }
            metrics.append(
                self._store(db, experiment_id, "run", run.id, "localization_match",
                            float(localization.localization_match), files)
            )
            metrics.append(
                self._store(db, experiment_id, "run", run.id, "file_overlap_jaccard",
                            localization.file_overlap_jaccard, files)
            )
        return metrics

    def _store_similarity(
        self,
        db: Session,
        experiment_id: str,
        run_data: list[dict],
        control_data: list[dict],
    ) -> list[Metric]:
        results = ChangedLineSimilarity().compute(run_data, control_data)
        control_runs = {row["run_id"] for row in control_data}
        stored = [
            self._store(db, experiment_id, "run", run_id, "changed_line_similarity", value,
                        {"original_run_id": original_run_id,
                         "control_repeat": run_id in control_runs})
            for run_id, (value, original_run_id) in results.per_run.items()
        ]
        for (agent, transformation), summary in sorted(results.per_transformation.items()):
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transformation}",
                            "changed_line_similarity_mean", summary.mean, summary.metadata())
            )
        for (agent, transformation), comparison in sorted(results.versus_control.items()):
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transformation}",
                            "changed_line_similarity_vs_control", comparison.mean_difference,
                            comparison.metadata())
            )
        for agent, summary in sorted(results.control.items()):
            stored.append(
                self._store(db, experiment_id, "agent", agent, "control_changed_line_similarity",
                            summary.mean, summary.metadata())
            )
        return stored

    def _store_exclusions(
        self,
        db: Session,
        experiment_id: str,
        excluded_status: list[dict],
        excluded_quality: list[dict],
        excluded_noop: list[dict],
        variant_cells: set[tuple[str, str]],
    ) -> list[Metric]:
        if excluded_status:
            log.warning(
                "Excluded %d run(s) from metrics A/F/G because they did not complete normally: %s",
                len(excluded_status), "; ".join(_describe(ref) for ref in excluded_status),
            )
        if excluded_quality:
            log.warning(
                "Excluded %d run(s) on quality-warning variants (identifier retention failed "
                "after retries) from metrics A/F/G: %s",
                len(excluded_quality), "; ".join(_describe(ref) for ref in excluded_quality),
            )
        if excluded_noop:
            log.warning(
                "Excluded %d run(s) on no-op variants (identical to the original after "
                "whitespace normalization) from metrics A/F/G: %s",
                len(excluded_noop), "; ".join(_describe(ref) for ref in excluded_noop),
            )
        quality_per_cell = Counter(
            (ref["agent_name"], ref["transformation_name"]) for ref in excluded_quality
        )
        noop_per_cell = Counter(
            (ref["agent_name"], ref["transformation_name"]) for ref in excluded_noop
        )
        stored = [
            self._store(
                db, experiment_id, "experiment", experiment_id, "excluded_runs_status",
                float(len(excluded_status)),
                {"by_status": dict(Counter(ref["status"] for ref in excluded_status)),
                 "runs": excluded_status},
            ),
            self._store(
                db, experiment_id, "experiment", experiment_id, "excluded_runs_quality_warning",
                float(len(excluded_quality)),
                {"by_transformation": dict(
                    Counter(ref["transformation_name"] for ref in excluded_quality)),
                 "runs": excluded_quality},
            ),
            self._store(
                db, experiment_id, "experiment", experiment_id, "excluded_runs_noop",
                float(len(excluded_noop)),
                {"by_transformation": dict(
                    Counter(ref["transformation_name"] for ref in excluded_noop)),
                 "runs": excluded_noop},
            ),
        ]
        for agent, transformation in sorted(variant_cells):
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transformation}",
                            "excluded_quality_warning",
                            float(quality_per_cell.get((agent, transformation), 0)))
            )
            stored.append(
                self._store(db, experiment_id, "agent", f"{agent}|{transformation}",
                            "excluded_noop",
                            float(noop_per_cell.get((agent, transformation), 0)))
            )
        return stored

    @staticmethod
    def _store(
        db: Session,
        experiment_id: str,
        scope: str,
        scope_key: str,
        metric_name: str,
        value: float,
        metadata: dict | None = None,
    ) -> Metric:
        m = Metric(
            experiment_id=experiment_id,
            scope=scope,
            scope_key=scope_key,
            metric_name=metric_name,
            metric_value=value,
            metric_metadata=json.dumps(metadata) if metadata is not None else None,
        )
        db.add(m)
        return m


def _describe(ref: dict) -> str:
    return f"{ref['issue_id']}/{ref['transformation_name']} [{ref['status']}] run {ref['run_id']}"
