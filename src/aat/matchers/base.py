"""BaseMatcher ABC — image matching interface.

TemplateMatcher, OCRMatcher, FeatureMatcher etc. implement this.
HybridMatcher injects list[BaseMatcher] via constructor to form a chain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aat.core.models import MatchResult, TargetSpec


class BaseMatcher(ABC):
    """Image matching abstract interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Matcher name for logging/debugging: 'template', 'ocr', 'feature'."""
        ...

    @abstractmethod
    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find target in screenshot.

        Args:
            target: What to find (image path, text, etc.)
            screenshot: Current screen PNG bytes.

        Returns:
            MatchResult if found (coordinates + confidence), None otherwise.
        """
        ...

    @abstractmethod
    def can_handle(self, target: TargetSpec) -> bool:
        """Whether this matcher can handle the given target.

        e.g. TemplateMatcher requires target.image,
             OCRMatcher requires target.text.
        """
        ...
