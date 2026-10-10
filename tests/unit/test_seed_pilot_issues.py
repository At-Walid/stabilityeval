"""scripts/seed_pilot_issues.py: idempotent, offline, verbatim, gold patch hidden, pilot source."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.data.database import create_all
from stability_eval.data.loaders.swebench import gold_patch_of, load_bundle
from stability_eval.data.models import PILOT_SOURCE, Issue

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_pilot_issues.py"
PILOT_IDS = Path(__file__).resolve().parents[2] / "scripts" / "output" / "pilot_issue_ids.json"


@pytest.fixture(scope="module")
def seed_script():
    spec = importlib.util.spec_from_file_location("seed_pilot_issues", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    yield eng
    eng.dispose()


def _issues(engine) -> dict[str, Issue]:
    with sessionmaker(bind=engine)() as db:
        rows = {issue.external_id: issue for issue in db.query(Issue)}
        db.expunge_all()
        return rows


def _pilot_ids() -> list[str]:
    return json.loads(PILOT_IDS.read_text(encoding="utf-8"))


def test_seeding_inserts_the_20_pilot_issues_verbatim_with_hidden_gold_patches(
    seed_script, engine, capsys, no_network
):
    assert seed_script.main([], engine=engine) == 0

    ids = _pilot_ids()
    issues = _issues(engine)
    assert len(ids) == 20 and set(issues) == set(ids)
    for instance in load_bundle(ids):
        issue = issues[instance.instance_id]
        assert issue.source == PILOT_SOURCE == "swebench_lite_pilot"
        assert issue.issue_text == instance.problem_statement  # verbatim
        assert issue.repo_name == instance.repo
        assert gold_patch_of(issue) == instance.gold_patch
        assert json.loads(issue.metadata_)["base_commit"] == instance.base_commit
        assert "diff --git" not in issue.issue_text  # the gold patch stays out of the text
    output = capsys.readouterr().out
    assert "inserted 20" in output and "Issues per source: swebench_lite_pilot=20" in output


def test_seeding_twice_changes_nothing(seed_script, engine, capsys):
    seed_script.main([], engine=engine)
    before = {k: (v.id, v.source, v.issue_text, v.metadata_) for k, v in _issues(engine).items()}
    capsys.readouterr()

    seed_script.main([], engine=engine)

    after = {k: (v.id, v.source, v.issue_text, v.metadata_) for k, v in _issues(engine).items()}
    assert after == before
    assert (
        "inserted 0 | already present 20 (relabelled 0, gold patch attached to 0)"
        in capsys.readouterr().out
    )


def test_an_existing_prescreen_issue_is_relabelled_in_place_and_gains_its_gold_patch(
    seed_script, engine, capsys
):
    first = load_bundle(_pilot_ids()[:1])[0]
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Issue(external_id=first.instance_id, repo_name=first.repo, source="swebench_lite",
                     issue_text=first.problem_statement,
                     metadata_=json.dumps({"stage": "prescreen_stage2"})))
        db.commit()
    row_id = _issues(engine)[first.instance_id].id

    seed_script.main([], engine=engine)

    issues = _issues(engine)
    issue = issues[first.instance_id]
    assert len(issues) == 20  # no duplicate row
    assert (issue.id, issue.source) == (row_id, PILOT_SOURCE)  # same row: its runs stay linked
    assert gold_patch_of(issue) == first.gold_patch
    assert json.loads(issue.metadata_)["stage"] == "prescreen_stage2"  # other metadata kept
    output = capsys.readouterr().out
    assert f"relabelled     {first.instance_id} (was swebench_lite)" in output
    assert f"gold attached  {first.instance_id}" in output


def test_an_existing_record_whose_text_is_not_verbatim_is_refused(seed_script, engine):
    first = load_bundle(_pilot_ids()[:1])[0]
    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Issue(external_id=first.instance_id, repo_name=first.repo, source="swebench_lite",
                     issue_text=first.problem_statement + " (edited)"))
        db.commit()

    with pytest.raises(ValueError, match="not the dataset's verbatim text"):
        seed_script.main([], engine=engine)
    issues = _issues(engine)
    assert list(issues) == [first.instance_id]  # nothing inserted
    assert issues[first.instance_id].source == "swebench_lite"  # nor relabelled
