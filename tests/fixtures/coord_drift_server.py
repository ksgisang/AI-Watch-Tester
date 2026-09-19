"""Local stand-in for a screen whose buttons move with the content.

This is the shape that made remembered coordinates dangerous in the field: the
same button sits at a different height depending on how long the question above
it is, so a position learned on one page misses on the next and lands on inert
background instead.

The page records every click in `window.__clicks` **without changing a pixel**,
so a test can tell a click that hit the button from one that hit nothing while
still letting the executor see "nothing moved on screen".

Usage:
    with coord_drift_server() as base_url:
        ...  # base_url is like "http://127.0.0.1:54321/?pad=40"

`pad` is the height of the spacer above the button: the taller it is, the lower
the button sits — the same button at a different place.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Quiz</title>
<style>
  body {{ font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }}
  label {{ display: block; margin-top: 8px; }}
  input {{ font-size: 18px; padding: 8px; width: 240px; }}
  #spacer {{ height: {pad}px; background: #fff; }}
  #grade {{ font-size: 20px; padding: 14px 28px; }}
  #panel {{ display: none; height: 320px; background: #2b6cb0; color: #fff;
            font-size: 28px; padding: 24px; }}
</style></head>
<body>
<h1>Quiz</h1>
<label for="nickname">Nickname</label>
<input id="nickname" name="nickname">
<label for="note">Note</label>
<input id="note" name="note">
<div id="spacer"></div>
<button id="grade" type="button">Grade it</button>
<div id="panel">Graded</div>
<script>
  // Clicks are recorded, never drawn: a click that misses the button has to
  // leave the screen untouched, or the tool could not tell it missed.
  window.__clicks = [];
  document.addEventListener('click', function (e) {{
    window.__clicks.push(e.target.id || e.target.tagName.toLowerCase());
  }}, true);
  document.getElementById('grade').addEventListener('click', function () {{
    document.getElementById('panel').style.display = 'block';
  }});
</script>
</body></html>
"""


class _QuizHandler(BaseHTTPRequestHandler):
    """Serves one page whose button height follows the `pad` query parameter."""

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        query = parse_qs(urlparse(self.path).query)
        try:
            pad = int(query.get("pad", ["40"])[0])
        except ValueError:
            pad = 40
        body = _PAGE.format(pad=max(0, min(pad, 4000))).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence per-request stderr logging during tests."""


@contextmanager
def coord_drift_server() -> Iterator[str]:
    """Run the quiz page server on an ephemeral port; yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuizHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
