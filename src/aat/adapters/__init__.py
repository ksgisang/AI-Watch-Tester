"""AI Adapter plugin registry."""

from aat.adapters.claude import ClaudeAdapter

ADAPTER_REGISTRY: dict[str, type] = {
    "claude": ClaudeAdapter,
}

__all__ = ["ADAPTER_REGISTRY", "ClaudeAdapter"]
