"""LLMBaselineAdapter request/response contract, with ``anthropic.Anthropic`` replaced by a fake.

- The agent must answer with a forced ``submit_patch`` tool call: ``tools`` holds the tool,
  ``tool_choice`` forces it, ``max_tokens`` is 4096. The tool's ``diff`` is the patch and its
  input (JSON) the raw log; the text extractor is only a fallback.
- The per-run guard params from configure() are honoured: ``timeout_seconds`` (SDK request
  timeout -> "timeout" status), ``cost_cap_usd`` (-> "cost_exceeded"), ``max_tokens``.
- A reply without a valid diff is ``no_patch`` (a failure, not a success).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import pytest

from stability_eval.agents.base import AgentInput, ExecutionMode
from stability_eval.agents.llm_baseline import (
    PROMPT_VERSION,
    SUBMIT_PATCH_CHOICE,
    SUBMIT_PATCH_TOOL,
    LLMBaselineAdapter,
)

PATCH = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def tool_call(diff=PATCH, **extra_input):
    return SimpleNamespace(
        type="tool_use", id="toolu_01", name="submit_patch", input={"diff": diff, **extra_input}
    )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def _response(*content, input_tokens=100, output_tokens=50, stop_reason="tool_use"):
    return SimpleNamespace(
        content=list(content) if content else [tool_call()],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )


def _install_fake_client(monkeypatch, *, create):
    """Replace anthropic.Anthropic; returns the list of constructor kwargs it was given."""
    ctor_kwargs: list[dict] = []

    class FakeAnthropic:
        def __init__(self, **kwargs):
            ctor_kwargs.append(kwargs)
            self.messages = SimpleNamespace(create=create)

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    return ctor_kwargs


def _recording_create(response=None):
    """A fake messages.create that records the request kwargs it receives."""
    requests: list[dict] = []

    def create(**kwargs):
        requests.append(kwargs)
        return response or _response()

    return create, requests


def _run(adapter: LLMBaselineAdapter):
    agent_input = AgentInput(issue_text="Fix the bug.", repo_name="test/repo")
    return adapter.run(agent_input, ExecutionMode.REAL)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


# ---------------------------------------------------------------------------
# Request contract: a forced submit_patch tool call
# ---------------------------------------------------------------------------


def test_request_forces_the_submit_patch_tool(monkeypatch):
    create, requests = _recording_create()
    _install_fake_client(monkeypatch, create=create)
    _run(LLMBaselineAdapter())

    (request,) = requests
    assert request["tools"] == [SUBMIT_PATCH_TOOL]
    assert request["tool_choice"] == {"type": "tool", "name": "submit_patch"} == SUBMIT_PATCH_CHOICE
    schema = SUBMIT_PATCH_TOOL["input_schema"]
    assert schema["properties"] == {"diff": schema["properties"]["diff"]}  # one parameter
    assert schema["properties"]["diff"]["type"] == "string" and schema["required"] == ["diff"]
    assert request["max_tokens"] == 4096
    assert request["temperature"] == 0.0
    assert request["model"] == LLMBaselineAdapter.DEFAULT_MODEL


def test_request_carries_repo_name_and_the_strict_format_instruction(monkeypatch):
    create, requests = _recording_create()
    _install_fake_client(monkeypatch, create=create)
    _run(LLMBaselineAdapter())

    (request,) = requests
    user_message = request["messages"][0]["content"]
    assert user_message.startswith("Repository: test/repo\n")
    assert user_message.endswith("Fix the bug.")
    assert "submit_patch tool" in request["system"]
    assert "exactly ONE unified diff" in request["system"]
    assert "no prose" in request["system"]


def test_configured_max_tokens_is_passed_through(monkeypatch):
    create, requests = _recording_create()
    _install_fake_client(monkeypatch, create=create)
    adapter = LLMBaselineAdapter()
    adapter.configure({"max_tokens": 2048})
    _run(adapter)
    assert requests[0]["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# The tool call is the answer
# ---------------------------------------------------------------------------


def test_the_tool_diff_is_the_patch_and_the_tool_input_the_raw_log(monkeypatch):
    _install_fake_client(monkeypatch, create=lambda **_: _response())
    output = _run(LLMBaselineAdapter())

    assert output.status == "success"
    assert output.patch == PATCH  # stored as submitted
    assert json.loads(output.raw_logs) == {"diff": PATCH}
    assert output.metadata["patch_source"] == "tool"


def test_text_next_to_the_tool_call_is_ignored(monkeypatch):
    reply = _response(text_block("Here is my fix, with ```diff\n--- a/x\n```"), tool_call())
    _install_fake_client(monkeypatch, create=lambda **_: reply)
    output = _run(LLMBaselineAdapter())

    assert output.patch == PATCH and json.loads(output.raw_logs) == {"diff": PATCH}


def test_a_fenced_diff_inside_the_tool_input_is_extracted_as_a_fallback(monkeypatch):
    draft = PATCH.replace("x = 2", "x = 3")
    wrapped = f"Draft:\n```diff\n{draft}```\nFinal:\n```diff\n{PATCH}```"
    _install_fake_client(monkeypatch, create=lambda **_: _response(tool_call(wrapped)))
    output = _run(LLMBaselineAdapter())

    assert output.status == "success"
    assert output.patch == PATCH.strip()  # the final draft only, without fences or prose
    assert json.loads(output.raw_logs) == {"diff": wrapped}
    assert output.metadata["patch_source"] == "tool_extracted"


def test_a_tool_call_without_a_valid_diff_is_no_patch(monkeypatch):
    reply = _response(tool_call("I need to see the repository first."))
    _install_fake_client(monkeypatch, create=lambda **_: reply)
    output = _run(LLMBaselineAdapter())

    assert output.status == "no_patch"
    assert output.patch is None
    assert output.error_message == "The submit_patch call contained no valid unified diff."
    assert json.loads(output.raw_logs)["diff"] == "I need to see the repository first."


def test_diff_headers_without_any_hunk_are_no_patch(monkeypatch):
    reply = _response(tool_call("--- a/foo.py\n+++ b/foo.py\n"))
    _install_fake_client(monkeypatch, create=lambda **_: reply)
    assert _run(LLMBaselineAdapter()).status == "no_patch"


def test_a_tool_call_cut_at_max_tokens_is_no_patch(monkeypatch):
    cut = PATCH + "--- a/bar.py\n+++ b/bar.py\n@@ -1,40 +1,41 @@\n def"  # looks valid, is cut
    reply = _response(tool_call(cut), stop_reason="max_tokens")
    _install_fake_client(monkeypatch, create=lambda **_: reply)
    output = _run(LLMBaselineAdapter())

    assert output.status == "no_patch" and output.patch is None
    assert "cut at max_tokens (4096): the diff is incomplete" in output.error_message
    assert json.loads(output.raw_logs) == {"diff": cut}  # kept for inspection


# ---------------------------------------------------------------------------
# Text fallback (no tool call in the reply)
# ---------------------------------------------------------------------------


def test_without_a_tool_call_the_text_extractor_is_the_fallback(monkeypatch):
    draft = PATCH.replace("x = 2", "x = 3")
    reply = (
        f"Looking at the issue...\n\n```diff\n{draft}```\n\n"
        f"Actually, a cleaner version:\n\n```diff\n{PATCH}```"
    )
    _install_fake_client(monkeypatch, create=lambda **_: _response(text_block(reply)))
    output = _run(LLMBaselineAdapter())

    assert output.status == "success"
    assert output.patch == PATCH.strip()
    assert output.raw_logs == reply
    assert output.metadata["patch_source"] == "text"


def test_text_without_a_valid_diff_is_no_patch_not_success(monkeypatch):
    reply = "I need to see the repository before I can write a patch."
    _install_fake_client(monkeypatch, create=lambda **_: _response(text_block(reply)))
    output = _run(LLMBaselineAdapter())

    assert output.status == "no_patch"
    assert output.patch is None
    assert output.raw_logs == reply
    assert "No submit_patch call" in output.error_message


def test_empty_response_is_no_patch(monkeypatch):
    _install_fake_client(monkeypatch, create=lambda **_: _response(text_block("")))
    output = _run(LLMBaselineAdapter())
    assert output.status == "no_patch"
    assert output.patch is None
    assert "empty response" in output.error_message


# ---------------------------------------------------------------------------
# Guard params
# ---------------------------------------------------------------------------


def test_default_timeout_is_applied_to_the_client(monkeypatch):
    ctor_kwargs = _install_fake_client(monkeypatch, create=lambda **_: _response())
    _run(LLMBaselineAdapter())
    assert ctor_kwargs == [{"api_key": "test-key-not-real", "timeout": 120.0}]


def test_configured_timeout_is_applied_to_the_client(monkeypatch):
    ctor_kwargs = _install_fake_client(monkeypatch, create=lambda **_: _response())
    adapter = LLMBaselineAdapter()
    adapter.configure({"timeout_seconds": 15})
    _run(adapter)
    assert ctor_kwargs[0]["timeout"] == 15.0


def test_sdk_timeout_becomes_timeout_status_not_an_exception(monkeypatch):
    def create(**_):
        raise anthropic.APITimeoutError(request=SimpleNamespace())

    _install_fake_client(monkeypatch, create=create)
    output = _run(LLMBaselineAdapter())

    assert output.status == "timeout"
    assert output.patch is None
    assert output.cost_usd == 0.0
    assert "120s" in output.error_message
    assert output.runtime_seconds >= 0.0


def test_other_api_errors_still_propagate(monkeypatch):
    def create(**_):
        raise anthropic.APIConnectionError(request=SimpleNamespace())

    _install_fake_client(monkeypatch, create=create)
    with pytest.raises(anthropic.APIConnectionError):
        _run(LLMBaselineAdapter())


def test_run_under_the_cost_cap_is_a_normal_success(monkeypatch):
    _install_fake_client(monkeypatch, create=lambda **_: _response())
    output = _run(LLMBaselineAdapter())

    assert output.status == "success"
    assert output.cost_usd == pytest.approx((100 * 3 + 50 * 15) / 1_000_000)
    assert output.error_message is None


def test_run_over_the_cost_cap_is_flagged_cost_exceeded(monkeypatch):
    # 100k output tokens ~ $1.50 at $15/MTok, over the default $0.50 cap.
    _install_fake_client(monkeypatch, create=lambda **_: _response(output_tokens=100_000))
    output = _run(LLMBaselineAdapter())

    assert output.status == "cost_exceeded"
    assert output.cost_usd == pytest.approx((100 * 3 + 100_000 * 15) / 1_000_000)
    assert "$0.50" in output.error_message


def test_configured_cost_cap_is_honoured(monkeypatch):
    _install_fake_client(monkeypatch, create=lambda **_: _response())
    adapter = LLMBaselineAdapter()
    adapter.configure({"cost_cap_usd": 0.0001})  # the 100-in/50-out run costs $0.00105
    assert _run(adapter).status == "cost_exceeded"


def test_metadata_records_prompt_version_stop_reason_and_patch_source(monkeypatch):
    _install_fake_client(monkeypatch, create=lambda **_: _response(stop_reason="tool_use"))
    metadata = _run(LLMBaselineAdapter()).metadata
    assert metadata["prompt_version"] == PROMPT_VERSION
    assert metadata["stop_reason"] == "tool_use"
    assert metadata["patch_source"] == "tool"
    assert metadata["model"] == LLMBaselineAdapter.DEFAULT_MODEL
