from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stableagent.agents.base import AbstractAgentAdapter


class AgentRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, type[AbstractAgentAdapter]] = {}

    def register(self, cls: type[AbstractAgentAdapter]) -> type[AbstractAgentAdapter]:
        self._registry[cls.name] = cls
        return cls

    def get(self, name: str) -> type[AbstractAgentAdapter]:
        if name not in self._registry:
            raise KeyError(f"No agent registered with name '{name}'")
        return self._registry[name]

    def list_names(self) -> list[str]:
        return list(self._registry.keys())


agent_registry = AgentRegistry()
