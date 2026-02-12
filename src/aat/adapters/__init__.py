"""AI Adapter plugin registry."""

from aat.adapters.claude import ClaudeAdapter
from aat.adapters.ollama import OllamaAdapter

ADAPTER_REGISTRY: dict[str, type] = {
    "claude": ClaudeAdapter,
    "ollama": OllamaAdapter,
}

__all__ = ["ADAPTER_REGISTRY", "ClaudeAdapter", "OllamaAdapter"]
