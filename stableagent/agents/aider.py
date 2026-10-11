from __future__ import annotations

from stableagent.agents.base import AbstractAgentAdapter, AgentInput, AgentOutput, ExecutionMode
from stableagent.agents.registry import agent_registry


@agent_registry.register
class AiderAdapter(AbstractAgentAdapter):
    """Stub adapter for Aider. Full implementation deferred to future work."""

    name = "aider"
    version = "stub"
    supported_modes = [ExecutionMode.MOCK]

    def configure(self, params: dict) -> None:
        pass

    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput:
        raise NotImplementedError(
            "Aider adapter is not yet implemented. "
            "See the Extending section of README.md for the adapter interface."
        )

    def health_check(self) -> bool:
        return False
