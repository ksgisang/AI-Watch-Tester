"""Tests for AI provider connection testing and URL health checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from aat.core.connection import test_ai_connection as check_ai_connection
from aat.core.connection import test_url as check_url
from aat.core.models import AIConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    provider: str = "ollama",
    api_key: str = "",
    model: str = "codellama:7b",
) -> AIConfig:
    return AIConfig(provider=provider, api_key=api_key, model=model)


def _mock_httpx_response(
    status_code: int = 200,
    json_data: dict | None = None,
    url: str = "http://localhost:11434/api/tags",
) -> httpx.Response:
    """Create a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data or {},
        request=httpx.Request("GET", url),
    )


# ---------------------------------------------------------------------------
# Tests: test_ai_connection — Ollama
# ---------------------------------------------------------------------------


class TestOllamaConnection:
    """Tests for Ollama provider connection."""

    async def test_ollama_model_available(self) -> None:
        """Returns success when model is found in Ollama."""
        resp = _mock_httpx_response(
            json_data={
                "models": [{"name": "codellama:7b"}, {"name": "llama3:8b"}],
            }
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = resp

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_ai_connection(_make_config())

        assert ok is True
        assert "codellama:7b" in msg
        assert "available" in msg.lower()

    async def test_ollama_model_not_found(self) -> None:
        """Returns success with warning when model is not in the list."""
        resp = _mock_httpx_response(
            json_data={
                "models": [{"name": "llama3:8b"}],
            }
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = resp

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_ai_connection(_make_config())

        assert ok is True
        assert "not found" in msg.lower()
        assert "llama3:8b" in msg

    async def test_ollama_no_models(self) -> None:
        """Returns failure when Ollama has no models installed."""
        resp = _mock_httpx_response(json_data={"models": []})
        mock_client = AsyncMock()
        mock_client.get.return_value = resp

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_ai_connection(_make_config())

        assert ok is False
        assert "no models" in msg.lower()

    async def test_ollama_connect_error(self) -> None:
        """Returns failure when Ollama is not running."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_ai_connection(_make_config())

        assert ok is False
        assert "Cannot connect" in msg

    async def test_ollama_custom_base_url(self) -> None:
        """Uses api_key as base URL when it starts with http."""
        resp = _mock_httpx_response(
            json_data={
                "models": [{"name": "codellama:7b"}],
            }
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = resp

        config = _make_config(api_key="http://remote:11434")

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_ai_connection(config)

        assert ok is True
        # Verify the custom URL was used
        mock_client.get.assert_called_once_with("http://remote:11434/api/tags")


# ---------------------------------------------------------------------------
# Tests: test_ai_connection — Claude
# ---------------------------------------------------------------------------


class TestClaudeConnection:
    """Tests for Claude provider connection."""

    async def test_claude_success(self) -> None:
        """Returns success when Claude API responds."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="pong")]

        mock_messages = AsyncMock()
        mock_messages.create.return_value = mock_resp

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            config = _make_config(
                provider="claude",
                api_key="sk-test-key",
                model="claude-sonnet-4-20250514",
            )
            ok, msg = await check_ai_connection(config)

        assert ok is True
        assert "Connected to Claude" in msg

    async def test_claude_empty_response(self) -> None:
        """Returns failure when Claude returns empty content."""
        mock_resp = MagicMock()
        mock_resp.content = []

        mock_messages = AsyncMock()
        mock_messages.create.return_value = mock_resp

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            config = _make_config(provider="claude", api_key="sk-test-key")
            ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "empty response" in msg.lower()

    async def test_claude_no_api_key(self) -> None:
        """Returns failure when API key is empty."""
        config = _make_config(provider="claude", api_key="")
        ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "API key is empty" in msg

    async def test_claude_api_error(self) -> None:
        """Returns failure when Claude API raises an exception."""
        mock_messages = AsyncMock()
        mock_messages.create.side_effect = Exception("Invalid API key")

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            config = _make_config(provider="claude", api_key="sk-bad-key")
            ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "Claude API error" in msg


# ---------------------------------------------------------------------------
# Tests: test_ai_connection — OpenAI
# ---------------------------------------------------------------------------


class TestOpenAIConnection:
    """Tests for OpenAI provider connection."""

    async def test_openai_success(self) -> None:
        """Returns success when OpenAI API lists models."""
        mock_model_1 = MagicMock()
        mock_model_1.id = "gpt-4o"
        mock_model_2 = MagicMock()
        mock_model_2.id = "gpt-4o-mini"

        mock_resp = MagicMock()
        mock_resp.data = [mock_model_1, mock_model_2]

        mock_models = AsyncMock()
        mock_models.list.return_value = mock_resp

        mock_client = MagicMock()
        mock_client.models = mock_models

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            config = _make_config(provider="openai", api_key="sk-test-key", model="gpt-4o")
            ok, msg = await check_ai_connection(config)

        assert ok is True
        assert "Connected to OpenAI" in msg
        assert "gpt-4o" in msg

    async def test_openai_no_api_key(self) -> None:
        """Returns failure when API key is empty."""
        config = _make_config(provider="openai", api_key="")
        ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "API key is empty" in msg

    async def test_openai_api_error(self) -> None:
        """Returns failure when OpenAI API raises an exception."""
        mock_models = AsyncMock()
        mock_models.list.side_effect = Exception("Rate limit exceeded")

        mock_client = MagicMock()
        mock_client.models = mock_models

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            config = _make_config(provider="openai", api_key="sk-bad-key")
            ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "OpenAI API error" in msg


# ---------------------------------------------------------------------------
# Tests: unknown provider
# ---------------------------------------------------------------------------


class TestUnknownProvider:
    """Tests for unsupported AI providers."""

    async def test_unknown_provider(self) -> None:
        """Returns failure for an unrecognized provider."""
        config = _make_config(provider="gemini", api_key="key")
        ok, msg = await check_ai_connection(config)

        assert ok is False
        assert "Unknown provider" in msg
        assert "gemini" in msg


# ---------------------------------------------------------------------------
# Tests: test_url
# ---------------------------------------------------------------------------


class TestURL:
    """Tests for URL health checks."""

    async def test_url_reachable(self) -> None:
        """Returns success when URL responds."""
        resp = _mock_httpx_response(status_code=200, url="http://localhost:3000")
        mock_client = AsyncMock()
        mock_client.get.return_value = resp

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_url("http://localhost:3000")

        assert ok is True
        assert "200" in msg

    async def test_url_connect_error(self) -> None:
        """Returns failure when URL is unreachable."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_url("http://localhost:9999")

        assert ok is False
        assert "Cannot connect" in msg

    async def test_url_timeout(self) -> None:
        """Returns failure when URL times out."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Timed out")

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_url("http://slow-server.example.com")

        assert ok is False
        assert "timed out" in msg.lower()

    async def test_url_generic_error(self) -> None:
        """Returns failure on unexpected exceptions."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("SSL error")

        with patch("aat.core.connection.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            ok, msg = await check_url("https://bad-cert.example.com")

        assert ok is False
        assert "URL check failed" in msg
