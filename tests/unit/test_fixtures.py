from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from stability_eval.agents.base import AgentOutput

FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "stability_eval" / "fixtures" / "mock_responses"
)

# skipped_variant: a recorded cell the runner never ran (excluded or no-op variant).
_VALID_STATUSES = {
    "success", "failure", "no_patch", "timeout", "error", "cost_exceeded", "skipped_variant",
}
_NAME_RE = re.compile(r"^.+__.+__mock_replay\.json$")


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def test_fixtures_directory_not_empty():
    assert len(_fixture_files()) > 0


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_filename_matches_naming_pattern(path):
    assert _NAME_RE.match(path.name), f"{path.name} does not match {{issue_id}}__{{variant}}__mock_replay.json"


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_matches_agent_output_schema(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    recorded = "recorded_from" in data  # recorded from an experiment (stabilityeval record-fixtures)
    _check_output(path, data, recorded)
    for repeat in data.get("control_repeats", []):
        assert path.name.endswith("__original__mock_replay.json"), "control runs re-run the original"
        _check_output(path, repeat, recorded)


@pytest.mark.parametrize(
    "path", [p for p in _fixture_files() if "recorded_from" in p.read_text(encoding="utf-8")],
    ids=lambda p: p.name,
)
def test_recorded_fixture_records_its_variant(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {"experiment_id", "run_id", "agent_name"} <= set(data["recorded_from"])
    if path.name.endswith("__original__mock_replay.json"):
        assert "variant" not in data
        return
    variant = data["variant"]
    assert isinstance(variant["transformed_text"], str) and variant["transformed_text"]
    assert {"params", "generator", "transform_version", "quality_warning", "noop",
            "exclusion_reason", "original_sha256"} <= set(variant)
    # A skipped cell is exactly a run on an excluded or no-op variant.
    assert (data["status"] == "skipped_variant") == (variant["quality_warning"] or variant["noop"])


def _check_output(path, data: dict, recorded: bool) -> None:
    # Must be constructible as an AgentOutput with exactly the documented fields.
    output = AgentOutput(
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

    assert output.status in _VALID_STATUSES
    assert isinstance(output.token_usage, dict)
    assert isinstance(output.cost_usd, (int, float))
    assert isinstance(output.runtime_seconds, (int, float))
    assert isinstance(output.raw_logs, str)
    assert isinstance(output.metadata, dict)

    if output.status == "success":
        assert output.patch, f"{path.name}: success fixture must have a non-empty patch"
        if not recorded:  # the LLM Baseline's forced submit_patch call returns only the diff
            assert output.explanation, f"{path.name}: success fixture must have an explanation"
        assert output.error_message is None
    else:
        assert output.patch is None, f"{path.name}: non-success fixture must not have a patch"
        assert output.error_message, f"{path.name}: non-success fixture must have an error_message"
