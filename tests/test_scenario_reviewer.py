"""Tests for ScenarioReviewer — human-readable scenario display + approval."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aat.core.scenario_reviewer import ScenarioReviewer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LOGIN_YAML = """
id: SC-001
name: 로그인 테스트
steps:
  - step: 1
    action: navigate
    value: "https://example.com/login"
    description: "Login page"
  - step: 2
    action: find_and_type
    target:
      text: "이메일"
    value: "test@example.com"
    description: "Enter email"
  - step: 3
    action: find_and_type
    target:
      text: "비밀번호"
    value: "Secret123!"
    description: "Enter password"
  - step: 4
    action: find_and_click
    target:
      text: "로그인"
    critical: true
    description: "Click login"
  - step: 5
    action: assert_url
    value: "/dashboard"
    on_fail: stop
    description: "Check redirect"
  - step: 6
    action: screenshot
    description: "Final state"
"""


# ---------------------------------------------------------------------------
# _format_detail
# ---------------------------------------------------------------------------


def test_format_navigate() -> None:
    r = ScenarioReviewer()
    step = {"action": "navigate", "value": "https://example.com", "step": 1}
    assert "example.com" in r._format_detail(step, "navigate")


def test_format_find_and_type_masks_password() -> None:
    r = ScenarioReviewer()
    step = {
        "action": "find_and_type",
        "target": {"text": "비밀번호"},
        "value": "Secret123!",
        "step": 3,
    }
    detail = r._format_detail(step, "find_and_type")
    assert "Secret123!" not in detail
    assert "•" in detail


def test_format_find_and_type_shows_email() -> None:
    r = ScenarioReviewer()
    step = {
        "action": "find_and_type",
        "target": {"text": "이메일"},
        "value": "test@example.com",
        "step": 2,
    }
    detail = r._format_detail(step, "find_and_type")
    assert "test@example.com" in detail


def test_format_type_text_masks_password_by_description() -> None:
    r = ScenarioReviewer()
    step = {
        "action": "type_text",
        "value": "MyPass!",
        "description": "비밀번호 입력",
        "step": 3,
    }
    detail = r._format_detail(step, "type_text")
    assert "MyPass!" not in detail
    assert "•" in detail


def test_format_wait_converts_ms() -> None:
    r = ScenarioReviewer()
    step = {"action": "wait", "value": "3000", "step": 2}
    detail = r._format_detail(step, "wait")
    assert "3.0s" in detail


def test_format_click_at_shows_coords() -> None:
    r = ScenarioReviewer()
    step = {"action": "click_at", "value": "640,480", "step": 5}
    detail = r._format_detail(step, "click_at")
    assert "640" in detail and "480" in detail


def test_format_assert_url() -> None:
    r = ScenarioReviewer()
    step = {"action": "assert_url", "value": "/dashboard", "step": 6}
    detail = r._format_detail(step, "assert_url")
    assert "/dashboard" in detail


def test_format_find_and_click_shows_label() -> None:
    r = ScenarioReviewer()
    step = {
        "action": "find_and_click",
        "target": {"text": "로그인"},
        "critical": True,
        "step": 4,
    }
    detail = r._format_detail(step, "find_and_click")
    assert "로그인" in detail


def test_format_assert_text_reads_target_text() -> None:
    """The reviewer must show what an assertion checks.

    Real scenarios put the expected string in target.text (executor.py reads
    that first). Reading only `value` left this line blank, so the approval
    panel hid the single most important fact about the step.
    """
    r = ScenarioReviewer()
    step = {"action": "assert_text", "target": {"text": "반가워요"}, "step": 3}
    assert "반가워요" in r._format_detail(step, "assert_text")


def test_format_assert_text_prefers_target_over_value() -> None:
    r = ScenarioReviewer()
    step = {"action": "assert_text", "target": {"text": "내 과목"}, "value": "stale", "step": 8}
    assert r._format_detail(step, "assert_text") == "내 과목"


def test_format_assert_text_falls_back_to_value_and_expected() -> None:
    r = ScenarioReviewer()
    assert r._format_detail({"action": "assert_text", "value": "환영"}, "assert_text") == "환영"
    assert r._format_detail({"action": "assert", "expected": "OK"}, "assert") == "OK"


# ---------------------------------------------------------------------------
# _format_step — critical marker
# ---------------------------------------------------------------------------


def test_format_step_critical_tag() -> None:
    r = ScenarioReviewer()
    step = {
        "step": 4,
        "action": "find_and_click",
        "target": {"text": "로그인"},
        "critical": True,
        "description": "Click login",
    }
    line = r._format_step(step)
    assert "⛔" in line


def test_format_step_on_fail_stop_tag() -> None:
    r = ScenarioReviewer()
    step = {
        "step": 5,
        "action": "assert_url",
        "value": "/dashboard",
        "on_fail": "stop",
    }
    line = r._format_step(step)
    assert "⛔" in line


# ---------------------------------------------------------------------------
# _step_changed
# ---------------------------------------------------------------------------


def test_step_changed_detects_value_change() -> None:
    old = {"action": "find_and_type", "value": "old@example.com"}
    new = {"action": "find_and_type", "value": "new@example.com"}
    assert ScenarioReviewer._step_changed(old, new) is True


def test_step_changed_no_change() -> None:
    step = {"action": "navigate", "value": "https://x.com"}
    assert ScenarioReviewer._step_changed(step, step.copy()) is False


# ---------------------------------------------------------------------------
# show_and_approve — auto_approve mode
# ---------------------------------------------------------------------------


def test_show_and_approve_auto_approve(capsys: pytest.CaptureFixture[str]) -> None:
    """auto_approve=True returns True without any prompt."""
    r = ScenarioReviewer()
    result = r.show_and_approve(_LOGIN_YAML, attempt=1, auto_approve=True)
    assert result is True
    captured = capsys.readouterr()
    assert "proceeding automatically" in captured.out


def test_show_and_approve_user_enters(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty input (Enter) → proceed."""
    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value=""),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        result = r.show_and_approve(_LOGIN_YAML, attempt=1)
    assert result is True


