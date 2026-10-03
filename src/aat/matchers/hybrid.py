"""HybridMatcher — 3-tier chain orchestrator for multiple matchers.

Tier 1: Template matching (OpenCV) — fast, free, uses saved templates
Tier 2: OCR (Tesseract + CLAHE + sharpening) — free, medium speed
Tier 3: Vision AI (Claude API) — expensive, last resort

Successful matches are auto-saved as templates for future Tier 1 matching.
Match history is recorded to SQLite for adaptive method selection.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from aat.core.models import MatchingConfig, MatchMethod
from aat.matchers import template_store
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import MatchResult, TargetSpec
    from aat.learning.store import LearnedStore

logger = logging.getLogger(__name__)

# Map from MatchMethod enum to matcher name for look-up
_METHOD_TO_NAME: dict[MatchMethod, str] = {
    MatchMethod.TEMPLATE: "template",
    MatchMethod.OCR: "ocr",
    MatchMethod.FEATURE: "feature",
    MatchMethod.VISION_AI: "vision_ai",
    # No MatchMethod.LEARNED entry: learned coordinates are the executor's job
    # (Priority 0.4), not a matcher's. See the class docstring.
}

#: Fallback scope when nobody told us which host this run is against.
_DEFAULT_SCOPE = template_store.UNSCOPED


class HybridMatcher(BaseMatcher):
    """3-tier chain orchestrator that delegates to concrete matchers.

    Matching strategy (in order):

    1. **Saved templates** -- Try auto-saved templates from previous runs.
    2. **Chain traversal** -- Walk tiers in order:
       - Tier 1: Template matching (if target.image provided)
       - Tier 2: OCR (enhanced preprocessing)
       - Tier 3: Vision AI (Claude API, expensive)
    3. **Give up** -- Return ``None``.

    After a successful match, the matched region is saved as a template
    for future Tier 1 matching (auto-learning).

    Learned coordinates are *not* consulted here. The step executor applies
    them at its own Priority 0.4 -- below an explicit selector, and only
    reinforced once the step's verification passes (AAT-109). This class once
    documented a learned-first tier, but no call site ever supplied a matcher
    named ``learned``, so the promise was never kept.
    """

    def __init__(
        self,
        matchers: list[BaseMatcher],
        config: MatchingConfig | None = None,
        learned_store: LearnedStore | None = None,
    ) -> None:
        self._matchers = {m.name: m for m in matchers}
        self._config = config or MatchingConfig()
        self._learned_store = learned_store
        self.template_scope = _DEFAULT_SCOPE
        """Which host the banked templates belong to.

        Writable because a scenario may navigate between hosts mid-run, so the
        step executor sets it per step. It is not a constructor argument for
        the same reason: one matcher outlives many pages. Left at
        ``UNSCOPED`` it still works, it just shares a drawer with every other
        unidentified run."""

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

                # Auto-save template on successful match
                self._auto_save_template(target, screenshot, result)

            return result
        except Exception:
            logger.exception("HybridMatcher.find failed")
            return None

    # -- 3-Tier matching with method/fallback support -------------------------

    async def find_with_options(
        self,
        target: TargetSpec,
        screenshot: bytes,
        *,
        method: str = "auto",
        fallback: bool = True,
        learn: bool = True,
    ) -> MatchResult | None:
        """Find with step-level method/fallback/learn options.

        Args:
            target: What to find.
            screenshot: Current screen PNG bytes.
            method: "auto", "template", "ocr", "vision".
            fallback: Allow tier fallback when specific method fails.
            learn: Record match history to pattern DB.
        """
        start = time.perf_counter()
        target_name = target.text or target.image or "unknown"
        result: MatchResult | None = None

        # Check learned best method first (adaptive)
        best_method = None
        if method == "auto" and self._learned_store is not None:
            best_method = self._learned_store.get_best_method(target_name)
            if best_method:
                logger.info(
                    "HybridMatcher: learned best method for '%s' → %s",
                    target_name,
                    best_method,
                )

        if method == "auto":
            # Full 3-tier chain, optionally starting with learned best method
            result = await self._run_3tier(target, screenshot, best_method)
        else:
            # Specific method requested
            result = await self._run_specific(target, screenshot, method)
            if result is None and fallback:
                logger.info(
                    "HybridMatcher: method=%s failed, falling back to full chain",
                    method,
                )
                result = await self._run_3tier(target, screenshot, None)

        elapsed = (time.perf_counter() - start) * 1000.0

        if result is not None:
            result = result.model_copy(update={"elapsed_ms": elapsed})
            self._auto_save_template(target, screenshot, result)

            # Record success to learning DB
            if learn and self._learned_store is not None:
                tier = self._method_to_tier(result.method)
                self._learned_store.record_match(
                    target_name=target_name,
                    method=result.method.value,
                    success=True,
                    confidence=result.confidence,
                    elapsed_ms=elapsed,
                    tier=tier,
                )
                logger.info(
                    "HybridMatcher: ✓ '%s' found via %s (tier %d, %.0fms, conf=%.2f)",
                    target_name,
                    result.method.value,
                    tier,
                    elapsed,
                    result.confidence,
                )

        return result

    async def _run_3tier(
        self,
        target: TargetSpec,
        screenshot: bytes,
        prioritized_method: str | None = None,
    ) -> MatchResult | None:
        """Run the 3-tier matching chain.

        Tier 1: Learned → Saved templates → Template matching
        Tier 2: OCR (enhanced)
        Tier 3: Vision AI
        """
        target_name = target.text or target.image or "unknown"

        # If a prioritized method is known from history, try it first
        if prioritized_method:
            matcher = self._matchers.get(prioritized_method)
            if matcher:
                result = await self._try_matcher(matcher, target, screenshot)
                if result is not None:
                    return result

        # --- Tier 1: Fast / Deterministic ---
        logger.info("HybridMatcher: Tier 1 — Template matching for '%s'", target_name)

        # 1a. Auto-saved template matching
        result = await self._try_saved_template(target, screenshot)
        if result is not None:
            logger.info("HybridMatcher: Tier 1 ✓ via saved template")
            return result

        # 1b. Template matching (if target has image)
        template = self._matchers.get("template")
        if template:
            result = await self._try_matcher(template, target, screenshot)
            if result is not None:
                logger.info("HybridMatcher: Tier 1 ✓ via template matching")
                return result

        # --- Tier 2: OCR ---
        logger.info("HybridMatcher: Tier 2 — OCR for '%s'", target_name)
        ocr = self._matchers.get("ocr")
        if ocr:
            result = await self._try_matcher(ocr, target, screenshot)
            if result is not None:
                logger.info("HybridMatcher: Tier 2 ✓ via OCR")
                return result

        # Feature matching (between Tier 2 and 3)
        feature = self._matchers.get("feature")
        if feature:
            result = await self._try_matcher(feature, target, screenshot)
            if result is not None:
                logger.info("HybridMatcher: Tier 2 ✓ via feature matching")
                return result

        # --- Tier 3: Vision AI (expensive) ---
        vision = self._matchers.get("vision_ai")
        if vision and vision.can_handle(target):
            logger.info("HybridMatcher: Tier 3 — Vision AI for '%s' (cost incurred)", target_name)
            result = await self._try_matcher(vision, target, screenshot)
            if result is not None:
                logger.info("HybridMatcher: Tier 3 ✓ via Vision AI")
                return result

        logger.info("HybridMatcher: all tiers failed for '%s'", target_name)
        return None

    async def _run_specific(
        self,
        target: TargetSpec,
        screenshot: bytes,
        method: str,
    ) -> MatchResult | None:
        """Run a specific method only."""
        method_map = {
            "template": "template",
            "ocr": "ocr",
            "vision": "vision_ai",
        }
        matcher_name = method_map.get(method, method)
        matcher = self._matchers.get(matcher_name)
        if matcher is None:
            logger.warning("HybridMatcher: unknown method '%s'", method)
            return None
        return await self._try_matcher(matcher, target, screenshot)

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
            logger.info(
                "Matcher '%s': %s (confidence: %.2f)",
                matcher.name,
                "FOUND" if result else "not found",
                result.confidence if result else 0.0,
            )
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
        """Legacy chain for backward compatibility (called by find())."""
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

        # Use 3-tier chain
        return await self._run_3tier(target, screenshot)

    # -- Template auto-save ---------------------------------------------------

    def _auto_save_template(
        self,
        target: TargetSpec,
        screenshot: bytes,
        result: MatchResult,
    ) -> None:
        """Bank the matched region so the cheap tier can find it next time.

        Worth doing even though the chain only runs *after* a DOM lookup
        failed: whatever healed this step was the expensive end of the chain
        (OCR, or a paid vision call), and a banked crop means the template tier
        answers next time instead.

        The rectangle is converted from the chain's centre-and-size convention.
        No viewport width is passed because the chain's coordinates were read
        off this very screenshot -- they are already in image pixels, so
        rescaling them would be wrong.
        """
        if result.width == 0 or result.height == 0:
            # No bounding box info — can't crop
            return

        target_name = target.text or target.image or ""
        if not target_name:
            return

        template_store.save(
            self.template_scope,
            target_name,
            screenshot,
            left=result.x - result.width / 2,
            top=result.y - result.height / 2,
            width=result.width,
            height=result.height,
            method=result.method.value,
            confidence=result.confidence,
        )

    async def _try_saved_template(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Try matching against auto-saved templates."""
        target_name = target.text or target.image or ""
        if not target_name:
            return None

        template_path = template_store.lookup(self.template_scope, target_name)
        if template_path is None:
            return None

        # Use TemplateMatcher logic directly
        template = self._matchers.get("template")
        if template is None:
            return None

        try:
            from aat.core.models import TargetSpec

            # Create a temporary target with the saved template image
            temp_target = TargetSpec(image=str(template_path), text=target.text)
            result = await template.find(temp_target, screenshot)
            if result is not None and result.found:
                return result
        except Exception:
            logger.debug("Saved template matching failed", exc_info=True)

        return None

    @staticmethod
    def _method_to_tier(method: MatchMethod) -> int:
        """Map MatchMethod to tier number for logging/stats.

        Tier 0 is the step executor's own DOM work, which happens before the
        chain is consulted. Every member is listed so the map is a complete
        statement rather than a silent fallthrough -- a new method that nobody
        classified would otherwise be filed under tier 0 and read as a DOM hit.
        """
        tier_map = {
            MatchMethod.PLAYWRIGHT: 0,
            MatchMethod.SEMANTICS: 0,
            MatchMethod.LEARNED: 1,
            MatchMethod.TEMPLATE: 1,
            MatchMethod.OCR: 2,
            MatchMethod.FEATURE: 2,
            MatchMethod.VISION_AI: 3,
        }
        return tier_map.get(method, 0)
