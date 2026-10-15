"""The one DOM text search, shared by every engine that owns a page.

Both engines in this repository drive a real Playwright page -- ``WebEngine``
because that is all it is, and ``DesktopEngine`` because it launches a headful
browser and clicks through the OS on top of it. So "find the element whose
label, placeholder, role name or text is *this*" has exactly one correct
answer in both, and it lives here rather than once per engine.

The reason it is a module and not two copies is written in this project's own
history. AAT-112 added ``find_text_box`` beside the older
``find_text_position`` and left the test helper that blinds the DOM paths
pointing at only the older one: the helper went on reporting that it had
blinded the search while the search quietly kept working, and two tests stayed
green for a repair that was not happening. A second copy of the strategy list
in a second engine is the same trap with a longer fuse -- the engines drift,
and the one that drifts is the one almost nobody runs, so nothing goes red.

What is deliberately *not* here: anything that clicks through the OS, measures
the screen, or converts between coordinate spaces. Every box this module
returns is in viewport CSS pixels, which is what ``engine.click()`` takes in
both engines (``DesktopEngine`` clicks through ``page.mouse`` too -- only its
``*_on_screen`` methods leave the viewport). An engine that one day drives a
native window with no page cannot use any of this and should not pretend to:
callers probe for these methods with ``hasattr`` rather than finding them on
``BaseEngine``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Locator, Page


def as_box(rect: Any) -> dict[str, float]:
    """Playwright's bounding box as a plain dict of four floats.

    ``bounding_box()`` returns a ``FloatRect``, which is not a ``dict[str,
    float]`` as far as the type checker is concerned. Copying the four keys we
    actually use keeps the return type honest and stops a Playwright type
    detail from leaking into every caller that wants to crop a screenshot.
    """
    return {
        "x": float(rect["x"]),
        "y": float(rect["y"]),
        "width": float(rect["width"]),
        "height": float(rect["height"]),
    }


def _strategies(page: Page, text: str) -> list[Callable[[], Locator]]:
    """The search order, in one place.

    Labels first, then placeholders, then the two roles, then raw text. The
    order is load-bearing and is tested elsewhere; what matters here is that
    every caller walks the same one.
    """
    return [
        lambda: page.get_by_label(text, exact=False).first,
        lambda: page.get_by_placeholder(text, exact=False).first,
        lambda: page.get_by_role("button", name=text, exact=False).first,
        lambda: page.get_by_role("link", name=text, exact=False).first,
        lambda: page.get_by_text(text, exact=False).first,
    ]


async def find_text_box(page: Page, text: str) -> dict[str, float] | None:
    """Locate ``text`` and return its box in viewport CSS pixels, or ``None``.

    The element is scrolled into view before it is measured, which is what
    makes anything below the fold reachable at all: a box measured without
    scrolling describes a place the pointer cannot reach, and an element that
    was merely off-screen would otherwise be indistinguishable from one that
    does not exist.

    A ``text`` that looks like a CSS selector is tried as one first, because a
    scenario that names ``#submit`` means the element, not the three
    characters.
    """
    if text.startswith(("#", "[", ".")) or text.startswith("input"):
        try:
            locator = page.locator(text).first
            if await locator.count() > 0:
                await locator.scroll_into_view_if_needed(timeout=3000)
                box = await locator.bounding_box()
                if box:
                    return as_box(box)
        except Exception:
            pass

    for strategy in _strategies(page, text):
        try:
            locator = strategy()
            # Presence in the DOM, not visibility: an element below the fold
            # is present and unseen, and scrolling is precisely the remedy.
            if await locator.count() == 0:
                continue
            await locator.scroll_into_view_if_needed(timeout=3000)
            box = await locator.bounding_box()
            if box:
                return as_box(box)
        except Exception:
            continue

    return None


async def find_text_position(page: Page, text: str) -> tuple[int, int] | None:
    """Centre of the element matching ``text``, or ``None``.

    A thin view over :func:`find_text_box` so the search strategy has one
    implementation. The box itself matters to callers that want to bank a
    picture of the element for self-healing, which a centre point cannot
    describe.
    """
    box = await find_text_box(page, text)
    if box is None:
        return None
    return (
        int(box["x"] + box["width"] / 2),
        int(box["y"] + box["height"] / 2),
    )


#: True when some ancestor has no room in a direction it does not let content
#: escape from. Walks up rather than testing the element itself, because the
#: clipped child keeps a box of its own -- that is the whole reason Playwright
#: is fooled.
#:
#: The border box, not ``clientHeight``. An inline ``<span>`` has
#: ``clientHeight`` 0 while being plainly on screen, so the cheaper property
#: would hide ordinary text inside any ``<span>`` that happens to carry
#: ``overflow: hidden``. Measured: the span case reads as clipped under
#: ``clientHeight`` and as visible under the border box.
#:
#: ``overflow !== 'visible'`` rather than a list of clipping values: ``hidden``,
#: ``clip``, ``auto`` and ``scroll`` all clip at zero size, and ``visible`` is
#: the only one that does not.
_ANCESTOR_CLIPS_TO_NOTHING = """
(el) => {
  let node = el;
  while (node) {
    const parent = node.parentElement;
    if (!parent) return false;
    const cs = getComputedStyle(parent);
    const rect = parent.getBoundingClientRect();
    if (cs.overflowY !== 'visible' && rect.height === 0) return true;
    if (cs.overflowX !== 'visible' && rect.width === 0) return true;
    node = parent;
  }
  return false;
}
"""


async def is_clipped_by_ancestor(locator: Locator) -> bool:
    """True when *locator* sits inside a container collapsed to nothing.

    Playwright's ``is_visible`` answers for the node itself, and a node inside
    a ``height: 0; overflow: hidden`` parent still has its own box, its own
    size and a position on the page. So a collapsed menu holding the words a
    step is watching for reads as visible, and ``if_visible`` runs a dismiss
    block against a popup that is not open -- the 2026-03-24 report arriving
    by a second route after ``display: none`` was closed off.

    Why this shape and not the obvious one: the direct test is "does a click at
    the element's centre land on the element" (``document.elementFromPoint``),
    which is correct *and* answers "no" for everything below the fold, because
    that function only sees the viewport. It would close this hole by undoing
    AAT-121. Asking instead whether an ancestor has collapsed never consults
    the scroll position, so an element 2,000px down the page is untouched
    (measured: ``y = 2119.9``, not clipped).

    What this deliberately does not catch: an element scrolled out of view
    *inside* a scroll container that has a real size. That is still reported
    visible, exactly as before -- no better, and no worse.

    Returns ``False`` if the question cannot be asked. An element that has gone
    away mid-check is not evidence that the page is hiding something.
    """
    try:
        return bool(await locator.evaluate(_ANCESTOR_CLIPS_TO_NOTHING))
    except Exception:
        return False


async def is_really_visible(locator: Locator) -> bool:
    """``is_visible`` plus the ancestor-clip question, as one answer.

    The two are always asked together; keeping them in one place stops a
    caller from getting half the check.
    """
    try:
        if not await locator.is_visible():
            return False
    except Exception:
        return False
    return not await is_clipped_by_ancestor(locator)


async def scroll_to_top(page: Page) -> None:
    """Scroll the document back to (0, 0)."""
    await page.evaluate("window.scrollTo(0, 0)")


async def force_click_by_text(page: Page, text: str) -> bool:
    """Find the element by the shared strategies and force-click it.

    ``force=True`` bypasses Playwright's actionability checks, which is the
    point: this is the last fallback, reached when an element is present but
    something -- typically a sticky header -- is sitting on top of it. Returns
    whether a click went out.

    A selector-looking ``text`` is tried *after* the strategies here, and
    *before* them in :func:`find_text_box`. That asymmetry is deliberate and
    predates this module: measuring the wrong element costs a miss, whereas
    force-clicking the wrong element presses it, so the clicking path reaches
    for the literal selector only once every named search has come up empty.
    """
    for strategy in _strategies(page, text):
        try:
            locator = strategy()
            if await locator.count() > 0:
                await locator.click(force=True, timeout=3000)
                return True
        except Exception:
            continue

    if text.startswith(("#", "[", ".")) or text.startswith("input"):
        try:
            locator = page.locator(text).first
            if await locator.count() > 0:
                await locator.click(force=True, timeout=3000)
                return True
        except Exception:
            pass

    return False
