from __future__ import annotations

import json
import pytest

from stability_eval.agents.base import AgentInput, AgentOutput, ExecutionMode
from stability_eval.agents.mock_replay import FixtureNotFoundError, MockReplayAdapter
from stability_eval.agents.registry import agent_registry

# Ensure all adapters are registered before tests run.
import stability_eval.agents  # noqa: F401


SAMPLE_FIXTURE = {
    "status": "success",
    "patch": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
    "explanation": "Corrected the value.",
    "token_usage": {"input": 100, "output": 50},
    "cost_usd": 0.002,
    "runtime_seconds": 0.01,
    "error_message": None,
    "raw_logs": "",
    "metadata": {},
}


def _write_fixture(directory, issue_id: str, transform: str, data: dict) -> None:
    path = directory / f"{issue_id}__{transform}__mock_replay.json"
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# MockReplayAdapter tests
# ---------------------------------------------------------------------------


def test_mock_replay_returns_correct_fixture(tmp_path):
    _write_fixture(tmp_path, "test__issue-001", "original", SAMPLE_FIXTURE)

    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(tmp_path)})

    agent_input = AgentInput(
        issue_text="Fix the off-by-one error.",
        repo_name="test/repo",
        metadata={"issue_id": "test__issue-001", "transformation_name": "original"},
    )
    output = adapter.run(agent_input, ExecutionMode.MOCK)

    assert isinstance(output, AgentOutput)
    assert output.status == "success"
    assert output.patch == SAMPLE_FIXTURE["patch"]
    assert output.cost_usd == pytest.approx(0.002)
    assert output.token_usage == {"input": 100, "output": 50}


def test_mock_replay_under_100ms(tmp_path):
    import time

    _write_fixture(tmp_path, "test__issue-001", "original", SAMPLE_FIXTURE)

    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(tmp_path)})

    agent_input = AgentInput(
        issue_text="Fix the off-by-one error.",
        repo_name="test/repo",
        metadata={"issue_id": "test__issue-001", "transformation_name": "original"},
    )

    start = time.perf_counter()
    adapter.run(agent_input, ExecutionMode.MOCK)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 100, f"MockReplayAdapter took {elapsed_ms:.1f}ms — must be under 100ms"


def test_fixture_not_found_error(tmp_path):
    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(tmp_path)})

    agent_input = AgentInput(
        issue_text="Fix the bug.",
        repo_name="test/repo",
        metadata={"issue_id": "nonexistent__issue-999", "transformation_name": "paraphrase"},
    )

    with pytest.raises(FixtureNotFoundError):
        adapter.run(agent_input, ExecutionMode.MOCK)


def test_fixture_not_found_error_is_subclass_of_file_not_found():
    assert issubclass(FixtureNotFoundError, FileNotFoundError)


def test_mock_replay_health_check_true(tmp_path):
    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(tmp_path)})
    assert adapter.health_check() is True


def test_mock_replay_health_check_false_missing_dir(tmp_path):
    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(tmp_path / "nonexistent")})
    assert adapter.health_check() is False


def test_mock_replay_reads_committed_fixture():
    """Smoke test: the committed sample fixture loads without error."""
    adapter = MockReplayAdapter()
    # Uses default FIXTURES_DIR from settings (stability_eval/fixtures/mock_responses)
    agent_input = AgentInput(
        issue_text="Fix the bug.",
        repo_name="test/repo",
        metadata={"issue_id": "test__issue-001", "transformation_name": "original"},
    )
    output = adapter.run(agent_input, ExecutionMode.MOCK)
    assert output.status == "success"


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_lookup_mock_replay():
    cls = agent_registry.get("mock_replay")
    assert cls is MockReplayAdapter


def test_registry_lookup_llm_baseline():
    from stability_eval.agents.llm_baseline import LLMBaselineAdapter

    cls = agent_registry.get("llm_baseline")
    assert cls is LLMBaselineAdapter


# ---------------------------------------------------------------------------
# LLMBaselineAdapter.DEFAULT_MODEL — single source of truth for the model
# string, so callers (dashboard display, direct API callers) can never drift
# out of sync with what the agent actually configures itself with.
# ---------------------------------------------------------------------------


def test_llm_baseline_default_model_is_class_attribute():
    from stability_eval.agents.llm_baseline import LLMBaselineAdapter

    assert isinstance(LLMBaselineAdapter.DEFAULT_MODEL, str)
    assert LLMBaselineAdapter.DEFAULT_MODEL


def test_llm_baseline_uses_default_model_when_unconfigured():
    from stability_eval.agents.llm_baseline import LLMBaselineAdapter

    adapter = LLMBaselineAdapter()
    assert adapter._model == LLMBaselineAdapter.DEFAULT_MODEL


def test_llm_baseline_configure_overrides_model():
    from stability_eval.agents.llm_baseline import LLMBaselineAdapter

    adapter = LLMBaselineAdapter()
    adapter.configure({"model": "claude-opus-4-8"})
    assert adapter._model == "claude-opus-4-8"


def test_registry_lookup_stubs():
    from stability_eval.agents.openhands import OpenHandsAdapter
    from stability_eval.agents.swe_agent import SWEAgentAdapter
    from stability_eval.agents.aider import AiderAdapter
    from stability_eval.agents.autocoderover import AutoCoderRoverAdapter

    assert agent_registry.get("openhands") is OpenHandsAdapter
    assert agent_registry.get("swe_agent") is SWEAgentAdapter
    assert agent_registry.get("aider") is AiderAdapter
    assert agent_registry.get("autocoderover") is AutoCoderRoverAdapter


def test_registry_raises_key_error_for_unknown():
    with pytest.raises(KeyError, match="No agent registered"):
        agent_registry.get("does_not_exist")


def test_registry_list_names():
    names = agent_registry.list_names()
    assert "mock_replay" in names
    assert "llm_baseline" in names
    assert "openhands" in names
