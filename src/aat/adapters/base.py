"""AIAdapter ABC — AI tool integration interface.

ClaudeAdapter, GPTAdapter etc. implement this.
Handles failure analysis, code fix generation, scenario generation, and document analysis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aat.core.models import AnalysisResult, FixResult, Scenario, TestResult


class AIAdapter(ABC):
    """AI tool integration abstract interface."""

    @abstractmethod
    async def analyze_failure(
        self,
        test_result: TestResult,
        screenshots: list[bytes] | None = None,
    ) -> AnalysisResult:
        """Analyze test failure cause.

        Args:
            test_result: Failed test result.
            screenshots: Failure-point screenshots (for Vision API).

        Returns:
            AnalysisResult with cause, suggestion, severity.
        """
        ...

    @abstractmethod
    async def generate_fix(
        self,
        analysis: AnalysisResult,
        source_files: dict[str, str],
    ) -> FixResult:
        """Generate code fix based on analysis.

        Args:
            analysis: Failure analysis result.
            source_files: {file_path: file_content} dict.

        Returns:
            FixResult with description, changed files, confidence.
        """
        ...

    @abstractmethod
    async def generate_scenarios(
        self,
        document_text: str,
        images: list[bytes] | None = None,
    ) -> list[Scenario]:
        """Generate test scenarios from document analysis.

        Args:
            document_text: Spec/design guide text.
            images: Images from the document.

        Returns:
            List of generated Scenario objects.
        """
        ...

    @abstractmethod
    async def analyze_document(
        self,
        document_text: str,
        images: list[bytes] | None = None,
    ) -> dict[str, Any]:
        """Analyze spec document to extract screens/elements/flows.

        Returns:
            dict: {"screens": [...], "elements": [...], "flows": [...]}
        """
        ...
