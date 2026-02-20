"""Element-based standard test pattern library.

Provides predefined test patterns for common HTML elements so that standard tests
can be generated without AI calls. Only non-standard or business-logic tests
need AI generation.
"""

from __future__ import annotations

from typing import Any

ELEMENT_TEST_PATTERNS: dict[str, dict[str, Any]] = {
    # -- Input fields --
    "input[type=text]": {
        "tests": [
            {"name": "빈값 제출", "action": "clear → submit", "assert": "에러 메시지 표시 또는 required 경고"},
            {"name": "정상 입력", "action": "값 입력 → submit", "assert": "에러 없음"},
            {"name": "최대 길이 초과", "action": "maxlength+1 입력", "assert": "입력 제한 또는 에러"},
        ],
    },
    "input[type=email]": {
        "tests": [
            {"name": "빈값 제출", "action": "clear → submit", "assert": "required 에러"},
            {"name": "잘못된 형식", "action": "'abc' 입력 → submit", "assert": "이메일 형식 에러"},
            {"name": "정상 입력", "action": "test@example.com 입력", "assert": "통과"},
        ],
    },
    "input[type=password]": {
        "tests": [
            {"name": "빈값 제출", "action": "clear → submit", "assert": "required 에러"},
            {"name": "정상 입력", "action": "값 입력", "assert": "마스킹 표시"},
        ],
    },
    "input[type=tel]": {
        "tests": [
            {"name": "문자 입력", "action": "'abc' 입력", "assert": "숫자만 허용 에러 또는 입력 제한"},
            {"name": "정상 입력", "action": "010-1234-5678", "assert": "통과"},
        ],
    },
    "input[type=number]": {
        "tests": [
            {"name": "문자 입력", "action": "'abc' 입력", "assert": "입력 불가 또는 에러"},
            {"name": "min/max 범위 밖", "action": "범위 초과값", "assert": "범위 에러"},
            {"name": "정상 입력", "action": "범위 내 숫자", "assert": "통과"},
        ],
    },
    "input[type=checkbox]": {
        "tests": [
            {"name": "체크", "action": "클릭", "assert": "checked 상태"},
            {"name": "체크 해제", "action": "다시 클릭", "assert": "unchecked 상태"},
        ],
    },
    "input[type=radio]": {
        "tests": [
            {"name": "선택", "action": "클릭", "assert": "selected 상태"},
            {"name": "다른 옵션 선택", "action": "다른 라디오 클릭", "assert": "이전 해제, 새 선택"},
        ],
    },
    "input[type=file]": {
        "tests": [
            {"name": "파일 업로드", "action": "테스트 파일 선택", "assert": "파일명 표시"},
        ],
    },
    "input[type=date]": {
        "tests": [
            {"name": "날짜 선택", "action": "날짜 입력", "assert": "선택된 날짜 표시"},
        ],
    },
    "input[type=search]": {
        "tests": [
            {
                "name": "검색어 입력 후 실행",
                "action": "키워드 입력 → Enter 또는 검색 버튼",
                "assert": "검색 결과 표시 또는 페이지 변화",
            },
        ],
    },
    # -- Select / Textarea --
    "select": {
        "tests": [
            {"name": "옵션 변경", "action": "다른 옵션 선택", "assert": "선택값 변경됨"},
            {"name": "기본값 확인", "action": "초기 상태", "assert": "기본 옵션 선택됨"},
        ],
    },
    "textarea": {
        "tests": [
            {"name": "빈값 제출", "action": "clear → submit", "assert": "required 에러 (있는 경우)"},
            {"name": "정상 입력", "action": "여러 줄 텍스트 입력", "assert": "입력된 텍스트 표시"},
        ],
    },
    # -- Buttons / Links --
    "button[type=submit]": {
        "tests": [
            {"name": "클릭", "action": "클릭", "assert": "폼 제출 또는 다음 단계 이동"},
        ],
    },
    "a[href]": {
        "tests": [
            {"name": "링크 이동", "action": "클릭", "assert": "페이지 이동 또는 섹션 스크롤"},
            {"name": "깨진 링크 확인", "action": "HTTP 상태 코드 체크", "assert": "200 OK"},
        ],
    },
    # -- Interactive components --
    "accordion": {
        "tests": [
            {"name": "펼치기", "action": "클릭", "assert": "숨겨진 콘텐츠 표시"},
            {"name": "접기", "action": "다시 클릭", "assert": "콘텐츠 숨김"},
        ],
    },
    "tab": {
        "tests": [
            {"name": "탭 전환", "action": "각 탭 클릭", "assert": "해당 탭 콘텐츠 표시, 다른 탭 숨김"},
        ],
    },
    "modal_trigger": {
        "tests": [
            {"name": "모달 열기", "action": "트리거 버튼 클릭", "assert": "모달 표시"},
            {"name": "모달 닫기", "action": "X 버튼 또는 배경 클릭", "assert": "모달 닫힘"},
        ],
    },
    "carousel": {
        "tests": [
            {"name": "다음 슬라이드", "action": "다음 버튼 클릭", "assert": "슬라이드 변경"},
            {"name": "이전 슬라이드", "action": "이전 버튼 클릭", "assert": "이전 슬라이드 표시"},
        ],
    },
    "dropdown_menu": {
        "tests": [
            {"name": "드롭다운 열기", "action": "호버 또는 클릭", "assert": "메뉴 항목 표시"},
            {"name": "항목 선택", "action": "메뉴 항목 클릭", "assert": "선택 동작 수행"},
        ],
    },
    "tooltip": {
        "tests": [
            {"name": "툴팁 표시", "action": "호버", "assert": "툴팁 텍스트 표시"},
        ],
    },
    # -- Media --
    "video": {
        "tests": [
            {"name": "재생", "action": "재생 버튼 클릭", "assert": "재생 시작 (paused=false)"},
        ],
    },
    "img": {
        "tests": [
            {"name": "이미지 로드", "action": "확인", "assert": "naturalWidth > 0 (깨진 이미지 아님)"},
        ],
    },
    # -- Navigation --
    "nav": {
        "tests": [
            {"name": "각 메뉴 항목 이동", "action": "각 링크 클릭", "assert": "해당 페이지/섹션 표시"},
        ],
    },
    # -- Form --
    "form": {
        "tests": [
            {"name": "빈 폼 제출", "action": "모든 필드 비우고 submit", "assert": "validation 에러 표시"},
            {"name": "정상 제출", "action": "모든 필수 필드 채우고 submit", "assert": "성공 메시지 또는 페이지 이동"},
        ],
    },
    # -- Table --
    "table": {
        "tests": [
            {"name": "데이터 표시 확인", "action": "확인", "assert": "행/열 데이터 존재"},
            {"name": "정렬 (있는 경우)", "action": "헤더 클릭", "assert": "데이터 정렬 변경"},
        ],
    },
    # -- Pagination --
    "pagination": {
        "tests": [
            {"name": "다음 페이지", "action": "다음 버튼 클릭", "assert": "콘텐츠 변경"},
            {"name": "이전 페이지", "action": "이전 버튼 클릭", "assert": "이전 콘텐츠 표시"},
        ],
    },
    # -- File download --
    "file_download": {
        "tests": [
            {
                "name": "파일 다운로드 링크 확인",
                "action": "HTTP HEAD 요청",
                "assert": "200 OK 응답 (파일 존재)",
            },
        ],
    },
}


