"""Tests for element test pattern library."""

from __future__ import annotations

from app.test_patterns import (
    ELEMENT_TEST_PATTERNS,
    build_pattern_summary,
    build_pattern_tests,
    match_elements_to_patterns,
)


# ---------------------------------------------------------------------------
# ELEMENT_TEST_PATTERNS structure validation
# ---------------------------------------------------------------------------


def test_patterns_dict_is_not_empty() -> None:
    """Pattern library should have entries."""
    assert len(ELEMENT_TEST_PATTERNS) > 20


def test_each_pattern_has_tests() -> None:
    """Every pattern entry must have a non-empty 'tests' list."""
    for key, value in ELEMENT_TEST_PATTERNS.items():
        assert "tests" in value, f"Pattern {key} missing 'tests'"
        assert len(value["tests"]) > 0, f"Pattern {key} has empty tests"


def test_each_test_has_required_fields() -> None:
    """Each test item must have name, action, assert."""
    for key, value in ELEMENT_TEST_PATTERNS.items():
        for t in value["tests"]:
            assert "name" in t, f"Pattern {key}: test missing 'name'"
            assert "action" in t, f"Pattern {key}: test missing 'action'"
            assert "assert" in t, f"Pattern {key}: test missing 'assert'"


# ---------------------------------------------------------------------------
# match_elements_to_patterns
# ---------------------------------------------------------------------------


def test_match_form_fields() -> None:
    """Form fields are matched to input patterns."""
    pages = [{
        "forms": [{
            "selector": "#login-form",
            "fields": [
                {"name": "email", "type": "email", "placeholder": "이메일", "selector": "#email"},
                {"name": "password", "type": "password", "placeholder": "비밀번호", "selector": "#pw"},
            ],
        }],
        "nav_menus": [],
        "links": [],
        "buttons": [],
    }]
    matched = match_elements_to_patterns(pages, [])

    # Should match email, password, and form-level
    pattern_keys = [m["pattern_key"] for m in matched]
    assert "input[type=email]" in pattern_keys
    assert "input[type=password]" in pattern_keys
    assert "form" in pattern_keys


def test_match_accordion_observations() -> None:
    """Accordion observations are matched to accordion pattern."""
    pages: list[dict] = [{"forms": [], "nav_menus": [], "links": [], "buttons": []}]
    observations = [
        {
            "element": {"text": "FAQ 질문 1", "selector": ".faq-item", "type": "accordion"},
            "observed_change": {"type": "content_expanded"},
        },
        {
            "element": {"text": "FAQ 질문 2", "selector": ".faq-item-2", "type": "accordion"},
            "observed_change": {"type": "content_expanded"},
        },
    ]
    matched = match_elements_to_patterns(pages, observations)
    accordion_matches = [m for m in matched if m["pattern_key"] == "accordion"]
    assert len(accordion_matches) == 2


def test_match_modal_observations() -> None:
    """Modal observations are matched to modal_trigger pattern."""
    pages: list[dict] = [{"forms": [], "nav_menus": [], "links": [], "buttons": []}]
    observations = [{
        "element": {"text": "로그인", "selector": "a.login-btn", "type": "button"},
        "observed_change": {"type": "modal_opened"},
    }]
    matched = match_elements_to_patterns(pages, observations)
    modal_matches = [m for m in matched if m["pattern_key"] == "modal_trigger"]
    assert len(modal_matches) == 1


def test_match_nav_menu() -> None:
    """Nav menus are matched to nav pattern."""
    pages = [{
        "forms": [],
        "nav_menus": [{"items": [{"text": "Home", "href": "/"}], "selector": "nav.main"}],
        "links": [],
        "buttons": [],
    }]
    matched = match_elements_to_patterns(pages, [])
    nav_matches = [m for m in matched if m["pattern_key"] == "nav"]
    assert len(nav_matches) == 1


def test_match_deduplication() -> None:
    """Duplicate elements are not matched twice."""
    pages = [{
        "forms": [{
            "selector": "#form",
            "fields": [
                {"name": "email", "type": "email", "placeholder": "이메일", "selector": "#e1"},
                {"name": "email", "type": "email", "placeholder": "이메일", "selector": "#e1"},
            ],
        }],
        "nav_menus": [],
        "links": [],
        "buttons": [],
    }]
    matched = match_elements_to_patterns(pages, [])
    email_matches = [m for m in matched if m["pattern_key"] == "input[type=email]"]
    assert len(email_matches) == 1


# ---------------------------------------------------------------------------
# build_pattern_tests
# ---------------------------------------------------------------------------


def test_build_pattern_tests_returns_category() -> None:
    """Build produces a valid category dict."""
    matched = [
        {
            "pattern_key": "input[type=email]",
            "element_info": "이메일",
            "tests": ELEMENT_TEST_PATTERNS["input[type=email]"]["tests"],
            "selector": "#email",
        },
    ]
    result = build_pattern_tests(matched, "ko")
    assert result is not None
    assert result["id"] == "patterns"
    assert len(result["tests"]) == 3  # email has 3 tests


def test_build_pattern_tests_empty() -> None:
    """Empty match list returns None."""
    assert build_pattern_tests([], "ko") is None


def test_build_pattern_tests_ids_start_at_100() -> None:
    """Pattern test IDs start at p100 to avoid collision."""
    matched = [{
        "pattern_key": "accordion",
        "element_info": "FAQ",
        "tests": ELEMENT_TEST_PATTERNS["accordion"]["tests"],
        "selector": ".faq",
    }]
    result = build_pattern_tests(matched, "ko")
    assert result is not None
    ids = [t["id"] for t in result["tests"]]
    assert ids[0] == "p100"
    assert ids[1] == "p101"


# ---------------------------------------------------------------------------
# build_pattern_summary
# ---------------------------------------------------------------------------


def test_build_pattern_summary_content() -> None:
    """Summary contains pattern info for AI prompt."""
    matched = [{
        "pattern_key": "input[type=email]",
        "element_info": "이메일",
        "tests": [{"name": "빈값 제출"}, {"name": "정상 입력"}],
        "selector": "#email",
    }]
    summary = build_pattern_summary(matched)
    assert "Standard Tests" in summary
    assert "input[type=email]" in summary
    assert "이메일" in summary
    assert "BUSINESS LOGIC" in summary


def test_build_pattern_summary_empty() -> None:
    """Empty match list returns empty string."""
    assert build_pattern_summary([]) == ""
