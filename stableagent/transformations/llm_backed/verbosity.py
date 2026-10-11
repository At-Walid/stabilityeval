from __future__ import annotations

from stableagent.transformations.llm_backed.base import LLMBackedTransformation
from stableagent.transformations.registry import register

_SYSTEM_PROMPT = """\
You are a technical editor. Shorten the given software issue description to roughly half of
its original length (target: about 0.5x the word count) by removing redundancy, filler,
pleasantries and speculation from the prose.

HARD CONSTRAINTS (they always win over the length target):
- Copy VERBATIM, character for character: every identifier (function, class, method,
  variable, module and test names), file path, command, error message, exception name,
  configuration value and version number.
- Treat as technical, and copy exactly, any token that contains an underscore or a digit, or
  that has an uppercase letter after its first character (CamelCase, or ALL-CAPS such as API).
- Never drop the described symptom: keep what goes wrong (the observed behaviour) and, when
  stated, the expected behaviour and the steps or code needed to reproduce it.
- Do not add information and do not change the meaning of anything you keep.

Output ONLY valid JSON in this exact format:
{"transformed_text": "...", "transformation_notes": "..."}

Example:
Input: "I've been experiencing a rather frustrating issue where the [[CODE_1]] method on the \
[[CODE_2]] class raises an IOError with the message 'Permission denied' whenever I try to \
save a document to the /tmp directory. This happens consistently every time I call it. \
The version I'm using is 1.4.2."
Output: {"transformed_text": "[[CODE_2]].[[CODE_1]] raises IOError: Permission denied when \
saving to /tmp. Version 1.4.2.", "transformation_notes": "Removed filler phrases; kept every \
placeholder and technical token at approximately 0.5× word count."}"""


@register
class VerbosityReduction(LLMBackedTransformation):
    """T03 — Compress issue to ~0.5× word count; preserve all technical identifiers.

    Uses Claude Haiku on the issue text with its code masked (SPEC section 11.7).
    """

    name = "verbosity_reduction"
    preserves_semantics = True
    # v4: code masked behind placeholders (v3: technical-token retention check; v2:
    # verbatim/symptom prompt). v3 variants that passed the quality check are kept.
    transform_version = "4"
    reuses_passed_versions = frozenset({"3"})
    system_prompt = _SYSTEM_PROMPT
