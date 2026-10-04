"""Two coordinate spaces, and the places that used to mix them.

``engine.click()`` takes viewport CSS pixels. ``engine.screenshot()`` returns
whatever the engine can capture, which for ``DesktopEngine`` is the whole
display at its physical resolution. Nothing named that difference, so the
executor handed screen pixels to ``page.mouse.click`` as if they were CSS
pixels: the click landed somewhere else and the step still reported a match.

A false pass with a screenshot attached is the worst outcome available here,
which is why these tests assert on *which* click API was called and with what,
rather than only that something was clicked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest

from aat.core.models import (
    ActionType,
    MatchMethod,
    MatchResult,
    ScreenshotSpace,
    StepConfig,
    TargetSpec,
)
from aat.engine.desktop import DesktopEngine
from aat.engine.executor import StepExecutor

if TYPE_CHECKING:
    from pathlib import Path


def _png(shade: int, size: tuple[int, int] = (40, 40)) -> bytes:
    return bytes(cv2.imencode(".png", np.full(size, shade, dtype=np.uint8))[1])


# ─── The engine contract ─────────────────────────────────────


class TestEngineDefaults:
    """An engine that does not think about this keeps what it had."""

    def test_base_engine_declares_viewport(self) -> None:
        from aat.engine.web import WebEngine

        engine = WebEngine()
        assert engine.screenshot_space is ScreenshotSpace.VIEWPORT

    def test_viewport_conversions_are_the_identity(self) -> None:
        from aat.engine.web import WebEngine

        engine = WebEngine()
        assert engine.screenshot_to_click(137, 291) == (137, 291)
        assert engine.viewport_to_screenshot(137, 291) == (137, 291)

    def test_web_engine_sets_no_device_scale_factor(self) -> None:
        """Why the identity is right for it, not merely convenient.

        ``new_context`` is called without ``device_scale_factor``, so Playwright
        uses 1 and a screenshot pixel *is* a CSS pixel. If that ever changes,
        this conversion stops being the identity and this test is the place
        that says so.
        """
        from pathlib import Path

        source = Path("src/aat/engine/web.py").read_text(encoding="utf-8")
        assert "device_scale_factor" not in source


class TestDesktopEngineSpace:
    def test_declares_screen_space(self) -> None:
        assert DesktopEngine().screenshot_space is ScreenshotSpace.SCREEN

    def test_scale_is_measured_not_assumed(self) -> None:
        """A 2x display: 1680x1050 logical, 3360x2100 captured.

        Measured on the machine this was written on. The point of measuring is
        that ``window.devicePixelRatio`` is the wrong number twice over -- it
        is the *page's* ratio, which browser zoom moves while the display's
        backing scale does not, and a headful browser may be sitting on a
        different monitor than the one the ratio describes.
        """
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.return_value = (1680, 1050)
        pag.screenshot.return_value = MagicMock(size=(3360, 2100))
        engine._pag = pag

        assert engine._screenshot_scale() == pytest.approx(2.0)
        assert engine.screenshot_to_click(600, 400) == (300, 200)

    def test_scale_is_measured_once(self) -> None:
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.return_value = (1680, 1050)
        pag.screenshot.return_value = MagicMock(size=(3360, 2100))
        engine._pag = pag

        engine._screenshot_scale()
        engine._screenshot_scale()
        assert pag.screenshot.call_count == 1

    def test_non_hidpi_display_is_the_identity(self) -> None:
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.return_value = (1920, 1080)
        pag.screenshot.return_value = MagicMock(size=(1920, 1080))
        engine._pag = pag

        assert engine._screenshot_scale() == pytest.approx(1.0)
        assert engine.screenshot_to_click(600, 400) == (600, 400)

    def test_non_uniform_scale_falls_back_to_one(self) -> None:
        """A capture spanning two displays of different scales looks like this.

        Guessing a single factor there would be wrong everywhere; 1.0 is at
        least wrong by a known amount, and the warning names the situation.
        """
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.return_value = (1680, 1050)
        pag.screenshot.return_value = MagicMock(size=(3360, 1050))
        engine._pag = pag

        assert engine._screenshot_scale() == pytest.approx(1.0)

    def test_unmeasurable_scale_falls_back_to_one(self) -> None:
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.side_effect = RuntimeError("no display")
        engine._pag = pag

        assert engine._screenshot_scale() == pytest.approx(1.0)

    def test_viewport_to_screenshot_applies_window_offset_then_scale(self) -> None:
        """Both corrections, in that order.

        The window offset is in logical screen points, so it is added before
        the scale, not after. Doing it the other way doubles the offset.
        """
        engine = DesktopEngine()
        pag = MagicMock()
        pag.size.return_value = (1680, 1050)
        pag.screenshot.return_value = MagicMock(size=(3360, 2100))
        engine._pag = pag
        engine._window_offset_x = 40
        engine._window_offset_y = 70

        assert engine.viewport_to_screenshot(100, 200) == pytest.approx((280.0, 540.0))


# ─── The executor's use of it ────────────────────────────────


def _step(action: ActionType = ActionType.FIND_AND_CLICK) -> StepConfig:
    return StepConfig(
        step=1,
        action=action,
        description="click the thing",
        target=TargetSpec(text="Save"),
        humanize=False,
    )


class _ScreenSpaceEngine:
    """The narrowest stand-in for an engine whose capture is the display.

    A ``MagicMock`` cannot play this part: it answers ``screenshot_space`` with
    a mock, which is not a ``ScreenshotSpace``, so the executor would read it
    as the viewport and the test would pass while measuring nothing.
    """

    screenshot_space = ScreenshotSpace.SCREEN

    def __init__(self, scale: float = 2.0) -> None:
        self._scale = scale
        self.viewport_clicks: list[tuple[int, int]] = []
        self.screen_clicks: list[tuple[int, int]] = []
        self._config = MagicMock(fast_mode=False)
        self.type_text = AsyncMock()
        self.key_combo = AsyncMock()
        self.press_key = AsyncMock()

    def screenshot_to_click(self, x: int, y: int) -> tuple[int, int]:
        return (int(x / self._scale), int(y / self._scale))

    def viewport_to_screenshot(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._scale, y * self._scale)

    async def click(self, x: int, y: int) -> None:
        self.viewport_clicks.append((x, y))

    async def double_click(self, x: int, y: int) -> None:
        self.viewport_clicks.append((x, y))

    async def right_click(self, x: int, y: int) -> None:
        self.viewport_clicks.append((x, y))

    async def click_on_screen(self, x: int, y: int) -> None:
        self.screen_clicks.append((x, y))

    async def double_click_on_screen(self, x: int, y: int) -> None:
        self.screen_clicks.append((x, y))

    async def right_click_on_screen(self, x: int, y: int) -> None:
        self.screen_clicks.append((x, y))


@pytest.fixture
def screen_executor(tmp_path: Path) -> tuple[StepExecutor, _ScreenSpaceEngine]:
    engine = _ScreenSpaceEngine()
    executor = StepExecutor(
        engine=engine,  # type: ignore[arg-type]
        matcher=MagicMock(),
        humanizer=MagicMock(),
        waiter=MagicMock(),
        comparator=MagicMock(),
        screenshot_dir=tmp_path,
    )
    return executor, engine


class TestClickRouting:
    """Facets ① and ②: the matcher chain's point and the healed point."""

    async def test_screenshot_point_goes_to_the_os_pointer(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        executor, engine = screen_executor
        await executor._act_at_pos(
            _step(),
            600,
            400,
            method=MatchMethod.TEMPLATE,
            in_screenshot_space=True,
        )
        assert engine.screen_clicks == [(300, 200)]
        assert engine.viewport_clicks == []

    async def test_dom_point_still_goes_to_the_page(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        """Unconverted and unrouted, because a DOM rectangle is already
        viewport coordinates even on this engine."""
        executor, engine = screen_executor
        await executor._act_at_pos(_step(), 600, 400, method=MatchMethod.PLAYWRIGHT)
        assert engine.viewport_clicks == [(600, 400)]
        assert engine.screen_clicks == []

    async def test_viewport_engine_ignores_the_flag(self, tmp_path: Path) -> None:
        """The reason this stayed invisible for so long.

        On an engine that screenshots its own viewport both branches do the
        same thing, so every test and every real run on ``WebEngine`` behaved
        identically whether or not the flag was passed.
        """
        engine = MagicMock()
        engine.click = AsyncMock()
        engine._config = MagicMock(fast_mode=False)
        del engine.screenshot_space
        executor = StepExecutor(
            engine=engine,
            matcher=MagicMock(),
            humanizer=MagicMock(),
            waiter=MagicMock(),
            comparator=MagicMock(),
            screenshot_dir=tmp_path,
        )

        await executor._act_at_pos(_step(), 600, 400, in_screenshot_space=True)
        engine.click.assert_awaited_once_with(600, 400)

    async def test_type_clicks_the_converted_point_too(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        executor, engine = screen_executor
        step = StepConfig(
            step=1,
            action=ActionType.FIND_AND_TYPE,
            description="type into the thing",
            target=TargetSpec(text="Email"),
            value="a@b.c",
            humanize=False,
        )
        await executor._act_at_pos(step, 600, 400, in_screenshot_space=True)
        assert engine.screen_clicks == [(300, 200)]
        engine.type_text.assert_awaited_once_with("a@b.c")

    async def test_the_matcher_chain_declares_its_space(self) -> None:
        """Facet ① at the call site, by source.

        The chain searches the screenshot, so its answer is in screenshot
        pixels -- the one fact ``_act_at_pos`` cannot infer. A test that drove
        the whole chain would need a real matcher and a real browser; what has
        to hold is that the flag is passed, and that is checkable here.
        """
        from pathlib import Path as _Path

        source = _Path("src/aat/engine/executor.py").read_text(encoding="utf-8")
        chain = source.split("# Adjust coordinates back to full viewport")[1]
        assert "in_screenshot_space=True" in chain.split("def _crop_to_region")[0]

    async def test_healing_declares_its_space(self) -> None:
        """Facet ②: the banked picture is found in the screenshot as well."""
        from pathlib import Path as _Path

        source = _Path("src/aat/engine/executor.py").read_text(encoding="utf-8")
        heal = source.split("Healed '%s' from a banked picture")[1]
        assert "in_screenshot_space=True" in heal.split("async def _do_click")[0]


class TestBankedCrop:
    """Facet ③: the crop is cut out of the screenshot, so it must be in its
    space -- and this is where a mixup does the most damage, because a wrong
    picture is healed from later and reported as a pass."""

    async def test_dom_box_is_converted_before_banking(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        executor, _engine = screen_executor
        executor._last_screenshot = _png(128, (400, 400))
        executor._propose_bank(
            _step(),
            {"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0},
            MatchMethod.PLAYWRIGHT,
            0.9,
            from_dom=True,
        )
        assert executor._pending_bank is not None
        assert executor._pending_bank["box"] == {
            "x": 20.0,
            "y": 40.0,
            "width": 60.0,
            "height": 80.0,
        }

    async def test_screenshot_box_is_banked_as_given(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        executor, _engine = screen_executor
        executor._last_screenshot = _png(128, (400, 400))
        box = {"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0}
        executor._propose_bank(_step(), box, MatchMethod.TEMPLATE, 0.9, from_dom=False)
        assert executor._pending_bank is not None
        assert executor._pending_bank["box"] == box

    async def test_viewport_engine_banks_the_box_unchanged(self, tmp_path: Path) -> None:
        engine = MagicMock()
        engine._config = MagicMock(fast_mode=False)
        del engine.screenshot_space
        executor = StepExecutor(
            engine=engine,
            matcher=MagicMock(),
            humanizer=MagicMock(),
            waiter=MagicMock(),
            comparator=MagicMock(),
            screenshot_dir=tmp_path,
        )
        executor._last_screenshot = _png(128, (400, 400))
        box = {"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0}
        executor._propose_bank(_step(), box, MatchMethod.PLAYWRIGHT, 0.9)
        assert executor._pending_bank is not None
        assert executor._pending_bank["box"] == box

    async def test_a_collapsed_conversion_banks_nothing(self, tmp_path: Path) -> None:
        """Better no picture than a picture of nothing.

        A zero-area crop would be saved as "what this element looks like" and
        then fail to match it for as long as the file survives.
        """
        engine = _ScreenSpaceEngine(scale=0.0)
        executor = StepExecutor(
            engine=engine,  # type: ignore[arg-type]
            matcher=MagicMock(),
            humanizer=MagicMock(),
            waiter=MagicMock(),
            comparator=MagicMock(),
            screenshot_dir=tmp_path,
        )
        executor._last_screenshot = _png(128, (400, 400))
        executor._propose_bank(
            _step(),
            {"x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0},
            MatchMethod.PLAYWRIGHT,
            0.9,
        )
        assert executor._pending_bank is None


class TestViewportWarnings:
    """Facet ④: both warnings measure against the viewport."""

    async def test_no_viewport_warning_for_a_screen_point(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Every screen point is "outside the viewport" and most of a display
        is in its "left 20%". Firing there teaches the reader to skip them."""
        executor, _engine = screen_executor
        with caplog.at_level("WARNING", logger="aat.engine.executor"):
            await executor._act_at_pos(_step(), 90, 1800, in_screenshot_space=True)
        assert "outside viewport" not in caplog.text
        assert "LEFT 20%" not in caplog.text

    async def test_viewport_warning_still_fires_for_a_dom_point(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        executor, _engine = screen_executor
        with caplog.at_level("WARNING", logger="aat.engine.executor"):
            await executor._act_at_pos(_step(), 90, 1800)
        assert "outside viewport" in caplog.text


class TestCoordinateLearning:
    """Facet ⑤: one column pair, so only one space may be written to it."""

    async def test_a_screen_point_is_not_learned(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        """``_act_on_learned_coords`` replays a stored position through
        ``click()``, which is viewport coordinates. A screen-space position
        stored here would come back as a click somewhere else -- AAT-109's
        silent mis-click, reintroduced through the back door."""
        executor, _engine = screen_executor
        executor._learned_store = MagicMock()
        await executor._act_at_pos(_step(), 600, 400, in_screenshot_space=True)
        assert executor._pending_learn is None

    async def test_a_dom_point_is_still_learned(
        self,
        screen_executor: tuple[StepExecutor, _ScreenSpaceEngine],
    ) -> None:
        executor, _engine = screen_executor
        executor._learned_store = MagicMock()
        await executor._act_at_pos(_step(), 600, 400)
        assert executor._pending_learn is not None
        assert (executor._pending_learn["x"], executor._pending_learn["y"]) == (600, 400)


class TestImageSearchOnScreen:
    """Facet ⑥: the path that already existed and was already wrong.

    ``find_on_screen`` locates a template inside a full-screen capture, so its
    answer is in screenshot pixels, while the OS pointer takes logical points.
    On the 2x display measured above every one of these clicks landed at twice
    the intended distance from the corner of the screen.
    """

    async def test_image_hit_is_converted_before_clicking(self, tmp_path: Path) -> None:
        engine = _ScreenSpaceEngine()
        engine.find_on_screen = AsyncMock(return_value=(600, 400))  # type: ignore[attr-defined]
        engine.screenshot = AsyncMock(return_value=_png(10))  # type: ignore[attr-defined]
        engine.find_text_position = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        executor = StepExecutor(
            engine=engine,  # type: ignore[arg-type]
            matcher=MagicMock(),
            humanizer=MagicMock(),
            waiter=MagicMock(),
            comparator=MagicMock(),
            screenshot_dir=tmp_path,
        )
        step = StepConfig(
            step=1,
            action=ActionType.FIND_AND_CLICK,
            description="click the pictured thing",
            target=TargetSpec(image="save.png", confidence=0.8),
            humanize=False,
        )

        result = await executor._find_and_act(step)

        assert isinstance(result, MatchResult)
        assert engine.screen_clicks == [(300, 200)]
        # The reported position is the one actually clicked, not the raw pixel
        # offset -- a report in a space the reader cannot act on is noise.
        assert (result.x, result.y) == (300, 200)
