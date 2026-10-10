from __future__ import annotations

from stability_eval.transformations.base import invented_versions
from stability_eval.transformations.llm_backed.base import LLMBackedTransformation
from stability_eval.transformations.registry import register

NOT_SPECIFIED = "Not specified"

_SYSTEM_PROMPT = """\
You are a technical writer. Reformat the given software issue description into a structured
bug report with exactly these sections, in this order: Summary, Steps to Reproduce, Expected
Behavior, Actual Behavior, Environment.

HARD CONSTRAINTS — never violate these:
- Use ONLY information present in the original issue. Do not infer, guess or complete anything.
- When the original gives no information for a section, write exactly "Not specified" as that
  section's content. Never fill a section with plausible-sounding text.
- Never invent version numbers, reproduction steps, commands, inputs, operating systems,
  library versions or any other environment detail. Steps to Reproduce lists only steps the
  original states or shows (for example its code snippet); otherwise "Not specified".
- Copy VERBATIM every technical identifier (function, class, method, variable, module and test
  names), file path, command, error message and version number.
- Do not drop any fact the original states.

Output ONLY valid JSON in this exact format:
{"transformed_text": "...", "transformation_notes": "..."}

Example:
Input: "The [[CODE_1]] function crashes with IndexError when the CSV has an empty first \
row:\\n\\n[[CODE_2]]\\n\\nExpected it to return an empty list."
Output: {"transformed_text": "## Summary\\n[[CODE_1]] raises IndexError on CSV files \
with an empty first row.\\n\\n## Steps to Reproduce\\n1. Run:\\n\\n[[CODE_2]]\\n\\n\
## Expected Behavior\\nReturns an empty list.\\n\\n## Actual Behavior\\nRaises IndexError.\\n\\n\
## Environment\\nNot specified", "transformation_notes": "Reformatted prose into the five \
sections; Environment is not given in the original."}"""


@register
class ParagraphToStructured(LLMBackedTransformation):
    """T10 — Reformat prose issue as structured bug report.

    Uses Claude Haiku on the issue text with its code masked (SPEC section 11.7). Only
    information present in the original may appear; missing sections read "Not specified".
    Besides the identifier-retention check, an output that mentions a version number the
    original does not is rejected (retry, then exclude).
    """

    name = "paragraph_to_structured"
    preserves_semantics = True
    # v5: code masked behind placeholders (v4: technical-token retention check; v3:
    # original-information-only prompt with "Not specified" sections + invented-version check).
    # v4 variants that passed the quality check are kept.
    transform_version = "5"
    reuses_passed_versions = frozenset({"4"})
    system_prompt = _SYSTEM_PROMPT

    def invented_details(self, original: str, transformed: str) -> list[str]:
        return [f"version {v}" for v in invented_versions(original, transformed)]
