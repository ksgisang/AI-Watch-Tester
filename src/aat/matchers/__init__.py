"""Matcher plugin registry."""

from __future__ import annotations

from aat.matchers.base import BaseMatcher
from aat.matchers.feature import FeatureMatcher
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.ocr import OCRMatcher
from aat.matchers.template import TemplateMatcher
from aat.matchers.vision_ai import VisionAIMatcher

MATCHER_REGISTRY: dict[str, type[BaseMatcher]] = {
    "template": TemplateMatcher,
    "ocr": OCRMatcher,
    "feature": FeatureMatcher,
    "hybrid": HybridMatcher,
    "vision_ai": VisionAIMatcher,
}

__all__ = [
    "BaseMatcher",
    "FeatureMatcher",
    "HybridMatcher",
    "MATCHER_REGISTRY",
    "OCRMatcher",
    "TemplateMatcher",
    "VisionAIMatcher",
]
