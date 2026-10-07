"""Keep AWT's own progress bar out of everything AWT then reads back.

``aat run`` paints a ``#awt-overlay`` bar on the page under test so a human
watching a headful browser can see which step is running. That bar is for the
*live window*. It must not reach a single capture, because every consumer of
``engine.screenshot()`` is AWT judging its own target:

* evidence screenshots and the PDF report -- the bar covers the bottom of the
  page and stamps the step description across the proof,
* visual-regression baselines -- a bar whose text changes per step makes every
  diff fail for a reason that has nothing to do with the product,
* the matcher chain and the OCR fallback -- these *search* the pixels, and the
  bar renders the expected text verbatim whenever an assertion fails
  (``Text '<expected>' not visible on page``). Reading that back finds the
  expected words and reports the assertion as passed: a false pass manufactured
  out of AWT's own complaint.

The DOM routes are handled structurally instead -- the bar lives in a closed
shadow root (see ``_OVERLAY_INIT_JS`` in ``cli/commands/run_cmd.py``), so
``inner_text("body")`` and Playwright's text engine cannot see it at all. Pixels
have no such boundary, which is why this module exists.

Hiding is reference-counted. Callers nest: the comparator hides the bar around
a whole OCR sweep, and each capture inside that sweep hides it again. Without a
counter the inner restore would put back the value the outer one had already
set to ``none``, leaving the bar hidden for the rest of the run.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

# ``dataset`` keys are camelCase in JS and land as ``data-awt-*`` attributes.
_HIDE_JS = """
() => {
  const b = document.getElementById('awt-overlay');
  if (!b) return false;
  const depth = (parseInt(b.dataset.awtHideDepth || '0', 10) || 0) + 1;
  b.dataset.awtHideDepth = String(depth);
  if (depth === 1) {
    b.dataset.awtPrevDisplay = b.style.display;
    b.style.display = 'none';
  }
  return true;
}
"""

_SHOW_JS = """
() => {
  const b = document.getElementById('awt-overlay');
  if (!b) return;
  const depth = (parseInt(b.dataset.awtHideDepth || '0', 10) || 0) - 1;
  if (depth > 0) {
    b.dataset.awtHideDepth = String(depth);
    return;
  }
  delete b.dataset.awtHideDepth;
  b.style.display = b.dataset.awtPrevDisplay || '';
}
"""


@contextlib.asynccontextmanager
async def overlay_hidden(page: Any) -> AsyncIterator[None]:
    """Hold the progress bar hidden for the duration of the block.

    ``page`` is a Playwright page or ``None``; anything that cannot run JS is a
    no-op, so engines without a page and the fake engines in the test suite
    pass straight through.

    Failing to hide never fails the caller. A capture carrying the bar is worse
    evidence, but refusing to capture at all is worse than that.
    """
    hidden = False
    if page is not None:
        try:
            hidden = bool(await page.evaluate(_HIDE_JS))
        except Exception as e:  # noqa: BLE001 - never let cosmetics break a capture
            logger.debug("Could not hide the AWT overlay before a capture: %s", e)
    try:
        yield
    finally:
        if hidden:
            with contextlib.suppress(Exception):
                await page.evaluate(_SHOW_JS)
