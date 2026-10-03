"""Flutter Semantics — locate elements via CanvasKit accessibility tree.

Flutter CanvasKit renders UI on Canvas, making DOM-based selectors useless.
When Semantics is enabled, Flutter creates flt-semantics elements with
aria-label attributes that Playwright can query for precise coordinates.

Activation flow:
1. Click flt-semantics-placeholder (triggers SemanticsBinding)
2. Wait for flt-semantics nodes to appear (max 3 retries, 3s each)
3. If all retries fail → fall back to OCR

This module is used by StepExecutor only when is_flutter_page() is True.
Non-Flutter pages are never affected.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Cache: avoid re-checking/re-activating on every find call
_semantics_state: dict[str, bool] = {}  # page_id → activated


async def is_flutter_page(page: Any) -> bool:
    """Check if the current page is a Flutter CanvasKit app."""
    try:
        result = await page.evaluate("""() => {
            return !!(
                document.querySelector('flt-glass-pane') ||
                document.querySelector('flutter-view') ||
                document.querySelector('[flt-renderer]')
            );
        }""")
        return bool(result)
    except Exception:
        return False


_FLUTTER_LOADER_JS = """
() => {
  const srcs = Array.from(document.querySelectorAll('script'))
    .map((s) => s.src || '')
    .concat([document.documentElement.innerHTML.slice(0, 4000)]);
  return srcs.some((s) =>
    s.includes('flutter_bootstrap.js') ||
    s.includes('main.dart.js') ||
    s.includes('flutter.js'));
}
"""


async def wait_until_flutter_ready(page: Any, timeout: float = 15.0) -> bool:
    """Wait for a Flutter app to finish booting, without stalling other sites.

    ``is_flutter_page`` looks for ``flt-glass-pane`` / ``flutter-view``, which
    CanvasKit only creates once its WASM is up: measured at 2.6s on a real app,
    while ``navigate()`` returned at 0.43s. Everything keyed off that check --
    Semantics activation, the font wait -- therefore ran against a page that
    did not look like Flutter yet, and silently did nothing. Scenario authors
    papered over it with hand-tuned ``wait: "10000"`` steps, which is why the
    hole stayed invisible: the workaround was in every scenario.

    The fix needs an earlier signal, and ``flutter_bootstrap.js`` (or the older
    ``main.dart.js`` / ``flutter.js``) is in the served HTML from the first
    byte. A page without it is not Flutter and returns immediately, so no
    ordinary site pays for this.
    """
    if await is_flutter_page(page):
        return True

    try:
        is_loading_flutter = bool(await page.evaluate(_FLUTTER_LOADER_JS))
    except Exception as e:
        logger.debug("[AWT] Flutter loader probe failed: %s", e)
        return False

    if not is_loading_flutter:
        return False

    logger.debug("[AWT] Flutter loader detected — waiting for the app to boot")
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(0.25)
        if await is_flutter_page(page):
            logger.info("[AWT] Flutter app booted")
            return True

    logger.warning("[AWT] Flutter loader found but the app never booted (%.0fs)", timeout)
    return False


async def activate_semantics(page: Any) -> bool:
    """Activate Flutter Semantics tree. Call after navigation.

    Clicks flt-semantics-placeholder to trigger SemanticsBinding,
    then waits for flt-semantics nodes to appear.
    Retries up to 3 times with 3-second waits.

    Returns True if Semantics nodes are present after activation.
    """
    page_id = str(id(page))

    # Already activated for this page instance
    if _semantics_state.get(page_id):
        count = await _count_semantics_nodes(page)
        if count > 0:
            return True
        # Nodes disappeared (page navigated) — re-activate
        _semantics_state[page_id] = False

    # Check if already active (no activation needed)
    count = await _count_semantics_nodes(page)
    if count > 0:
        _semantics_state[page_id] = True
        logger.info("[AWT] Flutter Semantics already active (%d nodes)", count)
        return True

    logger.info("[AWT] Flutter Semantics activating...")

    for attempt in range(1, 4):
        # Method 1: Click flt-semantics-placeholder
        # This is the official Flutter mechanism to enable Semantics
        activated = await _click_semantics_placeholder(page)

        if not activated:
            # Method 2: Trigger via accessibility snapshot request
            # Playwright's a11y API signals to Flutter that a screen
            # reader is present, which enables SemanticsBinding
            with contextlib.suppress(Exception):
                await page.accessibility.snapshot()  # type: ignore[union-attr]

        if not activated:
            # Method 3: Focus the Flutter container
            await _focus_flutter_container(page)

        # Wait for Semantics tree to populate
        count = await _wait_for_semantics(page, timeout=3.0)
        if count > 0:
            _semantics_state[page_id] = True
            logger.info(
                "[AWT] Flutter Semantics activated (%d nodes, attempt %d/3)",
                count,
                attempt,
            )
            return True

        logger.info(
            "[AWT] Semantics activation attempt %d/3 — no nodes yet",
            attempt,
        )

    logger.warning("[AWT] Semantics activation failed → OCR fallback")
    return False


# Matched against resource URLs rather than ``initiatorType``: CanvasKit
# fetches its fallback font from WASM, which reports as ``other``/``fetch``
# depending on the Chromium build, so the initiator tells us nothing reliable.
_FONT_URL_RE = r"/\.(ttf|otf|woff2?)(\?|$)|fonts\.(gstatic|googleapis)\.com/i"

_FONT_PROBE_JS = f"""
() => {{
  const re = {_FONT_URL_RE};
  const entries = performance.getEntriesByType('resource')
    .filter((e) => re.test(e.name));
  return {{
    total: entries.length,
    done: entries.filter((e) => e.responseEnd > 0).length,
  }};
}}
"""


_FONT_POLL_INTERVAL = 0.25

# How long a font count must stop changing before we believe it. Measured on a
# real CanvasKit app: the first batch of 3 fonts landed at 2.6s and *looked*
# complete (done == total), then 8 more arrived at 3.9s. A naive
# "every requested font has responded" check returns during that 1.3s gap and
# screenshots a half-repainted canvas, so the count must also hold still.
_FONT_QUIET_SECONDS = 1.5

# How long to wait for the *first* font request. CanvasKit has to boot its WASM
# before it asks for anything -- 2.6s on the same measurement -- so a short
# grace period concludes "this page uses no web fonts" about two seconds before
# the page gets around to proving otherwise.
_FONT_APPEAR_SECONDS = 5.0


async def wait_for_fonts(
    page: Any,
    timeout: float = 12.0,
    settle: float = 0.6,
    appear_timeout: float = _FONT_APPEAR_SECONDS,
    quiet: float = _FONT_QUIET_SECONDS,
) -> bool:
    """Wait for late-arriving web fonts, then for the repaint they cause.

    Flutter CanvasKit paints the whole UI into a ``<canvas>``. When the app
    registers no font for the script it is about to draw -- a Korean app whose
    ``pubspec.yaml`` never declared a Korean font, say -- CanvasKit fetches one
    (typically Noto from ``fonts.gstatic.com``) and *repaints*. Until that
    lands, every glyph is a tofu box.

    Nothing in the DOM announces this. The Semantics tree is already stable and
    correct while the canvas is still tofu, so screenshots, PDF reports, OCR
    matching and visual-regression baselines all captured unreadable evidence
    of a perfectly healthy app. Scenario authors worked around it by hand, with
    ``wait: "12000"`` steps tuned by trial and error.

    Pixel stability is not usable as the signal here: a dashboard with a
    loading spinner never reaches a stable frame. Font *requests* are the
    narrow, bounded signal, and the rule is that the request count must both
    be fully answered and have stopped growing.

    Both call sites gate this on :func:`is_flutter_page`, so the cost is paid
    only by pages that render their text into a canvas.

    Returns True if any font request was observed, False if the page fetched
    none within ``appear_timeout``.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    appear_deadline = loop.time() + appear_timeout

    last_total = -1
    unchanged_since = loop.time()

    while loop.time() < deadline:
        try:
            probe = await page.evaluate(_FONT_PROBE_JS)
        except Exception as e:
            logger.debug("[AWT] font probe failed: %s", e)
            return last_total > 0

        total = int(probe.get("total", 0))
        done = int(probe.get("done", 0))

        if total != last_total:
            last_total = total
            unchanged_since = loop.time()

        if total == 0:
            if loop.time() >= appear_deadline:
                logger.debug("[AWT] No web fonts requested — nothing to wait for")
                return False
        elif done >= total and loop.time() - unchanged_since >= quiet:
            # Every requested font has answered and no new ones have appeared
            # for a while. The repaint happens on the next frame, which is the
            # part that actually changes the pixels we are about to read.
            await asyncio.sleep(settle)
            logger.info("[AWT] Fonts settled (%d loaded) — canvas repainted", done)
            return True

        await asyncio.sleep(_FONT_POLL_INTERVAL)

    logger.info("[AWT] Font wait timed out after %.1fs — capturing anyway", timeout)
    return last_total > 0


