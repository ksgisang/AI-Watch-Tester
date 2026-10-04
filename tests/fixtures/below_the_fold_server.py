"""Local stand-in for a page whose content is not on the first screen.

Every screenshot AWT takes is the viewport, and until AAT-121 nothing scrolled
and re-captured. So a target the DOM could not name and that sat below the fold
was invisible to the matcher chain, to healing, and to the ``text_visible`` OCR
fallback -- and the report said "not found", which is a false failure about a
page that was perfectly fine.

Two layouts, because they fail differently and only one of them is obvious:

``mode=document``
    An ordinary tall page. ``window.scrollY`` moves when it scrolls, so an
    implementation that trusted ``scrollY`` would look correct here.

``mode=canvas``
    ``body { overflow: hidden }`` with the content inside an inner
    ``overflow: auto`` box. The wheel scrolls the box, the pixels move, and
    **``window.scrollY`` stays 0 forever.** This is the shape of a Flutter
    CanvasKit app, which scrolls its own content and never moves the document,
    and it is the reason the sweep decides "did it move?" from pixels rather
    than from a scroll offset. A ``scrollY``-based implementation passes the
    ``document`` case and silently does nothing here -- on exactly the pages
    the feature exists for.

The target is deliberately unreachable by selector: the element carries no id,
no stable class and no name, so the DOM routes have to fail and the visual
path has to be the one that answers. The filler above it is nonsense words
rather than lorem ipsum so that OCR cannot accidentally read the target phrase
out of the filler.

``?paint=image``
    Serves the target as a PNG with the words baked into the pixels instead of
    writing them as a text node, so ``inner_text("body")`` cannot see them.
    This is what forces the ``text_visible`` assertion down its OCR fallback:
    with a real text node the DOM check answers first and the OCR path never
    runs at all.

``?filler=N``
    How many filler blocks sit above the target, which is how far down it is.
    The default puts it out of reach of the OCR fallback on purpose -- that
    path is capped lower than the matcher chain because Tesseract is expensive
    per frame -- so a test of the OCR sweep has to ask for a shorter page, and
    a test of the cap asks for the default one.

Usage:
    with below_the_fold_server() as base_url:
        tall = f"{base_url}/?mode=document"
        canvas_like = f"{base_url}/?mode=canvas"
        pixels_only = f"{base_url}/?mode=document&paint=image"
        shorter = f"{base_url}/?mode=document&paint=image&filler=4"
"""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

#: The words only reachable by scrolling. Latin so the test does not depend on
#: a Korean traineddata file being installed; AAT-119 covers that separately.
TARGET_TEXT = "DEEP HARBOR GATE"

#: Sits on the first screen. Its whole job is to prove the sweep starts where
#: the page already is and does not need to scroll to find a visible target.
ABOVE_TEXT = "SURFACE MARKER"

#: How many filler blocks to put between them. At 220px each this pushes the
#: target roughly 2,600px down -- three screens at a 720px viewport, so a
#: single extra capture is not enough to reach it.
_FILLER_BLOCKS = 12

_FILLER_WORDS = (
    "quorn",
    "vellig",
    "trabast",
    "munder",
    "pellik",
    "dwarsh",
)

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Below the fold</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Helvetica, Arial, sans-serif; margin: 0; background: #fff;
    color: #111; {body_overflow}
  }}
  #scroller {{ {scroller_style} }}
  .filler {{
    height: 220px; padding: 16px; font-size: 18px; color: #777;
    border-bottom: 1px solid #eee;
  }}
  #above {{ font-size: 34px; font-weight: 700; padding: 24px; }}
  /* No id, no stable class, no name: the DOM must not be able to name it. */
  .t {{
    font-size: 40px; font-weight: 700; padding: 40px 24px; background: #ffd34d;
  }}
</style></head>
<body>
<div id="scroller">
  <div id="above">{above}</div>
  {filler}
  {target_block}
  <div class="filler">tail {words}</div>
</div>
</body></html>
"""

_MODES = {
    # Ordinary document scroll: window.scrollY moves.
    "document": ("", "min-height: 100%;"),
    # Inner container scroll: pixels move, window.scrollY never does.
    "canvas": ("overflow: hidden; height: 100vh;", "height: 100vh; overflow: auto;"),
}

#: ``?paint=image`` replaces the target ``<div>`` with an ``<img>`` whose PNG
#: has the same words baked into it. The text is then in the pixels and nowhere
#: else -- ``inner_text("body")`` cannot see it, and neither can any selector --
#: so the ``text_visible`` assertion has to reach it through the OCR fallback or
#: not at all. That is the shape of a Flutter CanvasKit screen, and it is the
#: only way to show the OCR path looks below the fold: with a real text node the
#: DOM check answers first and the OCR path never runs.
#:
#: It is a server-rendered PNG rather than a ``<canvas>`` the page paints
#: itself. Measured here, a 2D canvas in this headless Chromium never reaches
#: the screenshot at all: the fill reads back correctly inside the call that
#: drew it and comes back fully transparent from the next one, and the capture
#: shows nothing. (Real CanvasKit screens do render -- they paint through
#: WebGL.) A canvas fixture would therefore be testing the browser, not AWT.
_IMAGE_TARGET = '<img id="painted" src="/target.png" width="860" height="120" alt="">'

#: Pillow's bundled font rather than a system one: it renders identically on a
#: developer's macOS and on the CI runner, and Tesseract reads it at every PSM
#: mode the fallback tries. A system font path would make this fixture skip or
#: fail depending on which machine ran it.
_TARGET_PNG_SIZE = (860, 120)


def _target_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", _TARGET_PNG_SIZE, "#ffd34d")
    ImageDraw.Draw(image).text(
        (24, 28), TARGET_TEXT, fill="#111111", font=ImageFont.load_default(size=56)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _filler(count: int = _FILLER_BLOCKS) -> str:
    blocks = []
    for i in range(count):
        words = " ".join(_FILLER_WORDS[(i + j) % len(_FILLER_WORDS)] for j in range(5))
        blocks.append(f'<div class="filler">{i:02d} {words}</div>')
    return "\n  ".join(blocks)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        parsed = urlparse(self.path)
        if parsed.path == "/target.png":
            self._respond(_target_png(), "image/png")
            return
        query = parse_qs(parsed.query)
        mode = (query.get("mode") or ["document"])[0]
        paint = (query.get("paint") or ["dom"])[0]
        body_overflow, scroller_style = _MODES.get(mode, _MODES["document"])
        dom_target = f'<div class="t">{TARGET_TEXT}</div>'
        target_block = _IMAGE_TARGET if paint == "image" else dom_target
        try:
            blocks = int((query.get("filler") or [_FILLER_BLOCKS])[0])
        except ValueError:
            blocks = _FILLER_BLOCKS
        page = _PAGE.format(
            body_overflow=body_overflow,
            scroller_style=scroller_style,
            above=ABOVE_TEXT,
            target_block=target_block,
            filler=_filler(blocks),
            words=" ".join(_FILLER_WORDS),
        )
        self._respond(page.encode("utf-8"), "text/html; charset=utf-8")

    def _respond(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the per-request log so test output stays readable."""


@contextmanager
def below_the_fold_server() -> Iterator[str]:
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
