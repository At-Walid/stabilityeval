from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AgentConfig(BaseModel):
    # Recorded as every run's agent_name: the metrics are computed per agent name (SPEC 13).
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
    # Run on exactly the variants an earlier experiment ran on (its id): each issue's variant of
    # each enabled transformation is the stored variant that experiment's run used, never looked
    # up in the cache and never generated. The run fails before anything is recorded if some
    # variant is missing there, i.e. would have to be generated (SPEC section 12.1).
    reuse_variants_from: Optional[str] = None

    @model_validator(mode="after")
    def _agent_names_are_unique(self) -> "ExperimentConfig":
        """Runs carry their agent's name and the metrics group runs by it (each agent's variants
        are compared with that agent's own original), so two agents may not share a name."""
        names = [agent.name for agent in self.agents]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"Agent names must be unique within an experiment ({', '.join(duplicates)} "
                "appears more than once): give each agent its own name, e.g. "
                '"llm_baseline_gpt4o".'
            )
        return self
