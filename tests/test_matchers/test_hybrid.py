"""Tests for HybridMatcher."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from aat.core.models import (
    IconHint,
    MatchingConfig,
    MatchMethod,
    MatchResult,
    TargetSpec,
)
from aat.matchers import template_store
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


class TestMethodToTier:
    """Tier 0 is the executor's own DOM work, before the chain is consulted.

    The map used to fall through to 0 for anything it had not classified, so a
    method nobody tiered would be filed alongside DOM hits and read as one.
    """

    @pytest.mark.parametrize(
        ("method", "tier"),
        [
            (MatchMethod.PLAYWRIGHT, 0),
            (MatchMethod.SEMANTICS, 0),
            (MatchMethod.LEARNED, 1),
            (MatchMethod.TEMPLATE, 1),
            (MatchMethod.SAVED_TEMPLATE, 1),
            (MatchMethod.OCR, 2),
            (MatchMethod.FEATURE, 2),
            (MatchMethod.VISION_AI, 3),
        ],
    )
    def test_every_method_has_a_tier(self, method: MatchMethod, tier: int) -> None:
        assert HybridMatcher._method_to_tier(method) == tier

    def test_no_method_is_left_unclassified(self) -> None:
        """Parametrising above is only exhaustive if it covers the enum."""
        assert len(list(MatchMethod)) == 8


# ── healing from a banked picture ───────────────────────────────────────────


class TestHealFromBankedPicture:
    """The heal has to be distinguishable from an ordinary image match.

    ``TemplateMatcher`` reports ``TEMPLATE`` whether the image came from the
    scenario or from a crop AWT banked itself. Those are different events: one
    is the author supplying a picture, the other is "the selector in this
    scenario is stale and a picture from an earlier run rescued the run". Only
    the second is the self-healing claim, so only a separate label makes it
    countable.
    """

    @staticmethod
    def _hybrid(*, found: MatchResult | None = _FOUND) -> HybridMatcher:
        template = StubMatcher("template", handles_image=True, result=found)
        hybrid = HybridMatcher([template])
        hybrid.template_scope = "example.com"
        return hybrid

    @staticmethod
    def _bank(name: str, scope: str = "example.com") -> None:
        img = np.full((40, 60, 3), 70, dtype=np.uint8)
        saved = template_store.save(
            scope,
            name,
            bytes(cv2.imencode(".png", img)[1]),
            left=0,
            top=0,
            width=60,
            height=40,
            method="playwright",
            confidence=0.95,
        )
        assert saved is not None, "the fixture itself must bank something"

    @pytest.mark.asyncio
    async def test_a_hit_from_a_banked_picture_is_labelled_as_a_heal(self) -> None:
        self._bank("#submit")
        hybrid = self._hybrid()

        result = await hybrid.find_saved_template(TargetSpec(selector="#submit"), _SCREENSHOT)

        assert result is not None
        assert result.method == MatchMethod.SAVED_TEMPLATE

    @pytest.mark.asyncio
    async def test_a_selector_only_target_is_looked_up_by_its_selector(self) -> None:
        """The regression that made banking pointless for the case it exists for.

        The lookup name used to be ``text or image``, so a step named only by a
        selector never matched the picture the executor banked under that
        selector. A renamed selector *is* the failure healing addresses, so this
        was the whole population of interest.
        """
        self._bank("#submit")
        hybrid = self._hybrid()

        assert (
            await hybrid.find_saved_template(TargetSpec(selector="#submit"), _SCREENSHOT)
        ) is not None

    @pytest.mark.asyncio
    async def test_nothing_banked_means_the_matcher_is_never_asked(self) -> None:
        """A file-exists check is cheap; decoding a screenshot is not."""
        template = StubMatcher("template", handles_image=True, result=_FOUND)
        hybrid = HybridMatcher([template])
        hybrid.template_scope = "example.com"

        assert (
            await hybrid.find_saved_template(TargetSpec(selector="#submit"), _SCREENSHOT)
        ) is None
        assert template.find_called is False

    @pytest.mark.asyncio
    async def test_a_picture_banked_for_another_host_does_not_answer(self) -> None:
        """One application's "확인" button must not be matched against another's."""
        self._bank("#submit", scope="other.example.org")
        hybrid = self._hybrid()

        assert (
            await hybrid.find_saved_template(TargetSpec(selector="#submit"), _SCREENSHOT)
        ) is None

    @pytest.mark.asyncio
    async def test_an_icon_only_target_is_not_looked_up(self) -> None:
        """``icon`` is still a stub, so it is not yet a name to file a picture under."""
        hybrid = self._hybrid()
        icon_only = TargetSpec(icon=IconHint(description="a gear"))

        assert (await hybrid.find_saved_template(icon_only, _SCREENSHOT)) is None

    @pytest.mark.asyncio
    async def test_a_label_is_preferred_over_a_selector_as_the_name(self) -> None:
        """A caption outlives the class rename that broke the selector."""
        self._bank("Submit")
        hybrid = self._hybrid()

        result = await hybrid.find_saved_template(
            TargetSpec(selector=".btn-primary-v2", text="Submit"),
            _SCREENSHOT,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_the_chain_tries_the_banked_picture_before_ocr(self) -> None:
        """Healing is tier 1. Reaching OCR first would pay for what a crop answers."""
        self._bank("Submit")
        template = StubMatcher("template", handles_image=True, result=_FOUND)
        ocr = StubMatcher("ocr", handles_text=True, result=_FOUND_OCR)
        hybrid = HybridMatcher([template, ocr])
        hybrid.template_scope = "example.com"

        result = await hybrid.find_with_options(
            TargetSpec(selector="#submit", text="Submit"),
            _SCREENSHOT,
        )

        assert result is not None
        assert result.method == MatchMethod.SAVED_TEMPLATE
        assert ocr.find_called is False

    def test_a_heal_does_not_rewrite_the_picture_it_healed_from(self) -> None:
        """Re-banking from a heal lets the crop walk off the element.

        Template matching answers with where it *thinks* the element is. Bank
        that, and the next heal re-centres on this heal's error; a few runs of
        small drift add up to a picture of the element's neighbour. The original
        crop came from a DOM rectangle, which is exact, so it is kept.
        """
        self._bank("#submit")
        before = template_store.path_for("example.com", "#submit").read_bytes()
        hybrid = self._hybrid()
        healed = _FOUND.model_copy(update={"method": MatchMethod.SAVED_TEMPLATE})

        hybrid._auto_save_template(TargetSpec(selector="#submit"), _SCREENSHOT, healed)

        assert template_store.path_for("example.com", "#submit").read_bytes() == before

    def test_an_ordinary_chain_hit_still_banks(self) -> None:
        """The control for the test above: the guard must be about heals only.

        OCR or a paid vision call finding the element is exactly the case worth
        photographing, so that next time the cheap tier answers instead.
        """
        hybrid = self._hybrid()
        screen = bytes(cv2.imencode(".png", np.full((240, 320, 3), 30, dtype=np.uint8))[1])
        found_by_ocr = _FOUND_OCR.model_copy(update={"x": 100, "y": 100})

        hybrid._auto_save_template(TargetSpec(text="Submit"), screen, found_by_ocr)

        assert template_store.lookup("example.com", "Submit") is not None
