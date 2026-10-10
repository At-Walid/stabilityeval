from __future__ import annotations

import random
import re

from stability_eval.transformations.base import AbstractTransformation, IssueRecord, TransformedIssue
from stability_eval.transformations.registry import register

_DEFAULT_SEED = 42
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def split_paragraphs(text: str) -> list[str]:
    """Blank-line-separated paragraphs of LF text; a fenced code block is never split."""
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current.append(line)
        elif not line.strip() and not in_fence:
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


@register
class ReorderingTransformation(AbstractTransformation):
    """T07 — Shuffle paragraph order to test positional sensitivity.

    CRLF is normalised to LF first, the text is split on blank lines only (never inside a fenced
    code block), and whole paragraphs are shuffled. Text with fewer than 2 paragraphs is returned
    unchanged: single lines are never shuffled.

    Params:
        seed  int  random seed for reproducibility  (default 42)
    """

    name = "reordering"
    category = "deterministic"
    preserves_semantics = True
    transform_version = "2"  # v2: CRLF-aware, fence-aware paragraphs; no line shuffling

    def transform(self, issue: IssueRecord, params: dict) -> TransformedIssue:
        seed: int = params.get("seed", _DEFAULT_SEED)
        paragraphs = split_paragraphs(issue.text.replace("\r\n", "\n").replace("\r", "\n"))

        if len(paragraphs) < 2:
            return TransformedIssue(
                original_issue_id=issue.issue_id,
                transformation_name=self.name,
                transformation_params=params,
                transformed_text=issue.text,
                transformation_notes=(
                    "Fewer than 2 paragraphs (code blocks kept whole) — returned unchanged; "
                    "lines are never shuffled."
                ),
            )

        shuffled = paragraphs[:]
        random.Random(seed).shuffle(shuffled)
        notes = (
            f"Shuffled {len(paragraphs)} paragraph(s) (seed={seed}); CRLF normalised to LF, "
            "fenced code blocks kept whole."
        )
        if shuffled == paragraphs:
            notes += " The shuffle kept the original order."
        return TransformedIssue(
            original_issue_id=issue.issue_id,
            transformation_name=self.name,
            transformation_params=params,
            transformed_text="\n\n".join(shuffled),
            transformation_notes=notes,
        )
