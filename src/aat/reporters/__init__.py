"""Reporter plugin registry."""

from aat.reporters.markdown import MarkdownReporter

REPORTER_REGISTRY: dict[str, type] = {
    "markdown": MarkdownReporter,
}

__all__ = ["REPORTER_REGISTRY", "MarkdownReporter"]
