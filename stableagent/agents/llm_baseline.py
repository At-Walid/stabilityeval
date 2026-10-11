from __future__ import annotations

import json
import time
from dataclasses import dataclass
from types import SimpleNamespace

from stableagent.agents.base import AbstractAgentAdapter, AgentInput, AgentOutput, ExecutionMode
from stableagent.agents.registry import agent_registry
from stableagent.config.pricing import (
    ANTHROPIC,
    OPENAI,
    PROVIDERS,
    display_name,
    model_info,
)
from stableagent.config.settings import (
    API_KEY_ENV_VAR,
    OPENAI_API_KEY_ENV_VAR,
    get_anthropic_api_key,
    get_openai_api_key,
    settings,
)
from stableagent.metrics.patch_similarity import extract_final_patch, has_unified_diff

SYSTEM_PROMPT = (
    "You are an expert software engineer. You will be given a GitHub issue description\n"
    "and the repository name. Produce the patch that resolves the issue and submit it with\n"
    "the submit_patch tool: exactly ONE unified diff (--- / +++ headers and @@ hunks) covering\n"
    "every file you change. The diff string contains only the diff: no prose, no explanation,\n"
    "no code fences, no alternative versions."
)
# The model must answer by calling this tool (forced tool_choice): its one string parameter is the
# patch, so no diff has to be extracted from prose.
SUBMIT_PATCH_TOOL = {
    "name": "submit_patch",
    "description": "Submit the patch that resolves the issue, as one unified diff.",
    "input_schema": {
        "type": "object",
        "properties": {
            "diff": {
                "type": "string",
                "description": (
                    "One unified diff (--- a/path, +++ b/path headers and @@ hunks) for every "
                    "file the fix changes. Only the diff: no prose and no code fences."
                ),
            },
        },
        "required": ["diff"],
    },
}
SUBMIT_PATCH_CHOICE = {"type": "tool", "name": "submit_patch"}
# The same tool for the OpenAI provider (function calling): same name, description and parameters,
# and tool_choice forcing that function.
OPENAI_SUBMIT_PATCH_TOOL = {
    "type": "function",
    "function": {
        "name": SUBMIT_PATCH_TOOL["name"],
        "description": SUBMIT_PATCH_TOOL["description"],
        "parameters": SUBMIT_PATCH_TOOL["input_schema"],
    },
}
OPENAI_SUBMIT_PATCH_CHOICE = {"type": "function", "function": {"name": "submit_patch"}}
# Recorded in every run's metadata so results can be traced to the prompt that produced them.
PROMPT_VERSION = "issue-to-unified-diff-v3-submit-patch-tool"
# Where each provider's key is read from unless the agent params name another variable.
DEFAULT_API_KEY_ENV_VARS = {ANTHROPIC: API_KEY_ENV_VAR, OPENAI: OPENAI_API_KEY_ENV_VAR}
# OpenAI finish reasons in the Anthropic stop_reason vocabulary, so both providers' run records
# read the same ("max_tokens": the reply was cut). "stop" and "tool_calls" are mapped by whether
# the reply holds the tool call.
_OPENAI_STOP_REASONS = {"length": "max_tokens", "content_filter": "refusal"}


def build_user_message(agent_input: AgentInput) -> str:
    """The repository name and the issue text: everything the baseline is shown."""
    return f"Repository: {agent_input.repo_name}\n\nIssue:\n{agent_input.issue_text}"


def baseline_label(model: str) -> str:
    """E.g. "LLM Baseline (GPT-4o)": how the dashboard, the figure and the tables name the agent."""
    return f"LLM Baseline ({display_name(model)})"


@dataclass(frozen=True)
class BaselinePreset:
    """An LLM Baseline the dashboard offers as an agent of its own."""

    provider: str
    model: str

    @property
    def label(self) -> str:
        return baseline_label(self.model)

    @property
    def api_key_env_var(self) -> str:
        return DEFAULT_API_KEY_ENV_VARS[self.provider]


