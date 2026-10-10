"""SWE-bench Lite loader: the gold patch is kept, hidden, and never changes an issue's text.

No network: the dataset rows are supplied in-memory.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from stability_eval.data.loaders import swebench
from stability_eval.data.loaders.swebench import (
    gold_patch_of,
    instance_from_record,
    load_bundle,
    load_swebench_lite,
    store_instances,
)
from stability_eval.data.models import Base, Issue

GOLD = "--- a/pkg/core.py\n+++ b/pkg/core.py\n@@ -1 +1 @@\n-x = 1\n+x = 2  # GOLD-MARKER"
ROWS = [
    {
        "instance_id": "org__proj-1",
        "repo": "org/proj",
        "problem_statement": "core breaks on empty input",
        "base_commit": "abc123",
        "patch": GOLD,
    },
    {
        "instance_id": "org__proj-2",
        "repo": "org/proj",
        "problem_statement": "another bug",
        "base_commit": "def456",
        "patch": "--- a/pkg/b.py\n+++ b/pkg/b.py\n@@ -1 +1 @@\n-a\n+b",
    },
]


@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'loader.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def test_instance_keeps_the_gold_patch_but_never_shows_it_in_repr():
    instance = instance_from_record(ROWS[0])
    assert instance.gold_patch == GOLD
    assert "GOLD-MARKER" not in repr(instance)
    assert instance.base_commit == "abc123"


def test_load_filters_by_id_and_reports_unknown_ids():
    assert [i.instance_id for i in load_swebench_lite(["org__proj-2"], dataset=ROWS)] == [
        "org__proj-2"
    ]
    assert len(load_swebench_lite(dataset=ROWS)) == 2
    with pytest.raises(KeyError, match="nope__x-9"):
        load_swebench_lite(["org__proj-1", "nope__x-9"], dataset=ROWS)


def test_store_inserts_new_issues_with_a_hidden_gold_patch(Session):
    with Session() as db:
        store_instances(db, load_swebench_lite(dataset=ROWS))
        db.commit()
    with Session() as db:
        issue = db.query(Issue).filter_by(external_id="org__proj-1").one()
        assert issue.issue_text == "core breaks on empty input"
        assert issue.source == "swebench_lite"
        assert gold_patch_of(issue) == GOLD
        assert "GOLD-MARKER" not in issue.issue_text


def test_store_attaches_gold_to_an_existing_issue_without_touching_its_text(Session):
    with Session() as db:
        db.add(Issue(external_id="org__proj-1", repo_name="org/proj", source="swebench_lite",
                     issue_text="abridged text kept as is", metadata_='{"stage": 1}'))
        db.commit()
    with Session() as db:
        store_instances(db, load_swebench_lite(["org__proj-1"], dataset=ROWS))
        db.commit()
    with Session() as db:
        (issue,) = db.query(Issue).filter_by(external_id="org__proj-1").all()
        assert issue.issue_text == "abridged text kept as is"
        assert gold_patch_of(issue) == GOLD
        assert '"stage": 1' in issue.metadata_  # existing metadata preserved


def test_issue_without_gold_patch():
    assert gold_patch_of(Issue(external_id="x", repo_name="r", source="manual", issue_text="t")) is None
    broken = Issue(external_id="x", repo_name="r", source="manual", issue_text="t", metadata_="{bad")
    assert gold_patch_of(broken) is None


@pytest.fixture()
def cli(Session, monkeypatch):
    """The CLI module writing to the temporary database, with no TLS setup."""
    from stability_eval.cli import main as cli_module

    @contextmanager
    def temp_db():
        session = Session()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(cli_module, "get_db", temp_db)
    monkeypatch.setattr(cli_module, "create_all", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(cli_module, "_inject_truststore", lambda: calls.append("truststore"))
    monkeypatch.setattr(cli_module, "truststore_calls", calls, raising=False)
    return cli_module


def _bundle_file(tmp_path):
    """A two-issue bundle in the format of data/swebench_lite_issues.json."""
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"issues": [
        {"id": r["instance_id"], "repo": r["repo"], "problem_statement": r["problem_statement"],
         "base_commit": r["base_commit"], "gold_patch": r["patch"]}
        for r in ROWS
    ]}), encoding="utf-8")
    return path


def test_load_swebench_cli_reads_the_bundle_offline_by_default(
    cli, Session, monkeypatch, tmp_path, no_network
):
    bundle = _bundle_file(tmp_path)
    monkeypatch.setattr(swebench, "load_bundle", lambda ids: load_bundle(ids, path=bundle))

    def download(*_args, **_kwargs):
        raise AssertionError("the default path must not download the dataset")

    monkeypatch.setattr(swebench, "load_swebench_lite", download)

    result = CliRunner().invoke(cli.app, ["load-swebench", "--ids", "org__proj-1, org__proj-2"])

    assert result.exit_code == 0, result.output
    assert "org__proj-1: gold patch stored (1 file(s); hidden from agents)" in result.output
    assert "GOLD-MARKER" not in result.output
    assert cli.truststore_calls == []
    with Session() as db:
        assert {gold_patch_of(i) is not None for i in db.query(Issue).all()} == {True}


def test_load_swebench_cli_reports_ids_missing_from_the_bundle(cli, monkeypatch, tmp_path):
    bundle = _bundle_file(tmp_path)
    monkeypatch.setattr(swebench, "load_bundle", lambda ids: load_bundle(ids, path=bundle))

    result = CliRunner().invoke(cli.app, ["load-swebench", "--ids", "org__proj-1,nope__x-9"])

    assert result.exit_code == 1
    assert "nope__x-9" in result.output


def test_load_swebench_cli_can_still_download_from_hugging_face(cli, Session, monkeypatch):
    monkeypatch.setattr(
        swebench, "load_swebench_lite", lambda ids: load_swebench_lite(ids, dataset=ROWS)
    )

    result = CliRunner().invoke(
        cli.app, ["load-swebench", "--ids", "org__proj-2", "--from-huggingface"]
    )

    assert result.exit_code == 0, result.output
    assert cli.truststore_calls == ["truststore"]
    with Session() as db:
        assert [i.external_id for i in db.query(Issue).all()] == ["org__proj-2"]
