"""Choosing a reporter, and the options that choice carries.

`aat run` and `aat loop` both come through `build_reporter`, so a format's
options are checked in one place. Before this existed each command assembled
its own reporter, and a format that gained an option only gained it in the
command that happened to be edited that day.
"""

from __future__ import annotations

import pytest

from aat.core.exceptions import ReporterError
from aat.reporters import build_reporter
from aat.reporters.markdown import MarkdownReporter
from aat.reporters.pdf import PDFReporter


def test_a_known_format_is_built() -> None:
    assert isinstance(build_reporter("markdown"), MarkdownReporter)
    assert isinstance(build_reporter("pdf"), PDFReporter)


def test_the_screenshot_policy_is_carried_into_the_pdf_reporter() -> None:
    """'all' is the reason the option exists: showing the steps that worked."""
    assert build_reporter("pdf", "all")._screenshots == "all"
    assert build_reporter("pdf", "none")._screenshots == "none"
    assert build_reporter("pdf")._screenshots == "failures"


def test_a_format_that_cannot_carry_images_ignores_the_policy() -> None:
    """Markdown links its screenshots rather than embedding them.

    Asking it for 'all' is not an error — the same command line has to work
    for either format — it simply has nothing to apply.
    """
    assert isinstance(build_reporter("markdown", "all"), MarkdownReporter)


def test_an_unknown_format_names_the_ones_that_exist() -> None:
    with pytest.raises(ReporterError) as excinfo:
        build_reporter("powerpoint")

    message = str(excinfo.value)
    assert "powerpoint" in message
    assert "markdown" in message
    assert "pdf" in message


def test_an_unknown_policy_names_the_ones_that_exist() -> None:
    with pytest.raises(ReporterError) as excinfo:
        build_reporter("pdf", "everything")

    message = str(excinfo.value)
    assert "everything" in message
    assert "failures" in message
    assert "all" in message
