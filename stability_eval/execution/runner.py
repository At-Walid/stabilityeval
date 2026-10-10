from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stability_eval.agents.base import AgentInput, ExecutionMode
from stability_eval.agents.llm_baseline import LLMBaselineAdapter
from stability_eval.agents.mock_replay import MockReplayAdapter
from stability_eval.config.experiment_schema import AgentConfig, ExperimentConfig
from stability_eval.config.settings import redact_api_key, settings
from stability_eval.data.models import (
    Experiment,
    Issue,
    Run,
    TransformedIssue as TransformedIssueModel,
)
from stability_eval.execution.cost_guard import CostGuard, CostLimitExceeded
from stability_eval.execution.plan import enabled_transformations, find_issue, plan_runs
from stability_eval.execution.variants import check_variants_can_be_generated
from stability_eval.transformations.base import ORIGINAL, IssueRecord
from stability_eval.transformations.cache import TransformationCache
from stability_eval.transformations.registry import transformation_registry

log = logging.getLogger(__name__)

# (fraction done, message): the dashboard shows it as a progress bar.
ProgressCallback = Callable[[float, str], None]
# The status of a run recorded on an excluded (quality-warning) or no-op variant: the agent is never
# called on such a variant, so nothing is paid for a run the metrics would exclude anyway.
SKIPPED_VARIANT = "skipped_variant"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentRunner:
    """Synchronous experiment runner.

    Iterates over agents × issues × transformation variants × run_index, then runs each issue's
    original ``control_repeats`` more times as control runs (``Run.control_repeat``, run_index
    after the original's own). Executes exactly the runs ``plan.plan_runs`` counts.
    Persists every Run to the database immediately after execution so that
    partial results survive a crash.

    Variants come from the transformation cache in the experiment's execution mode: in real mode
    an LLM-backed variant is generated (or the experiment fails with a TransformationError); only
    mock and dry-run modes, which make no API calls, use placeholders (SPEC section 12.2). The
    agent never runs on an excluded (quality-warning) or no-op variant: each of its cells is
    recorded with status SKIPPED_VARIANT and no cost.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        db: Session,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._cost_guard = CostGuard(
            per_run_cap=settings.DEFAULT_COST_CAP_USD,
            total_limit=config.cost_limit_usd,
        )
        self._transform_cache = TransformationCache(db)
        self._progress_callback = progress_callback
        self._steps_done = 0
        self._plan = plan_runs(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Experiment:
        """Execute the full experiment and return the persisted Experiment record.

        In real mode, raises TransformationError before anything is created when LLM-backed
        variants still have to be generated and no API key is configured.
        """
        if self._config.execution_mode == "real":
            self._check_variants_can_be_generated()
        experiment = Experiment(
            name=self._config.experiment_name,
            description=self._config.description,
            config=self._config.model_dump_json(),
            status="running",
            started_at=_now(),
        )
        self._db.add(experiment)
        self._db.flush()
        self._db.commit()

        try:
            self._run_all_cells(experiment)
            experiment.status = "completed"
        except CostLimitExceeded as exc:
            log.warning("Cost limit exceeded: %s", exc)
            experiment.status = "cost_exceeded"
        except Exception as exc:
            log.error("Experiment failed: %s", redact_api_key(str(exc)))
            experiment.status = "failed"
            raise
        finally:
            experiment.completed_at = _now()
            experiment.total_cost_usd = self._cost_guard.running_total
            self._db.commit()

        return experiment

    # ------------------------------------------------------------------
    # Adapter factory — the ONLY place execution_mode is checked
    # ------------------------------------------------------------------

    def _make_adapter(self, agent_cfg: AgentConfig):
        """Return a configured adapter.  execution_mode determines the class; nothing else does."""
        if self._config.execution_mode == "mock":
            adapter = MockReplayAdapter()
        else:
            adapter = LLMBaselineAdapter()
        adapter.configure(agent_cfg.params)
        return adapter

    # ------------------------------------------------------------------
    # Inner execution loop
    # ------------------------------------------------------------------

    def _run_all_cells(self, experiment: Experiment) -> None:
        for agent_cfg in self._config.agents:
            adapter = self._make_adapter(agent_cfg)

            for issue_id in self._config.issues.issue_ids:
                issue = self._load_issue(issue_id)
                label = issue.external_id or issue.id
                issue_record = IssueRecord(
                    issue_id=issue.id,
                    repo_name=issue.repo_name,
                    text=issue.issue_text,
                    reproduction_steps=issue.reproduction_steps,
                    expected_behavior=issue.expected_behavior,
                    metadata={"external_id": label},
                )

                # Always run the original (un-transformed) variant first.
                original_ti = self._get_or_create_original_ti(issue)
                for run_index in range(self._config.runs_per_variant):
                    self._progress(f"Running {agent_cfg.name} on {label} / original")
                    self._execute_cell(
                        experiment, adapter, agent_cfg,
                        issue, original_ti, run_index,
                    )

                # Run each configured transformation variant.
                for transform_cfg in self._enabled_transformations():
                    transformation_cls = transformation_registry.get(transform_cfg.name)
                    transformation = transformation_cls()
                    self._progress(f"Preparing the {transformation.name} variant of {label}", 0)
                    # MockReplay fixtures recorded from an experiment hold the variant it ran on.
                    recorded = getattr(adapter, "recorded_variant", None)
                    ti = self._transform_cache.variant(
                        transformation, issue_record, transform_cfg.params,
                        mode=self._config.execution_mode,
                        recorded=recorded(label, transformation.name) if recorded else None,
                    )
                    self._db.commit()
                    transformed_record = IssueRecord(
                        issue_id=issue_record.issue_id,
                        repo_name=issue_record.repo_name,
                        text=ti.transformed_text,
                    )
                    for run_index in range(self._config.runs_per_variant):
                        if ti.quality_warning or ti.noop:
                            self._progress(f"Skipping {label} / {transformation.name}")
                            self._record_skipped(experiment, adapter, agent_cfg, ti, run_index)
                            continue
                        self._progress(
                            f"Running {agent_cfg.name} on {label} / {transformation.name}"
                        )
                        self._execute_cell(
                            experiment, adapter, agent_cfg,
                            issue, ti, run_index,
                            issue_record_override=transformed_record,
                        )

                # Control runs: the original again, after its variants (run-to-run noise floor).
                for repeat in range(self._plan.control_repeats):
                    self._progress(f"Running {agent_cfg.name} on {label} / original (control)")
                    self._execute_cell(
                        experiment, adapter, agent_cfg,
                        issue, original_ti, self._config.runs_per_variant + repeat,
                        control_repeat=True,
                    )

    def _enabled_transformations(self):
        """The transformations to apply: none in originals-only mode."""
        return enabled_transformations(self._config)

    def _check_variants_can_be_generated(self) -> None:
        """Real mode: fail before anything runs if uncached LLM-backed variants need a missing key."""
        check_variants_can_be_generated(self._config, self._db)

    def _progress(self, message: str, step: int = 1) -> None:
        """Report progress before a step; ``step`` = 1 for a run, 0 for variant preparation."""
        if self._progress_callback is None:
            return
        total = max(self._plan.total, 1)
        self._progress_callback(min(self._steps_done / total, 1.0), message)
        self._steps_done += step

    def _record_skipped(
        self,
        experiment: Experiment,
        adapter,
        agent_cfg: AgentConfig,
        ti: TransformedIssueModel,
        run_index: int,
    ) -> None:
        """Record, without calling the agent, a run on an excluded or no-op variant."""
        kind = "no-op variant" if ti.noop else "variant excluded"
        self._db.add(Run(
            experiment_id=experiment.id,
            transformed_issue_id=ti.id,
            agent_name=agent_cfg.name,
            agent_version=adapter.version,
            run_index=run_index,
            execution_mode=self._config.execution_mode,
            status=SKIPPED_VARIANT,
            cost_usd=0.0,
            error_message=f"Not run: {kind} ({ti.exclusion_reason or 'quality warning'})",
            completed_at=_now(),
        ))
        self._db.flush()
        self._db.commit()

    def _execute_cell(
        self,
        experiment: Experiment,
        adapter,
        agent_cfg: AgentConfig,
        issue: Issue,
        ti: TransformedIssueModel,
        run_index: int,
        *,
        issue_record_override: IssueRecord | None = None,
        control_repeat: bool = False,
    ) -> None:
        """Execute one (agent, transformed_issue, run_index) cell and persist the Run."""
        if not self._cost_guard.check_run(
            self._cost_guard.running_total,
            self._cost_guard.per_run_cap,
            self._cost_guard.total_limit,
        ):
            run = Run(
                experiment_id=experiment.id,
                transformed_issue_id=ti.id,
                agent_name=agent_cfg.name,
                agent_version=adapter.version,
                run_index=run_index,
                control_repeat=control_repeat,
                execution_mode=self._config.execution_mode,
                status="cost_exceeded",
                completed_at=_now(),
            )
            self._db.add(run)
            self._db.flush()
            self._db.commit()
            return

        if self._config.execution_mode == "dry_run":
            run = Run(
                experiment_id=experiment.id,
                transformed_issue_id=ti.id,
                agent_name=agent_cfg.name,
                agent_version=adapter.version,
                run_index=run_index,
                control_repeat=control_repeat,
                execution_mode=self._config.execution_mode,
                status="dry_run_skipped",
                completed_at=_now(),
            )
            self._db.add(run)
            self._db.flush()
            self._db.commit()
            return

        issue_text = issue_record_override.text if issue_record_override else ti.transformed_text
        metadata = {
            "issue_id": issue.external_id or issue.id,
            "transformation_name": ti.transformation_name,
        }
        if control_repeat:
            # 1 for the first control run: MockReplay replays the matching recorded re-run.
            metadata["control_repeat"] = run_index - self._config.runs_per_variant + 1
        agent_input = AgentInput(
            issue_text=issue_text, repo_name=issue.repo_name, metadata=metadata
        )

        run = Run(
            experiment_id=experiment.id,
            transformed_issue_id=ti.id,
            agent_name=agent_cfg.name,
            agent_version=adapter.version,
            run_index=run_index,
            control_repeat=control_repeat,
            execution_mode=self._config.execution_mode,
            status="running",
            started_at=_now(),
        )
        self._db.add(run)
        self._db.flush()
        self._db.commit()

        wall_start = time.monotonic()
        try:
            mode = ExecutionMode(self._config.execution_mode)
            output = adapter.run(agent_input, mode)
            run.status = output.status
            run.patch = output.patch
            run.explanation = output.explanation
            run.raw_logs = output.raw_logs or None
            run.token_input = output.token_usage.get("input")
            run.token_output = output.token_usage.get("output")
            run.cost_usd = output.cost_usd
            run.runtime_seconds = output.runtime_seconds or (time.monotonic() - wall_start)
            run.error_message = output.error_message
            run.metadata_ = json.dumps(output.metadata) if output.metadata else None
        except Exception as exc:
            # Stored and logged, so the API key is masked in case an SDK message ever quotes it.
            message = redact_api_key(str(exc))
            run.status = "error"
            run.error_message = message
            run.runtime_seconds = time.monotonic() - wall_start
            log.error(
                "Run failed — issue=%s agent=%s transform=%s: %s",
                agent_input.metadata.get("issue_id"),
                agent_cfg.name,
                ti.transformation_name,
                message,
            )
        finally:
            run.completed_at = _now()
            self._db.flush()
            self._db.commit()

        self._cost_guard.record_run(run.cost_usd or 0.0)
        experiment.total_cost_usd = self._cost_guard.running_total
        self._db.commit()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _load_issue(self, issue_id: str) -> Issue:
        """By database id, else by external id (a dataset record wins over an ad-hoc custom one)."""
        issue = find_issue(self._db, issue_id)
        if issue is None:
            raise ValueError(f"Issue '{issue_id}' not found in the database")
        return issue

    def _get_or_create_original_ti(self, issue: Issue) -> TransformedIssueModel:
        """Return the existing 'original' TransformedIssue or create one."""
        existing = (
            self._db.query(TransformedIssueModel)
            .filter_by(issue_id=issue.id, is_original=True)
            .first()
        )
        if existing:
            return existing
        ti = TransformedIssueModel(
            issue_id=issue.id,
            transformation_name="original",
            transformation_params=None,
            transformed_text=issue.issue_text,
            transformation_notes="Original issue text (no transformation applied)",
            quality_warning=False,
            is_original=True,
            generator=ORIGINAL,
            noop=False,
        )
        self._db.add(ti)
        self._db.flush()
        return ti
