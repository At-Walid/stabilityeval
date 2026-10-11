"""The LLM Baseline's provider parameter: "anthropic" (unchanged) and "openai".

Both providers' SDKs are replaced by fakes (tests/llm_fakes.py): no network, no key from .env.

- The same reply gives the same run record whichever provider sent it: status, patch, raw log,
  token usage, cost (at equal prices), error message, stop reason and patch source.
- The OpenAI request carries the same prompt text, temperature 0, 4096 tokens, the 120 s timeout,
  and forces the submit_patch function; its arguments are parsed as the patch.
- Cost comes from the model table; a model without a price, a model of the other provider and a
  missing key all fail before any API call, with a message naming what to fix.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import openai
import pytest

from stableagent.agents.base import AgentInput, ExecutionMode
from stableagent.agents.llm_baseline import (
    OPENAI_SUBMIT_PATCH_CHOICE,
    OPENAI_SUBMIT_PATCH_TOOL,
    PROMPT_VERSION,
    SUBMIT_PATCH_CHOICE,
    SUBMIT_PATCH_TOOL,
    SYSTEM_PROMPT,
    LLMBaselineAdapter,
    MissingAPIKeyError,
    build_user_message,
)
from stableagent.config import pricing
from stableagent.config.pricing import ModelInfo, UnknownModelError
from stableagent.config.settings import Settings, redact_api_key
from tests.llm_fakes import FakeAnthropicAgent, FakeOpenAI, Reply

PATCH = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
AGENT_INPUT = AgentInput(issue_text="Fix the bug in foo.", repo_name="test/repo")
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _adapter(**params) -> LLMBaselineAdapter:
    adapter = LLMBaselineAdapter()
    adapter.configure(params)
    return adapter


def _openai(**params) -> LLMBaselineAdapter:
    return _adapter(provider="openai", model="gpt-4o", **params)


def _record(output) -> dict:
    """The run record minus what differs by nature: wall-clock runtime and the model id."""
    record = dataclasses.asdict(output)
    record.pop("runtime_seconds")
    record["metadata"] = {k: v for k, v in record["metadata"].items() if k != "model"}
    return record


@pytest.fixture()
def same_prices(monkeypatch):
    """Two test models, one per provider, at the same prices."""
    monkeypatch.setitem(pricing.MODELS, "test-claude", ModelInfo("anthropic", "C", 3.0, 15.0, "-"))
    monkeypatch.setitem(pricing.MODELS, "test-gpt", ModelInfo("openai", "G", 3.0, 15.0, "-"))


# ── Identical run records ─────────────────────────────────────────────────────

REPLIES = {
    "clean diff": Reply(diff=PATCH),
    "diff in fences": Reply(diff=f"Here it is:\n```diff\n{PATCH}```"),
    "no valid diff": Reply(diff="I need to see the repository first."),
    "prose next to the call": Reply(diff=PATCH, text="Let me fix this."),
    "no tool call, diff in text": Reply(text=f"```diff\n{PATCH}```"),
    "no tool call, no diff": Reply(text="Cannot help."),
    "cut at the token limit": Reply(diff=PATCH, cut=True),
    "over the cost cap": Reply(diff=PATCH, output_tokens=100_000),
}


@pytest.mark.parametrize("case", list(REPLIES))
def test_both_providers_produce_identical_run_records_for_the_same_reply(
    case, monkeypatch, same_prices
):
    reply = REPLIES[case]
    FakeAnthropicAgent(respond=lambda _request: reply).install(monkeypatch)
    FakeOpenAI(respond=lambda _request: reply).install(monkeypatch)

    from_claude = _adapter(model="test-claude").run(AGENT_INPUT, ExecutionMode.REAL)
    from_gpt = _adapter(provider="openai", model="test-gpt").run(AGENT_INPUT, ExecutionMode.REAL)

    assert _record(from_gpt) == _record(from_claude)
    assert (from_claude.metadata["model"], from_gpt.metadata["model"]) == ("test-claude", "test-gpt")


def test_the_identical_records_cover_every_status(monkeypatch, same_prices):
    statuses = set()
    for reply in REPLIES.values():
        FakeOpenAI(respond=lambda _request, r=reply: r).install(monkeypatch)
        statuses.add(_adapter(provider="openai", model="test-gpt").run(
            AGENT_INPUT, ExecutionMode.REAL
        ).status)
    assert statuses == {"success", "no_patch", "truncated", "cost_exceeded"}  # timeout below


def test_a_timeout_is_the_same_record_for_both_providers(monkeypatch, same_prices):
    FakeAnthropicAgent(raises=anthropic.APITimeoutError(request=SimpleNamespace())).install(
        monkeypatch
    )
    FakeOpenAI(raises=openai.APITimeoutError(request=SimpleNamespace())).install(monkeypatch)

    from_claude = _adapter(model="test-claude").run(AGENT_INPUT, ExecutionMode.REAL)
    from_gpt = _adapter(provider="openai", model="test-gpt").run(AGENT_INPUT, ExecutionMode.REAL)

    assert from_gpt.status == from_claude.status == "timeout"
    assert _record(from_gpt) == _record(from_claude)
    assert "120s" in from_gpt.error_message


# ── The OpenAI request ────────────────────────────────────────────────────────

def test_the_openai_request_forces_the_submit_patch_function_with_the_same_prompt(
    monkeypatch, dummy_openai_api_key
):
    fake = FakeOpenAI(respond=lambda _request: Reply(diff=PATCH)).install(monkeypatch)
    _openai().run(AGENT_INPUT, ExecutionMode.REAL)

    (request,) = fake.requests
    assert request["tools"] == [OPENAI_SUBMIT_PATCH_TOOL]
    assert request["tool_choice"] == OPENAI_SUBMIT_PATCH_CHOICE == {
        "type": "function", "function": {"name": "submit_patch"},
    }
    assert request["parallel_tool_calls"] is False
    function = OPENAI_SUBMIT_PATCH_TOOL["function"]
    # The very tool the Anthropic path defines: same name, description and parameters.
    assert function["name"] == SUBMIT_PATCH_TOOL["name"] == SUBMIT_PATCH_CHOICE["name"]
    assert function["description"] == SUBMIT_PATCH_TOOL["description"]
    assert function["parameters"] == SUBMIT_PATCH_TOOL["input_schema"]
    assert request["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(AGENT_INPUT)},
    ]
    assert request["model"] == "gpt-4o"
    assert request["temperature"] == 0.0
    assert request["max_completion_tokens"] == 4096
    # The key comes from OPENAI_API_KEY (here the suite's dummy); the SDK timeout is 120 s.
    (client,) = fake.clients
    assert client == {"api_key": dummy_openai_api_key, "timeout": 120.0}


def test_the_anthropic_request_is_unchanged(monkeypatch, dummy_api_key):
    fake = FakeAnthropicAgent(respond=lambda _request: Reply(diff=PATCH)).install(monkeypatch)
    LLMBaselineAdapter().run(AGENT_INPUT, ExecutionMode.REAL)

    (request,) = fake.requests
    assert request == {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "temperature": 0.0,
        "system": SYSTEM_PROMPT,
        "tools": [SUBMIT_PATCH_TOOL],
        "tool_choice": {"type": "tool", "name": "submit_patch"},
        "messages": [{"role": "user", "content": build_user_message(AGENT_INPUT)}],
    }
    assert fake.clients == [{"api_key": dummy_api_key, "timeout": 120.0}]


def test_the_forced_tool_call_is_parsed_as_the_patch(monkeypatch):
    FakeOpenAI(respond=lambda _request: Reply(diff=PATCH, input_tokens=1516,
                                              output_tokens=337)).install(monkeypatch)
    output = _openai().run(AGENT_INPUT, ExecutionMode.REAL)

    assert output.status == "success"
    assert output.patch == PATCH  # stored exactly as submitted
    assert json.loads(output.raw_logs) == {"diff": PATCH}
    assert output.token_usage == {"input": 1516, "output": 337}
    assert output.cost_usd == pytest.approx((1516 * 2.50 + 337 * 10.00) / 1_000_000)
    assert output.metadata == {
        "model": "gpt-4o", "prompt_version": PROMPT_VERSION,
        "stop_reason": "tool_use", "patch_source": "tool",
    }


def test_arguments_cut_mid_json_are_truncated_and_kept_for_inspection(monkeypatch):
    cut = json.dumps({"diff": PATCH})[:-12]
    FakeOpenAI(respond=lambda _request: Reply(diff=PATCH, cut=True, raw_arguments=cut)).install(
        monkeypatch
    )
    output = _openai().run(AGENT_INPUT, ExecutionMode.REAL)

    assert output.status == "truncated" and output.patch is None
    assert output.error_message == (
        "The submit_patch call was cut at max_tokens (4096): the diff is incomplete."
    )
    assert output.metadata["stop_reason"] == "max_tokens"
    assert json.loads(output.raw_logs) == {"unparsed_arguments": cut}


def test_the_dated_snapshot_behind_an_alias_is_recorded(monkeypatch):
    FakeOpenAI(respond=lambda _request: Reply(diff=PATCH, model="gpt-4o-2024-08-06")).install(
        monkeypatch
    )
    metadata = _openai().run(AGENT_INPUT, ExecutionMode.REAL).metadata
    assert metadata["model"] == "gpt-4o"
    assert metadata["model_snapshot"] == "gpt-4o-2024-08-06"


def test_other_openai_errors_propagate(monkeypatch):
    FakeOpenAI(raises=openai.APIConnectionError(request=SimpleNamespace())).install(monkeypatch)
    with pytest.raises(openai.APIConnectionError):
        _openai().run(AGENT_INPUT, ExecutionMode.REAL)


def test_the_cost_cap_and_token_limit_params_apply_to_openai(monkeypatch):
    fake = FakeOpenAI(respond=lambda _request: Reply(diff=PATCH)).install(monkeypatch)
    output = _openai(cost_cap_usd=0.0001, max_tokens=2048, timeout_seconds=15).run(
        AGENT_INPUT, ExecutionMode.REAL
    )
    assert output.status == "cost_exceeded" and "$0.00" in output.error_message
    assert fake.requests[0]["max_completion_tokens"] == 2048
    assert fake.clients[0]["timeout"] == 15.0


# ── Prices from the model table ───────────────────────────────────────────────

def test_the_model_table_prices_each_run():
    assert pricing.model_info("claude-sonnet-4-6").cost(1_000_000, 0) == 3.0
    assert pricing.model_info("claude-sonnet-4-6").cost(0, 1_000_000) == 15.0
    assert pricing.model_info("gpt-4o").cost(1_000_000, 1_000_000) == 12.5
    assert pricing.model_info("claude-haiku-4-5-20251001").cost(1_000_000, 1_000_000) == 6.0
    assert {info.provider for info in pricing.MODELS.values()} == {"anthropic", "openai"}


def test_a_model_without_a_price_fails_before_any_call(monkeypatch):
    fake = FakeOpenAI().install(monkeypatch)
    with pytest.raises(UnknownModelError, match="gpt-5-unpriced.*no price.*pricing.py"):
        _adapter(provider="openai", model="gpt-5-unpriced").run(AGENT_INPUT, ExecutionMode.REAL)
    assert fake.clients == [] and fake.requests == []


def test_a_model_of_the_other_provider_fails_before_any_call(monkeypatch):
    fake = FakeAnthropicAgent().install(monkeypatch)
    with pytest.raises(ValueError, match='is an openai model.*"provider": "openai"'):
        _adapter(model="gpt-4o").run(AGENT_INPUT, ExecutionMode.REAL)  # provider left anthropic
    assert fake.requests == []


def test_an_unknown_provider_is_rejected_at_configure():
    with pytest.raises(ValueError, match="Unknown LLM Baseline provider 'mistral'"):
        _adapter(provider="mistral")


def test_switching_to_haiku_needs_only_provider_and_model(monkeypatch, dummy_api_key):
    fake = FakeAnthropicAgent(respond=lambda _request: Reply(diff=PATCH)).install(monkeypatch)
    adapter = _adapter(provider="anthropic", model="claude-haiku-4-5-20251001")
    output = adapter.run(AGENT_INPUT, ExecutionMode.REAL)

    assert adapter.api_key_env_var == "ANTHROPIC_API_KEY"
    assert fake.requests[0]["model"] == "claude-haiku-4-5-20251001"
    assert output.cost_usd == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1_000_000)


# ── The key: OPENAI_API_KEY only, never logged ────────────────────────────────

def test_a_missing_openai_key_is_a_clear_error_before_any_call(monkeypatch, no_openai_key):
    fake = FakeOpenAI().install(monkeypatch)
    adapter = _openai()
    with pytest.raises(MissingAPIKeyError) as excinfo:
        adapter.run(AGENT_INPUT, ExecutionMode.REAL)
    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message and ".env" in message
    assert "gpt-4o" in message and "No API call was made" in message
    assert fake.clients == []
    assert adapter.health_check() is False


def test_a_missing_anthropic_key_is_a_clear_error_too(monkeypatch, no_api_key):
    fake = FakeAnthropicAgent().install(monkeypatch)
    with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY.*not set"):
        LLMBaselineAdapter().run(AGENT_INPUT, ExecutionMode.REAL)
    assert fake.clients == []


def test_the_openai_key_is_read_from_the_configured_variable(monkeypatch, no_openai_key):
    monkeypatch.setenv("TEAM_OPENAI_KEY", "team-test-key")
    fake = FakeOpenAI(respond=lambda _request: Reply(diff=PATCH)).install(monkeypatch)
    _openai(api_key_env_var="TEAM_OPENAI_KEY").run(AGENT_INPUT, ExecutionMode.REAL)
    key_is_the_configured_one = fake.clients[0]["api_key"] == "team-test-key"
    assert key_is_the_configured_one


def test_the_openai_key_is_a_secret_and_redacted(monkeypatch):
    secret = "openai-key-THIS-VALUE-MUST-NOT-LEAK-0123"
    settings = Settings(_env_file=None, OPENAI_API_KEY=secret)
    assert "MUST-NOT-LEAK" not in repr(settings) + settings.model_dump_json()
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    assert redact_api_key(f"401: invalid key {secret}") == "401: invalid key [REDACTED]"


def test_the_suite_only_ever_sees_the_dummy_openai_key(dummy_openai_api_key):
    from stableagent.config.settings import get_openai_api_key, settings

    accessor_is_dummy = get_openai_api_key() == dummy_openai_api_key
    stored_is_dummy = settings.OPENAI_API_KEY.get_secret_value() == dummy_openai_api_key
    assert accessor_is_dummy, "a non-dummy OPENAI_API_KEY reached the test suite"
    assert stored_is_dummy, "settings holds a non-dummy OPENAI_API_KEY during tests"


def test_env_example_lists_an_empty_openai_key():
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "OPENAI_API_KEY=" in lines and "ANTHROPIC_API_KEY=" in lines
