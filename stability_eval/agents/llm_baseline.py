from __future__ import annotations

import json
import time

from stability_eval.agents.base import AbstractAgentAdapter, AgentInput, AgentOutput, ExecutionMode
from stability_eval.agents.registry import agent_registry
from stability_eval.config.settings import get_anthropic_api_key, settings
from stability_eval.metrics.patch_similarity import extract_final_patch, has_unified_diff

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
# Recorded in every run's metadata so results can be traced to the prompt that produced them.
PROMPT_VERSION = "issue-to-unified-diff-v3-submit-patch-tool"


def build_user_message(agent_input: AgentInput) -> str:
    """The repository name and the issue text: everything the baseline is shown."""
    return f"Repository: {agent_input.repo_name}\n\nIssue:\n{agent_input.issue_text}"


_NO_PATCH_MESSAGES = {
    "tool": "The submit_patch call contained no valid unified diff.",
    "tool_extracted": "The submit_patch call contained no valid unified diff.",
    "text": "No submit_patch call, and no valid unified diff could be extracted from the reply.",
    "empty": "Claude returned an empty response.",
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


@agent_registry.register
class LLMBaselineAdapter(AbstractAgentAdapter):
    """Single-call Claude Sonnet agent: receives an issue, returns a unified diff patch."""

    name = "llm_baseline"
    version = "1.0"
    supported_modes = [ExecutionMode.REAL, ExecutionMode.DRY_RUN]

    # Canonical default model — read by callers (dashboard display, direct API
    # callers) instead of hardcoding the model string themselves, so config and
    # display can never diverge. Overridable per-experiment via configure({"model": ...}).
    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    # The forced tool call returns only the diff (no prose), so 4096 output tokens suffice.
    DEFAULT_MAX_TOKENS: int = 4096

    def __init__(self) -> None:
        self._model: str = self.DEFAULT_MODEL
        self._temperature: float = 0.0
        self._max_tokens: int = self.DEFAULT_MAX_TOKENS
        self._timeout_seconds: int = settings.DEFAULT_TIMEOUT_SECONDS
        self._cost_cap_usd: float = settings.DEFAULT_COST_CAP_USD
        self._api_key_env_var: str = "ANTHROPIC_API_KEY"

    def configure(self, params: dict) -> None:
        self._model = params.get("model", self._model)
        self._temperature = params.get("temperature", self._temperature)
        self._max_tokens = params.get("max_tokens", self._max_tokens)
        self._timeout_seconds = params.get("timeout_seconds", self._timeout_seconds)
        self._cost_cap_usd = params.get("cost_cap_usd", self._cost_cap_usd)
        self._api_key_env_var = params.get("api_key_env_var", self._api_key_env_var)

    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput:
        api_key = get_anthropic_api_key(self._api_key_env_var)
        if not api_key:
            raise RuntimeError("Real mode requires ANTHROPIC_API_KEY")
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("The anthropic package is required for real mode") from None

        # timeout_seconds is the SDK's per-request timeout. The SDK also retries timeouts
        # (and 429/5xx) up to its default max_retries=2, so the wall-clock bound for one
        # run is roughly timeout_seconds x 3.
        client = anthropic.Anthropic(api_key=api_key, timeout=float(self._timeout_seconds))
        metadata = {"model": self._model, "prompt_version": PROMPT_VERSION}
        started = time.monotonic()
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
            # SDK retries exhausted: record a distinct failure mode (SPEC 12.3) rather than raise.
            return AgentOutput(
                status="timeout",
                error_message=(
                    f"No response within {self._timeout_seconds}s (SDK retries exhausted)."
                ),
                runtime_seconds=time.monotonic() - started,
                metadata=metadata,
            )
        patch, raw_logs, source = read_patch(response.content)
        truncated = response.stop_reason == "max_tokens"
        if truncated and source.startswith("tool"):
            patch = None  # the tool input was cut off: an incomplete diff is not a submission
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (input_tokens * 3 + output_tokens * 15) / 1_000_000

        if cost > self._cost_cap_usd:
            status = "cost_exceeded"
            error_message = (
                f"Run cost ${cost:.4f} exceeded the per-run cap of ${self._cost_cap_usd:.2f}."
            )
        elif patch is None:
            status = "no_patch"  # a failure, not a success: nothing applicable was produced
            error_message = _NO_PATCH_MESSAGES[source]
            if truncated:
                error_message = (
                    f"The reply was cut at max_tokens ({self._max_tokens}), so the diff is "
                    f"incomplete. {error_message}"
                    if not source.startswith("tool")
                    else f"The submit_patch call was cut at max_tokens ({self._max_tokens}): "
                    "the diff is incomplete."
                )
        else:
            status, error_message = "success", None
        return AgentOutput(
            status=status,
            patch=patch,
            token_usage={"input": input_tokens, "output": output_tokens},
            cost_usd=cost,
            runtime_seconds=time.monotonic() - started,
            error_message=error_message,
            raw_logs=raw_logs,
            metadata={**metadata, "stop_reason": response.stop_reason, "patch_source": source},
        )

    def health_check(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return get_anthropic_api_key(self._api_key_env_var) is not None
