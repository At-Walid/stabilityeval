"""scripts/seed_issues_from_stage1.py: idempotent, offline, verbatim, gold patch hidden."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.data.loaders.swebench import gold_patch_of, load_bundle
from stability_eval.data.models import Issue

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_issues_from_stage1.py"
CANDIDATES = Path(__file__).resolve().parents[2] / "scripts" / "output" / "stage1_candidates.json"


@pytest.fixture(scope="module")
def seed_script():
    spec = importlib.util.spec_from_file_location("seed_issues_from_stage1", SCRIPT)
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


def test_seeding_inserts_the_20_candidates_verbatim_with_hidden_gold_patches(
    seed_script, engine, capsys, no_network
):
    assert seed_script.main([], engine=engine) == 0

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    issues = _issues(engine)
    assert len(candidates) == 20 and set(issues) == {c["id"] for c in candidates}
    bundle = {i.instance_id: i for i in load_bundle([c["id"] for c in candidates])}
    for candidate in candidates:
        issue = issues[candidate["id"]]
        assert issue.source == "swebench_lite"
        assert issue.issue_text == candidate["problem_statement"]  # verbatim
        assert gold_patch_of(issue) == bundle[candidate["id"]].gold_patch
        assert "diff --git" not in issue.issue_text
    output = capsys.readouterr().out
    assert "inserted 20" in output and "Issues per source: swebench_lite=20" in output


def test_seeding_twice_changes_nothing(seed_script, engine, capsys):
    seed_script.main([], engine=engine)
    before = {k: (v.id, v.issue_text, v.metadata_) for k, v in _issues(engine).items()}
    capsys.readouterr()

    seed_script.main([], engine=engine)

    after = {k: (v.id, v.issue_text, v.metadata_) for k, v in _issues(engine).items()}
    assert after == before
    assert "inserted 0 | already present 20 (gold patch attached to 0)" in capsys.readouterr().out


def test_existing_issues_are_skipped_but_gain_a_missing_gold_patch(seed_script, engine, capsys):
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    first = candidates[0]
    from stability_eval.data.database import create_all

    create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Issue(external_id=first["id"], repo_name=first["repo"], source="swebench_lite",
                     issue_text=first["problem_statement"]))
        db.commit()

    seed_script.main([], engine=engine)

    issue = _issues(engine)[first["id"]]
    assert gold_patch_of(issue) is not None
    assert len(_issues(engine)) == 20  # no duplicate row
    assert f"gold attached  {first['id']}" in capsys.readouterr().out


def test_a_candidate_whose_text_is_not_verbatim_is_refused(seed_script, engine, tmp_path):
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))[:2]
    candidates[1]["problem_statement"] += " (edited)"
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(candidates), encoding="utf-8")

    with pytest.raises(ValueError, match="not the dataset's verbatim text"):
        seed_script.main(["--candidates", str(path)], engine=engine)
    assert _issues(engine) == {}
