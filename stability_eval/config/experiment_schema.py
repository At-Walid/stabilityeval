from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str
    version: str = "1.0"
    params: dict[str, Any] = Field(default_factory=dict)


class IssueConfig(BaseModel):
    source: Literal["swebench_lite", "github", "manual"] = "swebench_lite"
    issue_ids: list[str] = Field(default_factory=list)


class TransformationConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class ExperimentConfig(BaseModel):
    experiment_name: str
    description: Optional[str] = None
    execution_mode: Literal["real", "mock", "dry_run"] = "mock"
    agents: list[AgentConfig]
    issues: IssueConfig = Field(default_factory=IssueConfig)
    transformations: list[TransformationConfig] = Field(default_factory=list)
    runs_per_variant: int = 1
    # Extra runs of each issue's original per agent, after its variants: control runs, compared
    # with the original run to measure the run-to-run noise floor ("control_flip_rate"). They never
    # enter SC/TS. Skipped in originals-only mode.
    control_repeats: int = Field(default=0, ge=0)
    cost_limit_usd: float = 20.0
    output_dir: str = "./results"
    # Run only the original variant of every issue (no transformation is applied or generated):
    # a cheap check of the agent and of the localization outcome before a full run.
    originals_only: bool = False
