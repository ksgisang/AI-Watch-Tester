"""Tests for OpenAIAdapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aat.adapters.openai_adapter import OpenAIAdapter
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
        provider="openai",
        api_key="test-key-123",
        model="gpt-4o",
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
    """Create a mock OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = json.dumps(data)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_response_with_fences(data: Any) -> MagicMock:
    """Create a mock response where model wraps JSON in markdown fences."""
    message = MagicMock()
    message.content = f"```json\n{json.dumps(data)}\n```"
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def adapter() -> OpenAIAdapter:
    config = _make_config()
    with patch("aat.adapters.openai_adapter.AsyncOpenAI"):
        return OpenAIAdapter(config)


# ---------------------------------------------------------------------------
# Tests: analyze_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_failure_success(adapter: OpenAIAdapter) -> None:
    """analyze_failure returns AnalysisResult from mock API response."""
    mock_data = {
        "cause": "Button selector changed",
        "suggestion": "Update selector to .btn-submit",
        "severity": "critical",
        "related_files": ["src/pages/login.py"],
    }
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.analyze_failure(_make_test_result())

    assert isinstance(result, AnalysisResult)
    assert result.cause == "Button selector changed"
    assert result.severity == Severity.CRITICAL
    assert "src/pages/login.py" in result.related_files

    # Verify API was called with correct structure
    adapter._client.chat.completions.create.assert_called_once()
    call_kwargs = adapter._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"
    assert len(call_kwargs["messages"]) == 2
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_analyze_failure_with_screenshots(adapter: OpenAIAdapter) -> None:
    """analyze_failure includes base64 screenshots in request."""
    mock_data = {
        "cause": "UI changed",
        "suggestion": "Update layout",
        "severity": "warning",
        "related_files": [],
    }
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    screenshots = [b"\x89PNG_fake_image_data"]
    result = await adapter.analyze_failure(
        _make_test_result(), screenshots=screenshots,
    )

    assert result.severity == Severity.WARNING

    call_kwargs = adapter._client.chat.completions.create.call_args.kwargs
    user_content = call_kwargs["messages"][1]["content"]
    assert len(user_content) == 2  # text + image_url
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_analyze_failure_api_error(adapter: OpenAIAdapter) -> None:
    """analyze_failure wraps API errors in AdapterError."""
    adapter._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("API down"),
    )

    with pytest.raises(AdapterError, match="OpenAI API call failed"):
        await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_empty_response(adapter: OpenAIAdapter) -> None:
    """analyze_failure raises AdapterError on empty response."""
    message = MagicMock()
    message.content = ""
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    adapter._client.chat.completions.create = AsyncMock(return_value=response)

    with pytest.raises(AdapterError, match="Empty response from OpenAI"):
        await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_invalid_json(adapter: OpenAIAdapter) -> None:
    """analyze_failure raises AdapterError on invalid JSON."""
    message = MagicMock()
    message.content = "not valid json {"
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    adapter._client.chat.completions.create = AsyncMock(return_value=response)

    with pytest.raises(AdapterError, match="Failed to parse JSON"):
        await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_missing_field(adapter: OpenAIAdapter) -> None:
    """analyze_failure raises AdapterError when response is missing required fields."""
    mock_data = {"cause": "something"}  # missing suggestion, severity
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    with pytest.raises(AdapterError, match="Failed to parse analysis response"):
        await adapter.analyze_failure(_make_test_result())


# ---------------------------------------------------------------------------
# Tests: markdown fence stripping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strips_markdown_fences(adapter: OpenAIAdapter) -> None:
    """_call_api strips ```json ... ``` fences from GPT output."""
    mock_data = {
        "cause": "Fence test",
        "suggestion": "Check fences",
        "severity": "info",
        "related_files": [],
    }
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response_with_fences(mock_data),
    )

    result = await adapter.analyze_failure(_make_test_result())

    assert result.cause == "Fence test"
    assert result.severity == Severity.INFO


# ---------------------------------------------------------------------------
# Tests: generate_fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_fix_success(adapter: OpenAIAdapter) -> None:
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
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.generate_fix(
        _make_analysis(),
        {"src/pages/login.py": "old code"},
    )

    assert result.description == "Update button selector"
    assert len(result.files_changed) == 1
    assert result.files_changed[0].path == "src/pages/login.py"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_generate_fix_api_error(adapter: OpenAIAdapter) -> None:
    """generate_fix wraps API errors in AdapterError."""
    adapter._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("timeout"),
    )

    with pytest.raises(AdapterError, match="OpenAI API call failed"):
        await adapter.generate_fix(_make_analysis(), {})


# ---------------------------------------------------------------------------
# Tests: generate_scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_scenarios_success(adapter: OpenAIAdapter) -> None:
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
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.generate_scenarios("Login spec document")

    assert len(result) == 1
    assert result[0].id == "SC-001"
    assert result[0].name == "Login flow"


@pytest.mark.asyncio
async def test_generate_scenarios_with_images(adapter: OpenAIAdapter) -> None:
    """generate_scenarios includes images as base64 in request."""
    mock_data = [
        {
            "id": "SC-001",
            "name": "Test",
            "description": "Test",
            "tags": [],
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "description": "Go",
                    "value": "https://example.com",
                }
            ],
            "expected_result": [],
            "variables": {},
        }
    ]
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.generate_scenarios(
        "Spec doc", images=[b"fake_image"],
    )

    assert len(result) == 1

    call_kwargs = adapter._client.chat.completions.create.call_args.kwargs
    user_content = call_kwargs["messages"][1]["content"]
    assert len(user_content) == 2  # text + image_url
    assert user_content[1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_generate_scenarios_not_array(adapter: OpenAIAdapter) -> None:
    """generate_scenarios raises AdapterError if response is not a JSON array."""
    mock_data = {"scenarios": []}
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    with pytest.raises(AdapterError, match="Expected JSON array"):
        await adapter.generate_scenarios("some doc")


# ---------------------------------------------------------------------------
# Tests: analyze_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_document_success(adapter: OpenAIAdapter) -> None:
    """analyze_document returns dict with screens/elements/flows."""
    mock_data = {
        "screens": ["Login screen", "Dashboard"],
        "elements": ["username_input", "password_input"],
        "flows": ["Login flow"],
    }
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.analyze_document("Spec document text")

    assert "screens" in result
    assert len(result["screens"]) == 2


@pytest.mark.asyncio
async def test_analyze_document_with_images(adapter: OpenAIAdapter) -> None:
    """analyze_document includes images as base64 in request."""
    mock_data = {
        "screens": ["Login"],
        "elements": ["button"],
        "flows": ["Login flow"],
    }
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    result = await adapter.analyze_document(
        "Spec doc", images=[b"fake_image"],
    )

    assert "screens" in result

    call_kwargs = adapter._client.chat.completions.create.call_args.kwargs
    user_content = call_kwargs["messages"][1]["content"]
    assert len(user_content) == 2
    assert user_content[1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_analyze_document_not_dict(adapter: OpenAIAdapter) -> None:
    """analyze_document raises AdapterError if response is not a dict."""
    mock_data = ["not", "a", "dict"]
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_mock_response(mock_data),
    )

    with pytest.raises(AdapterError, match="Expected JSON object"):
        await adapter.analyze_document("some doc")


# ---------------------------------------------------------------------------
# Tests: registry
# ---------------------------------------------------------------------------


def test_adapter_registry() -> None:
    """OpenAIAdapter is registered in ADAPTER_REGISTRY."""
    from aat.adapters import ADAPTER_REGISTRY

    assert "openai" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["openai"] is OpenAIAdapter
