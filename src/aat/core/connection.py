"""AI Provider connection testing and URL health checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from aat.core.models import AIConfig


async def test_ai_connection(config: AIConfig) -> tuple[bool, str]:
    """Test AI provider connection.

    Returns:
        (success, message) tuple.
    """
    provider = config.provider

    if provider == "ollama":
        return await _test_ollama(config)
    elif provider == "claude":
        return await _test_claude(config)
    elif provider == "openai":
        return await _test_openai(config)
    else:
        return False, f"Unknown provider: {provider}"


async def _test_ollama(config: AIConfig) -> tuple[bool, str]:
    """Test Ollama connection by checking /api/tags."""
    base_url = (
        config.api_key if config.api_key and config.api_key.startswith("http")
        else "http://localhost:11434"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            if config.model in models:
                return True, f"Connected to Ollama. Model '{config.model}' available."
            elif models:
                return True, (
                    f"Connected to Ollama. Model '{config.model}' not found. "
                    f"Available: {', '.join(models)}"
                )
            else:
                return False, "Connected to Ollama but no models installed."
    except httpx.ConnectError:
        return False, f"Cannot connect to Ollama at {base_url}. Is it running?"
    except Exception as exc:
        return False, f"Ollama connection error: {exc}"


async def _test_claude(config: AIConfig) -> tuple[bool, str]:
    """Test Claude API connection with a minimal request."""
    if not config.api_key:
        return False, "API key is empty. Set ai.api_key first."
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.api_key)
        resp = await client.messages.create(
            model=config.model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        if resp.content:
            return True, f"Connected to Claude API. Model: {config.model}"
        return False, "Claude API returned empty response."
    except Exception as exc:
        return False, f"Claude API error: {exc}"


async def _test_openai(config: AIConfig) -> tuple[bool, str]:
    """Test OpenAI API connection by listing models."""
    if not config.api_key:
        return False, "API key is empty. Set ai.api_key first."
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=config.api_key)
        resp = await client.models.list()
        model_ids = [m.id for m in resp.data[:5]]
        return True, f"Connected to OpenAI API. Models available (e.g. {', '.join(model_ids)})"
    except Exception as exc:
        return False, f"OpenAI API error: {exc}"


async def test_url(url: str) -> tuple[bool, str]:
    """Test if a URL is reachable.

    Returns:
        (success, message) tuple.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            return True, f"URL reachable (HTTP {resp.status_code})"
    except httpx.ConnectError:
        return False, f"Cannot connect to {url}. Is the server running?"
    except httpx.TimeoutException:
        return False, f"Connection to {url} timed out (15s)."
    except Exception as exc:
        return False, f"URL check failed: {exc}"
