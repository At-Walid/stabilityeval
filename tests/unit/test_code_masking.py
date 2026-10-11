"""Mask-and-restore of code for LLM-backed transformations (SPEC section 11.7).

Uses the verbatim text of SWE-bench Lite issue astropy__astropy-12907 (from the bundled dataset
file: one inline span and four fenced Python blocks, CRLF line endings). No network: every Haiku
call is faked.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.loaders.swebench import load_bundle
from stableagent.data.models import Base, Issue
from stableagent.data.models import TransformedIssue as TIModel
from stableagent.transformations.base import (
    IssueRecord,
    check_identifier_retention,
    technical_content,
)
from stableagent.transformations.cache import (
    MAX_QUALITY_RETRIES,
    PLACEHOLDER_LOST,
    TransformationCache,
    find_cached_variant,
)
from stableagent.transformations.llm_backed import _api
from stableagent.transformations.llm_backed._api import HaikuReply, call_haiku
from stableagent.transformations.llm_backed.base import PLACEHOLDER_RULES
from stableagent.transformations.llm_backed.neutralize import NeutralizeTransformation
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.llm_backed.structure import ParagraphToStructured
from stableagent.transformations.llm_backed.verbosity import VerbosityReduction
from stableagent.transformations.masking import mask_code

ASTROPY = load_bundle(["astropy__astropy-12907"])[0]
TEXT = ASTROPY.problem_statement
MASKED = mask_code(TEXT)
CODE = list(MASKED.originals.values())  # in order: the span, then the four blocks

# What a paraphrasing model may answer for the masked text: prose reworded, [[CODE_4]] and
# [[CODE_5]] swapped, [[CODE_3]] wrapped in a code fence, [[CODE_4]] indented, [[CODE_5]] put
# inside a sentence, [[CODE_1]] wrapped in backticks. Every placeholder exactly once.
FAKE_REWRITE = """\
For nested CompoundModels, Modeling's `[[CODE_1]]` computes separability incorrectly.

Take this model:

[[CODE_2]]

As expected, its separability matrix is diagonal:

```
[[CODE_3]]
```

Once the compound models are nested, as in [[CODE_5]] the inputs and outputs stop being separable.

A more complex but un-nested model is still separable:

    [[CODE_4]]