async def reset_semantics_cache() -> None:
    """Reset the activation cache. Call after page navigation."""
    _semantics_state.clear()


async def find_by_semantics(
    page: Any,
    text: str,
) -> tuple[int, int] | None:
    """Find a Flutter element by its Semantics label.

    Priority:
    1. flt-semantics[aria-label*="text"] — exact CanvasKit nodes
    2. [aria-label*="text"] — broader ARIA match
    3. get_by_role() with name — button/link/textbox/tab

    Returns (x, y) center coordinates or None.
    """
    search = text.strip()
    if not search:
        return None

    # Ensure Semantics is active (no-op if already cached)
    if not await activate_semantics(page):
        return None

    # Strategy 1: flt-semantics nodes (most precise for CanvasKit)
    result = await _try_flt_semantics(page, search)
    if result:
        return result

    # Strategy 2: Any element with matching aria-label
    result = await _try_aria_label(page, search)
    if result:
        return result

    # Strategy 3: ARIA role-based lookup
    for role in ["button", "link", "textbox", "tab", "menuitem"]:
        try:
            loc = page.get_by_role(role, name=search)
            if await loc.count() > 0:
                box = await loc.first.bounding_box()
                if box:
                    x = int(box["x"] + box["width"] / 2)
                    y = int(box["y"] + box["height"] / 2)
                    logger.info(
                        "[AWT] Semantics: '%s' via role=%s at (%d,%d)",
                        search,
                        role,
                        x,
                        y,
                    )
                    return x, y
        except Exception:
            continue

    logger.debug("[AWT] Semantics: '%s' not found", search)
    return None


