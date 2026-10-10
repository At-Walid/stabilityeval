"""Unit tests for pure helpers in stability_eval.dashboard._results.

The dashboard package otherwise has no test coverage (it's exercised via
manual/browser verification), but _agent_display_name is a pure function
with no Streamlit/DB dependency, so it's cheap and worth locking down: it's
what normalizes both CLI-style ("mock_replay"/"llm_baseline") and
dashboard-style ("MockReplay"/"LLM Baseline") agent names into one
consistent display string for the results header.
"""
from __future__ import annotations

from stability_eval.dashboard._results import _agent_display_name


def test_agent_display_name_normalizes_registry_style_mock():
    assert _agent_display_name("mock_replay") == "MockReplay"


def test_agent_display_name_normalizes_dashboard_style_mock():
    assert _agent_display_name("MockReplay") == "MockReplay"


def test_agent_display_name_normalizes_registry_style_llm_baseline():
    assert _agent_display_name("llm_baseline") == "LLM Baseline"


def test_agent_display_name_normalizes_dashboard_style_llm_baseline():
    assert _agent_display_name("LLM Baseline") == "LLM Baseline"


def test_agent_display_name_defaults_to_llm_baseline_for_empty_or_unknown():
    assert _agent_display_name("") == "LLM Baseline"
    assert _agent_display_name(None) == "LLM Baseline"
    assert _agent_display_name("some_other_agent") == "LLM Baseline"
