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

`/longform` and `/cleanform` are the second half of the same lesson. The four
shapes above all misbehave in one element, so none of them can show text
landing in a field *other* than the one the step named -- the receiving field
holds a value and is perfectly ordinary. `/longform` reproduces the form where
that happened; `/cleanform` is the same four fields with placeholders that do
not name each other, and exists so the absence of a false positive can be
measured rather than assumed.

Usage:
    with signup_form_server() as base_url:
        form = f"{base_url}/signup"
        plain = f"{base_url}/plain"
        hazard = f"{base_url}/longform"
        clean = f"{base_url}/cleanform"
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

# The real signup form that scored three typing steps PASSED while leaving two
# of its fields empty. Reproduced field for field, because every part of the
# shape matters:
#
#   #school           placeholder contains '이름' -- and comes first in the
#                     document, so an '이름' target resolves to the school box
#   #name             labelled exactly '이름', and the field that stays empty
#   #password         placeholder says nothing about 비밀번호
#   #password-confirm placeholder '비밀번호 재입력' -- the only placeholder match
#                     for a '비밀번호' target, so both password steps land here
#
# '학교' and '비밀번호 확인' resolve correctly, which is the point: the collision
# only becomes visible by comparing the field the step *named* against the one
# that took the text.
_LONGFORM = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>직접 가입</title>
<style>
  body { font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }
  label { display: block; margin-top: 12px; font-size: 14px; }
  input { font-size: 15px; padding: 6px; width: 320px; }
</style></head>
<body>
<h1>학생 가입</h1>
<form id="signup">
  <label for="school">학교</label>
  <input id="school" name="school" placeholder="학교 이름을 입력하세요 (예: 인천하늘고등학교)" />

  <label for="name">이름</label>
  <input id="name" name="name" placeholder="이름을 입력하세요" />

  <label for="password">비밀번호</label>
  <input id="password" name="password" type="password" placeholder="8자 이상" />

  <label for="password-confirm">비밀번호 확인</label>
  <input id="password-confirm" name="passwordConfirm" type="password"
         placeholder="비밀번호 재입력" />
</form>
</body></html>
"""

# The same four fields with placeholders that do not name each other. Every
# target resolves to its own field, so this page is how the no-false-positive
# direction is measured: a run over it must report no warning at all.
_CLEANFORM = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>직접 가입 (정상)</title>
<style>
  body { font-family: sans-serif; margin: 0; padding: 24px; background: #fff; }
  label { display: block; margin-top: 12px; font-size: 14px; }
  input { font-size: 15px; padding: 6px; width: 320px; }
</style></head>
<body>
<h1>학생 가입</h1>
<form id="signup">
  <label for="school">학교</label>
  <input id="school" name="school" placeholder="예: 인천하늘고등학교" />

  <label for="name">이름</label>
  <input id="name" name="name" placeholder="성함" />

  <label for="password">비밀번호</label>
  <input id="password" name="password" type="password" placeholder="8자 이상" />

  <label for="phone">전화번호</label>
  <input id="phone" name="phone" type="tel" placeholder="010-0000-0000" />
</form>
<script>
  // The phone box reformats what it is given, so its value is never the
  // keystrokes. A rule that compared the two would report this -- which is why
  // no rule does, and why this field is on the page that must stay green.
  document.getElementById('phone').addEventListener('input', (e) => {
    const d = e.target.value.replace(/[^0-9]/g, '').slice(0, 11);
    e.target.value = d.length > 7
      ? d.slice(0, 3) + '-' + d.slice(3, 7) + '-' + d.slice(7)
      : d.length > 3 ? d.slice(0, 3) + '-' + d.slice(3) : d;
  });
</script>
</body></html>
"""

# A form that mirrors one field into another and then hands focus on, the way a
# "same as above" box or a live preview does. Afterwards the focused element is
# not the field that was named, *and both hold the text*. Nothing is wrong
# here, which is why it is not enough for the two elements to differ: the claim
# needs the text to be present where it landed and absent from the field the
# step named.
_ADVANCE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>자동 이동</title></head>
<body>
<form id="signup">
  <label for="name">이름</label>
  <input id="name" name="name" />
  <label for="nickname">표시 이름</label>
  <input id="nickname" name="nickname" />
</form>
<script>
  const _n = document.getElementById('name');
  const _k = document.getElementById('nickname');
  _n.addEventListener('input', (e) => {
    _k.value = e.target.value;
    if (e.target.value.length >= 8) _k.focus();
  });
</script>
</body></html>
"""

# The same hazard with no authored labels at all. Nothing on this page says
# which field '이름' was supposed to mean, so the text misses its field exactly
# as it does on /longform and AWT has to stay quiet about it. Here to pin that
# decision down: the alternative is guessing from a placeholder, and a
# placeholder substring is what sent the text to the wrong field to begin with.
_NOLABEL = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>라벨 없는 폼</title></head>
<body>
<form id="signup">
  <input id="school" name="school" placeholder="학교 이름을 입력하세요" />
  <input id="name" name="name" placeholder="성함을 입력하세요" />
</form>
</body></html>
"""

# What a component library looks like from the outside: the `<label for>` points
# at a hidden input that holds the committed value, while the box the user types
# into is a sibling. The named field really is empty afterwards and the text
# really is somewhere else, and reporting that would be wrong -- so the named
# field has to be visible before anything is claimed.
_SHIMFORM = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>shim</title></head>
<body>
<form id="signup">
  <label for="city-value">도시</label>
  <input id="city-value" name="city" type="hidden" />
  <input id="city-search" name="citySearch" placeholder="도시 검색" />
</form>
</body></html>
"""

# A rich-text box is not an `<input>`, and the ambiguity log has to survive
# that. The editor and the plain field are labelled the same thing, and the
# editor comes first, so the editor is what gets chosen -- which means the
# element that was chosen is itself labelled exactly what the step asked for.
# Saying "you got the editor, but input#memo is labelled exactly '메모'" would be
# telling the author about a choice that was not wrong.
_RICHTEXT = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>메모</title>
<style>
  #memo-editor { border: 1px solid #999; min-height: 60px; width: 320px; }
</style></head>
<body>
<form id="note">
  <div id="memo-editor" role="textbox" contenteditable="true" aria-label="메모"></div>

  <label for="memo">메모</label>
  <input id="memo" name="memo" />
</form>
</body></html>
"""

_PAGES = {
    "/signup": _SIGNUP,
    "/richtext": _RICHTEXT,
    "/plain": _PLAIN,
    "/longform": _LONGFORM,
    "/cleanform": _CLEANFORM,
    "/advance": _ADVANCE,
    "/nolabel": _NOLABEL,
    "/shimform": _SHIMFORM,
}


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
