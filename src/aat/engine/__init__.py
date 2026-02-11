"""Engine plugin registry."""

from aat.engine.web import WebEngine

ENGINE_REGISTRY: dict[str, type] = {
    "web": WebEngine,
}
