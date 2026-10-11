from __future__ import annotations

from stableagent.transformations.llm_backed.base import LLMBackedTransformation
from stableagent.transformations.registry import register

_SYSTEM_PROMPT = """\
You are a technical writing assistant. Rewrite the given software issue description in
different words while preserving its complete technical meaning.

HARD CONSTRAINTS — never violate these:
- All technical identifiers (function names, class names, variable names, method names),
  error messages, test names, and version numbers must appear VERBATIM in the output.
- The semantic content must be fully preserved: same bug, same reproduction steps, same
  expected and actual behaviors.
- Do not add or remove technical information.

Output ONLY valid JSON in this exact format:
{"transformed_text": "...", "transformation_notes": "..."}

Example:
Input: "The [[CODE_1]] function raises [[CODE_2]] when called with an empty session. \
Version 2.3.1."
Output: {"transformed_text": "An [[CODE_2]] is thrown by [[CODE_1]] when the session is \
empty. This affects version 2.3.1.", "transformation_notes": "Reworded sentence structure; \
moved the placeholders, kept the version verbatim."}"""


@register
class Paraphrase(LLMBackedTransformation):
    """T01 — Rewrite issue in different words; preserve all technical identifiers.

    Uses Claude Haiku on the issue text with its code masked (SPEC section 11.7).
    """

    name = "paraphrase"
    preserves_semantics = True
    # v4: code masked behind placeholders (v3: technical-token retention check; v2:
    # retry-then-exclude). v3 variants that passed the quality check are kept.
    transform_version = "4"
    reuses_passed_versions = frozenset({"3"})
    system_prompt = _SYSTEM_PROMPT
