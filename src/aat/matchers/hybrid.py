"""HybridMatcher — chain orchestrator for multiple matchers."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from aat.core.models import MatchingConfig, MatchMethod
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import MatchResult, TargetSpec

logger = logging.getLogger(__name__)

# Map from MatchMethod enum to matcher name for look-up
_METHOD_TO_NAME: dict[MatchMethod, str] = {
    MatchMethod.TEMPLATE: "template",
    MatchMethod.OCR: "ocr",
    MatchMethod.FEATURE: "feature",
    MatchMethod.VISION_AI: "vision_ai",
    MatchMethod.LEARNED: "learned",
}


class HybridMatcher(BaseMatcher):
    """Chain orchestrator that delegates to concrete matchers.

    Matching strategy (in order):

    1. **Explicit method** -- If ``target.match_method`` is set, use only
       the matching matcher.
    2. **Chain traversal** -- Walk ``config.chain_order`` and try each matcher
       that ``can_handle`` the target.  Return the first successful match.
    3. **Text fallback** -- If image-based matching failed and the target
       also carries ``text``, try the OCR matcher.
    4. **Give up** -- Return ``None``.
    """

    def __init__(
        self,
        matchers: list[BaseMatcher],
        config: MatchingConfig | None = None,
    ) -> None:
        self._matchers = {m.name: m for m in matchers}
        self._config = config or MatchingConfig()

    # -- BaseMatcher interface ------------------------------------------------

    @property
    def name(self) -> str:
        return "hybrid"

    def can_handle(self, target: TargetSpec) -> bool:
        """HybridMatcher can handle anything its children can handle."""
        return any(m.can_handle(target) for m in self._matchers.values())

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Orchestrate matching across all registered matchers."""
        start = time.perf_counter()
        try:
            result = await self._run_chain(target, screenshot)
            if result is not None:
                # Override elapsed_ms to reflect total chain time
                elapsed = (time.perf_counter() - start) * 1000.0
                result = result.model_copy(update={"elapsed_ms": elapsed})
            return result
        except Exception:
            logger.exception("HybridMatcher.find failed")
            return None

    # -- internal helpers -----------------------------------------------------

    def _get_matcher(self, method: MatchMethod) -> BaseMatcher | None:
        """Resolve a MatchMethod to a registered matcher."""
        matcher_name = _METHOD_TO_NAME.get(method)
        if matcher_name is None:
            return None
        return self._matchers.get(matcher_name)

    async def _try_matcher(
        self,
        matcher: BaseMatcher,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Safely try a single matcher; return None on any failure."""
        try:
            if not matcher.can_handle(target):
                return None
            result = await matcher.find(target, screenshot)
            if result is not None and result.found:
                logger.debug("HybridMatcher: match via %s", matcher.name)
                return result
        except Exception:
            logger.exception("HybridMatcher: %s raised", matcher.name)
        return None

    async def _run_chain(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        # Phase 1: explicit match_method
        if target.match_method is not None:
            matcher = self._get_matcher(target.match_method)
            if matcher is not None:
                return await self._try_matcher(matcher, target, screenshot)
            logger.warning(
                "No matcher registered for method=%s",
                target.match_method,
            )
            return None

        # Phase 2: chain traversal in configured order
        for method in self._config.chain_order:
            matcher = self._get_matcher(method)
            if matcher is None:
                continue
            result = await self._try_matcher(matcher, target, screenshot)
            if result is not None:
                return result

        # Phase 3: text fallback (OCR) if target has both image and text
        # and image-based matching didn't succeed
        if target.image is not None and target.text is not None:
            ocr = self._matchers.get("ocr")
            if ocr is not None:
                result = await self._try_matcher(ocr, target, screenshot)
                if result is not None:
                    return result

        # Phase 4: give up
        return None