def match_elements_to_patterns(
    pages: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match crawled elements and observations to standard test patterns.

    Returns a list of matched items:
    [{"pattern_key": str, "element_info": str, "tests": [...], "selector": str|None}]
    """
    matched: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 1. Match form fields from crawl data
    for page in pages:
        for form in page.get("forms", []):
            form_selector = form.get("selector")
            for field in form.get("fields", []):
                field_type = (field.get("type") or "text").lower()
                tag = "textarea" if field_type == "textarea" else "select" if field_type == "select" else None
                pattern_key = tag or f"input[type={field_type}]"

                if pattern_key not in ELEMENT_TEST_PATTERNS:
                    pattern_key = "input[type=text]"  # fallback

                label = (
                    field.get("label")
                    or field.get("placeholder")
                    or field.get("name")
                    or field_type
                )
                dedup_key = f"{pattern_key}:{label}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                matched.append({
                    "pattern_key": pattern_key,
                    "element_info": label,
                    "tests": ELEMENT_TEST_PATTERNS[pattern_key]["tests"],
                    "selector": field.get("selector"),
                    "context": f"form({form_selector or 'unknown'})",
                })

        # Match form-level pattern
        for form in page.get("forms", []):
            if form.get("fields"):
                dedup_key = f"form:{form.get('selector') or form.get('action', '')}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    field_names = [
                        f.get("label") or f.get("placeholder") or f.get("name") or "field"
                        for f in form.get("fields", [])
                    ]
                    matched.append({
                        "pattern_key": "form",
                        "element_info": ", ".join(field_names[:5]),
                        "tests": ELEMENT_TEST_PATTERNS["form"]["tests"],
                        "selector": form.get("selector"),
                    })

    # 2. Match observations — accordion, modal, tab, etc.
    for obs in observations:
        elem = obs.get("element", {})
        elem_type = elem.get("type", "")
        change_type = obs.get("observed_change", {}).get("type", "")

        if elem_type == "accordion" or change_type == "content_expanded":
            pattern_key = "accordion"
        elif change_type == "modal_opened":
            pattern_key = "modal_trigger"
        elif elem_type == "file_download" or change_type == "file_download":
            pattern_key = "file_download"
        else:
            continue

        if pattern_key not in ELEMENT_TEST_PATTERNS:
            continue

        elem_text = elem.get("text", "")[:60]
        dedup_key = f"{pattern_key}:{elem_text}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        matched.append({
            "pattern_key": pattern_key,
            "element_info": elem_text,
            "tests": ELEMENT_TEST_PATTERNS[pattern_key]["tests"],
            "selector": elem.get("selector"),
        })

    # 3. Match nav menus
    for page in pages:
        if page.get("nav_menus"):
            dedup_key = "nav:main"
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                matched.append({
                    "pattern_key": "nav",
                    "element_info": "navigation menu",
                    "tests": ELEMENT_TEST_PATTERNS["nav"]["tests"],
                    "selector": page["nav_menus"][0].get("selector"),
                })
            break

    return matched


def build_pattern_tests(
    matched: list[dict[str, Any]],
    language: str = "ko",
) -> dict[str, Any] | None:
    """Build a test category from matched patterns.

    Returns a category dict for the plan, or None if no matches.
    """
    if not matched:
        return None

    ko = language == "ko"
    tests: list[dict[str, Any]] = []
    tid = 100  # Start from 100 to avoid collision with other plan IDs

    for m in matched:
        pattern_key = m["pattern_key"]
        element_info = m["element_info"]
        selector = m.get("selector")

        for t in m["tests"]:
            test_name = (
                f"{element_info} — {t['name']}" if ko
                else f"{element_info} — {t['name']}"
            )
            tests.append({
                "id": f"p{tid}",
                "name": test_name,
                "description": f"{t['action']} → {t['assert']}",
                "priority": "medium",
                "estimated_time": 15,
                "requires_auth": False,
                "selected": True,
                "actual_elements": [selector] if selector else [element_info],
                "pattern_key": pattern_key,
            })
            tid += 1

    if not tests:
        return None

    return {
        "id": "patterns",
        "name": "표준 요소 테스트" if ko else "Standard Element Tests",
        "auto_selected": True,
        "tests": tests,
    }


def build_pattern_summary(matched: list[dict[str, Any]]) -> str:
    """Build a text summary of pattern-matched elements for AI prompts.

    Tells the AI which elements already have standard tests so it can
    focus on business logic only.
    """
    if not matched:
        return ""

    lines = [
        "## Pre-generated Standard Tests (DO NOT duplicate these)",
        "The following elements already have standard test patterns applied.",
        "Focus your test generation on BUSINESS LOGIC and non-standard interactions only.",
        "",
    ]
    for m in matched:
        tests_summary = ", ".join(t["name"] for t in m["tests"])
        lines.append(f"- {m['pattern_key']} ({m['element_info']}): {tests_summary}")

    return "\n".join(lines)