# The two models of the ICSE pilot (configs/icse_pilot.json, configs/icse_pilot_model2.json).
BASELINE_PRESETS = (BaselinePreset(ANTHROPIC, "claude-sonnet-4-6"), BaselinePreset(OPENAI, "gpt-4o"))


class MissingAPIKeyError(RuntimeError):
    """Real mode without the key of the agent's provider. Raised before any API call."""


_NO_PATCH_MESSAGES = {
    "tool": "The submit_patch call contained no valid unified diff.",
    "tool_extracted": "The submit_patch call contained no valid unified diff.",
    "text": "No submit_patch call, and no valid unified diff could be extracted from the reply.",
    "empty": "The model returned an empty response.",
}


def read_patch(content) -> tuple[str | None, str, str]:
    """(patch or None, raw_logs, source) from a reply's content blocks.

    The submit_patch tool call is the answer: its ``diff`` is the patch and its input, as JSON,
    the raw log (source "tool"). The text extractor is only a fallback: for a diff the model still
    wrapped in fences or prose ("tool_extracted"), and for a reply without the tool call ("text":
    the reply text is the raw log). Source "empty": nothing came back.
    """
    tool_input = next(
        (
            block.input
            for block in content
            if getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == SUBMIT_PATCH_TOOL["name"]
        ),
        None,
    )
    if tool_input is not None:
        diff = tool_input.get("diff") if isinstance(tool_input, dict) else None
        diff = diff if isinstance(diff, str) else ""
        raw_logs = json.dumps(tool_input, ensure_ascii=False)
        extracted = extract_final_patch(diff)  # a no-op on a clean diff
        if not has_unified_diff(extracted):
            return None, raw_logs, "tool"
        if extracted == diff.strip():
            return diff, raw_logs, "tool"  # clean: stored exactly as submitted
        return extracted, raw_logs, "tool_extracted"  # fallback: fences or prose in the string

    reply = "".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    ).strip()
    if not reply:
        return None, "", "empty"
    # Fallback: no tool call. Keep only the final diff (last version per file) of the reply.
    extracted = extract_final_patch(reply)
    return (extracted if has_unified_diff(extracted) else None), reply, "text"


@dataclass(frozen=True)
class _Reply:
    """A provider's response in one shape: Anthropic content blocks, the Anthropic stop_reason
    vocabulary, the token usage, and the dated model snapshot an alias resolved to (OpenAI)."""

    content: list
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    model_snapshot: str | None = None


def openai_reply(response, requested_model: str) -> _Reply:
    """An OpenAI chat completion as a _Reply: the message text as a text block, each function
    call as a tool_use block whose input is the parsed JSON arguments (arguments that are not
    valid JSON, e.g. cut at the token limit, are kept as ``{"unparsed_arguments": ...}``)."""
    choice = response.choices[0]
    message = choice.message
    content: list = []
    if getattr(message, "content", None):
        content.append(SimpleNamespace(type="text", text=message.content))
    for call in getattr(message, "tool_calls", None) or []:
        function = call.function
        try:
            arguments = json.loads(function.arguments)
        except (TypeError, ValueError):
            arguments = {"unparsed_arguments": function.arguments}
        content.append(SimpleNamespace(type="tool_use", name=function.name, input=arguments))

    finish_reason = choice.finish_reason
    if finish_reason in _OPENAI_STOP_REASONS:
        stop_reason = _OPENAI_STOP_REASONS[finish_reason]
    elif finish_reason in ("stop", "tool_calls"):
        called = any(block.type == "tool_use" for block in content)
        stop_reason = "tool_use" if called else "end_turn"
    else:
        stop_reason = finish_reason
    snapshot = getattr(response, "model", None)
    return _Reply(
        content=content,
        stop_reason=stop_reason,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model_snapshot=snapshot if snapshot and snapshot != requested_model else None,
    )


