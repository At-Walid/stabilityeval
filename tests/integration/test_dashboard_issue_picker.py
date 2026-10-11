"""Dashboard issue picker, end to end, offline.

The page runs under Streamlit's AppTest against a temporary database and a temporary fixture
directory, with network access blocked and the LLM-backed transformations rigged to fail if they are
ever generated. Also checks that the gold patch never reaches the agent and that the API key is
never stored or logged on either dashboard path.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest
import streamlit as st
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

import stableagent
from stableagent.agents.mock_replay import MockReplayAdapter
from stableagent.config.settings import settings
from stableagent.dashboard import _db, _runner
from stableagent.data import database
from stableagent.data.loaders.swebench import load_bundle
from stableagent.data.models import Base, Experiment, Issue, Run, TransformedIssue
from stableagent.transformations.llm_backed._api import TRANSFORMATION_MODEL
from stableagent.transformations.llm_backed.paraphrase import Paraphrase
from stableagent.transformations.registry import transformation_registry

PAGE = str(Path(stableagent.__file__).parent / "dashboard" / "StableAgent.py")
REAL_FIXTURES = Path(stableagent.__file__).parent / "fixtures" / "mock_responses"
FULL = "astropy__astropy-6938"  # all 7 variants recorded
PARTIAL = "django__django-11099"  # original, paraphrase and verbosity_reduction only
NOT_RECORDED = "psf__requests-2317"
ALL_VARIANTS = [
    "original", "paraphrase", "verbosity_reduction", "typo_injection", "reordering",
    "paragraph_to_structured", "neutralize_emotional",
]
LLM_BACKED = ["paraphrase", "verbosity_reduction", "paragraph_to_structured", "neutralize_emotional"]
REAL_AGENT = "LLM Baseline (Claude Sonnet 4.6)"
OPENAI_AGENT = "LLM Baseline (GPT-4o)"
SENTINEL_KEY = "anthropic-key-SENTINEL-never-store-me-0123456789"
DIFF = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a\n+b\n"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """A temporary database behind every dashboard module, with empty Streamlit caches."""
    eng = database.build_engine(f"sqlite:///{tmp_path / 'dashboard.db'}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(database, "_engine", eng)
    monkeypatch.setattr(_db, "build_engine", lambda *a, **k: eng)
    monkeypatch.setattr(_runner, "build_engine", lambda *a, **k: eng)
    st.cache_data.clear()
    yield eng
    st.cache_data.clear()
    eng.dispose()


@pytest.fixture()
def fixtures(tmp_path, monkeypatch):
    """MockReplay fixtures: every variant for FULL, three for PARTIAL, none for the others."""
    directory = tmp_path / "fixtures"
    directory.mkdir()
    for issue_id, variants in [(FULL, ALL_VARIANTS), (PARTIAL, ALL_VARIANTS[:3])]:
        for variant in variants:
            name = f"{issue_id}__{variant}__mock_replay.json"
            shutil.copy(REAL_FIXTURES / name, directory / name)
    monkeypatch.setattr(settings, "FIXTURES_DIR", str(directory))
    return directory


@pytest.fixture()
def llm_calls(monkeypatch):
    calls: list[str] = []
    for name in LLM_BACKED:
        def transform(self, issue, params, _name=name):
            calls.append(_name)
            raise AssertionError(f"{_name} was generated")

        monkeypatch.setattr(transformation_registry.get(name), "transform", transform)
    return calls


@pytest.fixture()
def offline(engine, fixtures, llm_calls, no_network):
    """Everything an offline dashboard session needs."""
    return llm_calls


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: records each request, never touches the network.

    Haiku (the transformation model) gets a JSON rewrite that keeps every token; the agent gets a
    fenced diff. With ``fail_first_agent_call`` the first agent call raises an error quoting the
    key, as a worst case for redaction.
    """

    def __init__(self, fail_first_agent_call: bool = False):
        self.requests: list[dict] = []
        self.keys: list[str] = []
        self._fail_first_agent_call = fail_first_agent_call

    @property
    def agent_requests(self) -> list[dict]:
        return [r for r in self.requests if r["model"] != TRANSFORMATION_MODEL]

    @property
    def transformation_requests(self) -> list[dict]:
        return [r for r in self.requests if r["model"] == TRANSFORMATION_MODEL]

    def Anthropic(self, api_key=None, **_kwargs):  # noqa: N802 - mirrors anthropic.Anthropic
        self.keys.append(api_key)

        def create(**kwargs):
            self.requests.append(kwargs)
            if kwargs["model"] == TRANSFORMATION_MODEL:
                text = json.dumps({
                    "transformed_text": f"Put differently: {kwargs['messages'][0]['content']}",
                    "transformation_notes": "fake",
                })
            else:
                if self._fail_first_agent_call and len(self.agent_requests) == 1:
                    raise RuntimeError(f"401 authentication_error: invalid x-api-key {api_key}")
                text = f"```diff\n{DIFF}```"
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                stop_reason="end_turn",
            )

        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def install(self, monkeypatch) -> FakeAnthropic:
        monkeypatch.setattr(anthropic, "Anthropic", self.Anthropic)
        return self


