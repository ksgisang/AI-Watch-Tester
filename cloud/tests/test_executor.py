"""Tests for executor: screenshot saving, prompt, and screenshot_dir config."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.executor import _SCENARIO_PROMPT, _screenshot_dir_for_test


def test_scenario_prompt_contains_instructions() -> None:
    """AI prompt includes key generation instructions."""
    prompt = _SCENARIO_PROMPT.format(
        url="https://example.com", page_text="Hello", page_elements="No elements",
    )

    assert "E2E test scenario" in prompt
    assert "JSON" in prompt
    assert "https://example.com" in prompt
    assert "Hello" in prompt
    # Should request exact text targets (not generic placeholders)
    assert "exact text" in prompt.lower()
    # Should include form submit rule
    assert "SUBMIT[form]" in prompt


def test_scenario_prompt_format_placeholders() -> None:
    """Prompt template accepts url, page_text, and page_elements placeholders."""
    prompt = _SCENARIO_PROMPT.format(
        url="https://myapp.com/login",
        page_text="Username Password Login",
        page_elements="email[form](#email, 'Email')",
    )
    assert "https://myapp.com/login" in prompt
    assert "Username Password Login" in prompt
    assert "email[form](#email" in prompt


def test_screenshot_dir_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_screenshot_dir_for_test creates nested directory."""
    from app import config

    monkeypatch.setattr(config.settings, "screenshot_dir", str(tmp_path / "ss"))

    d = _screenshot_dir_for_test(42)
    assert d.exists()
    assert d.is_dir()
    assert d == tmp_path / "ss" / "42"


def test_screenshot_dir_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling _screenshot_dir_for_test twice doesn't error."""
    from app import config

    monkeypatch.setattr(config.settings, "screenshot_dir", str(tmp_path / "ss"))

    d1 = _screenshot_dir_for_test(7)
    d2 = _screenshot_dir_for_test(7)
    assert d1 == d2
    assert d1.exists()


def test_screenshot_dir_config_default() -> None:
    """Default screenshot_dir is screenshots."""
    from app.config import settings

    assert settings.screenshot_dir == "screenshots"
