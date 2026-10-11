from __future__ import annotations

import pytest
from stableagent.transformations.llm_backed._api import HaikuReply

# Trigger registration of all four transformations before any test runs.
import stableagent.transformations  # noqa: F401

from stableagent.transformations.base import (
    IssueRecord,
    check_identifier_retention,
    technical_content,
)
from stableagent.transformations.registry import transformation_registry
from stableagent.transformations.deterministic.noise import TypoInjection
from stableagent.transformations.deterministic.reordering import ReorderingTransformation
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.llm_backed.neutralize import NeutralizeTransformation
from stableagent.transformations.llm_backed.verbosity import VerbosityReduction
from stableagent.transformations.llm_backed.structure import ParagraphToStructured

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Multi-sentence issue with technical identifiers in sentence 0 — designed so that
# every-other-sentence reduction (sentences 0, 2) retains all extracted tokens.
SAMPLE_ISSUE = IssueRecord(
    issue_id="test__issue-001",
    repo_name="test/repo",
    text=(
        "The `FooBar.process_items()` method raises `ValueError: invalid_arg` "
        "when called with an empty list on version 2.3.1. "
        "To reproduce: call `FooBar().process_items([])`. "
        "Expected: returns an empty list. "
        "Actual: raises ValueError."
    ),
)

