from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# Issue.source of an issue typed into the dashboard: an ad-hoc record, not a dataset issue. It is
# never listed in the SWE-bench picker and never resolved in place of a dataset record.
CUSTOM_SOURCE = "custom_adhoc"
# Issue.source of the ICSE pilot issues (scripts/output/pilot_issue_ids.json), seeded verbatim from
# SWE-bench Lite by scripts/seed_pilot_issues.py; other dataset issues keep "swebench_lite".
PILOT_SOURCE = "swebench_lite_pilot"


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    issue_text: Mapped[str] = mapped_column(Text, nullable=False)
    reproduction_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevant_tests: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON array
    metadata_: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)  # JSON blob
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)

    transformed_issues: Mapped[list[TransformedIssue]] = relationship(
        "TransformedIssue", back_populates="issue", cascade="all, delete-orphan"
    )


class TransformedIssue(Base):
    __tablename__ = "transformed_issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(String, ForeignKey("issues.id"), nullable=False)
    transformation_name: Mapped[str] = mapped_column(String, nullable=False)
    transformation_params: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    transformed_text: Mapped[str] = mapped_column(Text, nullable=False)
    transformation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_original: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)
    # Provenance (SPEC section 11.6). generator: the model id of an LLM-backed variant, or
    # "deterministic", "placeholder" (offline stand-in, never a generated variant), "original",
    # "unknown" (stored before provenance was recorded). generation_mode: the execution mode the
    # variant was produced in.
    generator: Mapped[str | None] = mapped_column(String, nullable=True)
    transform_version: Mapped[str | None] = mapped_column(String, nullable=True)
    generation_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    # Equal to the original after whitespace normalization: excluded from SC/TS (SPEC section 13).
    noop: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    # Why the variant is excluded from the metrics, when it is: the missing technical tokens (and
    # invented details) of a quality-warning variant, or the no-op note. NULL otherwise.
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # API cost of generating the variant, every attempt included (0 for deterministic variants
    # and placeholders). NULL for variants stored before it was recorded.
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    issue: Mapped[Issue] = relationship("Issue", back_populates="transformed_issues")
    runs: Mapped[list[Run]] = relationship(
        "Run", back_populates="transformed_issue", cascade="all, delete-orphan"
    )


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[str] = mapped_column(Text, nullable=False)   # full JSON config snapshot
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    runs: Mapped[list[Run]] = relationship(
        "Run", back_populates="experiment", cascade="all, delete-orphan"
    )
    metrics: Mapped[list[Metric]] = relationship(
        "Metric", back_populates="experiment", cascade="all, delete-orphan"
    )
    export_artifacts: Mapped[list[ExportArtifact]] = relationship(
        "ExportArtifact", back_populates="experiment", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(String, ForeignKey("experiments.id"), nullable=False)
    transformed_issue_id: Mapped[str] = mapped_column(
        String, ForeignKey("transformed_issues.id"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A control run: the original re-run (``control_repeats``), compared with the original run to
    # measure the run-to-run noise floor. Never part of SC/TS (SPEC section 13).
    control_repeat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    execution_mode: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)  # JSON
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="runs")
    transformed_issue: Mapped[TransformedIssue] = relationship(
        "TransformedIssue", back_populates="runs"
    )
    metrics: Mapped[list[Metric]] = relationship(
        "Metric",
        primaryjoin="and_(Metric.scope == 'run', Metric.scope_key == Run.id)",
        foreign_keys="Metric.scope_key",
        viewonly=True,
    )


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        String, ForeignKey("experiments.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String, nullable=False)       # run|agent_issue|agent|experiment
    scope_key: Mapped[str] = mapped_column(String, nullable=False)
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    computed_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="metrics")


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        String, ForeignKey("experiments.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)   # csv|json|report_md
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="export_artifacts")
