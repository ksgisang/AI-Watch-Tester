"""Matcher plugin registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aat.matchers.base import BaseMatcher
from aat.matchers.feature import FeatureMatcher
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.ocr import OCRMatcher
from aat.matchers.template import TemplateMatcher
from aat.matchers.vision_ai import VisionAIMatcher

if TYPE_CHECKING:
    from aat.core.models import MatchingConfig, VisionConfig

logger = logging.getLogger(__name__)

MATCHER_REGISTRY: dict[str, type[BaseMatcher]] = {
    "template": TemplateMatcher,
    "ocr": OCRMatcher,
    "feature": FeatureMatcher,
    "hybrid": HybridMatcher,
    "vision_ai": VisionAIMatcher,
}

# A `chain_order` entry that names no matcher, and why — so the warning can say
# where the work actually happens instead of only that something was dropped.
_NOT_MATCHERS: dict[str, str] = {
    "playwright": (
        "DOM lookup is the step executor's first move and always runs before "
        "the chain. It is a MatchMethod so match_history can tell a selector "
        "hit from a visual one; listing it here does nothing"
    ),
    "learned": (
        "learned coordinates are applied by the step executor, not by the "
        "matcher chain, and deliberately rank below every DOM lookup and "
        "below any picture an earlier run banked (AAT-109). Listing it here "
        "does nothing"
    ),
    "semantics": (
        "Flutter semantics lookup is part of the engine's element search, "
        "not a matcher. Listing it here does nothing"
    ),
    "saved_template": (
        "healing from a banked picture is the first thing the chain tries and "
        "needs no configuring; it reuses the template matcher. It is a "
        "MatchMethod so match_history can show how often healing saved a run. "
        "Listing it here does nothing"
    ),
}


def build_matchers(
    matching: MatchingConfig,
    *,
    vision: VisionConfig | None = None,
    ai: Any = None,
    include_vision: bool = True,
) -> list[BaseMatcher]:
    """Build the matcher chain named by ``matching.chain_order``.

    Six call sites used to assemble this by hand and had drifted apart. Four of
    them built ``VisionAIMatcher(matching)``, which binds a ``MatchingConfig``
    to the ``vision_config`` parameter — every ``can_handle`` call then raised
    ``AttributeError: 'MatchingConfig' object has no attribute 'api_key'``,
    which ``HybridMatcher.find`` swallows. Vision matching was silently dead in
    ``aat start`` and in every dashboard run, and nothing said so.

    An entry that names no matcher is **reported**, not quietly skipped. The
    default chain used to open with ``learned``, which has no registry key, so
    the matcher the config advertised as first priority never existed.

    Pass ``include_vision=False`` for visual-regression commands, which must
    not reach for a paid API behind the user's back.
    """
    matchers: list[BaseMatcher] = []
    for method in matching.chain_order:
        key = method.value
        if key == "vision_ai":
            if include_vision:
                matchers.append(
                    VisionAIMatcher(
                        vision_config=vision,
                        matching_config=matching,
                        ai_config=ai,
                    )
                )
            continue
        cls = MATCHER_REGISTRY.get(key)
        if cls is None or cls is HybridMatcher:
            logger.warning(
                "chain_order lists '%s', which is not a matcher: %s.",
                key,
                _NOT_MATCHERS.get(key, "no matcher is registered under that name"),
            )
            continue
        matchers.append(cls(matching))  # type: ignore[call-arg]

    if include_vision and not any(m.name == "vision_ai" for m in matchers):
        # Tier 3 fallback. It declines every target when no API key is set, so
        # appending it costs nothing when vision is unconfigured.
        matchers.append(
            VisionAIMatcher(
                vision_config=vision,
                matching_config=matching,
                ai_config=ai,
            )
        )
    return matchers


__all__ = [
    "BaseMatcher",
    "FeatureMatcher",
    "HybridMatcher",
    "MATCHER_REGISTRY",
    "OCRMatcher",
    "TemplateMatcher",
    "VisionAIMatcher",
    "build_matchers",
]
