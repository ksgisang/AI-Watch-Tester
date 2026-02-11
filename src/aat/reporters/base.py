"""BaseReporter ABC — report generation interface.

MarkdownReporter, HTMLReporter etc. implement this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aat.core.models import LoopResult, TestResult


class BaseReporter(ABC):
    """Report generation abstract interface."""

    @abstractmethod
    async def generate(
        self,
        result: TestResult | LoopResult,
        output_dir: Path,
    ) -> Path:
        """Generate report file from test results.

        Args:
            result: TestResult (single run) or LoopResult (loop run).
            output_dir: Output directory for the report.

        Returns:
            Path to the generated report file.
        """
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Report format name: 'markdown', 'html'."""
        ...