This looks like a bug, unless I am missing something."""


def _without(placeholder: str) -> str:
    return FAKE_REWRITE.replace(placeholder, "the code")


# ── Masking ──────────────────────────────────────────────────────────────────

def test_the_astropy_issue_shows_the_model_its_prose_and_no_code():
    assert list(MASKED.originals) == [f"[[CODE_{n}]]" for n in range(1, 6)]
    assert CODE[0] == "`separability_matrix`"  # inline span, backticks included
    assert MASKED.blocks == {"[[CODE_2]]", "[[CODE_3]]", "[[CODE_4]]", "[[CODE_5]]"}
    for block in CODE[1:]:
        assert block.startswith("```python") and block.endswith("```")
    assert "`" not in MASKED.text and "separability_matrix(" not in MASKED.text
    assert "Consider the following model:" in MASKED.text
    assert "Suddenly the inputs and outputs are no longer separable?" in MASKED.text
    code, _tokens = technical_content(MASKED.text)
    assert code == []  # the retention check finds no code left for the model to rewrite


def test_an_unchanged_reply_restores_the_original_byte_for_byte():
    assert "\r\n" in TEXT
    assert MASKED.problems(MASKED.text) == []
    assert MASKED.restore(MASKED.text) == TEXT


def test_a_rewritten_reply_restores_identical_code_blocks():
    assert MASKED.problems(FAKE_REWRITE) == []

    restored = MASKED.restore(FAKE_REWRITE)

    for code in CODE:
        assert restored.count(code) == 1  # byte for byte, CRLF line endings included
    for block in CODE[1:]:  # each block on lines of its own, with no fence the model added
        start = restored.index(block)
        assert start == 0 or restored[start - 1] == "\n"
        assert restored[start + len(block):][:1] in ("", "\n", "\r")
    assert "```\n```python" not in restored and " ```python" not in restored
    assert "``separability_matrix``" not in restored
    assert restored.index(CODE[4]) < restored.index(CODE[3])  # the model's order is kept
    assert check_identifier_retention(TEXT, restored) == (True, [])


def test_placeholder_problems_name_each_missing_repeated_or_unknown_placeholder():
    assert MASKED.problems(_without("[[CODE_3]]")) == ["[[CODE_3]] missing"]
    assert MASKED.problems(FAKE_REWRITE + "\n[[CODE_2]]") == ["[[CODE_2]] appears 2 times"]
    assert MASKED.problems(FAKE_REWRITE + " [[CODE_9]]") == ["[[CODE_9]] unknown"]
    assert MASKED.restore(_without("[[CODE_3]]")).count(CODE[2]) == 0


def test_every_kind_of_code_is_masked_and_restored():
    text = (
        "Title with ``a `tick` span`` and a literal [[CODE_1]] in prose.\r\n"
        "\r\n"
        "    indented = code()\r\n"
        "\r\n"
        "    more_indented()\r\n"
        "Prose again.\r\n"
        ">>> run(1)\r\n"
        "Traceback-free output\r\n"
        "\r\n"
        "Traceback (most recent call last):\r\n"
        '  File "x.py", line 1, in <module>\r\n'
        "ValueError: boom\r\n"
        "\r\n"
        "~~~\r\n"
        "tilde fenced\r\n"
        "~~~\r\n"
        "The end."
    )
    masked = mask_code(text)
    assert list(masked.originals.values()) == [
        "``a `tick` span``",
        "[[CODE_1]]",  # text that looks like a placeholder is masked too
        "    indented = code()\r\n\r\n    more_indented()",
        ">>> run(1)\r\nTraceback-free output",
        'Traceback (most recent call last):\r\n  File "x.py", line 1, in <module>\r\n'
        "ValueError: boom",
        "~~~\r\ntilde fenced\r\n~~~",
    ]
    assert masked.text == (
        "Title with [[CODE_1]] and a literal [[CODE_2]] in prose.\r\n\r\n[[CODE_3]]\r\n"
        "Prose again.\r\n[[CODE_4]]\r\n\r\n[[CODE_5]]\r\n\r\n[[CODE_6]]\r\nThe end."
    )
    assert masked.restore(masked.text) == text
    # A restored placeholder-like original is never replaced a second time, and block
    # placeholders put inside a line get lines of their own, without the spaces around them.
    assert masked.restore("[[CODE_2]] [[CODE_1]] [[CODE_3]] [[CODE_4]]") == (
        "[[CODE_1]] ``a `tick` span``\n    indented = code()\r\n\r\n    more_indented()\n\n"
        ">>> run(1)\r\nTraceback-free output"
    )


def test_every_bundled_issue_round_trips_and_leaves_no_code_to_the_model():
    for instance in load_bundle():
        masked = mask_code(instance.problem_statement)
        assert masked.restore(masked.text) == instance.problem_statement, instance.instance_id
        assert technical_content(masked.text)[0] == [], instance.instance_id


# ── Through the transformation cache ─────────────────────────────────────────

@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'masking.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Issue(id="astropy-1", external_id=ASTROPY.instance_id, source="swebench_lite",
                     repo_name=ASTROPY.repo, issue_text=TEXT))
        db.commit()
    yield factory
    engine.dispose()


RECORD = IssueRecord(issue_id="astropy-1", repo_name=ASTROPY.repo, text=TEXT)


def generate(Session, transformation) -> TIModel:
    """The stored variant (a detached copy), generated or taken from the cache."""
    with Session() as db:
        row = TransformationCache(db).variant(transformation, RECORD, {})
        db.commit()
        db.refresh(row)
        db.expunge(row)
        return row


def scripted_haiku(monkeypatch, replies: list[str], cost: float = 0.002) -> list[dict]:
    """Fake Haiku: answers ``replies`` in order and records every request."""
    requests: list[dict] = []
    answers = iter(replies)

    def fake(system_prompt, user_content, api_key, model=None, *, expect_json=True, retry=None):
        requests.append({"system": system_prompt, "user": user_content, "retry": retry})
        return HaikuReply(next(answers), "fake notes", cost_usd=cost)

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", fake)
    return requests


@pytest.mark.parametrize(
    "transformation_cls",
    [Paraphrase, VerbosityReduction, ParagraphToStructured, NeutralizeTransformation],
)
def test_every_llm_backed_transformation_sends_masked_text_and_restores_the_code(
    Session, monkeypatch, transformation_cls
):
    requests = scripted_haiku(monkeypatch, [FAKE_REWRITE])
    row = generate(Session, transformation_cls())

    (request,) = requests
    assert request["user"] == MASKED.text and request["retry"] is None
    assert request["system"].endswith(PLACEHOLDER_RULES)
    assert row.quality_warning is False and row.exclusion_reason is None
    for code in CODE:
        assert row.transformed_text.count(code) == 1
    assert row.generation_cost_usd == pytest.approx(0.002)
    assert "passed on attempt 1/2" in row.transformation_notes


def test_a_lost_placeholder_is_retried_once_with_feedback_naming_it(Session, monkeypatch):
    requests = scripted_haiku(monkeypatch, [_without("[[CODE_3]]"), FAKE_REWRITE])
    row = generate(Session, Paraphrase())

    assert len(requests) == 2
    previous, feedback = requests[1]["retry"]
    assert previous == _without("[[CODE_3]]")  # the model sees its own reply again
    assert "[[CODE_3]] missing" in feedback
    assert row.quality_warning is False and row.transformed_text.count(CODE[2]) == 1
    assert "passed on attempt 2/2" in row.transformation_notes
    assert row.generation_cost_usd == pytest.approx(0.004)  # both attempts


def test_a_placeholder_lost_twice_excludes_the_variant_after_two_attempts(Session, monkeypatch):
    requests = scripted_haiku(monkeypatch, [_without("[[CODE_3]]")] * 3)
    row = generate(Session, VerbosityReduction())

    assert MAX_QUALITY_RETRIES == 1 and len(requests) == 2  # never a third attempt
    assert row.quality_warning is True
    assert row.exclusion_reason == f"{PLACEHOLDER_LOST}: [[CODE_3]] missing"
    assert "after 2 attempts; excluded from metrics" in row.transformation_notes


def test_a_retention_failure_after_restoring_is_retried_with_the_missing_tokens(
    Session, monkeypatch
):
    lossy = FAKE_REWRITE.replace("CompoundModels", "compound models")
    requests = scripted_haiku(monkeypatch, [lossy, lossy])
    row = generate(Session, Paraphrase())

    assert "CompoundModels" in requests[1]["retry"][1]
    assert row.quality_warning is True
    assert row.exclusion_reason == "identifier retention failed (missing 1: CompoundModels)"


def test_call_haiku_sends_the_retry_conversation_and_prices_the_tokens(monkeypatch):
    sent = {}

    class FakeClient:
        def __init__(self, **_kwargs):
            self.messages = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs):
            sent.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(
                    {"transformed_text": "new [[CODE_1]]", "transformation_notes": "n"}
                ))],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
            )

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    reply = call_haiku("system", "masked [[CODE_1]]", "key", retry=("old reply", "fix it"))

    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert [m["content"] for m in sent["messages"]] == ["masked [[CODE_1]]", "old reply", "fix it"]
    assert (reply.text, reply.notes) == ("new [[CODE_1]]", "n")
    price_in, price_out = _api.HAIKU_PRICE_PER_MTOK
    assert reply.cost_usd == pytest.approx((1000 * price_in + 200 * price_out) / 1e6)


# ── Variants that already passed stay cached ─────────────────────────────────

class ParaphraseV3(Paraphrase):
    transform_version = "3"


class ParaphraseV2(Paraphrase):
    transform_version = "2"


def _store_old(Session, monkeypatch, transformation, replies):
    scripted_haiku(monkeypatch, replies)
    row = generate(Session, transformation)
    return row.id, row.quality_warning


def test_a_passed_variant_of_the_previous_version_is_reused_without_a_call(Session, monkeypatch):
    old_id, warned = _store_old(Session, monkeypatch, ParaphraseV3(), [FAKE_REWRITE])
    assert warned is False
    requests = scripted_haiku(monkeypatch, [])  # any call would raise StopIteration

    with Session() as db:
        row = TransformationCache(db).variant(Paraphrase(), RECORD, {})
        assert row.id == old_id and row.transform_version == "3"
        assert find_cached_variant(db, "astropy-1", Paraphrase(), {}).id == old_id
    assert requests == []


def test_a_failed_variant_of_the_previous_version_is_regenerated(Session, monkeypatch):
    lossy = FAKE_REWRITE.replace("CompoundModels", "compound models")
    old_id, warned = _store_old(Session, monkeypatch, ParaphraseV3(), [lossy, lossy])
    assert warned is True
    requests = scripted_haiku(monkeypatch, [FAKE_REWRITE])

    row = generate(Session, Paraphrase())
    assert row.id != old_id and row.transform_version == Paraphrase.transform_version
    assert row.quality_warning is False
    assert len(requests) == 1


def test_variants_of_older_versions_are_never_reused(Session, monkeypatch):
    old_id, _warned = _store_old(Session, monkeypatch, ParaphraseV2(), [FAKE_REWRITE])
    requests = scripted_haiku(monkeypatch, [FAKE_REWRITE])
    with Session() as db:
        row = TransformationCache(db).variant(Paraphrase(), RECORD, {})
        assert row.id != old_id
    assert len(requests) == 1


def test_a_no_op_variant_of_the_previous_version_is_reused(Session, monkeypatch):
    class NeutralizeV3(NeutralizeTransformation):
        transform_version = "3"

    _store_old(Session, monkeypatch, NeutralizeV3(), [MASKED.text])  # returned unchanged
    requests = scripted_haiku(monkeypatch, [])
    with Session() as db:
        row = TransformationCache(db).variant(NeutralizeTransformation(), RECORD, {})
        assert row.noop is True and row.transform_version == "3"
    assert requests == []


def test_every_llm_backed_transformation_keeps_the_passed_variants_of_its_previous_version():
    for cls in (Paraphrase, VerbosityReduction, ParagraphToStructured, NeutralizeTransformation):
        previous = str(int(cls.transform_version) - 1)
        assert cls.reuses_passed_versions == {previous}, cls.__name__
