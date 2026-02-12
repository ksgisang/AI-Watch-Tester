"""AI Adapter plugin registry."""

from aat.adapters.claude import ClaudeAdapter
from aat.adapters.ollama import OllamaAdapter
from aat.adapters.openai_adapter import OpenAIAdapter

ADAPTER_REGISTRY: dict[str, type] = {
    "claude": ClaudeAdapter,
    "ollama": OllamaAdapter,
    "openai": OpenAIAdapter,
}

__all__ = ["ADAPTER_REGISTRY", "ClaudeAdapter", "OllamaAdapter", "OpenAIAdapter"]
