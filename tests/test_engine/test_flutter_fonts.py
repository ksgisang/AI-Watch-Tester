"""Tests for wait_for_fonts — the CanvasKit late-font repaint wait (AAT-117).

A Flutter CanvasKit app that registers no font for the script it is about to
draw fetches one at runtime and repaints. Until that repaint lands the canvas
shows tofu boxes, and nothing in the DOM says so: the Semantics tree is already
complete and correct. Every screenshot AWT takes in that window -- evidence
images, the PDF report, visual-regression baselines, the OCR fallback's own
capture -- records an unreadable picture of a perfectly healthy app.

These tests drive the probe through a fake page, because the thing being tested
is the *decision* (how long to wait, and on what evidence), not Tesseract and
not Chromium. The end-to-end proof is a real run against a real Flutter app.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.engine.flutter_semantics import wait_for_fonts, wait_until_flutter_ready


class ProbePage:
    """A page whose font-resource counts follow a scripted sequence."""

    def __init__(self, sequence: list[dict[str, int]]) -> None:
        self._sequence = sequence
        self.calls = 0

    async def evaluate(self, _script: str) -> dict[str, int]:
        self.calls += 1
        idx = min(self.calls - 1, len(self._sequence) - 1)
        return self._sequence[idx]


class TestWaitForFonts:
    @pytest.mark.asyncio
    async def test_waits_until_every_font_has_responded(self) -> None:
        page = ProbePage(
            [
                {"total": 2, "done": 0},
                {"total": 2, "done": 1},
                {"total": 2, "done": 2},
            ]
        )
        assert await wait_for_fonts(page, settle=0.0, quiet=0.0) is True
        assert page.calls == 3, "must not stop at the first partial count"

    @pytest.mark.asyncio
    async def test_a_complete_looking_batch_is_not_trusted_immediately(self) -> None:
        """This is the measurement that rewrote the implementation.

        On a real CanvasKit app the first 3 fonts landed at 2.6s with
        ``done == total`` -- and 8 more arrived at 3.9s. "Everything I asked
        for has answered" is therefore not the same as "I have finished
        asking", and a screenshot taken in that 1.3s gap is still half tofu.
        So the count must also hold still before the wait returns.
        """
        page = ProbePage(
            [
                {"total": 3, "done": 3},  # looks finished, is not
                {"total": 3, "done": 3},
                {"total": 11, "done": 5},  # the rest of the font arrives
                {"total": 11, "done": 11},
            ]
        )
        assert await wait_for_fonts(page, settle=0.0, quiet=0.3) is True
        assert page.calls >= 4, "returned during the gap, before the real batch"

    @pytest.mark.asyncio
    async def test_waits_for_canvaskit_to_boot_before_concluding_no_fonts(self) -> None:
        """An empty first reading means nothing.

        CanvasKit boots its WASM before it requests anything -- 2.6s on the
        measured app. Returning on the first empty probe is the obvious
        implementation and the wrong one: it skips the wait on exactly the
        apps that need it.
        """
        page = ProbePage(
            [
                {"total": 0, "done": 0},
                {"total": 0, "done": 0},
                {"total": 0, "done": 0},
                {"total": 1, "done": 1},
            ]
        )
        assert await wait_for_fonts(page, settle=0.0, quiet=0.0) is True

    @pytest.mark.asyncio
    async def test_gives_up_when_no_font_is_ever_requested(self) -> None:
        """A Flutter app that bundles its fonts must not pay the full timeout."""
        page = ProbePage([{"total": 0, "done": 0}])
        assert (
            await wait_for_fonts(page, timeout=30.0, settle=0.0, appear_timeout=0.3)
            is False
        )
        assert page.calls <= 4, "should stop at appear_timeout, not at timeout"

    @pytest.mark.asyncio
    async def test_gives_up_at_the_timeout_rather_than_hanging(self) -> None:
        """A font request that never completes must not stall the run.

        A capture of tofu is bad evidence; a run that never finishes is no
        evidence at all, and the user cannot tell it from a hang.
        """
        page = ProbePage([{"total": 1, "done": 0}])
        assert await wait_for_fonts(page, timeout=0.5, settle=0.0) is True

    @pytest.mark.asyncio
    async def test_page_errors_are_not_fatal(self) -> None:
        """Navigation can close the page mid-wait. That is not a test failure."""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("Execution context destroyed"))
        assert await wait_for_fonts(page, timeout=0.5) is False


class TestWaitUntilFlutterReady:
    """The hole the font wait fell into, and the reason it stayed hidden.

    ``is_flutter_page`` looks for ``flt-glass-pane`` / ``flutter-view``, which
    CanvasKit creates only after its WASM is up. Measured on a real app:
    ``navigate()`` returned at 0.43s, the markers appeared at 2.57s. So the
    post-navigate Flutter hook asked "is this Flutter?" two seconds early,
    heard no, and did nothing -- on every cold load, since AWT's first release
    of the feature. Scenario authors compensated with hand-tuned
    ``wait: "10000"`` steps, which is exactly why nobody noticed: the
    workaround was in every scenario that touched Flutter.
    """

    @pytest.mark.asyncio
    async def test_returns_at_once_for_an_already_booted_app(self) -> None:
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        assert await wait_until_flutter_ready(page) is True
        assert page.evaluate.call_count == 1

    @pytest.mark.asyncio
    async def test_non_flutter_pages_pay_nothing(self) -> None:
        """One extra evaluate per navigate, and no waiting.

        If an ordinary site could be made to sit here, the fix would be a
        regression for everyone who is not testing Flutter.
        """
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=False)  # no markers, no loader
        assert await wait_until_flutter_ready(page, timeout=30.0) is False
        assert page.evaluate.call_count == 2

    @pytest.mark.asyncio
    async def test_waits_out_the_boot_when_the_loader_is_present(self) -> None:
        """``flutter_bootstrap.js`` is in the served HTML from the first byte.

        That is the signal that says "this *will* be Flutter", which is the
        only thing that justifies waiting.
        """
        readings = [False, True, False, False, True]  # markers, loader, markers...
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=readings)
        assert await wait_until_flutter_ready(page, timeout=5.0) is True

    @pytest.mark.asyncio
    async def test_gives_up_if_the_app_never_boots(self) -> None:
        """A Flutter build that fails to start must fail the step, not the run."""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=[False, True] + [False] * 100)
        assert await wait_until_flutter_ready(page, timeout=0.6) is False


class TestWaitIsWiredIn:
    """The wait existing is not the same as the wait running.

    Both defects this fixes were ordering defects, and an unwired helper
    reproduces them exactly while every unit test above stays green.
    """

    def test_scan_screenshots_after_the_font_wait(self) -> None:
        from pathlib import Path

        src = Path("src/aat/cli/commands/scan_cmd.py").read_text()
        wait_at = src.index("wait_for_fonts(page)")
        shot_at = src.index("ss_bytes = await engine.screenshot()")
        assert wait_at < shot_at, (
            "scan captured its screenshot before detecting Flutter at all, "
            "which is how the tofu images got written in the first place"
        )

    def test_executor_waits_after_activating_semantics(self) -> None:
        from pathlib import Path

        src = Path("src/aat/engine/executor.py").read_text()
        assert "await wait_for_fonts(page)" in src

    def test_navigate_hook_does_not_use_the_too_early_check(self) -> None:
        """Guarding the hook with ``is_flutter_page`` is what made it a no-op."""
        from pathlib import Path

        src = Path("src/aat/engine/executor.py").read_text()
        hook = src[src.index("async def _maybe_activate_flutter_semantics") :][:1200]
        assert "wait_until_flutter_ready(page)" in hook
        assert "if await is_flutter_page(page)" not in hook


@pytest.mark.asyncio
async def test_probe_script_counts_a_real_font_request() -> None:
    """The probe is a string until Chromium parses it.

    Two things can go wrong here that no mock can see. A regex escaped for
    Python but not for JS is still valid JS and still matches nothing, and
    the whole evaluate sits inside a ``try/except`` that logs at debug level
    -- so the wait would quietly become a no-op while every test above stayed
    green. Checking only that an empty page reports zero fonts would miss
    exactly that; this serves a real .woff2 and demands the probe find it.
    """
    playwright = pytest.importorskip("playwright.async_api")
    from aat.engine.flutter_semantics import _FONT_PROBE_JS

    async with playwright.async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def serve_font(route: Any) -> None:
                await route.fulfill(status=200, content_type="font/woff2", body=b"\x00" * 16)

            await page.route("**/*.woff2", serve_font)

            await page.goto("data:text/html,<p>hello</p>")
            empty: Any = await page.evaluate(_FONT_PROBE_JS)
            assert set(empty) == {"total", "done"}
            assert empty["total"] == 0, "no fonts requested yet"

            await page.evaluate(
                "() => fetch('https://example.invalid/NotoSansKR.woff2')"
                ".then(r => r.arrayBuffer())"
            )
            loaded: Any = await page.evaluate(_FONT_PROBE_JS)
            assert loaded["total"] == 1, "the URL pattern failed to match a real font"
            assert loaded["done"] == 1
        finally:
            await browser.close()