async def get_all_semantics_labels(page: Any) -> list[str]:
    """Get all aria-labels from flt-semantics nodes (shadow DOM aware)."""
    try:
        labels: list[str] = await page.evaluate("""() => {
            function collectLabels(root) {
                const nodes = root.querySelectorAll(
                    'flt-semantics[aria-label]'
                );
                return Array.from(nodes)
                    .map(n => n.getAttribute('aria-label'))
                    .filter(Boolean);
            }

            let labels = collectLabels(document);
            if (labels.length > 0) return labels;

            const fv = document.querySelector('flutter-view');
            if (fv && fv.shadowRoot) {
                labels = collectLabels(fv.shadowRoot);
                if (labels.length > 0) return labels;
            }

            const gp = document.querySelector('flt-glass-pane');
            if (gp && gp.shadowRoot) {
                labels = collectLabels(gp.shadowRoot);
                if (labels.length > 0) return labels;
            }

            return labels;
        }""")
        return labels
    except Exception:
        return []


# -- Internal helpers ---------------------------------------------------------


async def _count_semantics_nodes(page: Any) -> int:
    """Count flt-semantics nodes in DOM (including shadow DOM)."""
    try:
        count: int = await page.evaluate("""() => {
            // Direct DOM first
            let n = document.querySelectorAll('flt-semantics').length;
            if (n > 0) return n;

            // Flutter 3.x: inside flutter-view shadow DOM
            const fv = document.querySelector('flutter-view');
            if (fv && fv.shadowRoot) {
                n = fv.shadowRoot.querySelectorAll('flt-semantics').length;
                if (n > 0) return n;
            }

            // Flutter 2.x: inside flt-glass-pane shadow DOM
            const gp = document.querySelector('flt-glass-pane');
            if (gp && gp.shadowRoot) {
                n = gp.shadowRoot.querySelectorAll('flt-semantics').length;
                if (n > 0) return n;
            }

            // Also count ARIA elements (Semantics may use these)
            return document.querySelectorAll(
                '[flt-semantics], [aria-label][role]'
            ).length;
        }""")
        return count
    except Exception:
        return 0


async def _click_semantics_placeholder(page: Any) -> bool:
    """Click flt-semantics-placeholder to trigger activation."""
    try:
        clicked = await page.evaluate("""() => {
            // Flutter 3.x: flutter-view shadow DOM
            const fv = document.querySelector('flutter-view');
            if (fv && fv.shadowRoot) {
                const ph = fv.shadowRoot.querySelector(
                    'flt-semantics-placeholder'
                );
                if (ph) { ph.click(); return true; }
            }

            // Flutter 2.x: flt-glass-pane shadow DOM
            const gp = document.querySelector('flt-glass-pane');
            if (gp && gp.shadowRoot) {
                const ph = gp.shadowRoot.querySelector(
                    'flt-semantics-placeholder'
                );
                if (ph) { ph.click(); return true; }
            }

            // Direct DOM (some Flutter builds)
            const ph = document.querySelector('flt-semantics-placeholder');
            if (ph) { ph.click(); return true; }

            return false;
        }""")
        return bool(clicked)
    except Exception:
        return False


