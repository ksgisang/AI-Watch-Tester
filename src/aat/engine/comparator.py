"""Comparator — ExpectedResult evaluation against engine state.

Checks assertions like text_visible, url_contains, screenshot_match
against the current state of the test engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from aat.core.exceptions import StepExecutionError
from aat.core.models import AssertType, ExpectedResult

if TYPE_CHECKING:
    from aat.core.models import StepConfig
    from aat.engine.base import BaseEngine


class Comparator:
    """Compare expected results against actual engine state."""

    async def check(self, expected: ExpectedResult, engine: BaseEngine) -> None:
        """Verify an expected result. Raises StepExecutionError on failure.

        Args:
            expected: Expected result assertion.
            engine: BaseEngine instance for querying current state.
        """
        if expected.type == AssertType.TEXT_VISIBLE:
            page_text = await engine.get_page_text()
            if expected.value not in page_text:
                raise StepExecutionError(
                    f"Text '{expected.value}' not visible on page",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.TEXT_EQUALS:
            page_text = await engine.get_page_text()
            if expected.value != page_text.strip():
                raise StepExecutionError(
                    f"Text does not match '{expected.value}'",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.URL_CONTAINS:
            current_url = await engine.get_url()
            if expected.value not in current_url:
                raise StepExecutionError(
                    f"URL does not contain '{expected.value}'. "
                    f"Current: {current_url}",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.IMAGE_VISIBLE:
            # IMAGE_VISIBLE is handled at StepExecutor level via assert step.
            # Comparator passes through (no-op for now).
            pass

        elif expected.type == AssertType.SCREENSHOT_MATCH:
            screenshot = await engine.screenshot()
            similarity = self._compare_screenshots(screenshot, expected.value)
            threshold = 1.0 - expected.tolerance
            if similarity < threshold:
                raise StepExecutionError(
                    f"Screenshot similarity {similarity:.2%} "
                    f"below threshold {threshold:.2%}",
                    step=0,
                    action="assert",
                )

    async def check_assert(self, step: StepConfig, engine: BaseEngine) -> None:
        """Assert action handler. Uses step.assert_type and step.value.

        Args:
            step: StepConfig with assert_type and value.
            engine: BaseEngine instance.
        """
        assert step.assert_type is not None  # noqa: S101
        assert step.value is not None  # noqa: S101
        expected = ExpectedResult(type=step.assert_type, value=step.value)
        await self.check(expected, engine)

    @staticmethod
    def _compare_screenshots(current: bytes, reference_path: str) -> float:
        """Compare current screenshot with reference using normalized correlation.

        Args:
            current: Current screenshot as PNG bytes.
            reference_path: Path to reference screenshot image.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        img1 = cv2.imdecode(
            np.frombuffer(current, np.uint8),
            cv2.IMREAD_GRAYSCALE,
        )
        img2 = cv2.imread(reference_path, cv2.IMREAD_GRAYSCALE)
        if img2 is None:
            raise StepExecutionError(
                f"Reference screenshot '{reference_path}' not found",
                step=0,
                action="assert",
            )
        if img1 is None:
            raise StepExecutionError(
                "Failed to decode current screenshot",
                step=0,
                action="assert",
            )
        # Resize reference to match current
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        result = cv2.matchTemplate(img1, img2, cv2.TM_CCORR_NORMED)
        return float(result[0][0])
