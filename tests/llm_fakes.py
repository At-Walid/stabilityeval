"""Fake Anthropic and OpenAI clients for the LLM Baseline: same reply, either provider's shape.

``Reply`` describes what a model answered (a submit_patch call with its diff, optional text, the
token usage, whether it was cut at the token limit); ``anthropic_response`` and
``openai_response`` render it the way each SDK returns it. The fake clients record the
constructor arguments and every request, and never touch the network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable


@dataclass
class Reply:
    diff: str | None = None  # the submit_patch call's diff; None: no tool call
    text: str | None = None  # prose next to (or instead of) the tool call
    input_tokens: int = 1000
    output_tokens: int = 200
    cut: bool = False  # cut at max_tokens: the tool input / arguments are incomplete
    model: str | None = None  # the model the provider reports (OpenAI: a dated snapshot)
    raw_arguments: str | None = None  # OpenAI: the arguments string as sent, e.g. cut mid-JSON


def anthropic_response(reply: Reply):
    content = []
    if reply.text is not None:
        content.append(SimpleNamespace(type="text", text=reply.text))
    if reply.diff is not None:
        content.append(SimpleNamespace(
            type="tool_use", id="toolu_01", name="submit_patch", input={"diff": reply.diff},
        ))
    stop_reason = "max_tokens" if reply.cut else ("tool_use" if reply.diff is not None else
                                                  "end_turn")
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(input_tokens=reply.input_tokens, output_tokens=reply.output_tokens),
        stop_reason=stop_reason,
    )


def openai_response(reply: Reply, model: str = "gpt-4o"):
    tool_calls = None
    if reply.diff is not None:
        arguments = reply.raw_arguments or json.dumps({"diff": reply.diff})
        tool_calls = [SimpleNamespace(
            id="call_01", type="function",
            function=SimpleNamespace(name="submit_patch", arguments=arguments),
        )]
    message = SimpleNamespace(role="assistant", content=reply.text, tool_calls=tool_calls)
    # With a forced function call the API reports finish_reason "stop", not "tool_calls".
    finish_reason = "length" if reply.cut else "stop"
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=reply.input_tokens, completion_tokens=reply.output_tokens,
        ),
        model=reply.model or model,
    )


@dataclass
class FakeOpenAI:
    """Stands in for openai.OpenAI. ``respond(request) -> Reply`` (default: a fixed diff)."""

    respond: Callable[[dict], Reply] = lambda request: Reply(
        diff="--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    raises: Exception | None = None
    clients: list[dict] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)

    def OpenAI(self, **kwargs):  # noqa: N802 - mirrors openai.OpenAI
        self.clients.append(kwargs)

        def create(**request):
            self.requests.append(request)
            if self.raises is not None:
                raise self.raises
            return openai_response(self.respond(request), model=request["model"])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def install(self, monkeypatch) -> FakeOpenAI:
        import openai

        monkeypatch.setattr(openai, "OpenAI", self.OpenAI)
        return self


@dataclass
class FakeAnthropicAgent:
    """Stands in for anthropic.Anthropic for the LLM Baseline (not the transformations)."""

    respond: Callable[[dict], Reply] = lambda request: Reply(
        diff="--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    raises: Exception | None = None
    clients: list[dict] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)

    def Anthropic(self, **kwargs):  # noqa: N802 - mirrors anthropic.Anthropic
        self.clients.append(kwargs)

        def create(**request):
            self.requests.append(request)
            if self.raises is not None:
                raise self.raises
            return anthropic_response(self.respond(request))

        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def install(self, monkeypatch) -> FakeAnthropicAgent:
        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", self.Anthropic)
        return self
