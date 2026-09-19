"""Reporter plugin registry."""

from aat.reporters.markdown import MarkdownReporter
from aat.reporters.pdf import PDFReporter

REPORTER_REGISTRY: dict[str, type] = {
    "markdown": MarkdownReporter,
    "pdf": PDFReporter,
}

__all__ = ["REPORTER_REGISTRY", "MarkdownReporter", "PDFReporter"]
