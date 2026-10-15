"""Local stand-in for the two cases ``assert_screen_changed`` has to tell apart.

The assertion's whole job is one question: *did the step in front of me do
anything?* On 2026-10-15 it was measured answering ``Screen change 0.0%`` on a
screen that had visibly changed -- an FAQ accordion that the previous step had
just expanded, with the run's own ``step006_after.png`` showing it open. No
threshold could have rescued it, because the comparison was taking its baseline
at the start of the assert step itself and its reading at the end of that same
step, with no action in between. The answer was 0.0% before the browser was
ever asked.

That makes the failure invisible in exactly the way the repository keeps
running into: a green test suite could not have gone red, because nothing in it
drove two steps in sequence through a real page. So the fixture carries both
directions, and the test that uses it is only worth anything if it runs both.

``/`` serves one page with two controls:

``#expand``
    Expands a tall panel. A genuine, large, unmistakable change -- the shape
    the assertion exists to confirm. A repair that still reads 0% here has not
    worked.

``#inert``
    A button that is wired to nothing. Clicking it leaves every pixel where it
    was. A repair that reports *change* here has traded one wrong answer for
    another: scenarios would start passing on clicks that missed.

The panel is deliberately large (and dark against a light page) so the change
is far above any plausible threshold; the point under test is which frames get
compared, not how sensitive the comparison is.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Screen change fixture</title>
<style>
  body { font-family: sans-serif; margin: 0; padding: 24px; background: #ffffff; }
  button { font-size: 20px; padding: 12px 20px; margin-right: 12px; }
  #panel {
    display: none;
    margin-top: 24px;
    height: 460px;
    background: #202a3c;
    color: #ffffff;
    font-size: 28px;
    padding: 24px;
  }
  #panel.open { display: block; }
</style>
</head>
<body>
  <h1>Screen change fixture</h1>
  <button id="expand">Expand the panel</button>
  <button id="inert">Do nothing at all</button>
  <div id="panel">The panel is now open and covers most of the viewport.</div>
<script>
  document.getElementById('expand').addEventListener('click', function () {
    document.getElementById('panel').classList.add('open');
  });
  // #inert has no listener on purpose: clicking it must move no pixels.
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        payload = _PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the per-request log so test output stays readable."""


@contextmanager
def screen_change_server() -> Iterator[str]:
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
