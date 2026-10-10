"""Variant provenance, no-op detection, the paragraph_to_structured rules, the upgrade of older
databases, and the per-run API key override. No network."""
from __future__ import annotations

import json
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from stability_eval.config.settings import api_key_override, get_anthropic_api_key, redact_api_key
from stability_eval.data.database import create_all
from stability_eval.data.migrations import upgrade
from stability_eval.data.models import Base, Issue
from stability_eval.data.models import TransformedIssue as TIModel
from stability_eval.transformations.base import IssueRecord, invented_versions, is_noop
from stability_eval.transformations.cache import TransformationCache
from stability_eval.transformations.llm_backed import structure
from stability_eval.transformations.llm_backed._api import HaikuReply
from stability_eval.transformations.llm_backed.structure import ParagraphToStructured

ISSUE = IssueRecord(
    issue_id="issue-1",
    repo_name="org/proj",
    text="parse_rows() raises KeyError in DataLoader.\n\nIt should return an empty list.",
)


@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'provenance.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Issue(id=ISSUE.issue_id, source="manual", repo_name=ISSUE.repo_name,
                     issue_text=ISSUE.text))
        db.commit()
    yield factory
    engine.dispose()


# ── No-op detection ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("transformed", "noop"),
    [
        (ISSUE.text, True),
        (ISSUE.text.replace("\n\n", "\r\n\r\n"), True),  # CRLF only
        ("  " + ISSUE.text.replace(" ", "   ") + "\n", True),  # spacing only
        (ISSUE.text.replace("\n\n", " "), True),  # paragraph breaks only
        (ISSUE.text.replace("empty", "Empty"), False),  # case is a change
        (ISSUE.text + " Thanks!", False),
    ],
)
def test_noop_means_equal_after_whitespace_normalization(transformed, noop):
    assert is_noop(ISSUE.text, transformed) is noop


# ── paragraph_to_structured (E) ───────────────────────────────────────────────

def test_structure_prompt_allows_only_information_from_the_original():
    prompt = structure._SYSTEM_PROMPT
    assert "Use ONLY information present in the original issue" in prompt
    assert 'write exactly "Not specified"' in prompt
    assert "Never invent version numbers, reproduction steps" in prompt
    assert "environment detail" in prompt
    assert ParagraphToStructured.transform_version == "5"


def test_invented_versions_are_detected():
    original = "Fails on Django 3.2 with numpy 1.21.0."
    assert invented_versions(original, "Django 3.2, numpy 1.21.0") == []
    assert invented_versions(original, "Environment: Python 3.11, Django 3.2") == ["3.11"]
    assert invented_versions(original, "1. Run it.\n2. See the error.") == []  # list numbers


def _scripted_structure(monkeypatch, outputs):
    replies = iter([HaikuReply(text, "notes") for text in outputs])
    calls = []

    def fake_haiku(system_prompt, user_content, api_key, model=None, **_):
        calls.append(model)
        return next(replies)

    monkeypatch.setattr("stability_eval.transformations.llm_backed._api.call_haiku", fake_haiku)
    return calls


GOOD_STRUCTURE = (
    "## Summary\n`parse_rows()` raises `KeyError` in `DataLoader`.\n\n"
    "## Steps to Reproduce\nNot specified\n\n## Expected Behavior\nReturns an empty list.\n\n"
    "## Actual Behavior\nRaises `KeyError`.\n\n## Environment\nNot specified"
)
INVENTING = GOOD_STRUCTURE.replace(
    "## Environment\nNot specified", "## Environment\nPython 3.11, pandas 2.0.1"
)


def test_an_invented_version_is_retried_like_a_retention_failure(Session, monkeypatch):
    calls = _scripted_structure(monkeypatch, [INVENTING, GOOD_STRUCTURE])
    with Session() as db:
        row = TransformationCache(db).variant(ParagraphToStructured(), ISSUE, {})
        db.commit()
        assert row.transformed_text == GOOD_STRUCTURE and row.quality_warning is False
    assert len(calls) == 2 and set(calls) == {ParagraphToStructured.model}


def test_a_variant_that_keeps_inventing_versions_is_excluded(Session, monkeypatch):
    _scripted_structure(monkeypatch, [INVENTING] * 2)
    with Session() as db:
        row = TransformationCache(db).variant(ParagraphToStructured(), ISSUE, {})
        db.commit()
        assert row.quality_warning is True
        assert "invented details (version 2.0.1, version 3.11)" in row.transformation_notes
        assert "excluded from metrics" in row.transformation_notes
        assert (row.generator, row.transform_version, row.generation_mode) == (
            ParagraphToStructured.model, ParagraphToStructured.transform_version, "real"
        )


def test_a_no_op_llm_output_is_flagged(Session, monkeypatch):
    _scripted_structure(monkeypatch, [ISSUE.text.replace("\n\n", "\n")])
    with Session() as db:
        row = TransformationCache(db).variant(ParagraphToStructured(), ISSUE, {})
        assert row.noop is True and row.quality_warning is False


# ── Upgrading a database created before provenance existed ───────────────────

