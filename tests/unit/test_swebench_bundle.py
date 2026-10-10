"""The bundled SWE-bench Lite issues: file content, and an offline, idempotent import."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from stability_eval.data.loaders.swebench import (
    BUNDLE_PATH,
    gold_patch_of,
    import_bundle,
    load_bundle,
)
from stability_eval.data.models import Base, Issue

DEMO_SAMPLE = "django__django-11099"  # also inserted, abridged, by the dashboard's demo seed


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'bundle.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_bundle_holds_the_300_test_issues_with_attribution_and_a_license_note(bundle):
    issues = bundle["issues"]
    assert bundle["count"] == len(issues) == 300
    assert len({issue["id"] for issue in issues}) == 300
    assert bundle["source"]["dataset"] == "princeton-nlp/SWE-bench_Lite"
    assert bundle["source"]["split"] == "test"
    assert bundle["source"]["revision"]
    assert "arXiv:2310.06770" in bundle["source"]["paper"]
    assert "license" in bundle["license_note"].lower()
    for issue in issues:
        assert set(issue) == {"id", "repo", "problem_statement", "base_commit", "gold_patch"}
        assert issue["id"].startswith(issue["repo"].replace("/", "__") + "-")
        assert issue["problem_statement"].strip()
        assert issue["gold_patch"].startswith("diff --git")


def test_no_problem_statement_contains_its_gold_patch(bundle):
    assert not [
        issue["id"] for issue in bundle["issues"]
        if issue["gold_patch"].strip() in issue["problem_statement"]
    ]


def test_load_bundle_selects_ids_hides_gold_patches_and_rejects_unknown_ids(no_network):
    (instance,) = load_bundle([DEMO_SAMPLE])
    assert instance.repo == "django/django"
    assert instance.gold_patch.startswith("diff --git")
    assert "diff --git" not in repr(instance)
    with pytest.raises(KeyError, match="nope__x-9"):
        load_bundle([DEMO_SAMPLE, "nope__x-9"])


def test_import_is_offline_and_keeps_existing_texts(engine, bundle, no_network):
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(Issue(external_id=DEMO_SAMPLE, repo_name="django/django", source="swebench_lite",
                     issue_text="abridged demo text"))
        db.commit()

    with Session() as db:
        summary = import_bundle(db)
        db.commit()

    assert (summary.inserted, summary.updated, summary.total) == (299, 1, 300)
    assert summary.kept_text == (DEMO_SAMPLE,)
    by_id = {issue["id"]: issue for issue in bundle["issues"]}
    with Session() as db:
        issues = {issue.external_id: issue for issue in db.query(Issue)}
        assert len(issues) == 300
        assert issues[DEMO_SAMPLE].issue_text == "abridged demo text"
        assert gold_patch_of(issues[DEMO_SAMPLE]) == by_id[DEMO_SAMPLE]["gold_patch"]
        other = issues["psf__requests-2317"]
        assert other.issue_text == by_id["psf__requests-2317"]["problem_statement"]  # verbatim
        assert other.repo_name == "psf/requests" and other.source == "swebench_lite"
        assert gold_patch_of(other) == by_id["psf__requests-2317"]["gold_patch"]


def test_a_second_import_writes_nothing(engine, no_network):
    Session = sessionmaker(bind=engine)
    with Session() as db:
        import_bundle(db)
        db.commit()
    with Session() as db:
        before = {(i.id, i.external_id, i.issue_text, i.metadata_) for i in db.query(Issue)}

    writes: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    with Session() as db:
        summary = import_bundle(db)
        db.commit()
    event.remove(engine, "before_cursor_execute", record)

    assert (summary.inserted, summary.updated, summary.kept_text) == (0, 300, ())
    assert writes == []
    with Session() as db:
        assert {(i.id, i.external_id, i.issue_text, i.metadata_) for i in db.query(Issue)} == before
