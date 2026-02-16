"""Tests for OllamaAdapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aat.adapters.ollama import OllamaAdapter
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


def _make_config(model: str = "codellama:7b") -> AIConfig:
    return AIConfig(
        provider="ollama",
        api_key="",  # no API key needed for local Ollama
        model=model,
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


def _mock_ollama_response(data: Any) -> httpx.Response:
    """Create a mock Ollama HTTP response."""
    body = {
        "model": "codellama:7b",
        "message": {
            "role": "assistant",
            "content": json.dumps(data),
        },
        "done": True,
    }
    return httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )


def _mock_ollama_response_with_fences(data: Any) -> httpx.Response:
    """Create a mock response where model wraps JSON in markdown fences."""
    json_text = f"```json\n{json.dumps(data)}\n```"
    body = {
        "model": "codellama:7b",
        "message": {"role": "assistant", "content": json_text},
        "done": True,
    }
    return httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )


@pytest.fixture
def adapter() -> OllamaAdapter:
    return OllamaAdapter(_make_config())


# ---------------------------------------------------------------------------
# Tests: initialization
# ---------------------------------------------------------------------------


def test_default_base_url() -> None:
    """Default base URL is localhost:11434."""
    adapter = OllamaAdapter(_make_config())
    assert adapter._base_url == "http://localhost:11434"


def test_custom_base_url() -> None:
    """api_key field can override base URL when it starts with http."""
    config = AIConfig(
        provider="ollama",
        api_key="http://remote-host:11434",
        model="codellama:7b",
    )
    adapter = OllamaAdapter(config)
    assert adapter._base_url == "http://remote-host:11434"


# ---------------------------------------------------------------------------
# Tests: analyze_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_failure_success(adapter: OllamaAdapter) -> None:
    """analyze_failure returns AnalysisResult from mock Ollama response."""
    mock_data = {
        "cause": "Button selector changed",
        "suggestion": "Update selector to .btn-submit",
        "severity": "critical",
        "related_files": ["src/pages/login.py"],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.analyze_failure(_make_test_result())

    assert isinstance(result, AnalysisResult)
    assert result.cause == "Button selector changed"
    assert result.severity == Severity.CRITICAL
    assert "src/pages/login.py" in result.related_files


@pytest.mark.asyncio
async def test_analyze_failure_ignores_screenshots(adapter: OllamaAdapter) -> None:
    """analyze_failure works even with screenshots (ignored for text-only models)."""
    mock_data = {
        "cause": "UI changed",
        "suggestion": "Update layout",
        "severity": "warning",
        "related_files": [],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.analyze_failure(_make_test_result(), screenshots=[b"fake_image"])

    assert result.severity == Severity.WARNING


@pytest.mark.asyncio
async def test_analyze_failure_connection_error(adapter: OllamaAdapter) -> None:
    """analyze_failure raises AdapterError when Ollama is not running."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(AdapterError, match="Cannot connect to Ollama"):
            await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_invalid_json(adapter: OllamaAdapter) -> None:
    """analyze_failure raises AdapterError on non-JSON response."""
    body = {
        "model": "codellama:7b",
        "message": {"role": "assistant", "content": "not valid json {"},
        "done": True,
    }
    response = httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = response

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(AdapterError, match="Failed to parse JSON"):
            await adapter.analyze_failure(_make_test_result())


@pytest.mark.asyncio
async def test_analyze_failure_missing_field(adapter: OllamaAdapter) -> None:
    """analyze_failure raises AdapterError when response lacks required fields."""
    mock_data = {"cause": "something"}  # missing suggestion, severity

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(AdapterError, match="Failed to parse analysis response"):
            await adapter.analyze_failure(_make_test_result())


# ---------------------------------------------------------------------------
# Tests: markdown fence stripping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strips_markdown_fences(adapter: OllamaAdapter) -> None:
    """_call_api strips ```json ... ``` fences from LLM output."""
    mock_data = {
        "cause": "Fence test",
        "suggestion": "Check fences",
        "severity": "info",
        "related_files": [],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response_with_fences(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.analyze_failure(_make_test_result())

    assert result.cause == "Fence test"
    assert result.severity == Severity.INFO


# ---------------------------------------------------------------------------
# Tests: generate_fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_fix_success(adapter: OllamaAdapter) -> None:
    """generate_fix returns FixResult from mock Ollama response."""
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

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.generate_fix(
            _make_analysis(),
            {"src/pages/login.py": "old code"},
        )

    assert result.description == "Update button selector"
    assert len(result.files_changed) == 1
    assert result.confidence == 0.85


# ---------------------------------------------------------------------------
# Tests: generate_scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_scenarios_success(adapter: OllamaAdapter) -> None:
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

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.generate_scenarios("Login spec document")

    assert len(result) == 1
    assert result[0].id == "SC-001"


@pytest.mark.asyncio
async def test_generate_scenarios_not_array(adapter: OllamaAdapter) -> None:
    """generate_scenarios raises AdapterError if response is not a JSON array."""
    mock_data = {"scenarios": []}

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(AdapterError, match="Expected JSON array"):
            await adapter.generate_scenarios("some doc")


# ---------------------------------------------------------------------------
# Tests: analyze_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_document_success(adapter: OllamaAdapter) -> None:
    """analyze_document returns dict with screens/elements/flows."""
    mock_data = {
        "screens": ["Login screen", "Dashboard"],
        "elements": ["username_input", "password_input"],
        "flows": ["Login flow"],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await adapter.analyze_document("Spec document text")

    assert "screens" in result
    assert len(result["screens"]) == 2


@pytest.mark.asyncio
async def test_analyze_document_not_dict(adapter: OllamaAdapter) -> None:
    """analyze_document raises AdapterError if response is not a dict."""
    mock_data = ["not", "a", "dict"]

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_ollama_response(mock_data)

    with patch("aat.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(AdapterError, match="Expected JSON object"):
            await adapter.analyze_document("some doc")


# ---------------------------------------------------------------------------
# Tests: registry
# ---------------------------------------------------------------------------


def test_adapter_registry() -> None:
    """OllamaAdapter is registered in ADAPTER_REGISTRY."""
    from aat.adapters import ADAPTER_REGISTRY

    assert "ollama" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["ollama"] is OllamaAdapter
