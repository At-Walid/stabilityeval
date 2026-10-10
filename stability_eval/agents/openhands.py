from __future__ import annotations

from stability_eval.agents.base import AbstractAgentAdapter, AgentInput, AgentOutput, ExecutionMode
from stability_eval.agents.registry import agent_registry


@agent_registry.register
class OpenHandsAdapter(AbstractAgentAdapter):
    """Stub adapter for OpenHands. Full implementation deferred to TOSEM."""

    name = "openhands"
    version = "stub"
    supported_modes = [ExecutionMode.MOCK]

    def configure(self, params: dict) -> None:
        pass

    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput:
        raise NotImplementedError(
            "OpenHands adapter is not yet implemented. "
            "See the Extending section of README.md for the adapter interface."
        )

    def health_check(self) -> bool:
        return False
