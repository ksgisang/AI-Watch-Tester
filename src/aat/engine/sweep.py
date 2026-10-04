"""Look below the fold by scrolling and re-looking, one real frame at a time.

Every screenshot this product takes is the viewport (``full_page=False`` in
both of ``WebEngine``'s capture calls), and nothing ever scrolled and
re-captured. So anything the DOM could not name *and* that sat below the fold
did not exist as far as the matcher chain or the OCR fallback were concerned.
That is worst on exactly the pages those two paths were built for: on a Flutter
CanvasKit screen the text is in neither the DOM nor the captured pixels.

**Why this scrolls and re-looks rather than stitching the frames together.**
Stitching is the obvious design and it is wrong here. Two reasons:

1. A point found in a stitched image was never true at any single moment, so
   it cannot be converted into a click. The element was at that offset only in
   a composite that never appeared on screen.
2. Anything that does not scroll -- an app bar, a sticky header, a drawer --
   is repeated in every frame, so a match can land in the second copy. The
   click then lands on the chrome while the step reports a match, which is the
   false pass AAT-120 just finished removing.

Looking again at each scroll position has neither problem. A match is found
inside one real frame, so its viewport coordinates are valid *now*, and the
caller clicks before anything scrolls again.

(Stitching is the right answer for a visual-regression baseline, where nothing
is ever clicked. That is a different feature and this is not it.)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, TypeVar

import cv2
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aat.engine.base import BaseEngine

logger = logging.getLogger(__name__)

T = TypeVar("T")

# How many viewports down to look before giving up. At a 720px viewport this
# reaches roughly 6,000px, which covers an ordinary long page. It is a backstop
# rather than a budget: a page that stops moving exits after one extra capture,
# while a page carrying a permanent animation -- a spinner, a clock, a video --
# never reports "nothing moved", so something has to stop it.
MAX_SCREENS = 10

# Scroll by less than a full viewport. Without the overlap an element sitting
# across the fold line is cut in half in both frames and matches in neither.
_SCROLL_FRACTION = 0.85

# A repaint has to land before the frame is captured or the sweep photographs a
# half-drawn screen and scrolls past content that was really there. The speed
# preset's own settle can be shorter than that, so it is a floor, not a value.
MIN_SETTLE_S = 0.3

# Below this share of changed pixels the scroll moved nothing, and we are at the
# end of whatever was scrollable.
_MOVED_RATIO = 0.005


async def sweep_viewports(
    engine: BaseEngine,
    probe: Callable[[bytes], Awaitable[T | None]],
    *,
    max_screens: int = MAX_SCREENS,
    settle_s: float = MIN_SETTLE_S,
) -> T | None:
    """Run ``probe`` on this screen, then on each screen further down.

    ``probe`` receives one captured frame and returns what it found in that
    frame, or ``None``. It is called once before anything scrolls, so a target
    that is already on screen costs exactly what it cost before this function
    existed: the sweep is only ever paid for by a lookup that was going to
    fail anyway.

    The frame handed to ``probe`` is the same frame used to decide whether the
    scroll moved anything. Capturing twice would be both slower and wrong --
    the movement test would be answering about a frame nobody searched.

    Returns the first non-``None`` result, leaving the page at the scroll
    position where it was found, because that is what makes the result's
    coordinates usable. When nothing is found the scroll position is put back:
    a failed lookup must not move the page out from under the steps that
    follow it, nor under the screenshot that documents the failure.
    """
    previous = await engine.screenshot()
    found = await probe(previous)
    if found is not None:
        return found
    if max_screens <= 0:
        return None

    # The wheel acts on whatever is under the pointer, and the centre of the
    # viewport is the scrollable thing in every layout worth sweeping --
    # including an inner overflow container and a canvas, which is the whole
    # reason window.scrollY cannot be the signal here.
    width, height = _viewport_size(engine)
    centre_x, centre_y = width // 2, height // 2
    delta = max(int(height * _SCROLL_FRACTION), 1)
    settle = max(settle_s, MIN_SETTLE_S)

    start_offset = await _document_offset(engine)
    scrolled = 0
    try:
        for screen in range(1, max_screens + 1):
            try:
                await engine.scroll(centre_x, centre_y, delta)
            except Exception:
                logger.debug("Sweep could not scroll; stopping here", exc_info=True)
                return None
            scrolled += 1
            await asyncio.sleep(settle)
            current = await engine.screenshot()

            if not _frames_differ(previous, current):
                logger.debug(
                    "Sweep reached the end of the page after %d screen(s) below the fold",
                    screen - 1,
                )
                return None
            previous = current

            found = await probe(current)
            if found is not None:
                logger.info("Found it %d screen(s) below the fold", screen)
                return found
    finally:
        if found is None and scrolled:
            await _restore(engine, centre_x, centre_y, delta, scrolled, start_offset)
    return None


async def _restore(
    engine: BaseEngine,
    centre_x: int,
    centre_y: int,
    delta: int,
    scrolled: int,
    start_offset: float | None,
) -> None:
    """Put the scroll position back after a sweep that found nothing.

    Both mechanisms, because neither covers both cases. The wheel is the only
    thing that moves a canvas app or an inner overflow container, and it is
    approximate. ``window.scrollTo`` is exact but does nothing when the
    document itself never scrolled. Wheeling back and then correcting the
    document offset leaves an ordinary page exactly where it was, and a canvas
    app as close as a wheel can get it.
    """
    for _ in range(scrolled):
        try:
            await engine.scroll(centre_x, centre_y, -delta)
        except Exception:
            logger.debug("Sweep could not scroll back", exc_info=True)
            break
    if start_offset is None:
        return
    page = getattr(engine, "page", None)
    if page is None:
        return
    try:
        await page.evaluate("(y) => window.scrollTo(0, y)", start_offset)
    except Exception:
        logger.debug("Sweep could not restore the document offset", exc_info=True)


async def _document_offset(engine: BaseEngine) -> float | None:
    """``window.scrollY``, or ``None`` on an engine that cannot be asked.

    Recorded only so the sweep can be undone. It is deliberately *not* the
    signal for whether scrolling worked: a Flutter CanvasKit page scrolls its
    own content while this value stays nailed to 0, so an implementation that
    trusted it would conclude the page does not scroll on precisely the pages
    this function exists for.
    """
    page = getattr(engine, "page", None)
    if page is None:
        return None
    try:
        offset = await page.evaluate("() => window.scrollY")
    except Exception:
        return None
    return float(offset) if isinstance(offset, (int, float)) else None


def _frames_differ(before: bytes | None, after: bytes | None) -> bool:
    """Whether the scroll actually moved anything.

    Pixels are the signal because they are the only one that answers for every
    kind of scrolling: the document, an inner overflow container, and a canvas
    that paints its own scrollbar.

    When the two frames cannot be compared the answer is "yes". Stopping the
    sweep on a decoding failure would make a broken capture look exactly like
    the bottom of the page, and the sweep would then report "not found" for a
    reason that has nothing to do with the page.
    """
    if not before or not after:
        return True
    prev = cv2.imdecode(np.frombuffer(before, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    curr = cv2.imdecode(np.frombuffer(after, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if prev is None or curr is None or prev.shape != curr.shape:
        return True
    diff = cv2.absdiff(prev, curr)
    if diff.size == 0:
        return True
    return bool(np.count_nonzero(diff > 25) / diff.size > _MOVED_RATIO)


def _viewport_size(engine: BaseEngine) -> tuple[int, int]:
    config = getattr(engine, "_config", None)
    try:
        width = int(getattr(config, "viewport_width", 1280) or 1280)
        height = int(getattr(config, "viewport_height", 720) or 720)
    except (TypeError, ValueError):
        return 1280, 720
    return width, height
