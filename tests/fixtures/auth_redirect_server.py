"""Local stand-in for a login-gated web app.

Every protected path answers 307 -> /login?next=<path>, the same way a
Next.js auth gate does for a logged-out visitor. Login-redirect regression
tests run against this instead of a live deployment, so they keep working
offline and in CI.

Usage:
    with auth_redirect_server() as base_url:
        ...  # base_url is like "http://127.0.0.1:54321"
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

_LOGIN_PATH = "/login"

_LOGIN_HTML = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sign in</title></head>
<body style="font-family:sans-serif;padding:40px">
<h1>Sign in</h1>
<form><label>Nickname <input name="nickname"></label>
<label>PIN <input name="pin" type="password"></label>
<button type="submit">Sign in</button></form>
</body></html>
"""

_HOME_HTML = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dashboard</title></head>
<body style="font-family:sans-serif;padding:40px">
<h1>Dashboard</h1><p>Signed in content.</p>
</body></html>
"""


class _AuthGateHandler(BaseHTTPRequestHandler):
    """Serves the login page; redirects everything else to it."""

    # Set per-server: paths served without a redirect (simulates a signed-in user)
    public_paths: tuple[str, ...] = ()

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]

        if path == _LOGIN_PATH:
            self._respond(200, _LOGIN_HTML)
            return

        if path in self.public_paths:
            self._respond(200, _HOME_HTML)
            return

        self.send_response(307)
        self.send_header("Location", f"{_LOGIN_PATH}?next={quote(path, safe='')}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence per-request stderr logging during tests."""


@contextmanager
def auth_redirect_server(public_paths: tuple[str, ...] = ()) -> Iterator[str]:
    """Run the auth-gate server on an ephemeral port; yield its base URL.

    Args:
        public_paths: Paths served with 200 instead of the login redirect.
    """
    handler = type("_Handler", (_AuthGateHandler,), {"public_paths": public_paths})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
