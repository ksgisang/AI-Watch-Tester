"""Reporter plugin registry."""

from typing import cast, get_args

from aat.core.exceptions import ReporterError
from aat.reporters.base import BaseReporter
from aat.reporters.markdown import MarkdownReporter
from aat.reporters.pdf import PDFReporter, ScreenshotPolicy

REPORTER_REGISTRY: dict[str, type[BaseReporter]] = {
    "markdown": MarkdownReporter,
    "pdf": PDFReporter,
}

#: Which steps a report illustrates. Only the PDF report embeds images, so this
#: is ignored by the formats that cannot carry one. Read off the reporter's own
#: type so the CLI cannot come to offer a choice the reporter does not have.
SCREENSHOT_POLICIES: tuple[str, ...] = get_args(ScreenshotPolicy)


def build_reporter(report_format: str, screenshots: str = "failures") -> BaseReporter:
    """Make the reporter for a format, applying the options it understands.

    Both `aat run` and `aat loop` come through here so that a format gains its
    options in one place rather than in whichever command was edited last.
    """
    reporter_cls = REPORTER_REGISTRY.get(report_format)
    if reporter_cls is None:
        known = ", ".join(sorted(REPORTER_REGISTRY))
        msg = f"Unknown report format '{report_format}'. Available: {known}"
        raise ReporterError(msg)

    if issubclass(reporter_cls, PDFReporter):
        if screenshots not in SCREENSHOT_POLICIES:
            known = ", ".join(SCREENSHOT_POLICIES)
            msg = f"Unknown screenshot policy '{screenshots}'. Available: {known}"
            raise ReporterError(msg)
        return reporter_cls(screenshots=cast(ScreenshotPolicy, screenshots))

    return reporter_cls()


__all__ = [
    "REPORTER_REGISTRY",
    "SCREENSHOT_POLICIES",
    "MarkdownReporter",
    "PDFReporter",
    "build_reporter",
]
