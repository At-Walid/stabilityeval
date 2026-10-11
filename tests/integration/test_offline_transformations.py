"""Where variants come from, per execution mode (SPEC sections 11.6 and 12.2).

- mock / dry-run make no API calls: an LLM-backed variant is the cached generated one, else a
  placeholder (generator "placeholder", keyed separately, reused by later offline runs);
- real mode generates it, and NEVER falls back to a placeholder: a missing key or an API failure
  raises a clear TransformationError;
- every stored variant records its generator, transform_version, mode and no-op flag.

No network: anthropic.Anthropic is a fake that answers like Haiku (JSON) or like the agent (diff).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stableagent.config.experiment_schema import (
    AgentConfig,
    ExperimentConfig,
    IssueConfig,
    TransformationConfig,
)
from stableagent.data.models import Base, Experiment, Issue, Run, TransformedIssue
from stableagent.execution.runner import ExperimentRunner
from stableagent.transformations.base import PLACEHOLDER, IssueRecord
from stableagent.transformations.cache import (
    TransformationCache,
    TransformationError,
    cache_key,
    find_cached_variant,
)
from stableagent.transformations.llm_backed._api import TRANSFORMATION_MODEL
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.registry import transformation_registry

ISSUE_ID = "org__proj-7"
TEXT = "Calling parse_config() on an empty file raises KeyError in loader.py."
SINGLE_PARAGRAPH = TEXT  # reordering leaves it unchanged: a no-op
LLM_BACKED = ["paraphrase", "verbosity_reduction", "paragraph_to_structured", "neutralize_emotional"]
DIFF_REPLY = "```diff\n--- a/loader.py\n+++ b/loader.py\n@@ -1 +1 @@\n-a\n+b\n```"
PARAMS = {"typo_injection": {"seed": 1, "error_rate": 0.5}}  # seeded: never accidentally a no-op


@pytest.fixture()
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'variants.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(Issue(id="db-7", external_id=ISSUE_ID, repo_name="org/proj", source="manual",
                     issue_text=TEXT))
        db.commit()
    yield Session
    engine.dispose()


@pytest.fixture()
def llm_calls(monkeypatch):
    """Generating an LLM-backed variant is recorded and fails the run (offline tests)."""
    calls: list[str] = []
    for name in LLM_BACKED:
        def transform(self, issue, params, _name=name):
            calls.append(_name)
            raise AssertionError(f"{_name} was generated")

        monkeypatch.setattr(transformation_registry.get(name), "transform", transform)
    return calls


class FakeAnthropic:
    """anthropic.Anthropic stand-in: Haiku calls get a JSON rewrite, other models a diff."""

    requests: list[dict] = []
    fail_haiku = False

    def __init__(self, **_kwargs):
        self.messages = SimpleNamespace(create=self._create)

    @classmethod
    def _create(cls, **kwargs):
        cls.requests.append(kwargs)
        if kwargs["model"] == TRANSFORMATION_MODEL:
            if cls.fail_haiku:
                raise anthropic.APIConnectionError(request=None)
            content = kwargs["messages"][0]["content"]
            text = json.dumps({"transformed_text": f"Put differently: {content}",
                               "transformation_notes": "fake"})
        else:
            text = DIFF_REPLY
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=10),
            stop_reason="end_turn",
        )


@pytest.fixture()
def fake_api(monkeypatch, no_network):
    FakeAnthropic.requests = []
    FakeAnthropic.fail_haiku = False
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    return FakeAnthropic


@pytest.fixture()
def fixture_dir(tmp_path):
    directory = tmp_path / "fixtures"
    directory.mkdir()
    for variant in ["original", "paraphrase", "verbosity_reduction", "typo_injection",
                    "reordering"]:
        (directory / f"{ISSUE_ID}__{variant}__mock_replay.json").write_text(json.dumps({
            "status": "success",
            "patch": "--- a/loader.py\n+++ b/loader.py\n@@ -1 +1 @@\n-a\n+b\n",
            "cost_usd": 0.0,
            "runtime_seconds": 0.01,
        }), encoding="utf-8")
    return directory


def _config(mode, transformations, fixture_dir=None):
    agent = (
        AgentConfig(name="mock_replay", params={"fixtures_dir": str(fixture_dir)})
        if mode == "mock"
        else AgentConfig(name="llm_baseline")
    )
    return ExperimentConfig(
        experiment_name=f"variants_{mode}",
        execution_mode=mode,
        agents=[agent],
        issues=IssueConfig(issue_ids=[ISSUE_ID]),
        transformations=[
            TransformationConfig(name=t, enabled=True, params=PARAMS.get(t, {}))
            for t in transformations
        ],
        runs_per_variant=1,
        cost_limit_usd=1.0,
    )


def _run(Session, mode, transformations, fixture_dir=None):
    with Session() as db:
        experiment = ExperimentRunner(_config(mode, transformations, fixture_dir), db).run()
        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
        return experiment.status, {r.transformed_issue.transformation_name: r.status for r in runs}


def _variants(Session, name) -> list[TransformedIssue]:
    with Session() as db:
        rows = db.query(TransformedIssue).filter_by(transformation_name=name).all()
        db.expunge_all()
        return rows


def _params(row: TransformedIssue) -> dict:
    return json.loads(row.transformation_params or "{}")


# ── Offline modes ─────────────────────────────────────────────────────────────

def test_mock_mode_stores_a_labelled_placeholder_with_its_provenance(
    Session, fixture_dir, llm_calls, no_network
):
    status, runs = _run(Session, "mock", ["paraphrase", "verbosity_reduction"], fixture_dir)

    assert status == "completed" and set(runs.values()) == {"success"}
    assert llm_calls == []
    for name in ["paraphrase", "verbosity_reduction"]:
        (row,) = _variants(Session, name)
        assert row.transformed_text.startswith(f"[Offline placeholder: the {name} variant")
        assert row.transformed_text.endswith(TEXT)
        assert (row.generator, row.generation_mode, row.transform_version) == (
            PLACEHOLDER, "mock", transformation_registry.get(name).transform_version
        )
        assert row.noop is False
        assert _params(row)["_cache_key"] == cache_key(
            transformation_registry.get(name)(), {}, PLACEHOLDER
        )


def test_placeholders_are_reused_by_later_offline_runs(Session, fixture_dir, llm_calls):
    _run(Session, "mock", ["paraphrase", "typo_injection"], fixture_dir)
    _run(Session, "mock", ["paraphrase", "typo_injection"], fixture_dir)
    assert len(_variants(Session, "paraphrase")) == 1
    assert len(_variants(Session, "typo_injection")) == 1


def test_deterministic_variants_are_computed_in_any_mode_with_provenance(
    Session, fixture_dir, llm_calls
):
    _run(Session, "mock", ["typo_injection", "reordering"], fixture_dir)

    (typo,) = _variants(Session, "typo_injection")
    assert (typo.generator, typo.generation_mode, typo.transform_version) == (
        "deterministic", "mock", "1"
    )
    assert typo.noop is False
    (reordered,) = _variants(Session, "reordering")
    assert reordered.transformed_text == SINGLE_PARAGRAPH  # one paragraph: returned unchanged
    assert reordered.noop is True  # ... so it is flagged, and excluded from SC/TS


def test_dry_run_generates_no_llm_variant(Session, llm_calls, no_network):
    status, runs = _run(Session, "dry_run", ["paraphrase", "reordering"])
    assert status == "completed"
    # The single-paragraph reordering is a no-op variant: recorded, never run.
    assert runs == {"original": "dry_run_skipped", "paraphrase": "dry_run_skipped",
                    "reordering": "skipped_variant"}
    assert llm_calls == []
    (row,) = _variants(Session, "paraphrase")
    assert (row.generator, row.generation_mode) == (PLACEHOLDER, "dry_run")


# ── Real mode: generated, never a placeholder ────────────────────────────────

def test_real_mode_generates_variants_and_records_the_model(Session, fake_api):
    status, runs = _run(Session, "real", ["paraphrase", "typo_injection"])

    assert status == "completed" and set(runs.values()) == {"success"}
    (row,) = _variants(Session, "paraphrase")
    assert row.transformed_text == f"Put differently: {TEXT}"
    assert (row.generator, row.generation_mode, row.transform_version) == (
        TRANSFORMATION_MODEL, "real", Paraphrase.transform_version
    )
    assert [r["model"] for r in fake_api.requests].count(TRANSFORMATION_MODEL) == 1


def test_real_mode_never_uses_a_placeholder_even_when_one_is_cached(
    Session, fixture_dir, fake_api
):
    with Session() as db:  # an offline run left a placeholder behind
        TransformationCache(db).variant(
            Paraphrase(), IssueRecord("db-7", "org/proj", TEXT), {}, mode="mock"
        )
        db.commit()

    _run(Session, "real", ["paraphrase", "typo_injection"])

    rows = {row.generator: row for row in _variants(Session, "paraphrase")}
    assert set(rows) == {PLACEHOLDER, TRANSFORMATION_MODEL}
    with Session() as db:
        run_variant = (
            db.query(TransformedIssue).join(Run, Run.transformed_issue_id == TransformedIssue.id)
            .filter(TransformedIssue.transformation_name == "paraphrase").one()
        )
        assert run_variant.generator == TRANSFORMATION_MODEL
    # The superseded placeholder is invalidated: no lookup can return it any more.
    stale = _params(rows[PLACEHOLDER])
    assert "_cache_key" not in stale and "superseded" in stale["invalidated"]
    with Session() as db:
        assert TransformationCache(db).variant(
            Paraphrase(), IssueRecord("db-7", "org/proj", TEXT), {}, mode="mock"
        ).generator == TRANSFORMATION_MODEL  # offline runs now use the generated one


def test_real_mode_raises_a_clear_error_when_the_api_fails(Session, fake_api):
    fake_api.fail_haiku = True

    with pytest.raises(TransformationError) as error:
        _run(Session, "real", ["paraphrase", "typo_injection"])

    message = str(error.value)
    assert f"Could not generate the paraphrase variant of issue {ISSUE_ID}" in message
    assert TRANSFORMATION_MODEL in message and "APIConnectionError" in message
    assert "never substitutes a placeholder" in message
    assert _variants(Session, "paraphrase") == []  # nothing stored in its place
    with Session() as db:
        assert db.query(Experiment).one().status == "failed"


def test_real_mode_without_a_key_fails_before_running_anything(Session, fake_api, no_api_key):
    with pytest.raises(TransformationError, match="no Anthropic API key") as error:
        _run(Session, "real", ["paraphrase", "verbosity_reduction"])

    assert f"{ISSUE_ID}/paraphrase" in str(error.value)
    assert "Placeholders are only used in mock and dry-run modes" in str(error.value)
    assert fake_api.requests == []
    with Session() as db:
        assert db.query(Experiment).count() == 0 and db.query(TransformedIssue).count() == 0


def test_real_mode_without_a_key_is_fine_when_the_variants_are_cached(
    Session, fake_api, monkeypatch
):
    _run(Session, "real", ["paraphrase", "typo_injection"])  # generates and caches paraphrase
    from stableagent.config import settings as settings_module

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings_module.settings, "ANTHROPIC_API_KEY", None)
    with Session() as db:
        runner = ExperimentRunner(_config("real", ["paraphrase", "typo_injection"]), db)
        runner._check_variants_can_be_generated()  # nothing left to generate: no error


def test_a_variant_cached_by_another_model_is_not_reused(Session, fake_api):
    _run(Session, "real", ["paraphrase", "typo_injection"])

    class OtherModelParaphrase(Paraphrase):
        model = "claude-other-model"

    with Session() as db:
        assert find_cached_variant(db, "db-7", OtherModelParaphrase(), {}) is None
        assert find_cached_variant(db, "db-7", Paraphrase(), {}) is not None
