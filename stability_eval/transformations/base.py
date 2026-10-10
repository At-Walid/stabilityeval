from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IssueRecord:
    issue_id: str
    repo_name: str
    text: str
    reproduction_steps: Optional[str] = None
    expected_behavior: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class TransformedIssue:
    original_issue_id: str
    transformation_name: str
    transformation_params: dict
    transformed_text: str
    transformation_notes: str  # Human-readable explanation of changes
    # LLM-backed only (SPEC section 11.7): the code placeholders the model did not keep exactly
    # once (the text could not be fully restored), the attempt's API cost, and the model's raw
    # reply (shown to it again on a retry).
    placeholder_problems: list[str] = field(default_factory=list)
    generation_cost_usd: float = 0.0
    reply: Optional[str] = None


# A variant's ``generator`` (its provenance, SPEC section 11.6) is the model id of an LLM-backed
# transformation, or one of these.
DETERMINISTIC = "deterministic"
PLACEHOLDER = "placeholder"  # offline stand-in (mock / dry-run mode): never a generated variant
ORIGINAL = "original"  # the untransformed issue text
UNKNOWN = "unknown"  # stored before provenance was recorded


class AbstractTransformation(ABC):
    name: str
    category: str  # "deterministic" | "llm_backed"
    preserves_semantics: bool = True
    # Part of the cache key: bump it whenever the output for the same input can change (new
    # prompt, new algorithm, new quality rule), so variants cached by older versions are not reused.
    transform_version: str = "1"
    # Earlier versions whose variants that PASSED the quality check stay valid: the change since
    # then only matters for outputs that failed it. Failed variants of these versions are
    # regenerated; every other older version is never reused.
    reuses_passed_versions: frozenset[str] = frozenset()
    # The model an LLM-backed transformation calls: its variants' generator, part of the cache key.
    model: Optional[str] = None

    @abstractmethod
    def transform(self, issue: IssueRecord, params: dict) -> TransformedIssue: ...

    def retry(
        self, issue: IssueRecord, params: dict, previous: TransformedIssue, feedback: str
    ) -> TransformedIssue:
        """Another attempt after ``previous`` failed the quality check; ``feedback`` says why.

        A fresh attempt by default; LLM-backed transformations show the model its previous reply
        and the feedback.
        """
        return self.transform(issue, params)

    def preview(self, issue: IssueRecord, params: dict) -> str:
        return self.transform(issue, params).transformed_text

    @property
    def generator(self) -> str:
        """What produces this transformation's variants: its model id, or "deterministic"."""
        if self.category == "llm_backed":
            return self.model or UNKNOWN
        return DETERMINISTIC

    def invented_details(self, original: str, transformed: str) -> list[str]:
        """Details an LLM-backed output added that the original does not contain.

        Like missing technical tokens, any such detail fails the quality check (retry, then
        exclude). None are checked by default.
        """
        return []


def normalize_whitespace(text: str) -> str:
    """``text`` with every run of whitespace (newlines included) collapsed to one space."""
    return " ".join(text.split())


def is_noop(original: str, transformed: str) -> bool:
    """True when a variant equals the original after whitespace normalization: nothing changed."""
    return normalize_whitespace(original) == normalize_whitespace(transformed)


# ---------------------------------------------------------------------------
# Identifier retention check (SPEC section 11.5)
#
# Only technical content is protected; plain English words may change freely.
# - Code must survive as verbatim substrings: the content of fenced code blocks, ">>>" lines,
#   indented code lines (markdown: 4 spaces or a tab, after a blank line) and backtick spans.
# - Technical tokens of the prose must appear: identifiers containing _ . / or a digit, CamelCase
#   names, file paths, and *Error / *Exception names. Markdown formatting and GitHub issue-template
#   boilerplate are removed from the prose first (``normalize_markdown``).
# Comparisons ignore CRLF vs LF and spaces at line ends.
# ---------------------------------------------------------------------------

_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# A "/" right after "<" opens a closing tag ("</module>"), not a path.
_CANDIDATE_RE = re.compile(r"(?:(?<!<)[~/])?\w[\w./\\-]*\w|\w")
_LIST_ITEM_RE = re.compile(r"^([-*+]|\d+[.)])\s")
_CAMEL_CASE_RE = re.compile(r"[a-z][A-Z]|[A-Z]{2}[a-z]")
_ERROR_NAME_RE = re.compile(r"\w+(Error|Exception)")
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "a.k.a", "vs", "cf", "n.b", "p.s"})
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)*(?:[.\-]\w+)?\b")

