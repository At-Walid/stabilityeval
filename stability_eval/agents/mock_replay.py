from __future__ import annotations

import json
from pathlib import Path

from stability_eval.agents.base import AbstractAgentAdapter, AgentInput, AgentOutput, ExecutionMode
from stability_eval.agents.registry import agent_registry
from stability_eval.config.settings import settings


class FixtureNotFoundError(FileNotFoundError):
    """Raised when MockReplayAdapter cannot locate a fixture file for the requested combination."""


_FIXTURE_SUFFIX = "__mock_replay.json"


def fixture_filename(issue_id: str, transformation_name: str) -> str:
    """``{issue_id}__{transformation}__mock_replay.json``, the name MockReplay looks up."""
    return f"{issue_id}__{transformation_name}{_FIXTURE_SUFFIX}"


def fixture_index(fixtures_dir: str | Path | None = None) -> dict[str, set[str]]:
    """The recorded variants per issue id, from the fixture file names: no file is read.

    Issue ids may contain "__" (SWE-bench ids do); transformation names never do.
    """
    directory = Path(fixtures_dir if fixtures_dir is not None else settings.FIXTURES_DIR)
    if not directory.is_dir():
        return {}
    index: dict[str, set[str]] = {}
    for path in directory.glob(f"*{_FIXTURE_SUFFIX}"):
        issue_id, sep, transformation_name = path.name[: -len(_FIXTURE_SUFFIX)].rpartition("__")
        if sep and issue_id and transformation_name:
            index.setdefault(issue_id, set()).add(transformation_name)
    return index


def recorded_control_repeats(issue_id: str, fixtures_dir: str | Path | None = None) -> int:
    """How many control runs (re-runs of the original) the issue's original fixture recorded."""
    directory = Path(fixtures_dir if fixtures_dir is not None else settings.FIXTURES_DIR)
    path = directory / fixture_filename(issue_id, "original")
    if not path.is_file():
        return 0
    return len(json.loads(path.read_text(encoding="utf-8")).get("control_repeats") or [])


@agent_registry.register
class MockReplayAdapter(AbstractAgentAdapter):
    """Replays pre-recorded AgentOutput fixtures from disk. Never calls any external API.

    A fixture recorded from an experiment (``stabilityeval record-fixtures``) may also hold the
    outputs of the original's control runs (``control_repeats``, replayed in order for the
    runner's control runs; without them a control run replays the original's output) and the
    variant the run used (``variant``, see ``recorded_variant``).
    """

    name = "mock_replay"
    version = "1.0"
    supported_modes = [ExecutionMode.MOCK]

    def __init__(self) -> None:
        self._fixtures_dir = Path(settings.FIXTURES_DIR)

    def configure(self, params: dict) -> None:
        if "fixtures_dir" in params:
            self._fixtures_dir = Path(params["fixtures_dir"])

    def recorded_variant(self, issue_id: str, transformation_name: str) -> dict | None:
        """The variant the recorded run ran on, if its fixture recorded one (else None)."""
        path = self._fixtures_dir / fixture_filename(issue_id, transformation_name)
        if not path.is_file():
            return None
        variant = json.loads(path.read_text(encoding="utf-8")).get("variant")
        return variant if isinstance(variant, dict) else None

    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput:
        issue_id = agent_input.metadata.get("issue_id", "")
        transform = agent_input.metadata.get("transformation_name", "")
        fixture_path = self._fixtures_dir / fixture_filename(issue_id, transform)

        if not fixture_path.exists():
            raise FixtureNotFoundError(
                f"No fixture found for issue_id='{issue_id}', "
                f"transformation='{transform}', agent='{self.name}'. "
                f"Expected path: {fixture_path}"
            )

        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        # The runner numbers control runs 1, 2, ...: replay the recorded re-run when there is one.
        repeat = agent_input.metadata.get("control_repeat") or 0
        repeats = data.get("control_repeats") or []
        if 0 < repeat <= len(repeats):
            data = repeats[repeat - 1]
        return AgentOutput(
            status=data["status"],
            patch=data.get("patch"),
            explanation=data.get("explanation"),
            token_usage=data.get("token_usage", {}),
            cost_usd=data.get("cost_usd", 0.0),
            runtime_seconds=data.get("runtime_seconds", 0.0),
            error_message=data.get("error_message"),
            raw_logs=data.get("raw_logs", ""),
            metadata=data.get("metadata", {}),
        )

    def health_check(self) -> bool:
        return self._fixtures_dir.is_dir()
