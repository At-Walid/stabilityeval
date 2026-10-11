"""Placeholder integration tests. Replace with real tests as modules are implemented."""

def test_configs_are_valid_json():
    """Verify experiment config files are valid JSON."""
    import json
    import pathlib
    for config_file in pathlib.Path("configs").glob("*.json"):
        with open(config_file) as f:
            data = json.load(f)
        assert "experiment_name" in data
        assert "execution_mode" in data
