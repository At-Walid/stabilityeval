"""Base class of the LLM-backed transformations: one Haiku rewrite of the issue with its code masked.

Every attempt masks the code (SPEC section 11.7, ``transformations.masking``), asks the model to
rewrite the masked text under the placeholder rules below, checks the placeholders and restores the
code byte for byte. A placeholder the model did not keep exactly once is reported on the result
(``placeholder_problems``); the transformation cache then retries once with feedback, and
otherwise excludes the variant ("placeholder_lost").
"""
from __future__ import annotations

from stability_eval.config.settings import get_anthropic_api_key
from stability_eval.transformations.base import (
    AbstractTransformation,
    IssueRecord,
    TransformedIssue,
)
from stability_eval.transformations.llm_backed._api import TRANSFORMATION_MODEL
from stability_eval.transformations.masking import mask_code

PLACEHOLDER_RULES = """

CODE PLACEHOLDERS:
The code of the issue (code blocks, doctest sessions, tracebacks and inline code) has been
replaced by numbered placeholders such as [[CODE_1]]; the original code is put back after your
rewrite.
- Every placeholder must appear in your output exactly once, written exactly as in the input.
- You may move a placeholder, but never edit, split, merge or drop it, never wrap it in backticks
  or a code fence, and never write out the code it stands for.
- A placeholder on a line of its own stands for a whole block: keep it on a line of its own."""


class LLMBackedTransformation(AbstractTransformation):
    """A transformation whose output is one Claude Haiku rewrite of the masked issue text.

    Subclasses set ``name``, ``transform_version`` and ``system_prompt`` (the placeholder rules
    are appended to it); ``expect_json`` says whether the model answers with JSON
    {"transformed_text", "transformation_notes"} or with the text itself.
    """

    category = "llm_backed"
    model = TRANSFORMATION_MODEL
    system_prompt: str = ""
    expect_json: bool = True

    def transform(self, issue: IssueRecord, params: dict) -> TransformedIssue:
        return self._attempt(issue, params, retry=None)

    def retry(
        self, issue: IssueRecord, params: dict, previous: TransformedIssue, feedback: str
    ) -> TransformedIssue:
        """Ask again, showing the model its previous reply and the feedback."""
        return self._attempt(issue, params, retry=(previous.reply or "", feedback))

    def notes(self, original: str, transformed: str, model_notes: str) -> str:
        """The variant's transformation notes: the model's own by default."""
        return model_notes

    def _attempt(
        self, issue: IssueRecord, params: dict, *, retry: tuple[str, str] | None
    ) -> TransformedIssue:
        from stability_eval.transformations.llm_backed._api import call_haiku

        api_key = get_anthropic_api_key()
        if not api_key:
            raise RuntimeError("LLM-backed transformations require ANTHROPIC_API_KEY")
        masked = mask_code(issue.text)
        reply = call_haiku(
            self.system_prompt + PLACEHOLDER_RULES, masked.text, api_key, model=self.model,
            expect_json=self.expect_json, retry=retry,
        )
        text = masked.restore(reply.text)
        return TransformedIssue(
            original_issue_id=issue.issue_id,
            transformation_name=self.name,
            transformation_params=params,
            transformed_text=text,
            transformation_notes=self.notes(issue.text, text, reply.notes),
            placeholder_problems=masked.problems(reply.text),
            generation_cost_usd=reply.cost_usd,
            reply=reply.text if reply.raw is None else reply.raw,
        )
