"""VisionAIMatcher — AI vision-based matching (stub)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import MatchResult, TargetSpec


class VisionAIMatcher(BaseMatcher):
    """AI vision-based element matching (stub).

    Will be implemented when Vision AI integration is ready.
    """

    @property
    def name(self) -> str:
        return "vision_ai"

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Stub — always returns None."""
        return None

    def can_handle(self, target: TargetSpec) -> bool:
        """Stub — always returns False."""
        return False
