"""Local stand-in for a page that sometimes shows a dismissible popup.

``if_visible`` exists for the one thing E2E scenarios cannot predict: an
interstitial that is there on some runs and not on others -- a cookie banner, a
"session about to expire" notice, a first-visit tour. The contract is two
branches and nothing else: when the thing is on screen, run ``then``; when it
is not, skip and carry on as if the step were not written.

On 2026-03-24 it was reported doing the opposite, and the fix (``0516fd9``)
named the cause: the visibility check accepted *any* DOM node whose text
matched, without asking whether that node was on screen. A collapsed nav
holding a link labelled ``도움말`` was enough to convince it that a help popup
was open. Nothing closed the imaginary popup, so the retry ran three times and
the step failed -- a scenario broken by a page that was behaving perfectly.

That fix shipped with no reproduction, which is why this fixture exists. The
modes are the four states that question has:

``modal``
    The popup is genuinely on screen. ``then`` must run.

``clean``
    The phrase is on no part of the page, in the DOM or in the pixels.
    ``then`` must not run.

``hidden``
    **The regression shape.** The phrase is in the DOM, inside a
    ``display: none`` nav link, and the popup is not open. This is the
    ``도움말`` report, reduced: a text search alone says yes, and the answer is
    wrong.

``collapsed``
    The same idea through a different CSS route -- a zero-height
    ``overflow: hidden`` container, which is how a real collapsed menu is
    usually built. Worth asking separately because ``display: none`` and
    ``height: 0`` do not look the same to Playwright: the first gives the child
    no box at all, the second leaves the child its own box inside a clipped
    parent.

Every mode serves the same witness button, always present, always clickable,
and always *outside* the popup. It is what ``then`` presses, and it leaves two
marks: it bumps a counter the test can read, and it closes the popup if one is
open. Both are needed. Without the counter, "``then`` did not run" and
"``then`` ran and did nothing visible" are the same observation; without the
close, the ``modal`` branch would retry three times and fail for a reason that
has nothing to do with the branch being tested.

It sits outside the popup so that the two branches differ in exactly one thing
-- whether the popup is up. A button inside the popup would be missing in three
of the four modes, and then a skipped ``then`` and a ``then`` that could not
find its target would be indistinguishable.

The popup itself is pressable and dismisses itself, which the flag form of
``if_visible`` needs: that form gates an ordinary step on its own target, so
the target has to be something a click changes. A click that moves no pixels
earns AAT-109's "clicked and nothing happened" warning, and a test written
against an inert popup would measure that warning instead of the branch.

Usage:
    with dismissible_popup_server() as base_url:
        popup_is_up = f"{base_url}/?mode=modal"
        nothing_there = f"{base_url}/?mode=clean"
        the_2026_03_24_report = f"{base_url}/?mode=hidden"
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

#: What the scenario watches for. Latin, because this fixture is about
#: visibility and not about which Tesseract language packs are installed
#: (AAT-119 covers that); and a phrase no part of the chrome repeats, so the
#: OCR fallback cannot read it out of a button caption on the ``clean`` page.
POPUP_TEXT = "SESSION NOTICE"

#: Reads the counter. ``then`` pressing the witness is the only thing that
#: moves it, so its value is the whole answer to "did the branch run".
TALLY_SELECTOR = "#tally"

#: What ``then`` presses.
WITNESS_SELECTOR = "#witness"

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dismissible popup</title>
<style>
  body {{
    font-family: Helvetica, Arial, sans-serif; margin: 0; padding: 40px;
    background: #fff; color: #111;
  }}
  h1 {{ font-size: 28px; }}
  /* Above the popup on purpose: the witness must stay pressable in every
     mode, so that a failed press can never be mistaken for a skipped
     branch. */
  #witness {{
    position: fixed; top: 16px; left: 16px; z-index: 9999;
    font-size: 20px; padding: 12px 20px;
  }}
  #tally {{ font-size: 32px; font-weight: 700; padding: 24px 0; }}
  /* Clickable, and pressing it dismisses it. The flag form of ``if_visible``
     gates a normal step on its own target, so the target has to be something
     pressing actually changes -- otherwise the step earns AAT-109's "clicked
     and nothing moved" warning and the test measures that instead of the
     branch. */
  #popup {{
    position: fixed; top: 160px; left: 50%; transform: translateX(-50%);
    width: 460px; padding: 32px; background: #fffbe6;
    border: 3px solid #d4a017; font-size: 26px; font-weight: 700;
    text-align: center; cursor: pointer;
  }}
  /* The two ways a page hides text it still keeps in the DOM. */
  .display-none {{ display: none; }}
  .clipped {{ height: 0; overflow: hidden; }}
</style></head>
<body>
<button id="witness" onclick="witnessed()">WITNESS</button>
<h1>Dashboard</h1>
<div id="tally">0</div>
{nav}
{popup}
<script>
  function witnessed() {{
    const tally = document.getElementById('tally');
    tally.textContent = String(Number(tally.textContent) + 1);
    const popup = document.getElementById('popup');
    if (popup) popup.remove();
  }}
</script>
</body></html>
"""

_POPUP = f'<div id="popup" onclick="witnessed()">{POPUP_TEXT}</div>'

#: The ``도움말`` report in two lines: the words are in the document and the
#: popup is not open.
_HIDDEN_NAV = f'<nav class="display-none"><a href="#">{POPUP_TEXT}</a></nav>'
_CLIPPED_NAV = f'<nav class="clipped"><a href="#">{POPUP_TEXT}</a></nav>'

_MODES = {
    "modal": ("", _POPUP),
    "clean": ("", ""),
    "hidden": (_HIDDEN_NAV, ""),
    "collapsed": (_CLIPPED_NAV, ""),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        query = parse_qs(urlparse(self.path).query)
        mode = (query.get("mode") or ["clean"])[0]
        nav, popup = _MODES.get(mode, _MODES["clean"])
        payload = _PAGE.format(nav=nav, popup=popup).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the per-request log so test output stays readable."""


@contextmanager
def dismissible_popup_server() -> Iterator[str]:
    """Serve the page on a free localhost port; yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
