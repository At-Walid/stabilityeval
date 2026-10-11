"""scripts/requeue_retention_false_positives.py: only variants excluded for retention false
positives lose their cache key; every other variant stays as it is. No network."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.data.models import Base, Issue
from stableagent.data.models import TransformedIssue as TIModel
from stableagent.transformations.base import IssueRecord
from stableagent.transformations.cache import TransformationCache, cache_key, is_cached
from stableagent.transformations.llm_backed._api import HaikuReply
from stableagent.transformations.llm_backed.neutralize import NeutralizeTransformation
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.llm_backed.structure import ParagraphToStructured
from stableagent.transformations.llm_backed.verbosity import VerbosityReduction

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "requeue_retention_false_positives.py"

ISSUE_TEXT = (
    "### Bug summary\n\n"
    "_\\_repr\\_\\_ fails on pytest 5.4.3 for DataFrame objects.\n\n"
    "### Additional information\n\n_No response_\n\n"
    "<details><summary>Log</summary>\n\nsee the log\n\n</details>\n"
)
KEEPS_EVERYTHING = "__repr__ fails on pytest 5.4.3 for DataFrame objects."
DROPS_THE_VERSION = "__repr__ fails for DataFrame objects."


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("requeue_retention_false_positives", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass needs the module registered
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _variant(transformation, text, reason=None, *, version=None):
    """A stored variant keyed like the cache keys it (``version``: an older one)."""
    version = version or transformation.transform_version
    return TIModel(
        issue_id="i-1",
        transformation_name=transformation.name,
        transformation_params=json.dumps({
            "params": {}, "transform_version": version, "generator": transformation.generator,
            "_cache_key": cache_key(transformation, {}, None, version),
        }),
        transformed_text=text,
        quality_warning=reason is not None,
        exclusion_reason=reason,
        generator=transformation.generator,
        transform_version=version,
        generation_mode="real",
    )


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'requeue.db'}")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as db:
        db.add(Issue(id="i-1", external_id="org__proj-1", source="swebench_lite_pilot",
                     repo_name="org/proj", issue_text=ISSUE_TEXT))
        db.add_all([
            # Excluded under the old rules for template noise only: requeued.
            _variant(VerbosityReduction(), KEEPS_EVERYTHING,
                     "identifier retention failed (missing 5: /details, /summary, _No, "
                     "_\\_repr\\_\\_, response_)"),
            # A real omission: kept excluded.
            _variant(Paraphrase(), DROPS_THE_VERSION,
                     "identifier retention failed (missing 2: 5.4.3, _No)"),
            # Also excluded for something the new rules do not change: kept.
            _variant(ParagraphToStructured(), KEEPS_EVERYTHING + " Python 9.9.",
                     "identifier retention failed (missing 1: response_); invented details "
                     "(version 9.9)"),
            # Passed: stays cached.
            _variant(NeutralizeTransformation(), KEEPS_EVERYTHING),
            # An older version: never served again anyway, not touched.
            _variant(VerbosityReduction(), KEEPS_EVERYTHING,
                     "identifier retention failed (missing 1: response_)", version="3"),
        ])
        db.commit()
    yield eng
    eng.dispose()


def _rows(engine) -> dict[tuple[str, str], tuple[bool, str | None, str]]:
    with sessionmaker(bind=engine)() as db:
        return {
            (row.transformation_name, row.transform_version): (
                is_cached(row), row.exclusion_reason, row.transformation_params
            )
            for row in db.query(TIModel)
        }


def test_a_dry_run_lists_the_verdicts_and_changes_nothing(script, engine, capsys):
    before = _rows(engine)
    assert script.main(["--dry-run"], engine=engine) == 0
    assert _rows(engine) == before
    out = capsys.readouterr().out
    assert "requeue org__proj-1 / verbosity_reduction v4" in out
    assert "keep    org__proj-1 / paraphrase v4" in out and "still missing: 5.4.3" in out
    assert "2 cached variant(s) excluded for identifier retention only; 1 would be requeued" in out
    assert "Dry run: nothing changed." in out


def test_only_the_false_positive_exclusion_loses_its_cache_key(script, engine, capsys):
    before = _rows(engine)
    script.main([], engine=engine)
    after = _rows(engine)

    cached, reason, params = after[("verbosity_reduction", "4")]
    assert cached is False and reason == before[("verbosity_reduction", "4")][1]
    assert json.loads(params)["invalidated"].startswith(script.REQUEUE_NOTE)
    for key in [("paraphrase", "4"), ("paragraph_to_structured", "5"),
                ("neutralize_emotional", "4"), ("verbosity_reduction", "3")]:
        assert after[key] == before[key], key  # untouched, still cached
    assert "1 requeued (false positives), 1 kept excluded." in capsys.readouterr().out


def test_a_requeued_variant_is_regenerated_and_the_others_are_served(script, engine, monkeypatch):
    script.main([], engine=engine)
    calls = []

    def fake_haiku(system_prompt, user_content, api_key, model=None, **_):
        calls.append(system_prompt)
        return HaikuReply(KEEPS_EVERYTHING, "fake")

    monkeypatch.setattr("stableagent.transformations.llm_backed._api.call_haiku", fake_haiku)
    record = IssueRecord(issue_id="i-1", repo_name="org/proj", text=ISSUE_TEXT)
    with sessionmaker(bind=engine)() as db:
        cache = TransformationCache(db)
        regenerated = cache.variant(VerbosityReduction(), record, {})
        assert regenerated.quality_warning is False  # passes under the new rules
        assert cache.variant(Paraphrase(), record, {}).quality_warning is True  # still cached
        assert cache.variant(NeutralizeTransformation(), record, {}).quality_warning is False
    assert len(calls) == 1  # only the requeued variant
