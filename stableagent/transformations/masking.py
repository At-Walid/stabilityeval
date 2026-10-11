"""Mask-and-restore of code for LLM-backed transformations (SPEC section 11.7).

Before an LLM rewrites an issue, every piece of code is replaced by a numbered placeholder
([[CODE_1]], [[CODE_2]], ... in order of appearance):

- fenced code blocks (``` or ~~~, fence lines included; closed by the next fence line, as in the
  retention check; an unclosed fence runs to the end);
- indented code blocks (4 spaces or a tab after a blank line, list items excluded, as in the
  retention check), with their interior blank lines;
- ">>>" doctest blocks and tracebacks ("Traceback (most recent call last):"), each up to the next
  blank line;
- inline `code` spans (backticks included).

A block placeholder stands on a line of its own. The model may move placeholders but must keep
each exactly once: ``Masked.problems`` checks that, and ``Masked.restore`` then puts every original
back byte for byte. Text that already looks like a placeholder is masked too, so the model only
ever sees the placeholders made here.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# The retention check's own fence and list-item rules, so every piece of code it protects
# (SPEC section 11.5) lies inside a masked block.
from stableagent.transformations.base import _FENCE_LINE_RE, _LIST_ITEM_RE

PLACEHOLDER_RE = re.compile(r"\[\[CODE_\d+\]\]")

_DOCTEST_RE = re.compile(r"^[ \t]*>>>")
_TRACEBACK_RE = re.compile(r"^[ \t]*Traceback \(most recent call last\):")
# An inline code span (any backtick run, closed by a run of the same length on the same line), or
# text that already looks like a placeholder.
_INLINE_RE = re.compile(r"(?<!`)(`+)(?!`)[^\n]*?[^`\n]\1(?!`)|\[\[CODE_\d+\]\]")
# What a model may wrap around a placeholder; ``Masked.restore`` removes it.
_FENCED_PLACEHOLDER_RE = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[^\n]*\n[ \t]*(\[\[CODE_\d+\]\])[ \t]*\r?\n[ \t]*\1[ \t]*(?=\r?$)",
    re.MULTILINE,
)
_TICKED_PLACEHOLDER_RE = re.compile(r"(`+)(\[\[CODE_\d+\]\])\1")


@dataclass(frozen=True)
class Masked:
    """An issue text with its code replaced by placeholders."""

    text: str  # what the LLM sees
    originals: dict[str, str]  # placeholder -> the exact original code
    blocks: frozenset[str]  # the placeholders that stand for whole lines (not inline spans)

    def problems(self, output: str) -> list[str]:
        """How ``output`` breaks the placeholder contract: each placeholder missing, repeated or
        unknown. Empty when every placeholder appears exactly once."""
        counts = Counter(m.group() for m in PLACEHOLDER_RE.finditer(output))
        problems = []
        for placeholder in self.originals:
            n = counts.get(placeholder, 0)
            if n == 0:
                problems.append(f"{placeholder} missing")
            elif n > 1:
                problems.append(f"{placeholder} appears {n} times")
        problems += [f"{p} unknown" for p in counts if p not in self.originals]
        return problems

    def restore(self, output: str) -> str:
        """``output`` with every placeholder replaced by its original code, byte for byte.

        Backticks or a code fence the model put around a placeholder are removed first (the
        original already carries its own). A block placeholder always ends up on lines of its
        own: the spaces or indentation the model put around it are dropped, and one it put inside
        a line gets a line break before and after. Missing or unknown placeholders are left as
        they are (``problems`` reports them).
        """
        output = _FENCED_PLACEHOLDER_RE.sub(
            lambda m: m.group(2) if m.group(2) in self.blocks else m.group(), output
        )
        output = _TICKED_PLACEHOLDER_RE.sub(
            lambda m: m.group(2) if m.group(2) in self.originals else m.group(), output
        )
        if self.blocks:
            spaced_block = re.compile(
                r"[ \t]*(" + "|".join(map(re.escape, sorted(self.blocks))) + r")[ \t]*"
            )

            def own_line(m: re.Match) -> str:
                lead = "" if m.start() == 0 or output[m.start() - 1] == "\n" else "\n"
                trail = "" if m.end() == len(output) or output[m.end()] in "\r\n" else "\n"
                return lead + m.group(1) + trail

            output = spaced_block.sub(own_line, output)
        # One pass: restored code is never scanned again, even if it contains "[[CODE_n]]".
        return PLACEHOLDER_RE.sub(lambda m: self.originals.get(m.group(), m.group()), output)


def mask_code(text: str) -> Masked:
    """``text`` with its code blocks, doctests, tracebacks and inline code spans masked."""
    segments = _block_segments(text)
    prose_start = 0
    for start, end, _block in list(segments):
        segments += _inline_segments(text, prose_start, start)
        prose_start = end
    segments += _inline_segments(text, prose_start, len(text))
    segments.sort()

    parts: list[str] = []
    originals: dict[str, str] = {}
    blocks: set[str] = set()
    position = 0
    for number, (start, end, block) in enumerate(segments, start=1):
        placeholder = f"[[CODE_{number}]]"
        originals[placeholder] = text[start:end]
        if block:
            blocks.add(placeholder)
        parts += [text[position:start], placeholder]
        position = end
    parts.append(text[position:])
    return Masked("".join(parts), originals, frozenset(blocks))


def _inline_segments(text: str, start: int, end: int) -> list[tuple[int, int, bool]]:
    return [(m.start(), m.end(), False) for m in _INLINE_RE.finditer(text, start, end)]


def _block_segments(text: str) -> list[tuple[int, int, bool]]:
    """(start, end, True) of every code block: whole lines, without the last line's line ending."""
    lines = text.split("\n")
    offsets = [0]
    for line in lines[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)

    def span(first: int, last: int) -> tuple[int, int, bool]:
        end = offsets[last] + len(lines[last])
        if lines[last].endswith("\r"):
            end -= 1
        return offsets[first], end, True

    segments = []
    after_blank_or_code = True  # markdown: an indented code block follows a blank line
    i = 0
    while i < len(lines):
        line, stripped = lines[i], lines[i].strip()
        last = None
        if _FENCE_LINE_RE.match(line):
            # Closed by the next fence line, as in the retention check; unclosed: code up to the
            # last non-blank line.
            last = next(
                (j for j in range(i + 1, len(lines)) if _FENCE_LINE_RE.match(lines[j])),
                max(j for j in range(i, len(lines)) if lines[j].strip()),
            )
        elif (
            line.startswith(("    ", "\t"))
            and stripped
            and after_blank_or_code
            and not _LIST_ITEM_RE.match(stripped)
        ):
            last = i
            for j in range(i + 1, len(lines)):
                if lines[j].startswith(("    ", "\t")) and lines[j].strip():
                    last = j
                elif lines[j].strip():
                    break
        elif _DOCTEST_RE.match(line) or _TRACEBACK_RE.match(line):
            last = i
            while last + 1 < len(lines) and lines[last + 1].strip():
                last += 1
        if last is None:
            after_blank_or_code = not stripped
            i += 1
        else:
            segments.append(span(i, last))
            after_blank_or_code = True
            i = last + 1
    return segments
