"""Tests for the scroll-and-re-look sweep (AAT-121).

These pin the decisions, not the mechanics. The mechanics are two calls in a
loop; what is easy to get wrong is *when it stops*, *what it looks at*, and
*what state it leaves behind* -- and each of those has a specific failure that
would not show up as a red test anywhere else:

- stopping on ``window.scrollY`` instead of pixels silently does nothing on a
  canvas app, which is the only kind of page this exists for
- capturing twice per screen makes the movement test answer about a frame
  nobody searched
- not restoring the scroll position moves the page out from under the next
  step and under the screenshot that documents the failure

The real-browser proof that scrolled pixels actually get captured lives in
``tests/integration/test_scroll_sweep.py``. These are the cheap guards.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from aat.core.models import ScreenshotSpace
from aat.engine.sweep import (
    MAX_SCREENS,
    MIN_SETTLE_S,
    _frames_differ,
    _viewport_size,
    sweep_viewports,
)


def _frame(fill: int, *, size: tuple[int, int] = (80, 120)) -> bytes:
    """A solid PNG. Different ``fill`` values differ in every pixel."""
    img = np.full((size[0], size[1]), fill, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf.tobytes())


class _Config:
    viewport_width = 1000
    viewport_height = 500
    speed = "fast"


class _FakeEngine:
    """A page that shows a new frame for each scroll, then stops moving.

    Hand-written rather than mocked. ``MagicMock`` answers ``screenshot`` with
    a mock whose bytes cannot be decoded, so ``_frames_differ`` would take the
    cannot-compare branch and report movement forever -- the sweep would run
    to the cap on every test and nothing would be measuring the stop
    condition.
    """

    screenshot_space = ScreenshotSpace.VIEWPORT
    page = None

    def __init__(self, frames: int) -> None:
        self._config = _Config()
        self._frames = frames
        self.index = 0
        self.scrolls: list[tuple[int, int, int]] = []
        self.shots = 0

    async def screenshot(self) -> bytes:
        self.shots += 1
        # Stride 97 so consecutive frames differ by 97 or 159 grey levels --
        # comfortably past the sweep's own 25-level threshold, including where
        # the value wraps. A smaller stride makes every frame read as "the page
        # did not move" and the tests would be measuring the test double.
        return _frame((min(self.index, self._frames) * 97) % 256)

    async def scroll(self, x: int, y: int, delta: int) -> None:
        self.scrolls.append((x, y, delta))
        self.index += 1 if delta > 0 else -1
        self.index = max(self.index, 0)


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the repaint settle. It is real and needed; it is not under test."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("aat.engine.sweep.asyncio.sleep", _instant)


class TestProbeOnTheCurrentScreen:
    @pytest.mark.asyncio
    async def test_visible_target_does_not_scroll(self) -> None:
        """The cost of the sweep is paid only by a lookup that was going to fail.

        A target already on screen must not move the page, or every passing
        step would quietly reposition the app.
        """
        engine = _FakeEngine(frames=5)

        async def probe(_frame: bytes) -> str | None:
            return "hit"

        assert await sweep_viewports(engine, probe) == "hit"
        assert engine.scrolls == []
        assert engine.shots == 1, "one capture, exactly as before the sweep existed"

    @pytest.mark.asyncio
    async def test_probe_sees_each_frame_once(self) -> None:
        """The frame the probe searches is the frame the movement test used.

        Two captures per screen would be slower and wrong: the stop decision
        would be about pixels nobody looked for the target in.
        """
        engine = _FakeEngine(frames=3)
        seen: list[bytes] = []

        async def probe(frame: bytes) -> None:
            seen.append(frame)
            return None

        await sweep_viewports(engine, probe, max_screens=3)
        assert engine.shots == len(seen), "no capture went unsearched"
        assert len(set(seen)) == len(seen), "no frame searched twice"


class TestStopping:
    @pytest.mark.asyncio
    async def test_stops_when_the_pixels_stop_moving(self) -> None:
        engine = _FakeEngine(frames=2)

        async def probe(_frame: bytes) -> None:
            return None

        assert await sweep_viewports(engine, probe, max_screens=MAX_SCREENS) is None
        # Two frames of real movement, then one scroll that changed nothing.
        assert len(engine.scrolls) == 3 + 3, "3 down to the floor, then 3 back"

    @pytest.mark.asyncio
    async def test_cap_bounds_a_page_that_never_settles(self) -> None:
        """A spinner or a clock never reports "nothing moved"."""
        engine = _FakeEngine(frames=10_000)

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=4)
        assert sum(1 for s in engine.scrolls if s[2] > 0) == 4

    @pytest.mark.asyncio
    async def test_zero_screens_is_one_look_and_no_scroll(self) -> None:
        engine = _FakeEngine(frames=5)

        async def probe(_frame: bytes) -> None:
            return None

        assert await sweep_viewports(engine, probe, max_screens=0) is None
        assert engine.scrolls == []
        assert engine.shots == 1

    @pytest.mark.asyncio
    async def test_an_engine_that_cannot_scroll_stops_quietly(self) -> None:
        engine = _FakeEngine(frames=5)

        async def refuse(*_a: object) -> None:
            raise RuntimeError("no wheel here")

        engine.scroll = refuse  # type: ignore[method-assign]

        async def probe(_frame: bytes) -> None:
            return None

        assert await sweep_viewports(engine, probe) is None


class TestFindingItBelowTheFold:
    @pytest.mark.asyncio
    async def test_returns_the_find_and_leaves_the_page_there(self) -> None:
        """The page stays where the match was found, and that is the point.

        The result's coordinates are viewport coordinates valid *now*. Scrolling
        back before the caller clicks would make them describe a screen that is
        no longer showing.
        """
        engine = _FakeEngine(frames=9)
        calls = {"n": 0}

        async def probe(_frame: bytes) -> str | None:
            calls["n"] += 1
            return "found" if calls["n"] == 3 else None

        assert await sweep_viewports(engine, probe) == "found"
        assert sum(1 for s in engine.scrolls if s[2] > 0) == 2
        assert not [s for s in engine.scrolls if s[2] < 0], "must not scroll back"


class TestRestoringAfterAMiss:
    @pytest.mark.asyncio
    async def test_scrolls_back_exactly_as_far_as_it_went(self) -> None:
        """A failed lookup must not move the page under the following steps."""
        engine = _FakeEngine(frames=9)

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=5)
        down = [s[2] for s in engine.scrolls if s[2] > 0]
        up = [s[2] for s in engine.scrolls if s[2] < 0]
        assert len(down) == len(up)
        assert sum(down) + sum(up) == 0

    @pytest.mark.asyncio
    async def test_scrolls_down_by_less_than_a_viewport(self) -> None:
        """An element across the fold is cut in half in both frames otherwise."""
        engine = _FakeEngine(frames=9)

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=2)
        delta = engine.scrolls[0][2]
        assert 0 < delta < _Config.viewport_height
        assert engine.scrolls[0][:2] == (500, 250), "wheel at the viewport centre"

    @pytest.mark.asyncio
    async def test_document_offset_restored_when_the_page_reports_one(self) -> None:
        """Wheeling back is approximate; window.scrollTo is exact.

        Both run, because the wheel is the only thing that moves a canvas and
        scrollTo is the only thing that is exact about a document.
        """

        class _Page:
            def __init__(self) -> None:
                self.calls: list[tuple[str, object]] = []

            async def evaluate(self, script: str, arg: object = None) -> object:
                self.calls.append((script, arg))
                return 640.0 if "scrollY" in script else None

        engine = _FakeEngine(frames=9)
        page = _Page()
        engine.page = page  # type: ignore[assignment]

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=2)
        restores = [c for c in page.calls if "scrollTo" in c[0]]
        assert restores == [(restores[0][0], 640.0)]

    @pytest.mark.asyncio
    async def test_a_page_that_cannot_report_an_offset_still_wheels_back(self) -> None:
        """A canvas app answers 0 forever, and an engine with no page answers
        nothing at all. Neither may cost the wheel-based restore."""
        engine = _FakeEngine(frames=9)
        assert engine.page is None

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=3)
        assert [s[2] for s in engine.scrolls if s[2] < 0], "wheeled back regardless"


class TestMovementIsDecidedByPixels:
    def test_identical_frames_did_not_move(self) -> None:
        assert _frames_differ(_frame(40), _frame(40)) is False

    def test_different_frames_moved(self) -> None:
        assert _frames_differ(_frame(40), _frame(200)) is True

    def test_undecodable_frames_count_as_movement(self) -> None:
        """Stopping on a broken capture would make it look like the page floor.

        The sweep would then report "not found" for a reason that has nothing
        to do with the page.
        """
        assert _frames_differ(b"not a png", _frame(40)) is True
        assert _frames_differ(_frame(40), b"") is True
        assert _frames_differ(None, None) is True

    def test_a_resized_frame_counts_as_movement(self) -> None:
        """A viewport that changed mid-sweep is not the bottom of the page."""
        assert _frames_differ(_frame(40), _frame(40, size=(90, 120))) is True

    def test_a_one_pixel_blink_is_not_movement(self) -> None:
        """A caret or a clock tick must not read as a scroll, or a page that
        cannot scroll would sweep to the cap on every failing step."""
        img = np.full((80, 120), 40, dtype=np.uint8)
        ok, buf = cv2.imencode(".png", img)
        assert ok
        before = bytes(buf.tobytes())
        img[0, 0] = 255
        ok, buf = cv2.imencode(".png", img)
        assert ok
        assert _frames_differ(before, bytes(buf.tobytes())) is False


class TestSettleFloor:
    @pytest.mark.asyncio
    async def test_a_faster_preset_cannot_undercut_the_repaint_floor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fast preset's 0.1s settle is shorter than a CanvasKit repaint.

        Capturing early photographs a half-drawn screen and the sweep scrolls
        past content that was really there.
        """
        slept: list[float] = []

        async def _record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("aat.engine.sweep.asyncio.sleep", _record)
        engine = _FakeEngine(frames=9)

        async def probe(_frame: bytes) -> None:
            return None

        await sweep_viewports(engine, probe, max_screens=2, settle_s=0.01)
        assert slept and min(slept) == MIN_SETTLE_S


class TestViewportSize:
    def test_falls_back_when_the_engine_has_no_config(self) -> None:
        class _Bare:
            pass

        assert _viewport_size(_Bare()) == (1280, 720)  # type: ignore[arg-type]

    def test_reads_the_engine_config(self) -> None:
        assert _viewport_size(_FakeEngine(frames=1)) == (1000, 500)  # type: ignore[arg-type]
