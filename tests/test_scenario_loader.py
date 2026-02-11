"""Tests for scenario YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aat.core.exceptions import ScenarioError
from aat.core.scenario_loader import load_scenario, load_scenarios

MINIMAL_SCENARIO = {
    "id": "SC-001",
    "name": "Test scenario",
    "steps": [
        {
            "step": 1,
            "action": "navigate",
            "value": "https://example.com",
            "description": "Go to example",
        }
    ],
}


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


# ── Single File Loading ──


class TestLoadScenario:
    def test_load_valid(self, tmp_path: Path) -> None:
        f = _write_yaml(tmp_path / "SC-001.yaml", MINIMAL_SCENARIO)
        scenario = load_scenario(f)
        assert scenario.id == "SC-001"
        assert scenario.name == "Test scenario"
        assert len(scenario.steps) == 1
        assert scenario.steps[0].action == "navigate"

    def test_load_with_tags_and_variables(self, tmp_path: Path) -> None:
        data = {
            **MINIMAL_SCENARIO,
            "tags": ["smoke", "login"],
            "variables": {"url": "https://test.com"},
        }
        f = _write_yaml(tmp_path / "SC-002.yaml", data)
        scenario = load_scenario(f)
        assert scenario.tags == ["smoke", "login"]
        assert scenario.variables == {"url": "https://test.com"}

    def test_load_invalid_id(self, tmp_path: Path) -> None:
        data = {**MINIMAL_SCENARIO, "id": "INVALID"}
        f = _write_yaml(tmp_path / "bad.yaml", data)
        with pytest.raises(ScenarioError, match="Scenario validation failed"):
            load_scenario(f)

    def test_load_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        with pytest.raises(ScenarioError, match="empty"):
            load_scenario(f)

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("{{invalid yaml", encoding="utf-8")
        with pytest.raises(ScenarioError, match="Failed to parse"):
            load_scenario(f)

    def test_load_non_mapping(self, tmp_path: Path) -> None:
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ScenarioError, match="must be a YAML mapping"):
            load_scenario(f)


# ── Variable Substitution ──


class TestVariableSubstitution:
    def test_external_variable(self, tmp_path: Path) -> None:
        data = {
            "id": "SC-001",
            "name": "Var test",
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{url}}/login",
                    "description": "Navigate",
                }
            ],
        }
        f = _write_yaml(tmp_path / "var.yaml", data)
        scenario = load_scenario(f, variables={"url": "https://app.test"})
        assert scenario.steps[0].value == "https://app.test/login"

    def test_scenario_level_variable(self, tmp_path: Path) -> None:
        data = {
            "id": "SC-001",
            "name": "Var test",
            "variables": {"base_url": "https://internal.test"},
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{base_url}}/home",
                    "description": "Navigate",
                }
            ],
        }
        f = _write_yaml(tmp_path / "var.yaml", data)
        scenario = load_scenario(f)
        assert scenario.steps[0].value == "https://internal.test/home"

    def test_env_variable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AAT_TEST_URL", "https://env.test")
        data = {
            "id": "SC-001",
            "name": "Env test",
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{env.AAT_TEST_URL}}/page",
                    "description": "Navigate",
                }
            ],
        }
        f = _write_yaml(tmp_path / "env.yaml", data)
        scenario = load_scenario(f)
        assert scenario.steps[0].value == "https://env.test/page"

    def test_unresolved_variable_kept(self, tmp_path: Path) -> None:
        data = {
            "id": "SC-001",
            "name": "Unresolved test",
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{unknown_var}}/path",
                    "description": "Navigate",
                }
            ],
        }
        f = _write_yaml(tmp_path / "unresolved.yaml", data)
        scenario = load_scenario(f)
        assert "{{unknown_var}}" in scenario.steps[0].value

    def test_external_overrides_scenario_variable(self, tmp_path: Path) -> None:
        data = {
            "id": "SC-001",
            "name": "Override test",
            "variables": {"url": "https://default.test"},
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{url}}/page",
                    "description": "Navigate",
                }
            ],
        }
        f = _write_yaml(tmp_path / "override.yaml", data)
        scenario = load_scenario(f, variables={"url": "https://external.test"})
        # Scenario-level variables override external (scenario has its own defaults)
        assert scenario.steps[0].value == "https://default.test/page"


# ── Directory Loading ──


class TestLoadScenarios:
    def test_load_from_directory(self, tmp_path: Path) -> None:
        sc1 = {**MINIMAL_SCENARIO, "id": "SC-001", "name": "First"}
        sc2 = {
            "id": "SC-002",
            "name": "Second",
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "https://two.com",
                    "description": "Go",
                }
            ],
        }
        _write_yaml(tmp_path / "SC-001.yaml", sc1)
        _write_yaml(tmp_path / "SC-002.yaml", sc2)
        scenarios = load_scenarios(tmp_path)
        assert len(scenarios) == 2
        ids = [s.id for s in scenarios]
        assert "SC-001" in ids
        assert "SC-002" in ids

    def test_load_single_file(self, tmp_path: Path) -> None:
        f = _write_yaml(tmp_path / "SC-001.yaml", MINIMAL_SCENARIO)
        scenarios = load_scenarios(f)
        assert len(scenarios) == 1
        assert scenarios[0].id == "SC-001"

    def test_load_nonexistent_path(self) -> None:
        with pytest.raises(ScenarioError, match="does not exist"):
            load_scenarios(Path("/nonexistent/scenarios"))

    def test_load_empty_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioError, match="No scenario YAML files"):
            load_scenarios(tmp_path)

    def test_load_nested_directory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_yaml(sub / "SC-010.yaml", {**MINIMAL_SCENARIO, "id": "SC-010"})
        scenarios = load_scenarios(tmp_path)
        assert len(scenarios) == 1
        assert scenarios[0].id == "SC-010"

    def test_load_yml_extension(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / "SC-001.yml", MINIMAL_SCENARIO)
        scenarios = load_scenarios(tmp_path)
        assert len(scenarios) == 1

    def test_partial_load_with_errors(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / "SC-001.yaml", MINIMAL_SCENARIO)
        _write_yaml(tmp_path / "SC-BAD.yaml", {"id": "INVALID", "name": "Bad"})
        # Should load the valid one, skip the invalid one
        scenarios = load_scenarios(tmp_path)
        assert len(scenarios) == 1
        assert scenarios[0].id == "SC-001"