async def _focus_flutter_container(page: Any) -> None:
    """Focus the Flutter container to trigger accessibility mode."""
    with contextlib.suppress(Exception):
        await page.evaluate("""() => {
            const target = (
                document.querySelector('flutter-view') ||
                document.querySelector('flt-glass-pane')
            );
            if (target) {
                target.focus();
                target.dispatchEvent(new Event('focus', {bubbles: true}));
            }
        }""")


async def _wait_for_semantics(page: Any, timeout: float = 3.0) -> int:
    """Poll for flt-semantics nodes to appear."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        count = await _count_semantics_nodes(page)
        if count > 0:
            return count
        await asyncio.sleep(0.3)
    return 0


async def _try_flt_semantics(
    page: Any,
    text: str,
) -> tuple[int, int] | None:
    """Find via flt-semantics[aria-label] (shadow DOM aware).

    Selects the smallest matching node (most specific element)
    to avoid parent containers returning wrong coordinates.
    """
    try:
        result = await page.evaluate(
            """(searchText) => {
            function findAllInRoot(root) {
                const matches = [];
                const nodes = root.querySelectorAll('flt-semantics');
                for (const node of nodes) {
                    const label = node.getAttribute('aria-label') || '';
                    if (!label.includes(searchText)) continue;
                    const rect = node.getBoundingClientRect();
                    if (rect.width < 1 || rect.height < 1) continue;
                    matches.push({
                        label: label,
                        x: Math.round(rect.x + rect.width / 2),
                        y: Math.round(rect.y + rect.height / 2),
                        area: rect.width * rect.height,
                        exactMatch: label === searchText,
                    });
                }
                return matches;
            }

            let all = findAllInRoot(document);

            if (all.length === 0) {
                const fv = document.querySelector('flutter-view');
                if (fv && fv.shadowRoot) {
                    all = findAllInRoot(fv.shadowRoot);
                }
            }
            if (all.length === 0) {
                const gp = document.querySelector('flt-glass-pane');
                if (gp && gp.shadowRoot) {
                    all = findAllInRoot(gp.shadowRoot);
                }
            }

            if (all.length === 0) return null;

            // Prefer exact match over substring match
            const exact = all.filter(m => m.exactMatch);
            const candidates = exact.length > 0 ? exact : all;

            // Pick smallest area (most specific element)
            candidates.sort((a, b) => a.area - b.area);
            return candidates[0];
        }""",
            text,
        )

        if result:
            x, y = result["x"], result["y"]
            label = result.get("label", text)
            logger.info(
                "[AWT] Semantics: '%s' (label='%s') at (%d,%d) area=%.0f",
                text,
                label,
                x,
                y,
                result.get("area", 0),
            )
            return x, y
    except Exception:
        pass
    return None


async def _try_aria_label(
    page: Any,
    text: str,
) -> tuple[int, int] | None:
    """Find via any [aria-label] element (shadow DOM, smallest area)."""
    try:
        result = await page.evaluate(
            """(searchText) => {
            function findAllInRoot(root) {
                const matches = [];
                const nodes = root.querySelectorAll('[aria-label]');
                for (const node of nodes) {
                    const label = node.getAttribute('aria-label') || '';
                    if (!label.includes(searchText)) continue;
                    const rect = node.getBoundingClientRect();
                    if (rect.width < 1 || rect.height < 1) continue;
                    matches.push({
                        label: label,
                        x: Math.round(rect.x + rect.width / 2),
                        y: Math.round(rect.y + rect.height / 2),
                        area: rect.width * rect.height,
                        exactMatch: label === searchText,
                    });
                }
                return matches;
            }

            let all = findAllInRoot(document);
            const fv = document.querySelector('flutter-view');
            if (fv && fv.shadowRoot) {
                all = all.concat(findAllInRoot(fv.shadowRoot));
            }
            const gp = document.querySelector('flt-glass-pane');
            if (gp && gp.shadowRoot) {
                all = all.concat(findAllInRoot(gp.shadowRoot));
            }

            if (all.length === 0) return null;

            const exact = all.filter(m => m.exactMatch);
            const candidates = exact.length > 0 ? exact : all;
            candidates.sort((a, b) => a.area - b.area);
            return candidates[0];
        }""",
            text,
        )

        if result:
            x, y = result["x"], result["y"]
            logger.info(
                "[AWT] Semantics: '%s' via aria-label at (%d,%d)",
                text,
                x,
                y,
            )
            return x, y
    except Exception:
        pass
    return None


def _escape_css(text: str) -> str:
    """Escape special characters for CSS attribute selectors."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