def test_show_and_approve_user_cancels(capsys: pytest.CaptureFixture[str]) -> None:
    """'n' input → cancel."""
    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value="n"),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        result = r.show_and_approve(_LOGIN_YAML, attempt=1)
    assert result is False


def test_show_and_approve_shows_header(capsys: pytest.CaptureFixture[str]) -> None:
    """First attempt shows 검토 header."""
    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value=""),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        r.show_and_approve(_LOGIN_YAML, attempt=1)
    captured = capsys.readouterr()
    assert "Scenario Review" in captured.out
    assert "SC-001" in captured.out


def test_show_and_approve_retry_header(capsys: pytest.CaptureFixture[str]) -> None:
    """Second attempt shows 재시도 header."""
    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value=""),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        r.show_and_approve(_LOGIN_YAML, attempt=2, previous_yaml=_LOGIN_YAML)
    captured = capsys.readouterr()
    assert "attempt 2" in captured.out


def test_show_and_approve_diff_marker(capsys: pytest.CaptureFixture[str]) -> None:
    """Changed step shows ← 수정 marker on retry."""
    import yaml

    prev = yaml.safe_load(_LOGIN_YAML)
    prev["steps"][1]["value"] = "old@example.com"
    import yaml as _yaml

    prev_yaml = _yaml.safe_dump(prev, allow_unicode=True)

    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value=""),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        r.show_and_approve(_LOGIN_YAML, attempt=2, previous_yaml=prev_yaml)
    captured = capsys.readouterr()
    assert "← changed" in captured.out


def test_show_and_approve_invalid_yaml_fallback() -> None:
    """Broken YAML falls back gracefully."""
    r = ScenarioReviewer()
    with (
        patch("aat.core.scenario_reviewer._read_tty", return_value=""),
        patch("aat.core.scenario_reviewer._is_interactive", return_value=True),
    ):
        result = r.show_and_approve("not: valid: yaml: {{{", attempt=1)
    assert result is True
