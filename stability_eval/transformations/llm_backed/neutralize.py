from __future__ import annotations

from stability_eval.transformations.base import is_noop
from stability_eval.transformations.llm_backed.base import LLMBackedTransformation
from stability_eval.transformations.registry import register

_SYSTEM_PROMPT = """\
You are a technical editor. Remove emotional or informal language from a software issue report \
and change nothing else.

Emotional or informal language means: exclamation marks used for emphasis; emotional or \
judgemental words (terrible, horrible, awful, insane, ridiculous, stupid, annoying, broken \
beyond belief, ...); expressions of frustration, anger or sarcasm; insults; slang and chat \
abbreviations (wtf, lol, pls, gonna, ...). Ordinary contractions (it's, doesn't, can't) and a \
plain, neutral tone are NOT emotional or informal: leave them as they are.

RULES:
- If the report contains no emotional or informal language, output it EXACTLY as given, \
character for character.
- Otherwise rewrite ONLY the sentences that contain such language, in neutral professional \
language with the same technical meaning. Copy every other sentence, line, blank line, list \
and placeholder exactly as given.
- Never add, remove or reorder technical information. Identifiers, file paths, commands, error \
messages and version numbers stay verbatim.

Output only the resulting report text: no preamble, no explanation, no quotes around it."""


@register
class NeutralizeTransformation(LLMBackedTransformation):
    """T11 — Remove emotional/informal language; leave neutral text unchanged.

    Uses Claude Haiku on the issue text with its code masked (SPEC section 11.7). Only the
    offending sentences are rewritten; a report without emotional or informal language comes back
    unchanged, and the cache then flags the variant as a no-op.
    """

    name = "neutralize_emotional"
    preserves_semantics = True
    # v4: code masked behind placeholders (v3: rewrite only offending sentences, return neutral
    # text unchanged; technical-token retention check). v3 variants that passed the quality
    # check are kept.
    transform_version = "4"
    reuses_passed_versions = frozenset({"3"})
    system_prompt = _SYSTEM_PROMPT
    expect_json = False  # the reply is the text itself

    def notes(self, original: str, transformed: str, model_notes: str) -> str:
        if is_noop(original, transformed):
            return "No emotional or informal language found; returned unchanged (no-op)."
        return "Rewrote only the sentences with emotional or informal language."
