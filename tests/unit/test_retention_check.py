"""The identifier-retention check protects technical content only (SPEC section 11.5).

Code survives verbatim (fenced blocks, >>> lines, indented code lines, backtick spans); technical
tokens must appear (identifiers with _ . / or digits, CamelCase, paths, *Error/*Exception);
plain English may change freely. Failures are stored as the variant's exclusion_reason.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.models import Base, Issue
from stableagent.data.models import TransformedIssue as TIModel
from stableagent.transformations.base import (
    IssueRecord,
    check_identifier_retention,
    normalize_markdown,
    technical_content,
)
from stableagent.transformations.cache import TransformationCache
from stableagent.transformations.llm_backed._api import HaikuReply
from stableagent.transformations.llm_backed.paraphrase import Paraphrase

ISSUE_TEXT = """\
`QuerySet.delete()` raises IntegrityError when the model has a GenericRelation.

Steps:

    qs = Article.objects.filter(pk__in=[1, 2])
    qs.delete()

>>> from app.models import Article
>>> Article.objects.count()
2

```python
def test_delete():
    assert Article.objects.count() == 0
```

It happens on Django 3.2 with psycopg2 in django/db/models/deletion.py, e.g. on CI and/or
locally. This is really annoying and NOT what the docs promise!"""


def test_code_is_protected_whole_and_verbatim():
    code, _tokens = technical_content(ISSUE_TEXT)
    assert code == [
        ("line", "qs = Article.objects.filter(pk__in=[1, 2])"),
        ("line", "qs.delete()"),
        ("line", ">>> from app.models import Article"),
        ("line", ">>> Article.objects.count()"),
        ("block", "def test_delete():\n    assert Article.objects.count() == 0"),
        ("span", "QuerySet.delete()"),
    ]


def test_technical_tokens_of_the_prose():
    _code, tokens = technical_content(ISSUE_TEXT)
    assert tokens == {
        "IntegrityError",  # *Error (and CamelCase)
        "GenericRelation",  # CamelCase
        "3.2",  # digits / dots
        "psycopg2",  # digits
        "django/db/models/deletion.py",  # path
    }


@pytest.mark.parametrize(
    "word",
    ["Steps", "really", "annoying", "NOT", "e.g", "and/or", "CI", "docs", "promise", "2"],
)
def test_plain_english_is_free(word):
    _code, tokens = technical_content(ISSUE_TEXT)
    assert word not in tokens


@pytest.mark.parametrize(
    ("token", "technical"),
    [
        ("snake_case", True), ("os.path.join", True), ("settings.py", True), ("/tmp/out", True),
        ("src/app/x", True), ("v2", True), ("utf-8", True), ("2.3.1", True), ("DataLoader", True),
        ("HTTPServer", True), ("IOError", True), ("parseConfig", True), ("lib\\site\\x", True),
        ("and/or", False), ("e.g", False), ("i.e", False), ("API", False), ("Error", False),
        ("Exception", False), ("well-known", False), ("42", False), ("Django", False),
    ],
)
def test_what_counts_as_a_technical_token(token, technical):
    _code, tokens = technical_content(f"see {token} here")
    assert (token in tokens) is technical


def test_list_items_indented_under_a_list_are_not_code():
    text = "Notes:\n\n- first\n\n    - nested item that may be reworded\n"
    code, _tokens = technical_content(text)
    assert code == []


def test_a_rewording_that_keeps_all_technical_content_passes():
    reworded = ISSUE_TEXT.replace("This is really annoying and NOT what the docs promise!",
                                  "This contradicts the documentation.")
    reworded = reworded.replace("It happens on", "Seen with").replace("Steps:", "To reproduce:")
    assert check_identifier_retention(ISSUE_TEXT, reworded) == (True, [])


def test_line_endings_and_trailing_spaces_do_not_matter():
    crlf = ISSUE_TEXT.replace("\n", "  \r\n")
    assert check_identifier_retention(crlf, ISSUE_TEXT)[0] is True
    assert check_identifier_retention(ISSUE_TEXT, crlf)[0] is True


def test_changed_code_and_missing_tokens_are_listed():
    damaged = (
        ISSUE_TEXT.replace("qs.delete()", "qs.delete( )")
        .replace("    assert Article.objects.count() == 0", "    assert not Article.objects.all()")
        .replace("psycopg2", "the Postgres driver")
        .replace("`QuerySet.delete()`", "Deleting a queryset")
    )
    passed, missing = check_identifier_retention(ISSUE_TEXT, damaged)
    assert passed is False
    assert missing == [
        'code "qs.delete()"',
        'code "def test_delete():" (2 lines)',
        "`QuerySet.delete()`",
        "psycopg2",
    ]


# ── Markdown formatting and issue-template boilerplate are not technical ─────

def test_an_unanswered_issue_form_field_is_not_technical():
    _code, tokens = technical_content("### Python version\n\n_No response_\n")
    assert tokens == set()  # not "_No" and "response_"
    assert check_identifier_retention("Bug.\n\n_No response_\n", "Bug.") == (True, [])


def test_standard_template_headings_are_ignored_but_specific_ones_are_kept():
    text = (
        "### Additional information\n\n_No response_\n\n"
        "### Steps/Code to Reproduce\n\nRun it.\n\n### example.py\n\nfails\n"
    )
    _code, tokens = technical_content(text)
    assert tokens == {"example.py"}
    assert normalize_markdown(text).count("###") == 1


def test_escaped_underscores_give_the_dunder_name():
    _code, tokens = technical_content(r"_\_repr\_\_ of the estimator fails")
    assert tokens == {"__repr__"}
    # Present either as written by the model or with the original escapes.
    assert check_identifier_retention(r"Fix _\_repr\_\_.", "Fix the __repr__ method.")[0]
    assert check_identifier_retention(r"Fix _\_repr\_\_.", r"Fix _\_repr\_\_ please.")[0]
    assert not check_identifier_retention(r"Fix _\_repr\_\_.", "Fix the repr.")[0]


def test_html_tags_are_not_paths():
    text = "<details><summary>Traceback</summary>\n\nsee the log\n\n</details>\n<br/>"
    _code, tokens = technical_content(text)
    assert tokens == set()  # not "/details", "/summary"
    assert "/details" not in technical_content("in </details> and </module>")[1]
    assert "/module" not in technical_content("in </details> and </module>")[1]
    assert technical_content("written to /tmp/out")[1] == {"/tmp/out"}  # a real path still is


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("_original_ request object", set()),  # italic prose
        ("**Describe the bug**", set()),
        ("see *foo_bar* here", {"foo_bar"}),
        ("<!-- A short 1-2 sentences, see foo_bar -->", set()),  # template comment
        ("a lone _ underscore", set()),
        # Identifiers are never taken for emphasis.
        ("ZeroDivisionError in _sparse_fit for SVM with empty support_vectors_",
         {"ZeroDivisionError", "_sparse_fit", "support_vectors_"}),
        ("__init__ and __call__", {"__init__", "__call__"}),
        ("*args, **kwargs and 2*3*4", set()),
        (r"C:\Users\me\_base.py", {r"Users\me\_base.py"}),  # no unescaping in a Windows path
    ],
)
def test_markdown_normalization_keeps_identifiers(text, tokens):
    assert technical_content(text)[1] == tokens


# ── exclusion_reason ──────────────────────────────────────────────────────────

@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Issue(id="i-1", source="manual", repo_name="o/r", issue_text=ISSUE_TEXT))
        db.commit()
    yield factory
    engine.dispose()


def test_the_missing_tokens_become_the_variants_exclusion_reason(Session, monkeypatch):
    # The model sees the masked text: only the prose (with its technical tokens) can change.
    def lossy(text):
        return text.replace("psycopg2", "the driver").replace("GenericRelation", "relation")

    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: HaikuReply(lossy(text), "notes"),
    )
    record = IssueRecord(issue_id="i-1", repo_name="o/r", text=ISSUE_TEXT)
    with Session() as db:
        TransformationCache(db).variant(Paraphrase(), record, {})
        db.commit()
    with Session() as db:
        row = db.query(TIModel).one()
    assert row.quality_warning is True and row.noop is False
    assert row.exclusion_reason == (
        "identifier retention failed (missing 2: GenericRelation, psycopg2)"
    )


def test_a_passing_variant_has_no_exclusion_reason(Session, monkeypatch):
    monkeypatch.setattr(
        "stableagent.transformations.llm_backed._api.call_haiku",
        lambda system, text, key, model=None, **_: HaikuReply(
            text.replace("really annoying", "inconvenient"), "notes"
        ),
    )
    with Session() as db:
        row = TransformationCache(db).variant(
            Paraphrase(), IssueRecord("i-1", "o/r", ISSUE_TEXT), {}
        )
        assert (row.quality_warning, row.noop, row.exclusion_reason) == (False, False, None)


def test_the_upgrade_backfills_exclusion_reasons(tmp_path):
    from sqlalchemy import text

    from stableagent.data.migrations import upgrade

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transformed_issues DROP COLUMN exclusion_reason"))
        conn.execute(text(
            "INSERT INTO issues (id, source, repo_name, issue_text, created_at) "
            "VALUES ('i-1', 'manual', 'o/r', 'text', 'now')"
        ))
        rows = [
            ("q", 1, 0, "fake [QUALITY WARNING: identifier retention failed (missing 1: a_b) "
                        "after 3 attempts; excluded from metrics]"),
            ("n", 0, 1, "unchanged"),
            ("ok", 0, 0, "fine"),
        ]
        for row_id, quality, noop, notes in rows:
            conn.execute(
                text("INSERT INTO transformed_issues (id, issue_id, transformation_name, "
                     "transformed_text, transformation_notes, quality_warning, is_original, "
                     "created_at, noop) VALUES (:id, 'i-1', 'paraphrase', 'x', :notes, :q, 0, "
                     "'now', :n)"),
                {"id": row_id, "notes": notes, "q": quality, "n": noop},
            )

    steps = upgrade(engine)

    assert steps == [
        "added transformed_issues column: exclusion_reason",
        "backfilled exclusion_reason of 2 excluded variant row(s)",
    ]
    with sessionmaker(bind=engine)() as db:
        reasons = {row.id: row.exclusion_reason for row in db.query(TIModel)}
    assert reasons == {
        "q": "identifier retention failed (missing 1: a_b) after 3 attempts; excluded from "
             "metrics",
        "n": "no-op: identical to the original after whitespace normalization",
        "ok": None,
    }
    assert upgrade(engine) == []
    engine.dispose()


def test_exports_carry_the_exclusion_reason():
    from stableagent.export._metric_rows import PROVENANCE_FIELDS, provenance

    ti = TIModel(issue_id="i", transformation_name="paraphrase", transformed_text="x",
                 generator="m", transform_version="3", generation_mode="real", noop=False,
                 exclusion_reason="identifier retention failed (missing 1: a_b)")
    assert PROVENANCE_FIELDS[-1] == "exclusion_reason"
    assert json.dumps(provenance(ti))  # serializable as is
    assert provenance(ti)["exclusion_reason"] == "identifier retention failed (missing 1: a_b)"
