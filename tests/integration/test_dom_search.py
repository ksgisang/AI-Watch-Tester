"""Does the shared DOM search return a coordinate anything can actually click?

AAT-125. The matcher chain, the healing path and the picture bank all start by
asking an engine "where is the element matching this text", and until now each
engine answered with its own copy of the strategy list. ``WebEngine`` scrolled
the element into view before measuring it; ``DesktopEngine`` asked
``is_visible`` and measured where it stood. Measured against real Chromium on
the fixture used here, those two answers for the same element on the same page
are:

    is_visible              True
    box without scrolling   y = 2727
    box after scrolling     y = 374   (and window.scrollY = 2353)

A 720px viewport has no y = 2727. ``DesktopEngine.click`` goes through
``page.mouse``, so that coordinate is a press into nothing -- reported by the
step as a hit, because something *was* found. The failure is not "it could not
see below the fold"; it is worse than that, and it is the same family as every
other repair in this repository: a claim about a place the page was not.

A mock cannot be asked any of this. Whether ``is_visible`` is true for an
element four screens down, what ``scroll_into_view_if_needed`` does to the
document offset, and what number ``bounding_box`` returns afterwards are all
facts about Chromium. So this drives a real browser against a real page.

The fixture's target is deliberately unnameable by selector -- no id, no
stable class, no name -- so the search has to get there through the text
strategies, which is the path under test.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterator

import pytest

from aat.core.models import EngineConfig
from aat.engine import dom_search
from aat.engine.desktop import DesktopEngine
from aat.engine.web import WebEngine
from tests.fixtures.below_the_fold_server import (
    ABOVE_TEXT,
    TARGET_TEXT,
    below_the_fold_server,
)

VIEWPORT_W = 900
VIEWPORT_H = 600


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
            viewport_width=VIEWPORT_W,
            viewport_height=VIEWPORT_H,
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


async def _scroll_y(engine: WebEngine) -> int:
    return int(await engine.page.evaluate("() => window.scrollY"))


class TestABoxMustNameAPlaceThePointerCanReach:
    @pytest.mark.asyncio
    async def test_a_target_below_the_fold_comes_back_inside_the_viewport(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The whole repair, in one measurement.

        Not ``is not None`` -- the old path returned a box too. What makes the
        answer usable is that it names a row of pixels that exists on screen
        right now, which is exactly what the unscrolled y = 2727 did not.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        assert await _scroll_y(engine) == 0

        box = await dom_search.find_text_box(engine.page, TARGET_TEXT)

        assert box is not None, "the target was not found at all"
        assert 0 <= box["y"] <= VIEWPORT_H, (
            f"the box is at y={box['y']}, which is off a {VIEWPORT_H}px screen -- "
            "a click there presses nothing and the step reports a hit"
        )
        assert await _scroll_y(engine) > 0, "nothing scrolled, so nothing was reached"

    @pytest.mark.asyncio
    async def test_the_centre_point_agrees_with_the_box(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """One search, two views of it.

        These were separate implementations once, and the test helper that
        blinds the DOM paths went on blinding only one of them while the other
        quietly kept answering (AAT-112). Asserting they agree is what makes a
        future divergence go red instead of going unnoticed.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        point = await dom_search.find_text_position(engine.page, TARGET_TEXT)
        box = await dom_search.find_text_box(engine.page, TARGET_TEXT)

        assert point is not None
        assert box is not None
        assert point == (
            int(box["x"] + box["width"] / 2),
            int(box["y"] + box["height"] / 2),
        )

    @pytest.mark.asyncio
    async def test_a_target_already_on_screen_does_not_move_the_page(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The other direction: scrolling is a remedy, not a habit.

        A search that scrolled unconditionally would leave every step on a
        different screen than the one it was written against, which is the
        defect this work also repaired in the executor's fallback path. The
        element on the first screen must be measured where it already is.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        box = await dom_search.find_text_box(engine.page, ABOVE_TEXT)

        assert box is not None
        assert 0 <= box["y"] <= VIEWPORT_H
        assert await _scroll_y(engine) == 0, "a visible target still scrolled the page"

    @pytest.mark.asyncio
    async def test_scroll_to_top_returns_the_document(
        self, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/?mode=document")
        await dom_search.find_text_box(engine.page, TARGET_TEXT)
        assert await _scroll_y(engine) > 0

        await dom_search.scroll_to_top(engine.page)
        assert await _scroll_y(engine) == 0

    @pytest.mark.asyncio
    async def test_a_name_that_is_on_no_page_is_not_found(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """Silence, and no side effect.

        A search that reported a box for text that is not there would turn
        every stale scenario into a click somewhere arbitrary, and one that
        scrolled while failing would hand the next step a page it never saw.
        """
        await engine.navigate(f"{base_url}/?mode=document")
        assert await dom_search.find_text_box(engine.page, "NOTHING BY THIS NAME") is None
        assert await _scroll_y(engine) == 0


class TestBothEnginesAskTheSameQuestion:
    """The absence was the defect, so absence is what these check.

    The executor probes for these methods with ``hasattr`` and silently skips
    what it does not find. On ``DesktopEngine`` that meant the scroll-to-top
    retry, the force-click past a sticky header, and the box-shaped answer the
    picture bank needs were all missing -- not failing, missing, which is the
    one kind of gap no amount of green tests reports.
    """

    @pytest.mark.parametrize(
        "name", ["find_text_position", "find_text_box", "scroll_to_top", "force_click_by_text"]
    )
    def test_the_desktop_engine_answers_everything_the_web_engine_does(self, name: str) -> None:
        assert hasattr(WebEngine, name)
        assert hasattr(DesktopEngine, name), (
            f"DesktopEngine has no {name}; the executor probes with hasattr, "
            "so this path does not fail there -- it does not run"
        )

    @pytest.mark.parametrize("module", ["web", "desktop"])
    def test_neither_engine_keeps_its_own_copy_of_the_strategy_list(self, module: str) -> None:
        """Anti-drift lock.

        Two copies of the search order is how the engines came apart in the
        first place, and the one that drifts is the one almost nobody runs. If
        a future change reintroduces ``get_by_label`` into an engine, it should
        have to delete this test on purpose.
        """
        import importlib

        source = inspect.getsource(importlib.import_module(f"aat.engine.{module}"))
        assert "get_by_label" not in source, (
            f"aat/engine/{module}.py grew its own text search again; "
            "it belongs in aat/engine/dom_search.py"
        )
