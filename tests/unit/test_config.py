"""Unit tests for Settings and experiment configuration schema parsing."""
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from stability_eval.config.experiment_schema import (
    ExperimentConfig,
    IssueConfig,
)
from stability_eval.config.settings import Settings, get_anthropic_api_key

CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"

# Fake key used to check masking; it must never show up in any rendered output.
_SECRET = "sk-ant-THIS-VALUE-MUST-NOT-LEAK-0123456789"


def load_config(filename: str) -> ExperimentConfig:
    path = CONFIGS_DIR / filename
    return ExperimentConfig.model_validate_json(path.read_text())


# ---------------------------------------------------------------------------
# Settings
#
# Settings(_env_file=None) keeps a developer's .env (and its real key) out of these tests.
# ---------------------------------------------------------------------------

class TestSettings:
    def test_defaults(self, no_api_key):
        s = Settings(_env_file=None)
        assert "sqlite" in s.DATABASE_URL
        assert s.ANTHROPIC_API_KEY is None
        assert s.DEFAULT_COST_CAP_USD == pytest.approx(0.50)
        assert s.DEFAULT_TIMEOUT_SECONDS == 120
        assert s.DEFAULT_TOTAL_COST_LIMIT_USD == pytest.approx(20.0)

    def test_api_key_optional_no_error_when_absent(self, no_api_key):
        s = Settings(_env_file=None)
        assert s.ANTHROPIC_API_KEY is None
        assert get_anthropic_api_key() is None

    def test_api_key_accepts_string(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        s = Settings(_env_file=None)
        assert isinstance(s.ANTHROPIC_API_KEY, SecretStr)
        assert s.ANTHROPIC_API_KEY.get_secret_value() == "sk-test-key"

    def test_api_key_is_masked_in_every_rendering(self):
        s = Settings(_env_file=None, ANTHROPIC_API_KEY=_SECRET)
        renderings = [
            repr(s),
            str(s),
            s.model_dump_json(),
            repr(s.model_dump()),
            repr(s.ANTHROPIC_API_KEY),
            str(s.ANTHROPIC_API_KEY),
            f"{s.ANTHROPIC_API_KEY}",
        ]
        assert not any("MUST-NOT-LEAK" in text for text in renderings)

    def test_failed_assertion_about_the_key_does_not_print_it(self):
        # The original leak: `assert s.ANTHROPIC_API_KEY is None` failing printed the key.
        s = Settings(_env_file=None, ANTHROPIC_API_KEY=_SECRET)
        with pytest.raises(AssertionError) as excinfo:
            assert s.ANTHROPIC_API_KEY is None
        assert "MUST-NOT-LEAK" not in str(excinfo.value)
        assert "**********" in str(excinfo.value)

    def test_accessor_returns_plain_text_for_the_sdk(self, monkeypatch):
        monkeypatch.setattr("stability_eval.config.settings.settings.ANTHROPIC_API_KEY", None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-from-env")
        assert get_anthropic_api_key() == "sk-test-from-env"
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        monkeypatch.setattr(
            "stability_eval.config.settings.settings.ANTHROPIC_API_KEY", SecretStr("sk-test-stored")
        )
        assert get_anthropic_api_key() == "sk-test-stored"

    def test_the_suite_only_ever_sees_the_dummy_key(self, dummy_api_key):
        # Compare to a bool first so a failure can never print the key being compared.
        from stability_eval.config.settings import settings

        accessor_is_dummy = get_anthropic_api_key() == dummy_api_key
        stored_is_dummy = settings.ANTHROPIC_API_KEY.get_secret_value() == dummy_api_key
        assert accessor_is_dummy, "a non-dummy ANTHROPIC_API_KEY reached the test suite"
        assert stored_is_dummy, "settings holds a non-dummy ANTHROPIC_API_KEY during tests"


# ---------------------------------------------------------------------------
# ICSE config files parse correctly
# ---------------------------------------------------------------------------

class TestIcseConfigs:
    def test_icse_pilot_parses(self):
        config = load_config("icse_pilot.json")
        assert config.experiment_name == "icse_pilot_v1"
        assert config.execution_mode == "real"

    def test_icse_demo_parses(self):
        config = load_config("icse_demo.json")
        assert config.experiment_name == "icse_demo"
        assert config.execution_mode == "mock"

    def test_pilot_has_one_agent(self):
        config = load_config("icse_pilot.json")
        assert len(config.agents) == 1
        assert config.agents[0].name == "llm_baseline"

    def test_demo_uses_mock_replay(self):
        config = load_config("icse_demo.json")
        assert config.agents[0].name == "mock_replay"

    def test_pilot_has_six_transformations(self):
        config = load_config("icse_pilot.json")
        assert len(config.transformations) == 6
        assert all(t.enabled for t in config.transformations)

    def test_demo_has_six_transformations(self):
        # icse_demo.json exercises all 6 ICSE-pilot transformations (SPEC section 5.3)
        # against the 5 pre-loaded SWE-bench sample issues.
        config = load_config("icse_demo.json")
        assert len(config.transformations) == 6
        assert all(t.enabled for t in config.transformations)

    def test_transformation_names_match_spec(self):
        expected = {
            "paraphrase", "verbosity_reduction", "typo_injection", "reordering",
            "paragraph_to_structured", "neutralize_emotional",
        }
        config = load_config("icse_pilot.json")
        assert {t.name for t in config.transformations} == expected

    def test_pilot_cost_limit(self):
        config = load_config("icse_pilot.json")
        assert config.cost_limit_usd == pytest.approx(5.0)

    def test_demo_cost_limit_nonzero(self):
        # Must be > 0: CostGuard.check_run allows a run only while
        # current_total < total_limit, so a 0.0 limit blocks every run from the
        # start (even though mock-mode fixtures always report cost_usd == 0.0).
        config = load_config("icse_demo.json")
        assert config.cost_limit_usd > 0.0

    def test_issue_source_is_swebench_lite(self):
        for fname in ("icse_pilot.json", "icse_demo.json"):
            config = load_config(fname)
            assert config.issues.source == "swebench_lite"

    def test_pilot_agent_params_have_model(self):
        config = load_config("icse_pilot.json")
        assert config.agents[0].params["model"] == "claude-sonnet-4-6"

    def test_pilot_limits_match_the_adapter_defaults(self):
        from stability_eval.agents.llm_baseline import LLMBaselineAdapter

        params = load_config("icse_pilot.json").agents[0].params
        # The forced submit_patch tool call returns only the diff: 4096 tokens suffice.
        assert params["max_tokens"] == LLMBaselineAdapter.DEFAULT_MAX_TOKENS == 4096
        assert params["timeout_seconds"] == Settings(_env_file=None).DEFAULT_TIMEOUT_SECONDS == 120

    def test_verbosity_reduction_has_target_ratio(self):
        config = load_config("icse_pilot.json")
        vr = next(t for t in config.transformations if t.name == "verbosity_reduction")
        assert vr.params["target_ratio"] == pytest.approx(0.5)

    def test_typo_injection_has_error_rate(self):
        config = load_config("icse_pilot.json")
        ti = next(t for t in config.transformations if t.name == "typo_injection")
        assert ti.params["error_rate"] == pytest.approx(0.02)

    def test_demo_fixtures_dir_in_agent_params(self):
        config = load_config("icse_demo.json")
        assert "fixtures_dir" in config.agents[0].params


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_invalid_execution_mode_raises(self):
        with pytest.raises(ValidationError):
            ExperimentConfig.model_validate({
                "experiment_name": "test",
                "execution_mode": "invalid_mode",
                "agents": [{"name": "mock_replay"}],
                "issues": {"source": "swebench_lite"},
                "transformations": [],
            })

    def test_invalid_issue_source_raises(self):
        with pytest.raises(ValidationError):
            ExperimentConfig.model_validate({
                "experiment_name": "test",
                "execution_mode": "mock",
                "agents": [{"name": "mock_replay"}],
                "issues": {"source": "invalid_source"},
                "transformations": [],
            })

    def test_minimal_valid_config(self):
        config = ExperimentConfig.model_validate({
            "experiment_name": "minimal",
            "agents": [{"name": "mock_replay"}],
            "issues": {},
            "transformations": [],
        })
        assert config.execution_mode == "mock"
        assert config.runs_per_variant == 1
        assert config.issues.source == "swebench_lite"

    def test_issue_config_defaults(self):
        ic = IssueConfig()
        assert ic.source == "swebench_lite"
        assert ic.issue_ids == []
