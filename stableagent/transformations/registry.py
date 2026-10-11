from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stableagent.transformations.base import AbstractTransformation


class TransformationRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, type[AbstractTransformation]] = {}

    def register(self, cls: type[AbstractTransformation]) -> type[AbstractTransformation]:
        self._registry[cls.name] = cls
        return cls

    def get(self, name: str) -> type[AbstractTransformation]:
        if name not in self._registry:
            raise KeyError(
                f"Transformation '{name}' not registered. Available: {list(self._registry)}"
            )
        return self._registry[name]

    def list_names(self) -> list[str]:
        return list(self._registry.keys())


transformation_registry = TransformationRegistry()


def register(cls: type[AbstractTransformation]) -> type[AbstractTransformation]:
    """Class decorator that registers a transformation in the global registry."""
    return transformation_registry.register(cls)
