"""Material written for the paper stays true to the code.

- docs/paper/adapter_listing.py is at most 12 lines, valid Python, and real code: every line
  appears verbatim, in order, in stableagent/agents/base.py (trimmed, never invented), and
  it shows every abstract method of the adapter interface.
- configs/icse_pilot_model2.json is the pilot's design with a second model: same 20 issues, same
  6 transformations with the same params, 1 control repeat, the pilot's variants reused, the
  OpenAI baseline on gpt-4o, a $4 cap.
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from stableagent.agents.base import AbstractAgentAdapter
from stableagent.config.experiment_schema import ExperimentConfig

REPO = Path(__file__).resolve().parents[2]
LISTING = REPO / "docs" / "paper" / "adapter_listing.py"
BASE = REPO / "stableagent" / "agents" / "base.py"
PILOT = "bc6f1372-2088-45dd-907c-d741c0545d27"


def _load(name: str) -> ExperimentConfig:
    return ExperimentConfig.model_validate_json((REPO / "configs" / name).read_text("utf-8"))


def test_the_listing_is_at_most_12_lines_of_valid_python():
    lines = LISTING.read_text(encoding="utf-8").splitlines()
    assert 0 < len(lines) <= 12
    ast.parse("\n".join(lines))


def test_every_listing_line_is_real_code_in_order():
    source = BASE.read_text(encoding="utf-8").splitlines()
    position = 0
    for line in LISTING.read_text(encoding="utf-8").splitlines():
        assert line in source[position:], f"not in base.py (or out of order): {line!r}"
        position = source.index(line, position) + 1


def test_the_listing_shows_every_abstract_method():
    listing = LISTING.read_text(encoding="utf-8")
    for name in AbstractAgentAdapter.__abstractmethods__:
        signature = inspect.signature(getattr(AbstractAgentAdapter, name))
        assert f"def {name}{signature}".replace("'", "") in listing.replace("'", "")


def test_the_model2_config_is_the_pilot_design_with_a_second_model():
    pilot, model2 = _load("icse_pilot.json"), _load("icse_pilot_model2.json")
    assert model2.issues.issue_ids == pilot.issues.issue_ids and len(model2.issues.issue_ids) == 20
    assert [(t.name, t.enabled, t.params) for t in model2.transformations] == [
        (t.name, t.enabled, t.params) for t in pilot.transformations
    ]
    assert len(model2.transformations) == 6
    assert model2.control_repeats == 1 and model2.runs_per_variant == 1
    assert model2.reuse_variants_from == PILOT
    assert model2.cost_limit_usd == pytest.approx(4.0)
    assert model2.execution_mode == "real"
    (agent,) = model2.agents
    assert (agent.params["provider"], agent.params["model"]) == ("openai", "gpt-4o")
    # Same limits as the pilot's Anthropic agent.
    (pilot_agent,) = pilot.agents
    for key in ("temperature", "max_tokens", "timeout_seconds", "cost_cap_usd"):
        assert agent.params[key] == pilot_agent.params[key]
    # Switching model is provider + model only: the key variable follows the provider.
    assert "api_key_env_var" not in agent.params


def test_agent_names_must_be_unique_within_an_experiment():
    raw = json.loads((REPO / "configs" / "icse_pilot_model2.json").read_text("utf-8"))
    raw["agents"] = raw["agents"] * 2
    with pytest.raises(ValueError, match="Agent names must be unique.*llm_baseline"):
        ExperimentConfig.model_validate(raw)
