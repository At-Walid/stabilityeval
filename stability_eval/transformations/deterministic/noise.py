from __future__ import annotations

import random
import re

from stability_eval.transformations.base import AbstractTransformation, IssueRecord, TransformedIssue
from stability_eval.transformations.registry import register

# Approximate keyboard adjacency for lowercase letters
_NEIGHBORS: dict[str, str] = {
    "a": "sqzw", "b": "vghn", "c": "xdfv", "d": "ersfcx", "e": "wrsdf",
    "f": "rtdgvc", "g": "tyfhvb", "h": "yugjbn", "i": "uojkl", "j": "uihknm",
    "k": "iojlm", "l": "opk",  "m": "njk",  "n": "bhjm", "o": "iklp",
    "p": "ol",   "q": "wa",   "r": "etdf", "s": "wedxza", "t": "ryfge",
    "u": "yhji", "v": "cfgb", "w": "qsae", "x": "zsdc",  "y": "tghu",
    "z": "asx",
}

# Matches fenced code blocks (``` … ```) and inline backtick spans (` … `)
_CODE_RE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)", re.MULTILINE)


def _segments(text: str) -> list[tuple[str, bool]]:
    """Split *text* into (segment, is_code) pairs."""
    parts: list[tuple[str, bool]] = []
    last = 0
    for m in _CODE_RE.finditer(text):
        s, e = m.span()
        if s > last:
            parts.append((text[last:s], False))
        parts.append((text[s:e], True))
        last = e
    if last < len(text):
        parts.append((text[last:], False))
    return parts


def _apply_typo(word: str, rng: random.Random) -> str:
    """Apply one random character-level error; non-alpha chars are never mutated."""
    alpha = [i for i, c in enumerate(word) if c.isalpha()]
    if len(alpha) < 2:
        return word

    op = rng.randint(0, 2)
    chars = list(word)

    if op == 0:
        # Swap two adjacent alpha positions
        pairs = [(alpha[i], alpha[i + 1]) for i in range(len(alpha) - 1)]
        i, j = rng.choice(pairs)
        chars[i], chars[j] = chars[j], chars[i]
    elif op == 1:
        # Delete one alpha character
        i = rng.choice(alpha)
        del chars[i]
    else:
        # Replace with a keyboard-adjacent character
        i = rng.choice(alpha)
        c = word[i].lower()
        pool = _NEIGHBORS.get(c, "e")
        replacement = rng.choice(pool)
        chars[i] = replacement.upper() if word[i].isupper() else replacement

    return "".join(chars)


@register
class TypoInjection(AbstractTransformation):
    """T08 — Inject character-level typos into prose at a configurable word rate.

    Params:
        error_rate  float  fraction of prose words to corrupt  (default 0.02)
        seed        int    random seed for reproducibility     (default None)
    """

    name = "typo_injection"
    category = "deterministic"
    preserves_semantics = False

    DEFAULT_ERROR_RATE: float = 0.02

    def transform(self, issue: IssueRecord, params: dict) -> TransformedIssue:
        rate: float = params.get("error_rate", self.DEFAULT_ERROR_RATE)
        seed = params.get("seed", None)
        rng = random.Random(seed)

        result_parts: list[str] = []
        modified = 0

        for seg, is_code in _segments(issue.text):
            if is_code:
                result_parts.append(seg)
                continue

            # Split segment preserving whitespace runs
            tokens = re.split(r"(\s+)", seg)
            word_indices = [i for i, t in enumerate(tokens) if t.strip()]
            n_target = max(1, round(len(word_indices) * rate)) if word_indices else 0
            to_modify = set(rng.sample(word_indices, min(n_target, len(word_indices))))

            new_tokens: list[str] = []
            for i, t in enumerate(tokens):
                if i in to_modify:
                    new_tokens.append(_apply_typo(t, rng))
                    modified += 1
                else:
                    new_tokens.append(t)
            result_parts.append("".join(new_tokens))

        return TransformedIssue(
            original_issue_id=issue.issue_id,
            transformation_name=self.name,
            transformation_params=params,
            transformed_text="".join(result_parts),
            transformation_notes=(
                f"Injected character-level typos into ~{rate * 100:.0f}% of prose words "
                f"({modified} word(s) modified); code spans left untouched."
            ),
        )