def _gold_patch(issue_id: str) -> str:
    (instance,) = load_bundle([issue_id])
    return instance.gold_patch


def _import_bundle(engine) -> None:
    from stableagent.data.loaders.swebench import import_bundle

    with sessionmaker(bind=engine)() as db:
        import_bundle(db)
        db.commit()


def _bytes_on_disk(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


# ── AppTest helpers ───────────────────────────────────────────────────────────

def _app() -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _rerun(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _counter(at: AppTest) -> str:
    return next(c.value for c in at.caption if "loaded," in c.value)


def _run_button(at: AppTest):
    return next(b for b in at.button if "Run Experiment" in b.label)


def _warnings(at: AppTest) -> str:
    return "\n".join(w.value for w in at.warning)


def _load_bundle_through_the_page() -> AppTest:
    at = _app()
    at.button(key="load_bundle_button").click()
    return _rerun(at)


# ── The page, offline ─────────────────────────────────────────────────────────

def test_loading_the_bundle_works_offline_and_only_once(offline):
    at = _app()
    assert "0 of the 300 bundled SWE-bench Lite issues are loaded" in at.info[0].value
    assert _run_button(at).disabled

    at.button(key="load_bundle_button").click()
    _rerun(at)

    assert "Loaded 300 new SWE-bench Lite issue(s)" in at.success[0].value
    assert not [b for b in at.button if b.key == "load_bundle_button"]  # nothing left to load
    assert _counter(at) == "300 loaded, 2 replayable · 2 shown"


def test_mock_mode_shows_only_replayable_issues_and_runs_without_any_api_call(offline):
    at = _load_bundle_through_the_page()

    assert at.toggle(key="only_replayable").value is True  # default ON with MockReplay
    picker = at.multiselect(key="issue_selector")
    assert picker.value == [FULL]  # the first replayable issue is preselected
    assert all("✓ replayable" in label for label in picker.options)
    assert not _run_button(at).disabled

    _run_button(at).click()
    _rerun(at)

    assert "Experiment complete" in at.success[0].value
    assert offline == []  # no LLM-backed variant was generated
    with sessionmaker(bind=database._engine)() as db:
        (experiment,) = db.query(Experiment).all()
        statuses = {run.status for run in db.query(Run).filter_by(experiment_id=experiment.id)}
    assert experiment.status == "completed"
    assert "error" not in statuses
    # The Transformed Issues tab says what produced the text: here an offline placeholder.
    captions = [c.value for c in at.caption]
    assert (
        f"Generator: placeholder · transform_version {Paraphrase.transform_version} · "
        "produced in mock mode"
    ) in captions
    assert any(w.value.startswith("Placeholder: this variant was not generated")
               for w in at.warning)
    # RQ2 shows the symmetric flip rate next to the drop rate TS.
    rq2 = next(df.value for df in at.dataframe if "Sensitivity (G)" in df.value.columns)
    assert list(rq2.columns) == ["Transformation", "Sensitivity (G)", "Flip rate", "Interpretation"]


def test_a_custom_issue_is_ad_hoc_and_never_joins_the_dataset_picker(
    engine, monkeypatch, no_network
):
    _import_bundle(engine)
    FakeAnthropic().install(monkeypatch)
    custom = {"issue_id": FULL, "issue_text": "My own words about a bug in parse().",
              "repo_name": "me/mine", "custom": True}  # same label as a dataset issue

    experiment_id = _runner.run_real_experiment([custom], ["reordering", "typo_injection"],
                                                "custom", "k")

    with sessionmaker(bind=engine)() as db:
        rows = {issue.source: issue for issue in db.query(Issue).filter_by(external_id=FULL)}
        assert set(rows) == {"swebench_lite", "custom_adhoc"}
        assert rows["swebench_lite"].issue_text == load_bundle([FULL])[0].problem_statement
        texts = {
            run.transformed_issue.issue.issue_text
            for run in db.query(Run).filter_by(experiment_id=experiment_id)
        }
    assert texts == {custom["issue_text"]}  # the run used the custom text, not the dataset's
    st.cache_data.clear()
    listed = _db.load_issues()
    assert len(listed) == 300 and "custom_adhoc" not in set(listed["source"])


def test_badges_and_counter_follow_the_enabled_transformations(offline):
    at = _load_bundle_through_the_page()
    assert _counter(at) == "300 loaded, 2 replayable · 2 shown"

    at.checkbox(key="transform_ck_typo_injection").check()
    _rerun(at)  # PARTIAL has no typo_injection fixture

    assert _counter(at) == "300 loaded, 1 replayable · 1 shown"
    at.toggle(key="only_replayable").set_value(False)
    _rerun(at)
    labels = {label.split(" · ")[0]: label for label in at.multiselect(key="issue_selector").options}
    assert len(labels) == 300
    assert "✓ replayable" in labels[FULL]
    # No real run recorded: the expected cost at Sonnet 4.6 prices, $0.0096 a run.
    assert "real mode only (~$0.01 per variant)" in labels[PARTIAL]
    assert "real mode only (~$0.01 per variant)" in labels[NOT_RECORDED]


def test_filters_combine(offline):
    at = _load_bundle_through_the_page()
    at.toggle(key="only_replayable").set_value(False)
    _rerun(at)
    assert _counter(at) == "300 loaded, 2 replayable"

    at.selectbox(key="repo_filter").select("psf/requests")
    _rerun(at)
    assert _counter(at) == "300 loaded, 2 replayable · 6 shown"

    at.text_input(key="issue_keyword").input("PROXY")
    _rerun(at)
    shown = [label.split(" · ")[0] for label in at.multiselect(key="issue_selector").options]
    texts = {i.instance_id: i.problem_statement for i in load_bundle()}
    expected = sorted(
        i for i, text in texts.items() if i.startswith("psf__") and "proxy" in text.lower()
    )
    assert sorted(set(shown) - {FULL}) == expected  # FULL stays: it is still selected
    assert _counter(at) == f"300 loaded, 2 replayable · {len(expected)} shown"

    at.toggle(key="only_replayable").set_value(True)
    _rerun(at)
    assert _counter(at) == "300 loaded, 2 replayable · 0 shown"
    assert "No issues match the filters." in [i.value for i in at.info]


def test_mock_run_is_blocked_for_a_non_replayable_issue_and_says_why(offline):
    at = _load_bundle_through_the_page()
    at.toggle(key="only_replayable").set_value(False)
    _rerun(at)
    at.multiselect(key="issue_selector").select(NOT_RECORDED)
    _rerun(at)

    assert _run_button(at).disabled
    assert f"{NOT_RECORDED} (missing: original, paraphrase, verbosity_reduction)" in _warnings(at)
    assert "switch to LLM Baseline" in _warnings(at)
    assert not at.error  # explained up front, never a raw fixture-not-found error


def test_real_mode_previews_the_cost_and_blocks_runs_over_the_limit(offline, monkeypatch, no_api_key):
    at = _load_bundle_through_the_page()
    at.radio(key="agent_radio").set_value(REAL_AGENT)
    _rerun(at)

    assert at.toggle(key="only_replayable").value is False  # default OFF with LLM Baseline
    assert _counter(at) == "300 loaded, 2 replayable"
    preview = next(m.value for m in at.markdown if "Estimated cost" in m.value)
    # 1 issue x (original + 2 variants) at the expected cost of a Sonnet 4.6 run (no real run
    # recorded yet). "$" is escaped: two of them would render as LaTeX.
    assert r"\$0.03 = 3 run(s) × \$0.0096 per run" in preview
    assert "Enter an Anthropic API key" in _warnings(at)
    assert _run_button(at).disabled

    monkeypatch.setattr(settings, "DEFAULT_TOTAL_COST_LIMIT_USD", 0.02)
    at.text_input(key="api_key_input").input(SENTINEL_KEY)
    _rerun(at)
    assert r"Estimated cost \$0.03 exceeds the configured limit of \$0.02" in _warnings(at)
    assert _run_button(at).disabled


def test_real_mode_uses_the_environment_key_when_the_field_is_empty(offline):
    at = _load_bundle_through_the_page()  # the suite runs with a dummy ANTHROPIC_API_KEY
    at.radio(key="agent_radio").set_value(REAL_AGENT)
    _rerun(at)
    assert "Enter an Anthropic API key" not in _warnings(at)
    assert any("ANTHROPIC_API_KEY environment variable" in c.value for c in at.caption)
    assert at.session_state["api_key_input"] == ""  # the key is never copied into the page


def test_real_run_from_the_page_keeps_the_key_in_session_state_only(
    engine, fixtures, no_network, monkeypatch, tmp_path, caplog, capsys, no_api_key
):
    fake = FakeAnthropic().install(monkeypatch)
    caplog.set_level(logging.DEBUG)
    at = _load_bundle_through_the_page()
    at.radio(key="agent_radio").set_value(REAL_AGENT)
    _rerun(at)
    at.text_input(key="api_key_input").input(SENTINEL_KEY)
    _rerun(at)
    assert not _run_button(at).disabled

    _run_button(at).click()
    _rerun(at)

    assert "Experiment complete" in at.success[0].value
    # The agent and both LLM-backed variants (paraphrase, verbosity_reduction) used the key...
    assert set(fake.keys) == {SENTINEL_KEY}
    assert len(fake.agent_requests) == 3 and len(fake.transformation_requests) == 2
    assert at.session_state["api_key_input"] == SENTINEL_KEY  # ...kept in session state...
    assert os.environ.get("ANTHROPIC_API_KEY") is None  # ...never put in the environment...
    database._engine.dispose()
    assert SENTINEL_KEY.encode() not in _bytes_on_disk(tmp_path)  # ...nor stored
    assert SENTINEL_KEY not in caplog.text
    captured = capsys.readouterr()
    assert SENTINEL_KEY not in captured.out + captured.err
    gold = _gold_patch(FULL)
    sent = json.dumps(fake.requests)
    assert gold not in sent and "diff --git" not in sent


def test_real_run_from_the_page_reports_a_failed_variant_and_uses_no_placeholder(
    engine, fixtures, no_network, monkeypatch
):
    fake = FakeAnthropic().install(monkeypatch)
    real_create_client = fake.Anthropic

    def failing_haiku_client(api_key=None, **kwargs):
        client = real_create_client(api_key=api_key, **kwargs)
        create = client.messages.create

        def maybe_fail(**request):
            if request["model"] == TRANSFORMATION_MODEL:
                raise anthropic.APIConnectionError(request=None)
            return create(**request)

        client.messages.create = maybe_fail
        return client

    monkeypatch.setattr(anthropic, "Anthropic", failing_haiku_client)
    at = _load_bundle_through_the_page()
    at.radio(key="agent_radio").set_value(REAL_AGENT)
    _rerun(at)
    at.text_input(key="api_key_input").input(SENTINEL_KEY)
    _rerun(at)

    _run_button(at).click()
    _rerun(at)

    errors = "\n".join(e.value for e in at.error)
    assert "Could not generate the paraphrase variant of issue " + FULL in errors
    assert "never substitutes a placeholder" in errors
    assert not at.success
    with sessionmaker(bind=database._engine)() as db:
        generators = {ti.generator for ti in db.query(TransformedIssue)}
        assert "placeholder" not in generators
        assert db.query(Experiment).one().status == "failed"


# ── Two LLM Baselines: Claude Sonnet 4.6 and GPT-4o ───────────────────────────


def _info(at: AppTest) -> str:
    return "\n".join(i.value for i in at.info)


def test_the_agent_list_shows_each_model_as_an_agent_with_its_model_id(offline):
    at = _load_bundle_through_the_page()
    radio = at.radio(key="agent_radio")
    assert radio.options == ["MockReplay (free, instant)", REAL_AGENT, OPENAI_AGENT]

    radio.set_value(REAL_AGENT)
    _rerun(at)
    assert "**Model:** claude-sonnet-4-6 (provider anthropic)" in _info(at)

    at.radio(key="agent_radio").set_value(OPENAI_AGENT)
    _rerun(at)
    info = _info(at)
    assert "**Agent:** LLM Baseline (GPT-4o)" in info
    assert "**Model:** gpt-4o (provider openai)" in info
    assert "**API key:** OPENAI_API_KEY from .env — set" in info  # the suite's dummy key
    # No GPT-4o run recorded yet: its expected cost at gpt-4o prices ($0.0072 a run).
    assert r"~\$0.0072 per variant" in info


def test_gpt4o_is_blocked_without_the_openai_key_and_never_asks_for_it(offline, no_openai_key):
    at = _load_bundle_through_the_page()
    at.radio(key="agent_radio").set_value(OPENAI_AGENT)
    _rerun(at)

    assert "Set OPENAI_API_KEY in .env to run LLM Baseline (GPT-4o)" in _warnings(at)
    assert "Enter an Anthropic API key" not in _warnings(at)
    assert "**API key:** OPENAI_API_KEY from .env — **not set**" in _info(at)
    assert _run_button(at).disabled
    labels = [t.label for t in at.text_input]
    assert not any("OpenAI" in label for label in labels)  # only the Anthropic field exists


def test_a_gpt4o_run_from_the_page_calls_openai_with_the_forced_tool(
    engine, fixtures, no_network, monkeypatch
):
    from tests.llm_fakes import FakeOpenAI

    haiku = FakeAnthropic().install(monkeypatch)  # generates the two LLM-backed variants
    gpt = FakeOpenAI().install(monkeypatch)
    at = _load_bundle_through_the_page()
    at.radio(key="agent_radio").set_value(OPENAI_AGENT)
    _rerun(at)
    assert not _run_button(at).disabled

    _run_button(at).click()
    _rerun(at)

    assert "Experiment complete" in at.success[0].value
    assert len(gpt.requests) == 3 and haiku.agent_requests == []  # original + 2 variants
    assert {r["model"] for r in gpt.requests} == {"gpt-4o"}
    assert all(r["tool_choice"]["function"]["name"] == "submit_patch" for r in gpt.requests)
    gold = _gold_patch(FULL)
    assert gold not in json.dumps(gpt.requests)
    with sessionmaker(bind=database._engine)() as db:
        experiment = db.query(Experiment).one()
        params = json.loads(experiment.config)["agents"][0]["params"]
        runs = db.query(Run).filter_by(experiment_id=experiment.id).all()
    assert (params["provider"], params["model"]) == ("openai", "gpt-4o")
    assert {json.loads(run.metadata_)["model"] for run in runs} == {"gpt-4o"}
    assert all(run.cost_usd == pytest.approx((1000 * 2.5 + 200 * 10.0) / 1e6) for run in runs)
    assert "Results — LLM Baseline (gpt-4o)" in "\n".join(h.value for h in at.header)


# ── The run functions directly ────────────────────────────────────────────────

def test_mock_run_refuses_non_replayable_issues_before_creating_anything(engine, fixtures):
    _import_bundle(engine)
    issue = {"issue_id": NOT_RECORDED, "issue_text": "t", "repo_name": "psf/requests"}

    with pytest.raises(_runner.NotReplayableError, match="Nothing was run") as error:
        _runner.run_mock_experiment([issue], ["paraphrase", "reordering"], "refused")

    assert f"{NOT_RECORDED} (missing: original, paraphrase, reordering)" in str(error.value)
    with sessionmaker(bind=engine)() as db:
        assert db.query(Experiment).count() == 0


def test_gold_patch_never_reaches_the_mock_agent(engine, fixtures, offline, monkeypatch):
    _import_bundle(engine)
    seen = []
    original_run = MockReplayAdapter.run

    def spy(self, agent_input, mode):
        seen.append(agent_input)
        return original_run(self, agent_input, mode)

    monkeypatch.setattr(MockReplayAdapter, "run", spy)
    with sessionmaker(bind=engine)() as db:
        issue = db.query(Issue).filter_by(external_id=FULL).one()
        payload = {"issue_id": FULL, "issue_text": issue.issue_text, "repo_name": issue.repo_name}

    _runner.run_mock_experiment([payload], ["paraphrase", "reordering"], "gold_check")

    gold = _gold_patch(FULL)
    assert len(seen) == 3
    for agent_input in seen:
        assert "diff --git" not in agent_input.issue_text
        assert gold not in json.dumps(
            [agent_input.issue_text, agent_input.repo_name, agent_input.metadata]
        )


def test_gold_patch_never_reaches_the_real_agent_or_the_transformation_model(
    engine, monkeypatch, no_network
):
    _import_bundle(engine)
    fake = FakeAnthropic().install(monkeypatch)
    with sessionmaker(bind=engine)() as db:
        issue = db.query(Issue).filter_by(external_id=NOT_RECORDED).one()
        payload = {"issue_id": NOT_RECORDED, "issue_text": issue.issue_text,
                   "repo_name": issue.repo_name}

    _runner.run_real_experiment([payload], ["paraphrase", "reordering"], "gold_check", "k")

    assert len(fake.agent_requests) == 3 and len(fake.transformation_requests) == 1
    sent = json.dumps(fake.requests)
    assert _gold_patch(NOT_RECORDED) not in sent and "diff --git" not in sent
    # The dashboard's real path is the CLI's: the adapter's prompt and the pilot's parameters.
    from stableagent.agents.llm_baseline import SYSTEM_PROMPT

    assert {r["system"] for r in fake.agent_requests} == {SYSTEM_PROMPT}
    assert {r["max_tokens"] for r in fake.agent_requests} == {4096}


def test_api_key_never_reaches_disk_database_or_logs_even_in_errors(
    engine, monkeypatch, tmp_path, caplog, capsys, no_network, no_api_key
):
    caplog.set_level(logging.DEBUG)
    fake = FakeAnthropic(fail_first_agent_call=True).install(monkeypatch)  # quotes the key
    issue = {"issue_id": "custom-key-check", "issue_text": "Bug in parse()", "repo_name": "o/r",
             "custom": True}

    experiment_id = _runner.run_real_experiment(
        [issue], ["paraphrase", "reordering"], "key_check", SENTINEL_KEY
    )

    assert set(fake.keys) == {SENTINEL_KEY}
    with sessionmaker(bind=engine)() as db:
        runs = db.query(Run).filter_by(experiment_id=experiment_id).all()
        errors = [run.error_message for run in runs if run.status == "error"]
        (custom,) = db.query(Issue).filter_by(external_id="custom-key-check").all()
        assert custom.source == "custom_adhoc"
    assert errors == ["401 authentication_error: invalid x-api-key [REDACTED]"]
    engine.dispose()
    assert SENTINEL_KEY.encode() not in _bytes_on_disk(tmp_path)
    assert SENTINEL_KEY not in caplog.text
    captured = capsys.readouterr()
    assert SENTINEL_KEY not in captured.out + captured.err
    assert os.environ.get("ANTHROPIC_API_KEY") is None
