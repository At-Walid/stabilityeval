from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExecutionMode(Enum):
    MOCK = "mock"
    DRY_RUN = "dry_run"
    REAL = "real"


@dataclass
class AgentInput:
    issue_text: str
    repo_name: str
    repo_path: Optional[str] = None
    base_commit: Optional[str] = None
    relevant_tests: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentOutput:
    # "success" | "failure" | "no_patch" | "timeout" | "error" | "cost_exceeded"
    # ("no_patch": the agent answered but no valid unified diff could be extracted — a failure)
    status: str
    patch: Optional[str] = None
    explanation: Optional[str] = None
    token_usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    runtime_seconds: float = 0.0
    error_message: Optional[str] = None
    raw_logs: str = ""
    metadata: dict = field(default_factory=dict)


class AbstractAgentAdapter(ABC):
    name: str
    version: str
    supported_modes: list[ExecutionMode]

    @abstractmethod
    def configure(self, params: dict) -> None: ...

    @abstractmethod
    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput: ...

    @abstractmethod
    def health_check(self) -> bool: ...
