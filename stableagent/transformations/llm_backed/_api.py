from __future__ import annotations

import json
import re
from dataclasses import dataclass

# The model every LLM-backed transformation calls; recorded as its variants' generator.
TRANSFORMATION_MODEL = "claude-haiku-4-5-20251001"
# USD per million (input, output) tokens of TRANSFORMATION_MODEL.
HAIKU_PRICE_PER_MTOK = (1.0, 5.0)


@dataclass(frozen=True)
class HaikuReply:
    text: str  # the transformed text
    notes: str = ""  # the model's transformation notes (JSON replies only)
    raw: str | None = None  # the reply as sent (None: same as text); replayed on a retry
    cost_usd: float = 0.0


def call_haiku(
    system_prompt: str,
    user_content: str,
    api_key: str,
    model: str = TRANSFORMATION_MODEL,
    *,
    expect_json: bool = True,
    retry: tuple[str, str] | None = None,
) -> HaikuReply:
    """Call Claude Haiku once and return its transformed text, notes and cost.

    With ``expect_json`` the model returns JSON: {"transformed_text": "...",
    "transformation_notes": "..."}; raw text is returned when the response does not follow that
    contract. Without it, the reply is the text itself (notes ""). ``retry`` is (previous reply,
    feedback): the model sees its previous reply and the feedback, then answers again. API errors
    propagate: the caller decides (in real mode, the transformation cache raises a
    TransformationError).
    """
    import anthropic

    messages = [{"role": "user", "content": user_content}]
    if retry is not None:
        previous, feedback = retry
        messages += [
            {"role": "assistant", "content": previous},
            {"role": "user", "content": feedback},
        ]
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
    )
    raw: str = response.content[0].text.strip()
    usage = response.usage
    cost = (
        usage.input_tokens * HAIKU_PRICE_PER_MTOK[0] + usage.output_tokens * HAIKU_PRICE_PER_MTOK[1]
    ) / 1_000_000
    if not expect_json:
        return HaikuReply(raw, "", raw, cost)

    # Direct parse
    try:
        data = json.loads(raw)
        return HaikuReply(data["transformed_text"], data.get("transformation_notes", ""), raw, cost)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Extract JSON from markdown-fenced or partial response
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            data = json.loads(m.group())
            return HaikuReply(
                data["transformed_text"], data.get("transformation_notes", ""), raw, cost
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return HaikuReply(raw, "LLM returned non-JSON response; using raw output.", raw, cost)
