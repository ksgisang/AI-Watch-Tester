"""Does AWT actually capture scrolled pixels? Asked of a real Chromium.

AAT-121. Every screenshot this product takes is the viewport, and nothing
scrolled and re-captured, so a target the DOM could not name and that sat
below the fold was invisible to the matcher chain, to healing, and to the
`text_visible` OCR fallback. The report said "not found", which is a false
failure about a page that is perfectly fine.

A mock cannot answer any of this. The questions are "what does Chromium put in
a PNG after a wheel event", "does `window.scrollY` move for an inner overflow
container", and "does the page end up where it started afterwards" -- and a
mock answers whatever the test told it to. So this file drives a real browser
against a real local page and reads the pixels.

The two layouts in the fixture are not redundant:

  * `mode=document` scrolls the document, so `window.scrollY` moves. An
    implementation that decided "did it move?" from `scrollY` looks correct
    here.
  * `mode=canvas` scrolls an inner box while `window.scrollY` stays 0 forever.
    This is the shape of a Flutter CanvasKit app. A `scrollY`-based
    implementation does nothing at all here -- on exactly the pages the
    feature exists for. That is why the sweep decides from pixels.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest

from aat.core.exceptions import StepExecutionError
from aat.core.models import (
    ActionType,
    AssertType,
    EngineConfig,
    ExpectedResult,
    MatchingConfig,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.sweep import sweep_viewports
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.template import TemplateMatcher
from tests.fixtures.below_the_fold_server import (
    ABOVE_TEXT,
    TARGET_TEXT,
    below_the_fold_server,
)


def _has_tesseract() -> bool:
    """Only the English binary is needed: the target phrase is Latin.

    The skip is for a contributor without the package, not for CI -- AAT-119
    is the record of what a missing Tesseract looks like from the outside,
    which is a step reporting that perfectly visible text is "not visible on
    page". A red test that blames their code for that teaches them to stop
    reading the suite.
    """
    try:
        import pytesseract

        return bool(pytesseract.get_languages(config=""))
    except Exception:
        return False


requires_tesseract = pytest.mark.skipif(
    not _has_tesseract(),
    reason="tesseract missing (apt: tesseract-ocr, brew: tesseract)",
)


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with below_the_fold_server() as url:
        yield url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    eng = WebEngine(
        EngineConfig(
            headless=True,
            speed="fast",
            screenshot_mode="off",
            viewport_width=900,
            viewport_height=600,
        )
    )
    try:
        await eng.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    try:
        yield eng
    finally:
        await eng.stop()


def _executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    return StepExecutor(
        engine,
        HybridMatcher([TemplateMatcher(MatchingConfig())]),
        Humanizer(),
        Waiter(),
        Comparator(),
        tmp_path,
    )


def _brightness(shot: bytes) -> float:
    """Mean grey level. The target block is a bright yellow band, so this is
    enough to tell "the target is on screen" from "it is not" without OCR."""
    img = cv2.imdecode(np.frombuffer(shot, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert img is not None
    return float(np.mean(img))


def _yellow_mask(img: np.ndarray) -> np.ndarray:
    """Pixels belonging to the target's #ffd34d band.

    BGR for #ffd34d is (77, 211, 255). The hue is unique on the page, so this
    answers "is the target in this frame" by reading pixels rather than by
    running OCR -- which would add a second thing that can fail to a test
    whose only question is whether the capture contains the scrolled content.
    """
    b, g, r = cv2.split(img)
    return (r > 230) & (g > 185) & (g < 235) & (b < 120)


def _has_yellow_band(shot: bytes) -> bool:
    """Whether the target's #ffd34d band is in this frame."""
    img = cv2.imdecode(np.frombuffer(shot, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return bool(np.count_nonzero(_yellow_mask(img)) > 2_000)


async def _crop_the_target_then_return_to_the_top(
    engine: WebEngine, tmp_path: Path
) -> Path:
    """Scroll down, cut a picture of the target out of the screen, scroll back.

    This is how the chain gets a target the DOM cannot answer. An image target
    has no selector and no text, so every DOM route is skipped by
    construction and the matcher chain is the only thing that can find it --
    which makes it the one target that proves the chain itself looks below the
    fold, rather than proving Playwright can find off-screen elements.

    The wheel is used rather than ``scrollIntoView`` so the same helper works
    in the canvas layout, where the document never scrolls at all.
    """
    shot = await engine.screenshot()
    img = cv2.imdecode(np.frombuffer(shot, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    rows = np.nonzero(_yellow_mask(img).any(axis=1))[0]
    turns = 0
    # Keep going until the band is not merely visible but fully in frame: a
    # crop taken from a band clipped by the viewport edge is a picture of
    # something that is not on the page, and it would never match again.
    while rows.size < 80 and turns < 20:
        await engine.scroll(450, 300, 500)
        await engine.page.wait_for_timeout(150)
        shot = await engine.screenshot()
        img = cv2.imdecode(np.frombuffer(shot, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        rows = np.nonzero(_yellow_mask(img).any(axis=1))[0]
        turns += 1
    assert rows.size >= 80, "the fixture never brought the whole target into frame"

    top = int(rows[0])
    # Inset so the crop carries the lettering rather than flat colour -- a
    # plain yellow rectangle would match any part of the band.
    crop = img[top + 8 : top + 72, 20:320]
    path = tmp_path / "target_crop.png"
    assert cv2.imwrite(str(path), crop)

    for _ in range(turns):
        await engine.scroll(450, 300, -500)
    await engine.page.evaluate("() => window.scrollTo(0, 0)")
    await engine.page.wait_for_timeout(200)
    assert not _has_yellow_band(await engine.screenshot()), "failed to get back to the top"
    return path


class TestTheProblemIsReal:
    """Before claiming a fix, pin the thing being fixed."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["document", "canvas"])
    async def test_a_single_screenshot_does_not_contain_the_target(
        self, engine: WebEngine, base_url: str, mode: str
    ) -> None:
        """One capture at the fold cannot see three screens down.

        This is the defect in one line. If this test ever goes green on its
        own -- say because someone switches `screenshot()` to `full_page` --
        the sweep is not what is being measured any more and these tests must
        be re-read rather than trusted.
        """
        await engine.navigate(f"{base_url}/?mode={mode}")
        shot = await engine.screenshot()
        assert not _has_yellow_band(shot)

    @pytest.mark.asyncio
    async def test_the_canvas_layout_never_moves_window_scrolly(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The reason the sweep cannot use `scrollY` as its signal.

        The pixels move and the offset does not. Any implementation that asks
        the document where it is concludes this page does not scroll.
        """
        await engine.navigate(f"{base_url}/?mode=canvas")
        before = await engine.screenshot()
        await engine.scroll(450, 300, 500)
        after = await engine.screenshot()

        assert await engine.page.evaluate("() => window.scrollY") == 0
        assert _brightness(before) != _brightness(after), "but the pixels did move"

    @pytest.mark.asyncio
    async def test_the_document_layout_does_move_window_scrolly(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The control. Without it, the test above proves nothing about the
        fixture -- a page that simply refused to scroll would also pass it.

        The settle is not decoration: `mouse.wheel` returns once the event is
        dispatched, so reading the offset immediately reads it before the
        scroll has been applied. The canvas test above happens to be safe from
        that only because two screenshots pass the time for it.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        await engine.scroll(450, 300, 500)
        await engine.page.wait_for_timeout(300)
        assert await engine.page.evaluate("() => window.scrollY") > 0


class TestTheSweepCapturesScrolledPixels:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["document", "canvas"])
    async def test_a_frame_containing_the_target_reaches_the_probe(
        self, engine: WebEngine, base_url: str, mode: str
    ) -> None:
        """The claim in its most direct form: scrolled content is captured.

        The probe is handed real PNG bytes from a real browser, and one of
        them contains a band that was not on screen when the sweep started.
        """
        await engine.navigate(f"{base_url}/?mode={mode}")
        frames: list[bytes] = []

        async def probe(frame: bytes) -> bytes | None:
            frames.append(frame)
            return frame if _has_yellow_band(frame) else None

        hit = await sweep_viewports(engine, probe)
        assert hit is not None, f"{mode}: the sweep never captured the target"
        assert not _has_yellow_band(frames[0]), "it was not visible to begin with"
        assert len(frames) > 1, "so it took scrolling to see it"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["document", "canvas"])
    async def test_the_page_is_put_back_when_nothing_matches(
        self, engine: WebEngine, base_url: str, mode: str
    ) -> None:
        """A failed lookup must not leave the app scrolled somewhere else.

        The next step would act on a screen the scenario never asked for, and
        the evidence screenshot would show it. Compared on pixels because that
        is the only comparison the canvas layout can answer.
        """
        await engine.navigate(f"{base_url}/?mode={mode}")
        start = await engine.screenshot()

        async def never(_frame: bytes) -> None:
            return None

        assert await sweep_viewports(engine, never, max_screens=3) is None
        end = await engine.screenshot()
        assert abs(_brightness(start) - _brightness(end)) < 1.0, (
            f"{mode}: the sweep left the page somewhere else"
        )

    @pytest.mark.asyncio
    async def test_it_stops_at_the_bottom_rather_than_running_to_the_cap(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The end-of-page signal works on a real page, not just a test double.

        Without it, every failing lookup on every short page would pay for ten
        screenshots and ten matches.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        seen = 0

        async def count(_frame: bytes) -> None:
            nonlocal seen
            seen += 1
            return None

        await sweep_viewports(engine, count, max_screens=40)
        # The fixture is about 2,900px tall against a 600px viewport, so the
        # floor arrives after roughly six screens. The generous bound is
        # deliberate: this asserts "it stopped", not a pixel-exact page height.
        assert 3 < seen < 15, f"swept {seen} screens"


class TestTextVisibleReachesBelowTheFold:
    """The assertion path, end to end, through `Comparator.check`.

    Two routes, and the difference between them is the whole point. For
    ordinary HTML the DOM answers and the OCR fallback never runs, so those
    cases pin that the sweep did not change what was already working. The
    `?paint=image` page has the words in pixels only, which is the one shape
    where the fallback is the sole route -- and before this sweep it could only
    read the first screen, so text one scroll down came back "not visible on
    page" about a page that was perfectly fine.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["document", "canvas"])
    async def test_dom_text_below_the_fold_still_passes_without_scrolling(
        self, engine: WebEngine, base_url: str, mode: str
    ) -> None:
        """`inner_text("body")` was never limited to the viewport.

        Worth pinning precisely because it makes the sweep look unnecessary
        for ordinary HTML: the OCR fallback is for text that is in neither the
        DOM nor the first screen, and nothing else.
        """
        await engine.navigate(f"{base_url}/?mode={mode}")
        comparator = Comparator()
        await comparator.check(
            ExpectedResult(type=AssertType.TEXT_VISIBLE, value=TARGET_TEXT), engine
        )

    @pytest.mark.asyncio
    async def test_text_that_is_nowhere_still_fails(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The negative. A sweep that reported success for absent text would
        turn every `text_visible` into a no-op, and the suite would be green."""
        await engine.navigate(f"{base_url}/?mode=document")
        comparator = Comparator()
        with pytest.raises(StepExecutionError):
            await comparator.check(
                ExpectedResult(type=AssertType.TEXT_VISIBLE, value="NO SUCH PHRASE"),
                engine,
            )

    @pytest.mark.asyncio
    @requires_tesseract
    async def test_pixel_only_text_below_the_fold_is_read_by_ocr(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The case this whole change exists for.

        The words are baked into a PNG, so `inner_text("body")` cannot see
        them and no selector can name them -- the OCR fallback is the only
        route. And they sit two screens down, so reading the first capture is
        not enough. Un-wire the sweep from `_ocr_text_check` and this is the
        test that goes red.
        """
        await engine.navigate(f"{base_url}/?mode=document&paint=image&filler=4")
        assert TARGET_TEXT not in await engine.get_page_text(), (
            "the fixture leaked the target into the DOM, so this would pass "
            "without OCR running at all"
        )
        await Comparator().check(
            ExpectedResult(type=AssertType.TEXT_VISIBLE, value=TARGET_TEXT), engine
        )

    @pytest.mark.asyncio
    @requires_tesseract
    async def test_the_sweep_puts_the_page_back_when_ocr_finds_nothing(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """A failing assertion must not leave the page scrolled.

        The screenshot that documents the failure is taken after the check,
        and so are the steps that follow it. If a miss left the page wherever
        the sweep stopped, a single absent phrase would silently relocate
        everything after it.
        """
        await engine.navigate(f"{base_url}/?mode=document&paint=image&filler=4")
        before = await engine.page.evaluate("() => window.scrollY")
        with pytest.raises(StepExecutionError):
            await Comparator().check(
                ExpectedResult(type=AssertType.TEXT_VISIBLE, value="NO SUCH PHRASE"),
                engine,
            )
        assert await engine.page.evaluate("() => window.scrollY") == before

    @pytest.mark.asyncio
    @requires_tesseract
    async def test_the_ocr_sweep_stops_at_its_cap(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """Pixel-only text far enough down is *not* found, by design.

        The OCR path is capped lower than the matcher chain because each
        missed frame costs up to two image variants x two languages x three
        PSM modes. Worth a test because the limit is otherwise invisible: it
        looks like a bug from the outside, and someone will raise the constant
        without knowing what they are buying. The default fixture page puts the
        target past the cap; `filler=4` is the same page inside it.
        """
        await engine.navigate(f"{base_url}/?mode=document&paint=image")
        with pytest.raises(StepExecutionError):
            await Comparator().check(
                ExpectedResult(type=AssertType.TEXT_VISIBLE, value=TARGET_TEXT), engine
            )


class TestTheMatcherChainSweeps:
    @pytest.mark.asyncio
    async def test_a_visible_target_is_found_without_scrolling(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The cost of the sweep falls only on lookups that were failing.

        If a passing step scrolled the app, every scenario would drift.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        executor = _executor(engine, tmp_path)
        before = await engine.page.evaluate("() => window.scrollY")
        result = await executor.execute_step(
            StepConfig(
                step=1,
                action=ActionType.FIND_AND_CLICK,
                description=f"click {ABOVE_TEXT}",
                target=TargetSpec(text=ABOVE_TEXT),
            )
        )
        # `WARNING` is the honest answer here and not a failure of this test:
        # the target is a heading, so clicking it changes no pixels, and
        # AAT-109 reports a click that changed nothing as a warning rather
        # than a pass. What matters is that the step did not go looking
        # further down the page.
        assert result.status is not StepStatus.FAILED, result.error_message
        assert await engine.page.evaluate("() => window.scrollY") == before

    @pytest.mark.asyncio
    async def test_an_absent_target_still_fails_after_the_sweep(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """And the page is where it started when it does.

        The failure message is the product's answer when it genuinely cannot
        find something, and the evidence screenshot taken right after has to
        show the screen the step was actually run against.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        executor = _executor(engine, tmp_path)
        start = await engine.screenshot()
        result = await executor.execute_step(
            StepConfig(
                step=1,
                action=ActionType.FIND_AND_CLICK,
                description="click something that is not there",
                target=TargetSpec(text="ABSENT PHRASE NOBODY RENDERED"),
            )
        )
        assert result.status is StepStatus.FAILED
        end = await engine.screenshot()
        assert abs(_brightness(start) - _brightness(end)) < 1.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["document", "canvas"])
    async def test_an_image_target_below_the_fold_is_clicked(
        self, engine: WebEngine, base_url: str, tmp_path: Path, mode: str
    ) -> None:
        """The test that fails if the executor is not wired to the sweep.

        The two tests above pass whether or not the chain sweeps -- a visible
        target needs no scrolling and an absent one is absent at every scroll
        position -- so neither of them pins the wiring. This one does: the
        target is an image, so no DOM route can answer it, and it is three
        screens down, so the single viewport screenshot the chain used to take
        does not contain it.
        """
        await engine.navigate(f"{base_url}/?mode={mode}")
        picture = await _crop_the_target_then_return_to_the_top(engine, tmp_path)

        executor = _executor(engine, tmp_path)
        result = await executor.execute_step(
            StepConfig(
                step=1,
                action=ActionType.FIND_AND_CLICK,
                description="click the banded target by picture",
                target=TargetSpec(image=str(picture)),
            )
        )
        # Clicking a coloured heading changes no pixels, so AAT-109 calls it a
        # warning; what is under test is that it was found at all.
        assert result.status is not StepStatus.FAILED, result.error_message
        assert result.match_result is not None
        # And the page is left at the scroll position the match was found at,
        # which is the only thing that makes the coordinates it clicked true.
        assert _has_yellow_band(await engine.screenshot())
