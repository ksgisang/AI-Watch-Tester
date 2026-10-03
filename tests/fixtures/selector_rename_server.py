"""Local stand-in for the refactor that breaks every selector in a suite.

This is the failure self-healing exists for, and it is the most ordinary thing
a front-end developer does: a component is renamed, so `#grade` becomes
`#grade-v2`, and **the page looks exactly the same**. Every tool that finds
elements by selector alone fails here, and every scenario has to be rewritten
by hand.

So the page is styled by class and identified by id, and only the id follows the
`id` query parameter. The button's pixels are byte-identical across versions —
which is the whole premise: a picture of it taken before the rename is still a
true description of it after.

The button draws a panel when clicked, so a test can tell a click that hit it
from one that landed on background. Unlike `coord_drift_server`, hitting it is
*supposed* to change the screen here: a heal that finds the element but misses
it would otherwise read as a pass.

Usage:
    with selector_rename_server() as base_url:
        before = f"{base_url}/?id=grade"       # the selector the scenario names
        after = f"{base_url}/?id=grade-v2"     # the same button, renamed

`text` renames the caption instead, for the case where nothing durable is left.
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
  /* Styled by class, never by id: the rename must not change one pixel, or
     the test would be proving that the picture matches a *different* button. */
  body {{ font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }}
  .btn {{ font-size: 20px; padding: 14px 28px; background: #e2e8f0;
          border: 2px solid #1a202c; color: #1a202c; }}
  #panel {{ display: none; height: 260px; background: #2b6cb0; color: #fff;
            font-size: 28px; padding: 24px; }}
</style></head>
<body>
<h1>Quiz</h1>
<p>Answer the question, then grade it.</p>
<button id="{button_id}" class="btn" type="button">{text}</button>
<div id="panel">Graded</div>
<script>
  window.__clicks = [];
  document.addEventListener('click', function (e) {{
    window.__clicks.push(e.target.id || e.target.tagName.toLowerCase());
  }}, true);
  document.getElementById('{button_id}').addEventListener('click', function () {{
    document.getElementById('panel').style.display = 'block';
  }});
</script>
</body></html>
"""


class _RenameHandler(BaseHTTPRequestHandler):
    """Serves one page whose button id — and only its id — follows the query."""

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        query = parse_qs(urlparse(self.path).query)
        button_id = query.get("id", ["grade"])[0][:40] or "grade"
        text = query.get("text", ["Grade it"])[0][:40] or "Grade it"
        body = _PAGE.format(button_id=button_id, text=text).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence per-request stderr logging during tests."""


@contextmanager
def selector_rename_server() -> Iterator[str]:
    """Run the rename page server on an ephemeral port; yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RenameHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
