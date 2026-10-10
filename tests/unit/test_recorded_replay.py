"""MockReplay's recorded control runs and variants, and when the transformation cache restores a
recorded variant (TransformationCache.restore_recorded) instead of making a placeholder."""
from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stability_eval.agents.base import AgentInput, ExecutionMode
from stability_eval.agents.mock_replay import MockReplayAdapter, recorded_control_repeats
from stability_eval.data.models import Base, Issue
from stability_eval.transformations.base import PLACEHOLDER, IssueRecord
from stability_eval.transformations.cache import TransformationCache, recorded_variant
from stability_eval.transformations.registry import transformation_registry

TEXT = "Crash in pkg.core when the input is empty."


@pytest.fixture()
def fixtures(tmp_path):
    original = {"status": "success", "patch": "P0", "cost_usd": 0.1,
                "control_repeats": [{"status": "success", "patch": "P1"},
                                    {"status": "no_patch", "patch": None, "error_message": "e"}]}
    (tmp_path / "org__a-1__original__mock_replay.json").write_text(json.dumps(original))
    (tmp_path / "org__a-1__paraphrase__mock_replay.json").write_text(
        json.dumps({"status": "success", "patch": "PV", "variant": {"transformed_text": "V"}})
    )
    return tmp_path


def _run(adapter, transformation, control_repeat=None):
    metadata = {"issue_id": "org__a-1", "transformation_name": transformation}
    if control_repeat is not None:
        metadata["control_repeat"] = control_repeat
    return adapter.run(AgentInput(issue_text="x", repo_name="o/r", metadata=metadata),
                       ExecutionMode.MOCK)


def test_control_runs_replay_the_recorded_re_runs_in_order(fixtures):
    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(fixtures)})
    assert _run(adapter, "original").patch == "P0"
    assert _run(adapter, "original", control_repeat=1).patch == "P1"
    assert _run(adapter, "original", control_repeat=2).status == "no_patch"
    # beyond what was recorded (older fixtures have none): the original's own output
    assert _run(adapter, "original", control_repeat=3).patch == "P0"
    assert recorded_control_repeats("org__a-1", fixtures) == 2
    assert recorded_control_repeats("org__zzz-9", fixtures) == 0


def test_recorded_variant_is_read_from_the_fixture(fixtures):
    adapter = MockReplayAdapter()
    adapter.configure({"fixtures_dir": str(fixtures)})
    assert adapter.recorded_variant("org__a-1", "paraphrase") == {"transformed_text": "V"}
    assert adapter.recorded_variant("org__a-1", "original") is None
    assert adapter.recorded_variant("org__a-1", "reordering") is None


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        issue = Issue(external_id="org__a-1", repo_name="o/r", source="swebench_lite",
                      issue_text=TEXT)
        session.add(issue)
        session.commit()
        yield session, IssueRecord(issue.id, "o/r", TEXT)
    engine.dispose()


def _recorded(transformation, **overrides):
    record = {
        "transformed_text": "Reworded crash report.",
        "transformation_notes": "n",
        "params": {},
        "generator": transformation.generator,
        "transform_version": transformation.transform_version,
        "generation_mode": "real",
        "quality_warning": False,
        "noop": False,
        "exclusion_reason": None,
        "generation_cost_usd": 0.002,
        "original_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    record.update(overrides)
    return record


def test_mock_mode_restores_a_recorded_variant_with_its_provenance(db):
    session, issue = db
    paraphrase = transformation_registry.get("paraphrase")()
    cache = TransformationCache(session)
    row = cache.variant(paraphrase, issue, {}, mode="mock", recorded=_recorded(
        paraphrase, quality_warning=True, exclusion_reason="missing 1: pkg.core"
    ))
    assert row.transformed_text == "Reworded crash report."
    assert (row.generator, row.generation_mode) == (paraphrase.generator, "real")
    assert row.quality_warning and row.exclusion_reason == "missing 1: pkg.core"
    assert row.generation_cost_usd == 0.002
    # it is now an ordinary cache entry, served as such, and round-trips through the recorder
    assert cache.variant(paraphrase, issue, {}, mode="mock") is row
    again = recorded_variant(row, TEXT)
    assert again == _recorded(paraphrase, quality_warning=True,
                              exclusion_reason="missing 1: pkg.core")


@pytest.mark.parametrize("override", [
    {"generator": "placeholder"},
    {"generator": "claude-some-other-model"},
    {"transform_version": "1"},
    {"params": {"temperature": 1}},
    {"original_sha256": "0" * 64},
])
def test_a_recorded_variant_the_cache_would_not_serve_gives_a_placeholder(db, override):
    session, issue = db
    paraphrase = transformation_registry.get("paraphrase")()
    row = TransformationCache(session).variant(
        paraphrase, issue, {}, mode="mock", recorded=_recorded(paraphrase, **override)
    )
    assert row.generator == PLACEHOLDER


def test_a_passed_variant_of_a_reused_version_is_restored_but_not_a_failed_one(db):
    session, issue = db
    paraphrase = transformation_registry.get("paraphrase")()
    (old_version,) = paraphrase.reuses_passed_versions
    cache = TransformationCache(session)
    failed = cache.variant(paraphrase, issue, {}, mode="mock", recorded=_recorded(
        paraphrase, transform_version=old_version, quality_warning=True
    ))
    assert failed.generator == PLACEHOLDER
    passed = cache.variant(paraphrase, issue, {}, mode="mock", recorded=_recorded(
        paraphrase, transform_version=old_version
    ))
    assert (passed.generator, passed.transform_version) == (paraphrase.generator, old_version)


def test_a_recorded_deterministic_variant_is_restored_as_recorded(db):
    session, issue = db
    typo = transformation_registry.get("typo_injection")()
    params = {"error_rate": 0.02}
    row = TransformationCache(session).variant(typo, issue, params, mode="mock", recorded=_recorded(
        typo, transformed_text="Crash in pkg.core wehn the input is empty.", params=params
    ))
    assert row.transformed_text == "Crash in pkg.core wehn the input is empty."


def test_real_mode_never_restores(db):
    session, issue = db
    typo = transformation_registry.get("typo_injection")()
    params = {"error_rate": 0.02, "seed": 1}
    row = TransformationCache(session).variant(typo, issue, params, mode="real", recorded=_recorded(
        typo, transformed_text="recorded", params=params
    ))
    assert row.transformed_text != "recorded"