@agent_registry.register
class LLMBaselineAdapter(AbstractAgentAdapter):
    """Single-call LLM agent: receives an issue, returns a unified diff patch.

    The provider is a parameter (``provider``: "anthropic", the default, or "openai"), with
    ``model`` and ``api_key_env_var`` (default ANTHROPIC_API_KEY / OPENAI_API_KEY). Both providers
    get the same system prompt and user message, temperature 0, the same token limit and timeout,
    and must answer with a forced ``submit_patch`` call; the reply goes through the same diff
    extraction and validation and gets the same statuses. The cost of a run comes from its token
    usage and the model table (stableagent/config/pricing.py).
    """

    name = "llm_baseline"
    version = "1.0"
    supported_modes = [ExecutionMode.REAL, ExecutionMode.DRY_RUN]

    # Canonical default model — read by callers (dashboard display, direct API
    # callers) instead of hardcoding the model string themselves, so config and
    # display can never diverge. Overridable per-experiment via configure({"model": ...}).
    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    DEFAULT_PROVIDER: str = ANTHROPIC
    # The forced tool call returns only the diff (no prose), so 4096 output tokens suffice.
    DEFAULT_MAX_TOKENS: int = 4096

    def __init__(self) -> None:
        self._provider: str = self.DEFAULT_PROVIDER
        self._model: str = self.DEFAULT_MODEL
        self._temperature: float = 0.0
        self._max_tokens: int = self.DEFAULT_MAX_TOKENS
        self._timeout_seconds: int = settings.DEFAULT_TIMEOUT_SECONDS
        self._cost_cap_usd: float = settings.DEFAULT_COST_CAP_USD
        self._api_key_env_var: str | None = None  # None: the provider's default variable

    def configure(self, params: dict) -> None:
        provider = params.get("provider", self._provider)
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown LLM Baseline provider {provider!r}: use one of {', '.join(PROVIDERS)}."
            )
        self._provider = provider
        self._model = params.get("model", self._model)
        self._temperature = params.get("temperature", self._temperature)
        self._max_tokens = params.get("max_tokens", self._max_tokens)
        self._timeout_seconds = params.get("timeout_seconds", self._timeout_seconds)
        self._cost_cap_usd = params.get("cost_cap_usd", self._cost_cap_usd)
        self._api_key_env_var = params.get("api_key_env_var", self._api_key_env_var)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def api_key_env_var(self) -> str:
        return self._api_key_env_var or DEFAULT_API_KEY_ENV_VARS[self._provider]

    def _api_key(self) -> str | None:
        if self._provider == OPENAI:
            return get_openai_api_key(self.api_key_env_var)
        return get_anthropic_api_key(self.api_key_env_var)

    def has_api_key(self) -> bool:
        """Whether the provider's key is set (presence only; the key is never returned)."""
        return self._api_key() is not None

    def check_ready(self) -> None:
        """Raise, before any API call, what would stop a real run: a model without a price
        (UnknownModelError), a model of another provider (ValueError), a missing key
        (MissingAPIKeyError). The runner calls it before an experiment starts in real mode."""
        info = model_info(self._model)
        if info.provider != self._provider:
            raise ValueError(
                f"Model '{self._model}' is an {info.provider} model but the LLM Baseline is "
                f"configured with provider '{self._provider}': set \"provider\": "
                f"\"{info.provider}\" in the agent params."
            )
        if not self.has_api_key():
            where = (
                "in .env (see .env.example); the dashboard never asks for it"
                if self._provider == OPENAI
                else "in .env or the environment, or enter it in the dashboard"
            )
            raise MissingAPIKeyError(
                f"Real mode with the LLM Baseline on {self._model} (provider {self._provider}) "
                f"needs an API key in {self.api_key_env_var}, which is not set. Set it {where}. "
                "No API call was made."
            )

    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput:
        self.check_ready()
        api_key = self._api_key()
        metadata = {"model": self._model, "prompt_version": PROMPT_VERSION}
        started = time.monotonic()
        call = self._call_openai if self._provider == OPENAI else self._call_anthropic
        reply = call(agent_input, api_key)
        if reply is None:
            # SDK retries exhausted: record a distinct failure mode (SPEC 12.3) rather than raise.
            return AgentOutput(
                status="timeout",
                error_message=(
                    f"No response within {self._timeout_seconds}s (SDK retries exhausted)."
                ),
                runtime_seconds=time.monotonic() - started,
                metadata=metadata,
            )
        patch, raw_logs, source = read_patch(reply.content)
        truncated = reply.stop_reason == "max_tokens"
        if truncated and source.startswith("tool"):
            patch = None  # the tool input was cut off: an incomplete diff is not a submission
        input_tokens = reply.input_tokens
        output_tokens = reply.output_tokens
        cost = model_info(self._model).cost(input_tokens, output_tokens)

        if cost > self._cost_cap_usd:
            status = "cost_exceeded"
            error_message = (
                f"Run cost ${cost:.4f} exceeded the per-run cap of ${self._cost_cap_usd:.2f}."
            )
        elif patch is None:
            status = "no_patch"  # a failure, not a success: nothing applicable was produced
            error_message = _NO_PATCH_MESSAGES[source]
            if truncated:
                # Cut at the token limit: a budget limit, not an answer. Excluded from the
                # outcome metrics like a timeout (SPEC section 13).
                status = "truncated"
                error_message = (
                    f"The reply was cut at max_tokens ({self._max_tokens}), so the diff is "
                    f"incomplete. {error_message}"
                    if not source.startswith("tool")
                    else f"The submit_patch call was cut at max_tokens ({self._max_tokens}): "
                    "the diff is incomplete."
                )
        else:
            status, error_message = "success", None
        metadata = {**metadata, "stop_reason": reply.stop_reason, "patch_source": source}
        if reply.model_snapshot:
            metadata["model_snapshot"] = reply.model_snapshot
        return AgentOutput(
            status=status,
            patch=patch,
            token_usage={"input": input_tokens, "output": output_tokens},
            cost_usd=cost,
            runtime_seconds=time.monotonic() - started,
            error_message=error_message,
            raw_logs=raw_logs,
            metadata=metadata,
        )

    def _call_anthropic(self, agent_input: AgentInput, api_key: str) -> _Reply | None:
        """One Messages API call; None when the SDK timed out (after its retries)."""
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("The anthropic package is required for real mode") from None

        # timeout_seconds is the SDK's per-request timeout. The SDK also retries timeouts
        # (and 429/5xx) up to its default max_retries=2, so the wall-clock bound for one
        # run is roughly timeout_seconds x 3.
        client = anthropic.Anthropic(api_key=api_key, timeout=float(self._timeout_seconds))
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system=SYSTEM_PROMPT,
                tools=[SUBMIT_PATCH_TOOL],
                tool_choice=SUBMIT_PATCH_CHOICE,
                messages=[{"role": "user", "content": build_user_message(agent_input)}],
            )
        except anthropic.APITimeoutError:
            return None
        return _Reply(
            content=response.content,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def _call_openai(self, agent_input: AgentInput, api_key: str) -> _Reply | None:
        """One Chat Completions call with the submit_patch function forced; None on a timeout.

        Same prompt text as the Anthropic call (the system prompt as the system message), same
        temperature, token limit and per-request timeout; the SDK's default max_retries is 2 too.
        """
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "The openai package is required for the openai provider (pip install openai)"
            ) from None

        client = openai.OpenAI(api_key=api_key, timeout=float(self._timeout_seconds))
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_completion_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_message(agent_input)},
                ],
                tools=[OPENAI_SUBMIT_PATCH_TOOL],
                tool_choice=OPENAI_SUBMIT_PATCH_CHOICE,
                parallel_tool_calls=False,
            )
        except openai.APITimeoutError:
            return None
        return openai_reply(response, self._model)

    def health_check(self) -> bool:
        try:
            __import__("openai" if self._provider == OPENAI else "anthropic")
        except ImportError:
            return False
        return self.has_api_key()
