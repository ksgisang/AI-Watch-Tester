"""Tests for HybridMatcher."""

from __future__ import annotations

import pytest

from aat.core.models import MatchingConfig, MatchMethod, MatchResult, TargetSpec
from aat.matchers.base import BaseMatcher
from aat.matchers.hybrid import HybridMatcher

# ── stub matchers ────────────────────────────────────────────────────────────


class StubMatcher(BaseMatcher):
    """Configurable stub matcher for testing HybridMatcher chains."""

    def __init__(
        self,
        matcher_name: str,
        handles_image: bool = False,
        handles_text: bool = False,
        result: MatchResult | None = None,
    ) -> None:
        self._name = matcher_name
        self._handles_image = handles_image
        self._handles_text = handles_text
        self._result = result
        self.find_called = False

    @property
    def name(self) -> str:
        return self._name

    def can_handle(self, target: TargetSpec) -> bool:
        if self._handles_image and target.image is not None:
            return True
        return bool(self._handles_text and target.text is not None)

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        self.find_called = True
        return self._result


class RaisingMatcher(BaseMatcher):
    """Matcher that raises on find(), for error-handling tests."""

    @property
    def name(self) -> str:
        return "raising"

    def can_handle(self, target: TargetSpec) -> bool:
        return True

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        msg = "Boom!"
        raise RuntimeError(msg)


# ── helpers ──────────────────────────────────────────────────────────────────

_FOUND = MatchResult(
    found=True,
    x=100,
    y=200,
    width=50,
    height=30,
    confidence=0.95,
    method=MatchMethod.TEMPLATE,
    elapsed_ms=1.0,
)

_FOUND_OCR = MatchResult(
    found=True,
    x=300,
    y=400,
    width=80,
    height=20,
    confidence=0.90,
    method=MatchMethod.OCR,
    elapsed_ms=2.0,
)

_SCREENSHOT = b"\x89PNG fake screenshot bytes"


# ── can_handle ───────────────────────────────────────────────────────────────


class TestCanHandle:
    def test_delegates_to_children(self) -> None:
        m1 = StubMatcher("template", handles_image=True)
        hybrid = HybridMatcher([m1])
        assert hybrid.can_handle(TargetSpec(image="x.png")) is True
        assert hybrid.can_handle(TargetSpec(text="hello")) is False

    def test_empty_matchers(self) -> None:
        hybrid = HybridMatcher([])
        assert hybrid.can_handle(TargetSpec(text="hello")) is False


# ── Phase 1: explicit match_method ──────────────────────────────────────────


class TestPhase1:
    @pytest.mark.asyncio()
    async def test_explicit_method_used(self) -> None:
        """When target.match_method is set, only that matcher is tried."""
        tmpl = StubMatcher("template", handles_image=True, result=_FOUND)
        ocr = StubMatcher("ocr", handles_text=True, result=_FOUND_OCR)

        config = MatchingConfig(chain_order=[MatchMethod.TEMPLATE, MatchMethod.OCR])
        hybrid = HybridMatcher([tmpl, ocr], config=config)

        target = TargetSpec(image="x.png", text="hello", match_method=MatchMethod.TEMPLATE)
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is not None
        assert result.found is True
        assert tmpl.find_called is True
        assert ocr.find_called is False

    @pytest.mark.asyncio()
    async def test_explicit_method_not_registered(self) -> None:
        """If the requested method has no matcher registered, return None."""
        tmpl = StubMatcher("template", handles_image=True, result=_FOUND)
        hybrid = HybridMatcher([tmpl])

        target = TargetSpec(text="hello", match_method=MatchMethod.VISION_AI)
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is None


# ── Phase 2: chain traversal ────────────────────────────────────────────────


class TestPhase2:
    @pytest.mark.asyncio()
    async def test_chain_first_success_wins(self) -> None:
        """Chain returns first successful result."""
        tmpl = StubMatcher("template", handles_image=True, result=None)
        feature = StubMatcher("feature", handles_image=True, result=_FOUND)

        config = MatchingConfig(
            chain_order=[MatchMethod.TEMPLATE, MatchMethod.FEATURE],
        )
        hybrid = HybridMatcher([tmpl, feature], config=config)

        target = TargetSpec(image="x.png")
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is not None
        assert result.found is True
        assert tmpl.find_called is True
        assert feature.find_called is True

    @pytest.mark.asyncio()
    async def test_chain_all_fail(self) -> None:
        """If all matchers in the chain fail, result is None."""
        tmpl = StubMatcher("template", handles_image=True, result=None)
        feature = StubMatcher("feature", handles_image=True, result=None)

        config = MatchingConfig(
            chain_order=[MatchMethod.TEMPLATE, MatchMethod.FEATURE],
        )
        hybrid = HybridMatcher([tmpl, feature], config=config)

        target = TargetSpec(image="x.png")
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is None

    @pytest.mark.asyncio()
    async def test_skips_matcher_that_cannot_handle(self) -> None:
        """Matchers whose can_handle is False are skipped."""
        ocr = StubMatcher("ocr", handles_text=True, result=_FOUND_OCR)

        config = MatchingConfig(chain_order=[MatchMethod.OCR])
        hybrid = HybridMatcher([ocr], config=config)

        target = TargetSpec(image="x.png")  # OCR can't handle image-only
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is None
        assert ocr.find_called is False


# ── Phase 3: text fallback ──────────────────────────────────────────────────


class TestPhase3:
    @pytest.mark.asyncio()
    async def test_fallback_to_ocr(self) -> None:
        """If image matchers fail, OCR is tried as fallback for targets with text."""
        tmpl = StubMatcher("template", handles_image=True, result=None)
        ocr = StubMatcher("ocr", handles_text=True, result=_FOUND_OCR)

        config = MatchingConfig(chain_order=[MatchMethod.TEMPLATE])
        hybrid = HybridMatcher([tmpl, ocr], config=config)

        target = TargetSpec(image="x.png", text="Login")
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is not None
        assert result.found is True
        assert ocr.find_called is True

    @pytest.mark.asyncio()
    async def test_no_fallback_when_no_text(self) -> None:
        """No text fallback when target has only an image."""
        tmpl = StubMatcher("template", handles_image=True, result=None)
        ocr = StubMatcher("ocr", handles_text=True, result=_FOUND_OCR)

        config = MatchingConfig(chain_order=[MatchMethod.TEMPLATE])
        hybrid = HybridMatcher([tmpl, ocr], config=config)

        target = TargetSpec(image="x.png")
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is None


# ── error handling ───────────────────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio()
    async def test_raising_matcher_returns_none(self) -> None:
        """A matcher that raises should be caught; chain continues."""
        raising = RaisingMatcher()
        tmpl = StubMatcher("template", handles_image=True, result=_FOUND)

        config = MatchingConfig(chain_order=[MatchMethod.TEMPLATE])
        hybrid = HybridMatcher([raising, tmpl], config=config)

        target = TargetSpec(image="x.png")
        result = await hybrid.find(target, _SCREENSHOT)

        assert result is not None
        assert result.found is True


# ── name ─────────────────────────────────────────────────────────────────────


class TestName:
    def test_name_is_hybrid(self) -> None:
        assert HybridMatcher([]).name == "hybrid"
