"""TransformationCache: retry-then-exclude for LLM-backed outputs, and versioned cache keys.

No network: LLM-backed transformations are fakes, or their Haiku call is faked.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.models import Base, Issue
from stableagent.data.models import TransformedIssue as TIModel
from stableagent.transformations.base import (
    AbstractTransformation,
    IssueRecord,
    TransformedIssue,
)
from stableagent.transformations.cache import (
    MAX_QUALITY_RETRIES,
    TransformationCache,
    cache_key,
    find_cached_variant,
)
from stableagent.transformations.deterministic.reordering import ReorderingTransformation
from stableagent.transformations.llm_backed._api import HaikuReply
from stableagent.transformations.llm_backed.neutralize import NeutralizeTransformation
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.llm_backed.structure import ParagraphToStructured
from stableagent.transformations.llm_backed.verbosity import VerbosityReduction

ISSUE = IssueRecord(
    issue_id="issue-1",
    repo_name="org/proj",
    text="parse_rows() raises KeyError in DataLoader on version 2.3.1.\n\nIt should not.",
)
GOOD = "parse_rows() raises KeyError in DataLoader (2.3.1)."  # keeps every technical token
BAD = "parse_rows() crashes."  # keeps 1 of the 4 technical tokens
WORSE = "Crash."  # keeps none


@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add(Issue(id=ISSUE.issue_id, source="manual", repo_name=ISSUE.repo_name,
                     issue_text=ISSUE.text))
        db.commit()
    yield session_factory
    engine.dispose()


def scripted(outputs: list[str], *, category="llm_backed", version="1"):
    """A transformation returning the given outputs in order; records how often it ran."""

    class Scripted(AbstractTransformation):
        name = "scripted"
        transform_version = version
        calls = 0

        def transform(self, issue, params):
            text = outputs[min(type(self).calls, len(outputs) - 1)]
            type(self).calls += 1
            return TransformedIssue(issue.issue_id, self.name, params, text, "generated")

    Scripted.category = category
    return Scripted()


def stored_row(Session, name="scripted") -> TIModel:
    with Session() as db:
        return db.query(TIModel).filter_by(issue_id=ISSUE.issue_id, transformation_name=name).one()


# ---------------------------------------------------------------------------
# Retry-then-exclude
# ---------------------------------------------------------------------------


def test_failing_output_is_retried_until_it_passes(Session):
    transformation = scripted([BAD, GOOD])
    with Session() as db:
        result = TransformationCache(db).get_or_transform(transformation, ISSUE, {})
        db.commit()

    assert type(transformation).calls == 2
    assert result.transformed_text == GOOD
    row = stored_row(Session)
    assert row.quality_warning is False
    assert "passed on attempt 2/2" in row.transformation_notes


def test_output_still_failing_after_one_retry_is_flagged_for_exclusion(Session):
    transformation = scripted([WORSE, BAD, GOOD])
    with Session() as db:
        result = TransformationCache(db).get_or_transform(transformation, ISSUE, {})
        db.commit()

    assert MAX_QUALITY_RETRIES == 1
    assert type(transformation).calls == 2  # two attempts in total, never a third
    assert result.transformed_text == BAD  # the attempt that kept the most tokens
    row = stored_row(Session)
    assert row.quality_warning is True
    assert "QUALITY WARNING" in row.transformation_notes
    assert "excluded from metrics" in row.transformation_notes


def test_deterministic_transformations_are_never_retried(Session):
    transformation = scripted([BAD, GOOD], category="deterministic")
    with Session() as db:
        TransformationCache(db).get_or_transform(transformation, ISSUE, {})
        db.commit()
    assert type(transformation).calls == 1
    assert stored_row(Session).quality_warning is False


@pytest.mark.parametrize(
    "transformation_cls",
    [Paraphrase, VerbosityReduction, ParagraphToStructured, NeutralizeTransformation],
)
def test_every_llm_backed_transformation_gets_the_retry(Session, monkeypatch, transformation_cls):
    replies = iter([HaikuReply(BAD, "first"), HaikuReply(GOOD, "second")])
    calls = []

    def fake_haiku(system_prompt, user_content, api_key, model=None, *, retry=None, **_):
        calls.append(retry)
        return next(replies)

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", fake_haiku)
    with Session() as db:
        result = TransformationCache(db).get_or_transform(transformation_cls(), ISSUE, {})
        db.commit()

    assert len(calls) == 2 and result.transformed_text == GOOD
    assert calls[0] is None  # the retry shows the model its reply and names what was missing
    previous, feedback = calls[1]
    assert previous == BAD and "KeyError" in feedback and "DataLoader" in feedback
    assert stored_row(Session, transformation_cls.name).quality_warning is False


# ---------------------------------------------------------------------------
# Versioned cache keys
# ---------------------------------------------------------------------------


def test_cache_hit_within_one_version(Session):
    first = scripted([GOOD], category="deterministic", version="2")
    with Session() as db:
        TransformationCache(db).get_or_transform(first, ISSUE, {"seed": 1})
        db.commit()
    with Session() as db:
        TransformationCache(db).get_or_transform(first, ISSUE, {"seed": 1})
    assert type(first).calls == 1


def test_version_bump_causes_a_cache_miss(Session):
    old = scripted(["old output"], category="deterministic", version="2")
    new = scripted(["new output"], category="deterministic", version="3")

    with Session() as db:
        TransformationCache(db).get_or_transform(old, ISSUE, {"seed": 42})
        db.commit()
    with Session() as db:
        result = TransformationCache(db).get_or_transform(new, ISSUE, {"seed": 42})
        db.commit()

    assert type(new).calls == 1  # same issue and params, but a new version: regenerated
    assert result.transformed_text == "new output"
    assert cache_key(old, {"seed": 42}) != cache_key(new, {"seed": 42})
    with Session() as db:
        # Both variants stay stored; each version finds its own.
        assert find_cached_variant(db, ISSUE.issue_id, old, {"seed": 42}).transformed_text == (
            "old output"
        )
        assert find_cached_variant(db, ISSUE.issue_id, new, {"seed": 42}).transformed_text == (
            "new output"
        )
        stored = json.loads(find_cached_variant(db, ISSUE.issue_id, new, {"seed": 42})
                            .transformation_params)
        assert stored["transform_version"] == "3"


def test_variants_cached_before_versioning_are_not_reused(Session):
    # A line-shuffled reordering cached by the pre-screen, keyed by sha256(params) only.
    legacy_key = hashlib.sha256(json.dumps({"seed": 42}, sort_keys=True).encode()).hexdigest()
    with Session() as db:
        db.add(TIModel(issue_id=ISSUE.issue_id, transformation_name="reordering",
                       transformation_params=json.dumps({"params": {"seed": 42},
                                                         "_cache_key": legacy_key}),
                       transformed_text="It should not.\nparse_rows() raises ... (lines shuffled)"))
        db.commit()

    with Session() as db:
        result = TransformationCache(db).get_or_transform(
            ReorderingTransformation(), ISSUE, {"seed": 42}
        )
        db.commit()

    assert "lines shuffled" not in result.transformed_text
    assert result.transformed_text.split("\n\n") == ["It should not.", ISSUE.text.split("\n\n")[0]]
    with Session() as db:
        assert db.query(TIModel).filter_by(transformation_name="reordering").count() == 2


def test_changed_transformations_carry_a_bumped_version():
    # v4/v5: the LLM-backed transformations mask code behind placeholders (new prompts); the
    # passed variants of the previous version (technical-token retention check) stay valid.
    expected = {
        ReorderingTransformation: "2",
        VerbosityReduction: "4",
        Paraphrase: "4",
        ParagraphToStructured: "5",
        NeutralizeTransformation: "4",
    }
    for cls, version in expected.items():
        assert cls.transform_version == version, cls.__name__


def test_the_generator_is_part_of_the_key():
    paraphrase = Paraphrase()
    assert paraphrase.generator == "claude-haiku-4-5-20251001"
    assert ReorderingTransformation().generator == "deterministic"
    assert cache_key(paraphrase, {}) == cache_key(paraphrase, {}, paraphrase.generator)
    assert cache_key(paraphrase, {}) != cache_key(paraphrase, {}, "placeholder")
    assert cache_key(paraphrase, {}) != cache_key(paraphrase, {}, "claude-other-model")


def test_a_paragraph_to_structured_version_bump_invalidates_its_cached_variants(
    Session, monkeypatch
):
    """An older version's cached output is not reused once the version changed."""
    replies = iter([
        HaikuReply("## Summary\nv2 output parse_rows() KeyError DataLoader 2.3.1", "old"),
        HaikuReply("## Summary\nv3 output parse_rows() KeyError DataLoader 2.3.1", "new"),
    ])
    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: next(replies),
    )

    class OldStructure(ParagraphToStructured):
        transform_version = "2"

    with Session() as db:
        TransformationCache(db).get_or_transform(OldStructure(), ISSUE, {})
        db.commit()
    with Session() as db:
        result = TransformationCache(db).get_or_transform(ParagraphToStructured(), ISSUE, {})
        db.commit()

    assert result.transformed_text.startswith("## Summary\nv3 output")
    with Session() as db:
        versions = {row.transform_version for row in db.query(TIModel).filter_by(
            transformation_name="paragraph_to_structured")}
    assert versions == {"2", ParagraphToStructured.transform_version}
