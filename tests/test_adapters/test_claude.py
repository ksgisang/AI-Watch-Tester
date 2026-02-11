"""Tests for ClaudeAdapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aat.adapters.claude import ClaudeAdapter
from aat.core.exceptions import AdapterError
from aat.core.models import (
    ActionType,
    AIConfig,
    AnalysisResult,
    Severity,
    StepResult,
    StepStatus,
    TestResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config() -> AIConfig:
    return AIConfig(
        provider="claude",
        api_key="test-key-123",
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        temperature=0.3,
    )


def _make_test_result(passed: bool = False) -> TestResult:
    return TestResult(
        scenario_id="SC-001",
        scenario_name="Login test",
        passed=passed,
        steps=[
            StepResult(
                step=1,
                action=ActionType.NAVIGATE,
                status=StepStatus.PASSED,
                description="Navigate to login page",
                elapsed_ms=100.0,
            ),
            StepResult(
                step=2,
                action=ActionType.FIND_AND_CLICK,
                status=StepStatus.FAILED,
                description="Click submit button",
                error_message="Element not found",
                elapsed_ms=5000.0,
            ),
        ],
        total_steps=2,
        passed_steps=1,
        failed_steps=1,
        duration_ms=5100.0,
    )


def _make_analysis() -> AnalysisResult:
    return AnalysisResult(
        cause="Submit button not found",
        suggestion="Check button selector",
        severity=Severity.CRITICAL,
        related_files=["src/pages/login.py"],
    )


def _mock_response(data: Any) -> MagicMock:
    """Create a mock API response with JSON text content."""
    text_block = MagicMock()
    text_block.text = json.dumps(data)
    response = MagicMock()
    response.content = [text_block]
    return response


@pytest.fixture
def adapter() -> ClaudeAdapter:
    config = _make_config()
    with patch("aat.adapters.claude.AsyncAnthropic"):
        return ClaudeAdapter(config)


# ---------------------------------------------------------------------------
# Tests: analyze_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_failure_success(adapter: ClaudeAdapter) -> None:
    """analyze_failure returns AnalysisResult from mock API response."""
    mock_data = {
        "cause": "Button selector changed",
        "suggestion": "Update selector to .btn-submit",
        "severity": "critical",
        "related_files": ["src/pages/login.py"],
    }
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    result = await adapter.analyze_failure(_make_test_result())

    assert isinstance(result, AnalysisResult)
    assert result.cause == "Button selector changed"
    assert result.severity == Severity.CRITICAL
    assert "src/pages/login.py" in result.related_files

    # Verify API was called with correct structure
    adapter._client.messages.create.assert_called_once()
    call_kwargs = adapter._client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"
    assert len(call_kwargs["messages"]) == 1
    assert call_kwargs["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_analyze_failure_with_screenshots(adapter: ClaudeAdapter) -> None:
    """analyze_failure includes base64 screenshots in request."""
    mock_data = {
        "cause": "UI changed",
        "suggestion": "Update layout",
        "severity": "warning",
        "related_files": [],
    }
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    screenshots = [b"\x89PNG_fake_image_data"]
    result = await adapter.analyze_failure(_make_test_result(), screenshots=screenshots)

    assert result.severity == Severity.WARNING

    call_kwargs = adapter._client.messages.create.call_args.kwargs
    user_content = call_kwargs["messages"][0]["content"]
    assert len(user_content) == 2  # text + image
    assert user_content[1]["type"] == "image"
    assert user_content[1]["source"]["type"] == "base64"


@pytest.mark.asyncio
async def test_analyze_failure_api_error(adapter: ClaudeAdapter) -> None:
    """analyze_failure wraps API errors in AdapterError."""
    adapter._client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))

    with pytest.raises(AdapterError, match="Claude API call failed"):
        await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_invalid_json(adapter: ClaudeAdapter) -> None:
    """analyze_failure raises AdapterError on invalid JSON."""
    text_block = MagicMock()
    text_block.text = "not valid json {"
    response = MagicMock()
    response.content = [text_block]
    adapter._client.messages.create = AsyncMock(return_value=response)

    with pytest.raises(AdapterError, match="Failed to parse JSON"):
        await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_missing_field(adapter: ClaudeAdapter) -> None:
    """analyze_failure raises AdapterError when response is missing required fields."""
    mock_data = {"cause": "something"}  # missing suggestion, severity
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    with pytest.raises(AdapterError, match="Failed to parse analysis response"):
        await adapter.analyze_failure(_make_test_result())


# ---------------------------------------------------------------------------
# Tests: generate_fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_fix_success(adapter: ClaudeAdapter) -> None:
    """generate_fix returns FixResult from mock API response."""
    mock_data = {
        "description": "Update button selector",
        "files_changed": [
            {
                "path": "src/pages/login.py",
                "original": "old code",
                "modified": "new code",
                "description": "Fixed selector",
            }
        ],
        "confidence": 0.85,
    }
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    result = await adapter.generate_fix(
        _make_analysis(),
        {"src/pages/login.py": "old code"},
    )

    assert result.description == "Update button selector"
    assert len(result.files_changed) == 1
    assert result.files_changed[0].path == "src/pages/login.py"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_generate_fix_api_error(adapter: ClaudeAdapter) -> None:
    """generate_fix wraps API errors in AdapterError."""
    adapter._client.messages.create = AsyncMock(side_effect=RuntimeError("timeout"))

    with pytest.raises(AdapterError, match="Claude API call failed"):
        await adapter.generate_fix(_make_analysis(), {})


# ---------------------------------------------------------------------------
# Tests: generate_scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_scenarios_success(adapter: ClaudeAdapter) -> None:
    """generate_scenarios returns list of Scenario objects."""
    mock_data = [
        {
            "id": "SC-001",
            "name": "Login flow",
            "description": "Test login",
            "tags": ["auth"],
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "description": "Go to login",
                    "value": "https://example.com/login",
                }
            ],
            "expected_result": [],
            "variables": {},
        }
    ]
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    result = await adapter.generate_scenarios("Login spec document")

    assert len(result) == 1
    assert result[0].id == "SC-001"
    assert result[0].name == "Login flow"


@pytest.mark.asyncio
async def test_generate_scenarios_not_array(adapter: ClaudeAdapter) -> None:
    """generate_scenarios raises AdapterError if response is not a JSON array."""
    mock_data = {"scenarios": []}
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    with pytest.raises(AdapterError, match="Expected JSON array"):
        await adapter.generate_scenarios("some doc")


# ---------------------------------------------------------------------------
# Tests: analyze_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_document_success(adapter: ClaudeAdapter) -> None:
    """analyze_document returns dict with screens/elements/flows."""
    mock_data = {
        "screens": ["Login screen", "Dashboard"],
        "elements": ["username_input", "password_input"],
        "flows": ["Login flow"],
    }
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    result = await adapter.analyze_document("Spec document text")

    assert "screens" in result
    assert len(result["screens"]) == 2


@pytest.mark.asyncio
async def test_analyze_document_not_dict(adapter: ClaudeAdapter) -> None:
    """analyze_document raises AdapterError if response is not a dict."""
    mock_data = ["not", "a", "dict"]
    adapter._client.messages.create = AsyncMock(return_value=_mock_response(mock_data))

    with pytest.raises(AdapterError, match="Expected JSON object"):
        await adapter.analyze_document("some doc")


# ---------------------------------------------------------------------------
# Tests: registry
# ---------------------------------------------------------------------------


def test_adapter_registry() -> None:
    """ClaudeAdapter is registered in ADAPTER_REGISTRY."""
    from aat.adapters import ADAPTER_REGISTRY

    assert "claude" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["claude"] is ClaudeAdapter