LEGACY_SCHEMA = [
    """CREATE TABLE issues (id VARCHAR NOT NULL, source VARCHAR NOT NULL, external_id VARCHAR,
       repo_name VARCHAR NOT NULL, issue_text TEXT NOT NULL, reproduction_steps TEXT,
       expected_behavior TEXT, relevant_tests TEXT, metadata TEXT, created_at VARCHAR NOT NULL,
       PRIMARY KEY (id))""",
    """CREATE TABLE transformed_issues (id VARCHAR NOT NULL, issue_id VARCHAR NOT NULL,
       transformation_name VARCHAR NOT NULL, transformation_params TEXT,
       transformed_text TEXT NOT NULL, transformation_notes TEXT, quality_warning BOOLEAN NOT NULL,
       is_original BOOLEAN NOT NULL, created_at VARCHAR NOT NULL, PRIMARY KEY (id),
       FOREIGN KEY(issue_id) REFERENCES issues (id))""",
]
LEGACY_ROWS = [
    # id, name, params, text, is_original
    ("t-orig", "original", None, "A bug.\n\nDetails.", 1),
    ("t-para", "paraphrase", json.dumps({"params": {}, "_cache_key": "old"}), "Reworded bug.", 0),
    ("t-noop", "reordering", json.dumps({"params": {"seed": 42}, "_cache_key": "old"}),
     "A bug.\r\n\r\nDetails.", 0),
    ("t-ph", "verbosity_reduction",
     json.dumps({"params": {}, "transform_version": "2", "offline_placeholder": True,
                 "_cache_key": "k"}),
     "[Offline placeholder ...]\n\nA bug.\n\nDetails.", 0),
    ("t-adhoc", "typo_injection", None, "A bgu.\n\nDetails.", 0),
]


@pytest.fixture()
def legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        for statement in LEGACY_SCHEMA:
            conn.execute(text(statement))
        conn.execute(text(
            "INSERT INTO issues (id, source, repo_name, issue_text, created_at) "
            "VALUES ('i-1', 'swebench_lite', 'o/r', 'A bug.\n\nDetails.', 'now')"
        ))
        for row_id, name, params, body, original in LEGACY_ROWS:
            conn.execute(
                text("INSERT INTO transformed_issues (id, issue_id, transformation_name, "
                     "transformation_params, transformed_text, quality_warning, is_original, "
                     "created_at) VALUES (:id, 'i-1', :name, :params, :body, 0, :orig, 'now')"),
                {"id": row_id, "name": name, "params": params, "body": body, "orig": original},
            )
    yield engine
    engine.dispose()


def test_upgrade_adds_provenance_and_invalidates_placeholders(legacy_engine):
    steps = upgrade(legacy_engine)

    assert steps[0] == (
        "added transformed_issues columns: generator, transform_version, generation_mode, noop"
    )
    assert "1 placeholder (invalidated)" in steps[1] and "1 no-op" in steps[1]
    with sessionmaker(bind=legacy_engine)() as db:
        rows = {row.id: row for row in db.query(TIModel)}
    assert (rows["t-orig"].generator, rows["t-orig"].noop) == ("original", False)
    assert (rows["t-para"].generator, rows["t-para"].generation_mode) == ("unknown", "unknown")
    assert rows["t-noop"].noop is True  # CRLF-only difference
    assert rows["t-adhoc"].generator == "unknown" and rows["t-adhoc"].noop is False
    placeholder = rows["t-ph"]
    assert (placeholder.generator, placeholder.transform_version) == ("placeholder", "2")
    params = json.loads(placeholder.transformation_params)
    assert "_cache_key" not in params and "invalidated" in params
    assert json.loads(rows["t-para"].transformation_params)["_cache_key"] == "old"  # untouched


def test_upgrade_is_idempotent_and_create_all_runs_it(legacy_engine):
    create_all(legacy_engine)  # creates the missing tables and upgrades the old one
    tables = set(inspect(legacy_engine).get_table_names())
    assert {"runs", "experiments", "metrics"} <= tables
    with sessionmaker(bind=legacy_engine)() as db:
        before = [(r.id, r.generator, r.noop, r.transformation_params) for r in db.query(TIModel)]
    assert upgrade(legacy_engine) == []
    create_all(legacy_engine)
    with sessionmaker(bind=legacy_engine)() as db:
        after = [(r.id, r.generator, r.noop, r.transformation_params) for r in db.query(TIModel)]
    assert after == before


def test_a_current_database_needs_no_upgrade(Session):
    engine = Session.kw["bind"]
    assert upgrade(engine) == []


# ── The per-run API key ───────────────────────────────────────────────────────

def test_api_key_override_is_scoped_and_never_touches_the_environment(dummy_api_key):
    before = dict(os.environ)
    with api_key_override("sk-ant-session-key"):
        assert get_anthropic_api_key() == "sk-ant-session-key"
        assert redact_api_key("bad key sk-ant-session-key") == "bad key [REDACTED]"
        seen_elsewhere = []
        worker = threading.Thread(target=lambda: seen_elsewhere.append(get_anthropic_api_key()))
        worker.start()
        worker.join()
        assert seen_elsewhere == [dummy_api_key]  # another thread (session) does not see it
    assert get_anthropic_api_key() == dummy_api_key
    assert dict(os.environ) == before
