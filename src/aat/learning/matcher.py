"""LearnedMatcher — matching based on learned data."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from aat.core.models import MatchMethod, MatchResult
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import TargetSpec
    from aat.learning.store import LearnedStore

logger = logging.getLogger(__name__)


class LearnedMatcher(BaseMatcher):
    """Match UI elements using previously learned positions.

    Queries a :class:`LearnedStore` by screenshot hash, then filters
    by target name. A hit increments the stored use count.
    """

    def __init__(self, store: LearnedStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "learned"

    def can_handle(self, target: TargetSpec) -> bool:
        """Always returns True — learned data is tried first in the chain."""
        return True

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find target in screenshot using learned data.

        1. Compute MD5 hash of screenshot.
        2. Query store by hash.
        3. Filter results by target name (image or text).
        4. If found, increment use_count and return MatchResult.
        """
        screenshot_hash = hashlib.md5(screenshot).hexdigest()  # noqa: S324
        elements = self._store.find_by_hash(screenshot_hash)

        target_name = target.image or target.text or ""
        for elem in elements:
            if elem.target_name == target_name:
                if elem.id is not None:
                    self._store.increment_use_count(elem.id)
                return MatchResult(
                    found=True,
                    x=elem.correct_x,
                    y=elem.correct_y,
                    confidence=elem.confidence,
                    method=MatchMethod.LEARNED,
                )

        return None
