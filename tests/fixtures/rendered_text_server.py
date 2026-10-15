"""Local stand-in for a page that shows the right words wrapped in junk.

This is §9-2: a quiz app rendered its LaTeX source instead of the formula, so
where the reader should have seen `질량` the page said `\\(\\text{질량}\\)`. The
suite was green throughout, and it was green honestly -- every text assertion
AWT offers is a substring match, and `질량` is a substring of the junk. The bug
was visible to anyone looking at the screen and invisible to every assertion
pointed at it.

So the page serves the same words three ways, chosen by `render`:

    clean  — `질량`                 what the reader should see
    latex  — `\\(\\text{질량}\\)`      the leak, substring-identical
    empty  — ``                     rendered nothing at all
    split  — `질량` plus a phrase broken across two block elements

A fourth mode, `split`, answers a different question: it puts `NOTICE` and
`WORD` in two adjacent block elements, so the phrase `NOTICE\nWORD` is in
`inner_text("body")` and is matched by no single element. Measured: that
phrase is in the page text and `get_by_text` returns zero candidates. Any
check that reads "`get_by_text` found nothing" as "the text is hidden" fails
this page, which is perfectly readable.

Every mode also carries a `#hidden` paragraph holding text that is in the DOM but
`display: none`, because "the DOM has it" and "a person can read it" are not
the same claim. AAT-115 taught `assert_text` to tell them apart.

It also carries the harder shape of the same problem: `NOTICE` appears twice,
in a hidden stale template **first** and in the live view second. Document
order puts the unreadable copy ahead of the readable one, so checking only the
first match -- the obvious implementation -- fails a page that is perfectly
fine. One copy is not enough to catch that; two in this order are.

Usage:
    with rendered_text_server() as base_url:
        good = f"{base_url}/?render=clean"
        leak = f"{base_url}/?render=latex"
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

#: The word the scenario is written against.
WORD = "질량"

#: What the page says when the template leaks. `WORD` is a substring of it,
#: which is the entire reason the original bug survived its own test suite.
LEAKED = "\\(\\text{질량}\\)"

#: Present twice: hidden copy first, visible copy second. See the module docstring.
NOTICE = "주의 사항"

#: The phrase no single element holds. Written with the newline `inner_text`
#: puts between two block elements, because that is the form in which it is
#: genuinely a substring of the page text.
SPLIT_PHRASE = f"{NOTICE}\n{WORD}"

_BODIES = {
    "clean": WORD,
    "latex": LEAKED,
    "empty": "",
}

#: Adjacent block elements, so `inner_text` joins them with a single newline.
_SPLIT = f'<div id="split-a">{NOTICE}</div><div id="split-b">{WORD}</div>'

_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>문항</title>
<style>
  body {{ font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }}
  #question {{ font-size: 24px; }}
  /* In the DOM, unreadable on screen. */
  #hidden {{ display: none; }}
  #stale-notice {{ display: none; }}
</style></head>
<body>
<h1>문항</h1>
<p id="question">{body}</p>
<p id="hidden">삭제된 안내문</p>
<p id="stale-notice">{notice}</p>
<p id="live-notice">{notice}</p>
{extra}
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        render = (parse_qs(urlparse(self.path).query).get("render") or ["clean"])[0]
        page = _PAGE.format(
            body=_BODIES.get(render, _BODIES["clean"]),
            notice=NOTICE,
            extra=_SPLIT if render == "split" else "",
        )
        payload = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the per-request log so test output stays readable."""


@contextmanager
def rendered_text_server() -> Iterator[str]:
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
