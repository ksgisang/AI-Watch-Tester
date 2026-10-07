"""The signup form shape that reported a typing failure as a pass.

SC-901 step 6 was `find_and_type` against a field labelled 학교. The live page
served a `<select>`, not an `<input>`. The selector route clicks the element and
then types on the keyboard, so the click opened the dropdown, the keystrokes
walked the option list, and nothing read the value back -- the step was scored
`PASSED`. No account was created, and the eighteen steps after it ran against a
login screen.

So the page serves the four shapes a `find_and_type` target can actually be:

    #school    `<select>`              typing cannot enter text here at all
    #email     ordinary `<input>`      the case that must stay a pass
    #code      `readonly` input        refuses the keystrokes, silently
    #referrer  `disabled` input        never even takes focus

The last one is why the probe needs a selector fallback: `document.activeElement`
is the path-independent way to ask what received the keystrokes, but a disabled
field never becomes the active element, so asking only that question reports the
`<body>` and learns nothing.

`/plain` is the other half of the fixture: an ordinary page that does **not**
contain the words a failing assertion would print, so an assertion pointed at it
has exactly one honest answer.

Usage:
    with signup_form_server() as base_url:
        form = f"{base_url}/signup"
        plain = f"{base_url}/plain"
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

#: The phrase SC-901 looked for after signup. Deliberately absent from every
#: page this server serves: the only way an assertion for it can pass here is
#: if AWT read back something AWT itself wrote.
APPROVAL_NOTICE = "승인 대기"

#: What the dropdown is showing before anyone touches it. The warning quotes it
#: back so the reader can see the field did not take the text.
SCHOOL_PLACEHOLDER = "선택"

_SIGNUP = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>가입</title>
<style>
  body {{ font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }}
  label {{ display: block; margin-top: 12px; font-size: 14px; }}
  input, select {{ font-size: 15px; padding: 6px; width: 260px; }}
</style></head>
<body>
<h1>학원 가입</h1>
<form id="signup">
  <label for="school">학교</label>
  <select id="school" name="school">
    <option value="">{SCHOOL_PLACEHOLDER}</option>
    <option value="garak">가락고등학교</option>
    <option value="hanul">하늘고등학교</option>
  </select>

  <label for="email">이메일</label>
  <input id="email" name="email" type="email" />

  <label for="code">추천 코드</label>
  <input id="code" name="code" value="" readonly />

  <label for="referrer">소개자</label>
  <input id="referrer" name="referrer" value="" disabled />
</form>
</body></html>
"""

_PLAIN = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>로그인</title>
<style>body { font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }</style>
</head>
<body>
<h1>로그인</h1>
<p id="notice">이메일 또는 비밀번호가 올바르지 않습니다.</p>
</body></html>
"""

_PAGES = {"/signup": _SIGNUP, "/plain": _PLAIN}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
        page = _PAGES.get(urlparse(self.path).path, _PLAIN)
        payload = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the per-request log so test output stays readable."""


@contextmanager
def signup_form_server() -> Iterator[str]:
    """Serve the pages on a free localhost port; yield the base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