# Markdown formatting and issue-template boilerplate, removed from the prose before its technical
# tokens are taken (``normalize_markdown``).
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
# Formatting tags of GitHub markdown, with their attributes ("<details>", "</summary>", "<br/>").
_HTML_TAG_RE = re.compile(
    r"</?(?:a|b|i|s|u|p|br|hr|em|tt|li|ol|ul|dl|dt|dd|td|th|tr|del|div|img|ins|kbd|pre|sub|sup"
    r"|code|span|font|small|table|tbody|thead|strong|center|summary|details|blockquote|h[1-6])"
    r"\b[^<>]*>",
    re.IGNORECASE,
)
# An issue-form field left empty: GitHub fills it with "_No response_".
_NO_RESPONSE_RE = re.compile(r"^[ \t]*_No response_[ \t]*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
# The standard section headings of GitHub issue templates (GitHub's defaults and the issue forms
# of the SWE-bench Lite repositories), lowercase, without trailing punctuation. A heading naming
# something specific (e.g. "### example.py") is not boilerplate and keeps its tokens.
TEMPLATE_HEADINGS = frozenset({
    "actual behavior", "actual behaviour", "actual outcome", "actual results",
    "additional context", "additional dependencies", "additional information",
    "anything else we need to know", "bug description", "bug report", "bug summary", "checklist",
    "code for reproduction", "command used", "configuration", "context", "current behavior",
    "describe alternatives you've considered", "describe the bug", "describe the solution you'd like",
    "description", "environment", "environment info", "expected behavior", "expected behaviour",
    "expected outcome", "expected results", "feature request", "how to reproduce", "installation",
    "is your feature request related to a problem? please describe", "jupyter version",
    "matplotlib backend", "matplotlib version", "minimal complete verifiable example",
    "motivation", "mvce confirmation", "operating system", "os / environment", "possible solution",
    "problem", "proposed solution", "pylint output", "pylint version", "python version",
    "relevant log output", "screenshots", "steps to reproduce", "steps/code to reproduce",
    "summary", "to reproduce", "versions", "what did you expect to happen", "what happened",
    "your project",
})
# Emphasis around words (_text_, *text*, **text**): the markers must stand at word boundaries
# (after a space, a bracket or a quote; before a space or punctuation) and _..._ must not contain
# another underscore, so identifiers ("_sparse_fit ... support_vectors_", "Request.**init**()")
# and escaped markers ("\_\_repr\_\_") are left alone; "__" never counts (dunder names).
_BEFORE_EMPHASIS = r"(?<![^\s(\[\"'])"
_AFTER_EMPHASIS = r"(?=[\s.,;:!?)\]\"']|$)"
_EMPHASIS_RE = re.compile(
    _BEFORE_EMPHASIS + r"(?:_([^\s_\\](?:[^_\n]*[^\s_\\])?)_"
    r"|(\*\*?)([^\s*\\](?:[^*\n]*[^\s*\\])?)\2)" + _AFTER_EMPHASIS,
    re.MULTILINE,
)
# Markdown backslash escapes of punctuation ("\_" -> "_"), except in Windows paths ("C:\Users\_x").
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
_WINDOWS_PATH_RE = re.compile(r"\\[A-Za-z0-9]")


def normalize_markdown(text: str) -> str:
    """``text`` without markdown formatting and issue-template boilerplate.

    Removes HTML comments, "_No response_" lines, standard template section headings
    (TEMPLATE_HEADINGS) and formatting HTML tags; then strips emphasis markers and unescapes
    backslash escapes. Emphasis goes before unescaping so that escaped markers stay literal.
    """
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _NO_RESPONSE_RE.sub("", text)
    text = _HEADING_RE.sub(
        lambda m: "" if _heading_key(m.group(1)) in TEMPLATE_HEADINGS else m.group(), text
    )
    text = _HTML_TAG_RE.sub(" ", text)
    text = _strip_emphasis(text)
    return re.sub(
        r"\S+",
        lambda m: m.group() if _WINDOWS_PATH_RE.search(m.group()) else _ESCAPE_RE.sub(r"\1", m.group()),
        text,
    )


def _strip_emphasis(text: str) -> str:
    for _ in range(3):  # nested emphasis ("**_text_**")
        stripped = _EMPHASIS_RE.sub(lambda m: m.group(1) or m.group(3), text)
        if stripped == text:
            break
        text = stripped
    return text


def _heading_key(heading: str) -> str:
    return re.sub(r"[\s:.!?]+$", "", _strip_emphasis(heading).strip().lower())


def _normalize_lines(text: str) -> str:
    return "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )


def _split_code(text: str) -> tuple[list[tuple[str, str]], str]:
    """((kind, code) items that must survive verbatim, the remaining prose) of normalized text."""
    code: list[tuple[str, str]] = []
    prose: list[str] = []
    fenced: list[str] | None = None
    after_blank_or_code = True  # markdown: an indented code block follows a blank line
    for line in text.split("\n"):
        stripped = line.strip()
        if _FENCE_LINE_RE.match(line):
            if fenced is None:
                fenced = []
            else:
                if any(part.strip() for part in fenced):
                    code.append(("block", "\n".join(fenced).strip("\n")))
                fenced = None
                after_blank_or_code = True
            prose.append("")
        elif fenced is not None:
            fenced.append(line)
        elif stripped.startswith(">>>"):
            code.append(("line", stripped))
            prose.append("")
            after_blank_or_code = True
        elif (
            line.startswith(("    ", "\t"))
            and stripped
            and after_blank_or_code
            and not _LIST_ITEM_RE.match(stripped)
        ):
            code.append(("line", stripped))
            prose.append("")
        else:
            after_blank_or_code = not stripped
            prose.append(line)
    if fenced is not None and any(part.strip() for part in fenced):  # unclosed fence
        code.append(("block", "\n".join(fenced).strip("\n")))
    text_prose = "\n".join(prose)
    code.extend(("span", m.group(1)) for m in _BACKTICK_RE.finditer(text_prose))
    return code, _BACKTICK_RE.sub(" ", text_prose)


def _is_technical(token: str) -> bool:
    if token.lower() in _ABBREVIATIONS or not any(c.isalnum() for c in token):
        return False  # an abbreviation, or punctuation only ("_", "__")
    if token.startswith(("/", "~")):
        return len(token) > 1  # an absolute or home-relative path
    if "_" in token or "." in token or "\\" in token:
        return True  # snake_case, dotted names, file names, versions, Windows paths
    if "/" in token:  # a path, but not "and/or"
        return token.count("/") >= 2 or any(c.isdigit() for c in token)
    if any(c.isdigit() for c in token):
        return not token.isdigit()  # identifiers with digits; plain numbers are prose
    return bool(_CAMEL_CASE_RE.search(token) or _ERROR_NAME_RE.fullmatch(token))


def technical_content(text: str) -> tuple[list[tuple[str, str]], set[str]]:
    """What the retention check protects in ``text``: (verbatim code items, technical tokens).

    Code items are (kind, code) with kind "block" (fenced), "line" (">>>" or indented) or "span"
    (backticks). Tokens are taken from the prose only, once markdown formatting and template
    boilerplate are removed (``normalize_markdown``): code is protected as a whole.
    """
    code, prose = _split_code(_normalize_lines(text))
    prose = normalize_markdown(prose)
    tokens = {m.group() for m in _CANDIDATE_RE.finditer(prose) if _is_technical(m.group())}
    return code, tokens


def _code_label(kind: str, code: str) -> str:
    if kind == "span":
        return f"`{code}`"
    first = code.split("\n", 1)[0]
    first = first if len(first) <= 50 else first[:50] + "…"
    lines = code.count("\n") + 1
    return f'code "{first}"' + (f" ({lines} lines)" if lines > 1 else "")


def check_identifier_retention(original: str, transformed: str) -> tuple[bool, list[str]]:
    """Return (passed, missing). ``missing`` lists the code (as labels) and technical tokens of
    ``original`` absent from ``transformed``; passed=True when nothing is missing. Code must
    appear verbatim; a token may also appear in the markdown-normalized text (so "\\_\\_repr\\_\\_"
    in ``transformed`` counts as "__repr__")."""
    code, tokens = technical_content(original)
    target = _normalize_lines(transformed)
    plain_target = normalize_markdown(target)
    missing = [
        _code_label(kind, item) for kind, item in dict.fromkeys(code) if item not in target
    ]
    missing += sorted(t for t in tokens if t not in target and t not in plain_target)
    return not missing, missing


def invented_versions(original: str, transformed: str) -> list[str]:
    """Version numbers (e.g. "3.11", "v2.0.1") in ``transformed`` that ``original`` never mentions."""
    known = set(_VERSION_RE.findall(original))
    return sorted({v for v in _VERSION_RE.findall(transformed) if v not in known})
