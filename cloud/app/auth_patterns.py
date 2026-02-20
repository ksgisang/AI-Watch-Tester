"""Auth Pattern Detection — registration/login page pattern analysis.

Detects auth page patterns (single_page, multi_step, social_only, captcha, etc.)
and provides crawl strategies, test data generation, and AI prompt context.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registration patterns (10)
# ---------------------------------------------------------------------------

REGISTRATION_PATTERNS: dict[str, dict[str, Any]] = {
    "single_page": {
        "description": "단일 페이지 회원가입 (모든 필드가 한 화면에)",
        "indicators": ["form with 3+ input fields", "password confirm field"],
        "fields_min": 3,
        "crawl_strategy": "collect_all_fields",
        "testable": True,
    },
    "multi_step": {
        "description": "멀티스텝 회원가입 (다음 버튼으로 단계 진행)",
        "indicators": ["next/continue button", "step indicator", "progress bar"],
        "next_button_texts": ["다음", "Next", "Continue", "계속", "진행"],
        "crawl_strategy": "fill_and_advance",
        "testable": True,
    },
    "social_only": {
        "description": "소셜 로그인만 가능 (이메일 가입 불가)",
        "indicators": ["google/kakao/naver/github button only", "no email input"],
        "crawl_strategy": "detect_only",
        "testable": False,
        "limitation": "소셜 인증(OAuth)만 지원 — 자동 테스트 불가",
    },
    "social_plus_email": {
        "description": "소셜 + 이메일 가입 모두 가능",
        "indicators": ["social buttons + email input"],
        "crawl_strategy": "collect_all_fields",
        "testable": True,
    },
    "email_verification": {
        "description": "이메일 인증 필요 (인증코드 입력 단계)",
        "indicators": ["verification code input", "인증번호", "verify"],
        "crawl_strategy": "collect_all_fields",
        "testable": "partial",
        "limitation": "이메일 인증 단계는 자동 테스트 불가 — 폼 제출까지만 테스트",
    },
    "invite_only": {
        "description": "초대 코드 필요",
        "indicators": ["invite code input", "초대 코드", "invitation"],
        "crawl_strategy": "collect_all_fields",
        "testable": "partial",
        "limitation": "초대 코드가 필요 — 코드 없이 가입 흐름만 테스트",
    },
    "phone_otp": {
        "description": "휴대폰 인증 (SMS OTP)",
        "indicators": ["phone input + verify button", "인증번호 발송"],
        "crawl_strategy": "collect_all_fields",
        "testable": "partial",
        "limitation": "SMS 인증 단계는 자동 테스트 불가 — 폼 제출까지만 테스트",
    },
    "captcha": {
        "description": "CAPTCHA 포함",
        "indicators": ["recaptcha", "hcaptcha", "turnstile", "captcha iframe"],
        "crawl_strategy": "collect_all_fields",
        "testable": False,
        "limitation": "CAPTCHA 감지 — 자동 테스트 불가",
    },
    "terms_agreement": {
        "description": "약관 동의 필수 (체크박스)",
        "indicators": ["terms checkbox", "이용약관", "개인정보"],
        "crawl_strategy": "collect_all_fields",
        "testable": True,
    },
    "modal_registration": {
        "description": "모달/팝업 기반 가입",
        "indicators": ["modal with form fields after button click"],
        "crawl_strategy": "collect_all_fields",
        "testable": True,
    },
}

# ---------------------------------------------------------------------------
# Login patterns (6)
# ---------------------------------------------------------------------------

LOGIN_PATTERNS: dict[str, dict[str, Any]] = {
    "email_password": {
        "description": "이메일 + 비밀번호 로그인",
        "indicators": ["email input + password input + submit"],
        "testable": True,
    },
    "username_password": {
        "description": "아이디 + 비밀번호 로그인",
        "indicators": ["text input (id/username) + password input + submit"],
        "testable": True,
    },
    "social_only": {
        "description": "소셜 로그인만 가능",
        "indicators": ["social buttons only, no form inputs"],
        "testable": False,
        "limitation": "소셜 인증만 지원 — 자동 테스트 불가",
    },
    "social_plus_form": {
        "description": "소셜 + 이메일/아이디 로그인",
        "indicators": ["social buttons + email/id input"],
        "testable": True,
    },
    "phone_otp": {
        "description": "전화번호 OTP 로그인",
        "indicators": ["phone input + send code button"],
        "testable": False,
        "limitation": "SMS 인증 필요 — 자동 테스트 불가",
    },
    "passwordless": {
        "description": "비밀번호 없는 로그인 (매직링크 등)",
        "indicators": ["email only, no password field"],
        "testable": False,
        "limitation": "이메일 매직링크 방식 — 자동 테스트 불가",
    },
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_auth_pattern(
    fields: list[dict],
    page_html_hints: dict,
    page_type: str = "registration",
) -> dict:
    """Detect auth pattern from form fields and HTML hints.

    Returns {"pattern": "...", "details": {...}, "limitations": [...]}.
    """
    limitations: list[str] = []
    detected: str = ""

    has_email = any(
        f.get("type") == "email"
        or "email" in (f.get("name", "") + f.get("placeholder", "") + f.get("label", "")).lower()
        or "이메일" in (f.get("placeholder", "") + f.get("label", ""))
        for f in fields
    )
    has_password = any(f.get("type") == "password" for f in fields)
    has_text_input = any(
        f.get("type") in ("text", "search")
        and f.get("tag") != "button"
        for f in fields
    )
    social_buttons = page_html_hints.get("social_buttons", [])
    has_social = bool(social_buttons)
    has_captcha = page_html_hints.get("has_captcha", False)
    has_next_button = page_html_hints.get("has_next_button", False)
    has_terms = page_html_hints.get("has_terms", False)
    has_invite_code = page_html_hints.get("has_invite_code", False)
    has_phone_verify = page_html_hints.get("has_phone_verify", False)

    # Input fields (excluding buttons)
    input_fields = [f for f in fields if f.get("type") != "submit_button"]

    if page_type == "login":
        return _detect_login_pattern(
            has_email=has_email,
            has_password=has_password,
            has_text_input=has_text_input,
            has_social=has_social,
            social_buttons=social_buttons,
            has_captcha=has_captcha,
        )

    # --- Registration detection ---

    # 1) CAPTCHA (highest priority — can overlap with other patterns)
    if has_captcha:
        pat = REGISTRATION_PATTERNS["captcha"]
        limitations.append(pat["limitation"])
        detected = "captcha"

    # 2) Social only (no email field)
    if has_social and not has_email and not has_password:
        pat = REGISTRATION_PATTERNS["social_only"]
        limitations.append(pat["limitation"])
        if not detected:
            detected = "social_only"

    # 3) Social + email
    elif has_social and (has_email or has_password):
        if not detected:
            detected = "social_plus_email"

    # 4) Multi-step (next button)
    if has_next_button and not detected:
        detected = "multi_step"

    # 5) Invite code
    if has_invite_code:
        pat = REGISTRATION_PATTERNS["invite_only"]
        limitations.append(pat["limitation"])
        if not detected:
            detected = "invite_only"

    # 6) Phone OTP
    if has_phone_verify:
        pat = REGISTRATION_PATTERNS["phone_otp"]
        limitations.append(pat["limitation"])
        if not detected:
            detected = "phone_otp"

    # 7) Terms agreement (additive — doesn't override)
    if has_terms and not detected:
        detected = "terms_agreement"

    # 8) Default: single_page
    if not detected:
        detected = "single_page" if len(input_fields) >= 3 else "single_page"

    patterns = REGISTRATION_PATTERNS
    pattern_data = patterns.get(detected, {})

    return {
        "pattern": detected,
        "details": pattern_data,
        "limitations": limitations,
        "page_type": page_type,
        "social_buttons": social_buttons,
        "field_count": len(input_fields),
    }


def _detect_login_pattern(
    *,
    has_email: bool,
    has_password: bool,
    has_text_input: bool,
    has_social: bool,
    social_buttons: list,
    has_captcha: bool,
) -> dict:
    """Detect login page pattern."""
    limitations: list[str] = []
    detected: str = ""

    if has_captcha:
        # Captcha on login page — use registration captcha limitation
        limitations.append(REGISTRATION_PATTERNS["captcha"]["limitation"])

    # Social only (no form inputs)
    if has_social and not has_email and not has_password and not has_text_input:
        detected = "social_only"
        pat = LOGIN_PATTERNS["social_only"]
        limitations.append(pat["limitation"])

    # Social + form
    elif has_social and (has_email or has_password or has_text_input):
        detected = "social_plus_form"

    # Email + password
    elif has_email and has_password:
        detected = "email_password"

    # Username + password (text input, not email)
    elif has_text_input and has_password:
        detected = "username_password"

    # Phone OTP (no password)
    elif has_text_input and not has_password:
        detected = "passwordless"
        pat = LOGIN_PATTERNS["passwordless"]
        limitations.append(pat["limitation"])

    # Fallback
    else:
        detected = "email_password"

    pattern_data = LOGIN_PATTERNS.get(detected, {})

    return {
        "pattern": detected,
        "details": pattern_data,
        "limitations": limitations,
        "page_type": "login",
        "social_buttons": social_buttons,
    }


# ---------------------------------------------------------------------------
# HTML hint collection (runs in browser via page.evaluate)
# ---------------------------------------------------------------------------


async def collect_page_html_hints(page: Any) -> dict:
    """Collect auth-related hints from page HTML via page.evaluate()."""
    return await page.evaluate("""() => {
        const hints = {
            social_buttons: [],
            has_captcha: false,
            has_next_button: false,
            has_terms: false,
            has_invite_code: false,
            has_phone_verify: false,
        };

        // Social buttons: href/class containing provider names
        const socialProviders = [
            'google', 'kakao', 'naver', 'github',
            'facebook', 'apple', 'twitter',
        ];
        document.querySelectorAll('a, button').forEach(el => {
            const href = (el.getAttribute('href') || '').toLowerCase();
            const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
            const text = (el.textContent || '').toLowerCase().trim();
            const id = (el.id || '').toLowerCase();
            for (const provider of socialProviders) {
                if (href.includes(provider) || cls.includes(provider)
                    || text.includes(provider) || id.includes(provider)
                    || href.includes('oauth') || href.includes('social')) {
                    hints.social_buttons.push(provider);
                    break;
                }
            }
        });
        hints.social_buttons = [...new Set(hints.social_buttons)];

        // CAPTCHA: iframe or div
        const captchaSelectors = [
            'iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]',
            'iframe[src*="turnstile"]', '.g-recaptcha', '.h-captcha',
            '[data-sitekey]', '#captcha', '.captcha',
        ];
        for (const sel of captchaSelectors) {
            if (document.querySelector(sel)) {
                hints.has_captcha = true;
                break;
            }
        }

        // Next/Continue button
        const nextTexts = ['다음', 'next', 'continue', '계속', '진행'];
        document.querySelectorAll('button, input[type="submit"], a.btn, a.button').forEach(el => {
            const text = (el.textContent || el.value || '').trim().toLowerCase();
            if (nextTexts.some(nt => text.includes(nt))) {
                hints.has_next_button = true;
            }
        });

        // Terms checkbox
        const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
        const termsKeywords = [
            '이용약관', '개인정보', 'terms of service',
            'privacy policy', 'terms and conditions',
        ];
        if (document.querySelector('input[type="checkbox"]')) {
            if (termsKeywords.some(kw => bodyText.includes(kw))) {
                hints.has_terms = true;
            }
        }

        // Invite code field
        document.querySelectorAll('input').forEach(el => {
            const ph = (el.placeholder || '').toLowerCase();
            const name = (el.name || '').toLowerCase();
            const label = (el.getAttribute('aria-label') || '').toLowerCase();
            const hint = ph + ' ' + name + ' ' + label;
            if (hint.includes('초대') || hint.includes('invite') || hint.includes('invitation')) {
                hints.has_invite_code = true;
            }
        });

        // Phone verification
        const hasTel = !!document.querySelector('input[type="tel"]');
        if (hasTel) {
            const verifyTexts = ['인증', 'verify', '발송', 'send code', 'otp'];
            document.querySelectorAll('button').forEach(el => {
                const text = (el.textContent || '').trim().toLowerCase();
                if (verifyTexts.some(vt => text.includes(vt))) {
                    hints.has_phone_verify = true;
                }
            });
        }

        return hints;
    }""")


# ---------------------------------------------------------------------------
# Multi-step form crawling
# ---------------------------------------------------------------------------


async def crawl_multi_step_form(
    page: Any,
    fields: list[dict],
    max_steps: int = 5,
) -> list[list[dict]]:
    """Crawl multi-step form by filling fields and clicking Next.

    Returns list of field lists, one per step.
    """
    all_steps: list[list[dict]] = [fields]

    for _step_num in range(2, max_steps + 1):
        # 1) Fill current fields with test data
        for field in fields:
            value = generate_test_data(field)
            if not value:
                continue
            selector = field.get("selector")
            if not selector:
                continue
            try:
                if value == "__CHECK__":
                    await page.click(selector)
                elif value == "__SELECT_FIRST__":
                    await page.select_option(selector, index=0)
                else:
                    await page.fill(selector, value)
            except Exception:
                logger.debug("Failed to fill field %s", selector)

        # 2) Click "Next" button
        next_clicked = await _click_next_button(page)
        if not next_clicked:
            break
        await asyncio.sleep(1.0)

        # 3) Collect new fields
        new_fields = await _collect_visible_fields(page)
        if not new_fields or new_fields == fields:
            break
        all_steps.append(new_fields)
        fields = new_fields

    return all_steps


async def _click_next_button(page: Any) -> bool:
    """Find and click a Next/Continue button. Returns True if clicked."""
    return await page.evaluate("""() => {
        const nextTexts = ['다음', 'next', 'continue', '계속', '진행'];
        const buttons = document.querySelectorAll(
            'button, input[type="submit"], a.btn, a.button'
        );
        for (const b of buttons) {
            const text = (b.textContent || b.value || '').trim().toLowerCase();
            if (nextTexts.some(nt => text.includes(nt))
                && b.offsetParent !== null) {
                b.click();
                return true;
            }
        }
        return false;
    }""")


async def _collect_visible_fields(page: Any) -> list[dict]:
    """Collect currently visible form fields from the page."""
    return await page.evaluate("""() => {
        const fields = [];
        document.querySelectorAll('input, textarea, select').forEach(f => {
            if (f.type === 'hidden') return;
            if (f.offsetParent === null && f.offsetWidth === 0) return;
            const labelEl = f.id
                ? document.querySelector('label[for="' + f.id + '"]')
                : null;
            const parentLabel = !labelEl ? f.closest('label') : null;
            const labelNode = labelEl || parentLabel;
            const label = labelNode
                ? (labelNode.childNodes[0]?.textContent?.trim()
                   || labelNode.textContent?.trim()?.substring(0, 100))
                : '';
            let sel = null;
            if (f.id) sel = '#' + f.id;
            else if (f.name) sel = f.tagName.toLowerCase()
                + '[name="' + f.name + '"]';
            else if (f.type && f.type !== 'text')
                sel = f.tagName.toLowerCase()
                + '[type="' + f.type + '"]';
            fields.push({
                tag: f.tagName.toLowerCase(),
                type: f.type || 'text',
                name: f.name || '',
                placeholder: f.placeholder || '',
                label: label || '',
                aria_label: f.getAttribute('aria-label') || '',
                selector: sel,
                required: f.required || false,
            });
        });
        return fields;
    }""")


# ---------------------------------------------------------------------------
# Test data generation
# ---------------------------------------------------------------------------


def generate_test_data(field: dict) -> str | None:
    """Generate dummy test data appropriate for the field type."""
    f_type = field.get("type", "text")
    ph = field.get("placeholder", "").lower()
    label = field.get("label", "").lower()
    name = field.get("name", "").lower()
    hint = f"{ph} {label} {name}"

    if f_type == "email" or "email" in hint or "이메일" in hint:
        return "awttest@example.com"
    if f_type == "password" or "password" in hint or "비밀번호" in hint:
        return "TestPass123!"
    if f_type == "tel" or "phone" in hint or "전화" in hint or "휴대" in hint:
        return "01012345678"
    if "이름" in hint or "name" in hint:
        return "테스트유저"
    if f_type == "checkbox":
        return "__CHECK__"
    if f_type == "select":
        return "__SELECT_FIRST__"
    if f_type in ("text", "search"):
        return "테스트 입력"
    return None


# ---------------------------------------------------------------------------
# AI prompt context builder
# ---------------------------------------------------------------------------


def build_auth_context_for_ai(auth_info: dict) -> str:
    """Build auth pattern context string for AI prompt injection."""
    parts: list[str] = []
    pattern = auth_info.get("pattern", "unknown")
    pattern_data = REGISTRATION_PATTERNS.get(pattern) or LOGIN_PATTERNS.get(pattern)

    if pattern_data:
        parts.append(f"AUTH PATTERN: {pattern} — {pattern_data['description']}")

    limitations = auth_info.get("limitations", [])
    if limitations:
        parts.append("LIMITATIONS (정직하게 리포트):")
        for lim in limitations:
            parts.append(f"  - {lim}")
        parts.append("→ 테스트 불가 항목은 SKIP하고 사유를 description에 명시할 것")

    steps_data = auth_info.get("multi_step_fields")
    if steps_data and len(steps_data) > 1:
        parts.append(f"MULTI-STEP FORM: {len(steps_data)} 단계 감지됨")
        for i, step_fields in enumerate(steps_data, 1):
            field_names = [
                f.get("label") or f.get("placeholder") or f.get("name")
                for f in step_fields
            ]
            parts.append(f"  Step {i}: {', '.join(f for f in field_names if f)}")

    return "\n".join(parts) if parts else ""