PLAIN_ISSUE = IssueRecord(
    issue_id="test__issue-002",
    repo_name="test/repo",
    text="Fix the bug in the login page where users cannot sign in.",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_all_four():
    names = transformation_registry.list_names()
    for expected in ("typo_injection", "reordering", "paraphrase", "verbosity_reduction", "paragraph_to_structured", "neutralize_emotional"):
        assert expected in names


def test_registry_get_returns_correct_class():
    assert transformation_registry.get("typo_injection") is TypoInjection
    assert transformation_registry.get("reordering") is ReorderingTransformation
    assert transformation_registry.get("paraphrase") is Paraphrase
    assert transformation_registry.get("verbosity_reduction") is VerbosityReduction
    assert transformation_registry.get("paragraph_to_structured") is ParagraphToStructured
    assert transformation_registry.get("neutralize_emotional") is NeutralizeTransformation


def test_registry_raises_for_unknown():
    with pytest.raises(KeyError, match="not registered"):
        transformation_registry.get("does_not_exist")


# ---------------------------------------------------------------------------
# Identifier retention utilities
# ---------------------------------------------------------------------------


def test_technical_content_protects_backtick_spans_and_technical_tokens():
    code, tokens = technical_content("Call `FooBar.process_items()` on version 2.3.1.")
    assert code == [("span", "FooBar.process_items()")]  # kept whole, verbatim
    assert tokens == {"2.3.1"}


def test_technical_content_ignores_plain_english():
    code, tokens = technical_content("Fix the bug in the code. It's broken, e.g. and/or NOT ok.")
    assert code == [] and tokens == set()


def test_check_identifier_retention_passes():
    passed, missing = check_identifier_retention(
        "Call `FooBar.process_items()` on version 2.3.1.",
        "Invoke `FooBar.process_items()` (version 2.3.1).",
    )
    assert passed is True
    assert missing == []


def test_check_identifier_retention_fails_when_token_absent():
    passed, missing = check_identifier_retention(
        "Call `FooBar.process_items()` on version 2.3.1.",
        "Invoke the method on version 2.3.1.",
    )
    assert passed is False
    assert missing == ["`FooBar.process_items()`"]


# ---------------------------------------------------------------------------
# T08 TypoInjection
# ---------------------------------------------------------------------------


def test_typo_injection_output_non_empty():
    result = TypoInjection().transform(SAMPLE_ISSUE, {"seed": 42})
    assert result.transformed_text.strip() != ""


def test_typo_injection_differs_from_input():
    result = TypoInjection().transform(SAMPLE_ISSUE, {"seed": 42})
    assert result.transformed_text != SAMPLE_ISSUE.text


def test_typo_injection_deterministic_with_seed():
    r1 = TypoInjection().transform(SAMPLE_ISSUE, {"seed": 7})
    r2 = TypoInjection().transform(SAMPLE_ISSUE, {"seed": 7})
    assert r1.transformed_text == r2.transformed_text


def test_typo_injection_preserves_inline_code_span():
    issue = IssueRecord(
        issue_id="t",
        repo_name="r",
        text="Some prose here. `exact_code_span` must not change. More words.",
    )
    # High rate ensures prose is definitely mutated; code span must be untouched.
    result = TypoInjection().transform(issue, {"error_rate": 1.0, "seed": 0})
    assert "`exact_code_span`" in result.transformed_text


def test_typo_injection_preserves_fenced_code():
    issue = IssueRecord(
        issue_id="t",
        repo_name="r",
        text="See:\n```python\ndef foo():\n    pass\n```\nEnd.",
    )
    result = TypoInjection().transform(issue, {"error_rate": 1.0, "seed": 0})
    assert "def foo():" in result.transformed_text
    assert "    pass" in result.transformed_text


def test_typo_injection_metadata_fields():
    result = TypoInjection().transform(SAMPLE_ISSUE, {"seed": 99})
    assert result.original_issue_id == SAMPLE_ISSUE.issue_id
    assert result.transformation_name == "typo_injection"
    assert result.transformation_notes != ""


def test_typo_injection_category():
    assert TypoInjection.category == "deterministic"
    assert TypoInjection.preserves_semantics is False


# ---------------------------------------------------------------------------
# LLM-backed transformation API behavior
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("transform_cls", [Paraphrase, VerbosityReduction, ParagraphToStructured])
def test_llm_transform_calls_haiku(transform_cls, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: HaikuReply(
            "rewritten issue", "LLM transformation"
        ),
    )
    result = transform_cls().transform(SAMPLE_ISSUE, {})
    assert result.transformed_text == "rewritten issue"
    assert result.transformation_notes == "LLM transformation"
    assert result.original_issue_id == SAMPLE_ISSUE.issue_id


@pytest.mark.parametrize("transform_cls", [Paraphrase, VerbosityReduction, ParagraphToStructured])
def test_llm_transform_requires_api_key(transform_cls, no_api_key):
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        transform_cls().transform(SAMPLE_ISSUE, {})


# ---------------------------------------------------------------------------
# TransformationCache
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from stableagent.data.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_issue(Session, issue: IssueRecord):
    from stableagent.data.models import Issue

    with Session() as s:
        s.add(Issue(
            id=issue.issue_id,
            source="manual",
            repo_name=issue.repo_name,
            issue_text=issue.text,
        ))
        s.commit()


def test_cache_hit_skips_transform(tmp_path):
    """transform() is called once; a second identical call returns the cached result."""
    from stableagent.transformations.cache import TransformationCache

    Session = _make_db(tmp_path)
    _seed_issue(Session, SAMPLE_ISSUE)

    call_count = 0

    class CountingTypo(TypoInjection):
        def transform(self, issue, params):
            nonlocal call_count
            call_count += 1
            return super().transform(issue, params)

    t = CountingTypo()

    with Session() as s:
        r1 = TransformationCache(s).get_or_transform(t, SAMPLE_ISSUE, {"seed": 1})
        s.commit()

    with Session() as s:
        r2 = TransformationCache(s).get_or_transform(t, SAMPLE_ISSUE, {"seed": 1})

    assert call_count == 1, f"transform() called {call_count}×; expected 1 (cache hit on 2nd call)"
    assert r1.transformed_text == r2.transformed_text


def test_cache_miss_on_different_params(tmp_path):
    """Different params → different cache key → transform() called twice."""
    from stableagent.transformations.cache import TransformationCache

    Session = _make_db(tmp_path)
    _seed_issue(Session, SAMPLE_ISSUE)

    call_count = 0

    class CountingTypo(TypoInjection):
        def transform(self, issue, params):
            nonlocal call_count
            call_count += 1
            return super().transform(issue, params)

    t = CountingTypo()

    with Session() as s:
        TransformationCache(s).get_or_transform(t, SAMPLE_ISSUE, {"seed": 1})
        s.commit()

    with Session() as s:
        TransformationCache(s).get_or_transform(t, SAMPLE_ISSUE, {"seed": 2})
        s.commit()

    assert call_count == 2


def test_cache_stores_quality_warning_for_failed_retention(tmp_path, no_api_key):
    """LLM-backed transform whose output drops an identifier gets quality_warning=True in DB."""
    from stableagent.transformations.cache import TransformationCache
    from stableagent.data.models import TransformedIssue as TIModel

    Session = _make_db(tmp_path)
    _seed_issue(Session, SAMPLE_ISSUE)

    class BadParaphrase(Paraphrase):
        """Returns output that drops all identifiers."""
        def transform(self, issue, params):
            from stableagent.transformations.base import TransformedIssue as TR
            return TR(
                original_issue_id=issue.issue_id,
                transformation_name=self.name,
                transformation_params=params,
                transformed_text="something totally generic with no identifiers",
                transformation_notes="bad",
            )

        def retry(self, issue, params, previous, feedback):
            return self.transform(issue, params)

    t = BadParaphrase()

    with Session() as s:
        TransformationCache(s).get_or_transform(t, SAMPLE_ISSUE, {})
        s.commit()

    with Session() as s:
        row = s.query(TIModel).filter_by(
            issue_id=SAMPLE_ISSUE.issue_id,
            transformation_name="paraphrase",
        ).one()
        assert row.quality_warning is True


# ---------------------------------------------------------------------------
# T07 ReorderingTransformation
# ---------------------------------------------------------------------------

_MULTI_PARA_ISSUE = IssueRecord(
    issue_id="test__issue-reorder-001",
    repo_name="test/repo",
    text="First paragraph describes the bug.\n\nSecond paragraph gives steps to reproduce.\n\nThird paragraph states expected behavior.",
)

_SINGLE_LINE_ISSUE = IssueRecord(
    issue_id="test__issue-reorder-002",
    repo_name="test/repo",
    text="Line one explains the issue.\nLine two adds more context.\nLine three wraps up.",
)


def test_reordering_changes_order():
    result = ReorderingTransformation().transform(_MULTI_PARA_ISSUE, {"seed": 42})
    assert result.transformed_text != _MULTI_PARA_ISSUE.text


def test_reordering_preserves_words():
    result = ReorderingTransformation().transform(_MULTI_PARA_ISSUE, {"seed": 42})
    original_words = sorted(_MULTI_PARA_ISSUE.text.split())
    result_words = sorted(result.transformed_text.split())
    assert original_words == result_words


def test_reordering_reproducible():
    r1 = ReorderingTransformation().transform(_MULTI_PARA_ISSUE, {"seed": 7})
    r2 = ReorderingTransformation().transform(_MULTI_PARA_ISSUE, {"seed": 7})
    assert r1.transformed_text == r2.transformed_text


def test_reordering_never_shuffles_lines():
    # One paragraph of several lines: returned unchanged (the old fallback shuffled the lines).
    result = ReorderingTransformation().transform(_SINGLE_LINE_ISSUE, {"seed": 42})
    assert result.transformed_text == _SINGLE_LINE_ISSUE.text
    assert "returned unchanged" in result.transformation_notes
    assert "never shuffled" in result.transformation_notes


def test_reordering_short_text_unchanged():
    single_paragraph = IssueRecord(
        issue_id="test__issue-reorder-003",
        repo_name="test/repo",
        text="This is a single line issue with no paragraph or line breaks at all.",
    )
    result = ReorderingTransformation().transform(single_paragraph, {"seed": 42})
    assert result.transformed_text == single_paragraph.text
    assert result.transformation_notes.startswith("Fewer than 2 paragraphs")


def test_reordering_normalises_crlf_and_shuffles_whole_paragraphs():
    paragraphs = [
        "The parser drops the last row.\r\nIt happens with CRLF input files.",
        "Steps:\r\n1. load data.csv\r\n2. call parse_rows()",
        "Expected: all rows are returned.",
    ]
    issue = IssueRecord(issue_id="crlf-1", repo_name="test/repo", text="\r\n\r\n".join(paragraphs))
    result = ReorderingTransformation().transform(issue, {"seed": 42})

    assert "\r" not in result.transformed_text
    shuffled = result.transformed_text.split("\n\n")
    expected = [p.replace("\r\n", "\n") for p in paragraphs]
    assert sorted(shuffled) == sorted(expected)  # whole paragraphs, nothing split or lost
    assert shuffled != expected  # seed 42 moves them
    assert "CRLF normalised" in result.transformation_notes


def test_reordering_crlf_single_paragraph_is_returned_unchanged():
    text = "Line one of the issue.\r\nLine two.\r\nLine three."
    issue = IssueRecord(issue_id="crlf-2", repo_name="test/repo", text=text)
    result = ReorderingTransformation().transform(issue, {"seed": 42})
    assert result.transformed_text == text  # exactly the input, CRLF included


def test_reordering_never_splits_inside_a_fenced_code_block():
    code = "```python\nimport pkg\n\nresult = pkg.run()\n\nprint(result)\n```"
    issue = IssueRecord(
        issue_id="fence-1",
        repo_name="test/repo",
        text=f"Running this fails:\n{code}\n\nThe traceback ends in KeyError.\n\nUsing pkg 1.2.",
    )
    result = ReorderingTransformation().transform(issue, {"seed": 42})
    assert code in result.transformed_text  # the code block, blank lines included, stays whole
    assert len(result.transformed_text.split("\n\n")) >= 3


def test_split_paragraphs_ignores_blank_lines_inside_fences():
    from stableagent.transformations.deterministic.reordering import split_paragraphs

    text = "intro\n\n```\na\n\nb\n```\n\noutro"
    assert split_paragraphs(text) == ["intro", "```\na\n\nb\n```", "outro"]
    assert split_paragraphs("only one\nparagraph") == ["only one\nparagraph"]


def test_reordering_metadata_fields():
    result = ReorderingTransformation().transform(_MULTI_PARA_ISSUE, {"seed": 42})
    assert result.original_issue_id == _MULTI_PARA_ISSUE.issue_id
    assert result.transformation_name == "reordering"
    assert result.transformation_notes != ""


def test_reordering_category():
    assert ReorderingTransformation.category == "deterministic"
    assert ReorderingTransformation.preserves_semantics is True


# ---------------------------------------------------------------------------
# T11 NeutralizeTransformation — Claude Haiku
# ---------------------------------------------------------------------------

_EMOTIONAL_ISSUE = IssueRecord(
    issue_id="test__issue-neutral-001",
    repo_name="test/repo",
    text=(
        "This is terrible! The `FooBar.process_items()` method raises `ValueError` "
        "when called with an empty list on version 2.3.1. "
        "I'm so frustrated with this broken behavior! "
        "Expected: returns an empty list. Actual: raises ValueError."
    ),
)


def test_neutralize_calls_haiku_for_plain_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    def fake_haiku(system, text, key, model=None, **kwargs):
        calls.append(kwargs)
        return HaikuReply("neutral issue")

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", fake_haiku)
    result = NeutralizeTransformation().transform(_EMOTIONAL_ISSUE, {})
    assert result.transformed_text == "neutral issue"
    assert result.transformation_notes == (
        "Rewrote only the sentences with emotional or informal language."
    )
    # The reply is the text itself, not JSON; a first attempt, not a retry.
    assert calls == [{"expect_json": False, "retry": None}]


def test_neutralize_prompt_returns_neutral_text_unchanged():
    from stableagent.transformations.llm_backed.neutralize import _SYSTEM_PROMPT

    assert "output it EXACTLY as given, character for character" in _SYSTEM_PROMPT
    assert "rewrite ONLY the sentences that contain such language" in _SYSTEM_PROMPT
    assert "Ordinary contractions (it's, doesn't, can't)" in _SYSTEM_PROMPT
    assert NeutralizeTransformation.transform_version == "4"


def test_neutralize_unchanged_output_is_a_noop(tmp_path, monkeypatch):
    """A neutral report comes back unchanged: the variant is flagged noop, excluded from SC/TS."""
    from stableagent.data.models import TransformedIssue as TIModel
    from stableagent.transformations.cache import NOOP_REASON, TransformationCache

    neutral = IssueRecord(issue_id="n-1", repo_name="o/r",
                          text="parse() raises KeyError on empty input.\r\n\r\nIt should not.")
    Session = _make_db(tmp_path)
    _seed_issue(Session, neutral)
    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: HaikuReply(text.replace("\r\n", "\n")),
    )
    with Session() as s:
        TransformationCache(s).variant(NeutralizeTransformation(), neutral, {})
        s.commit()
    with Session() as s:
        row = s.query(TIModel).filter_by(transformation_name="neutralize_emotional").one()
        assert row.noop is True and row.quality_warning is False
        assert row.exclusion_reason == NOOP_REASON
        assert "returned unchanged (no-op)" in row.transformation_notes


def test_neutralize_requires_api_key(no_api_key):
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        NeutralizeTransformation().transform(_EMOTIONAL_ISSUE, {})


def test_neutralize_metadata(monkeypatch):
    # The suite's dummy key is set; the Haiku call itself is faked so nothing leaves the machine.
    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: HaikuReply(
            "neutral issue", "LLM transformation"
        ),
    )
    result = NeutralizeTransformation().transform(_EMOTIONAL_ISSUE, {})
    assert result.original_issue_id == _EMOTIONAL_ISSUE.issue_id
    assert result.transformation_name == "neutralize_emotional"


def test_neutralize_category():
    assert NeutralizeTransformation.category == "llm_backed"
    assert NeutralizeTransformation.preserves_semantics is True
