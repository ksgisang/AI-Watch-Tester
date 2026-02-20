"""Smart Scan endpoints — site crawling, AI test plan, execution."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.crawler import crawl_site, get_scan_limits
from app.database import get_db
from app.models import Scan, ScanStatus, User
from app.test_patterns import (
    build_pattern_summary,
    build_pattern_tests,
    match_elements_to_patterns,
)
from app.schemas import (
    ScanExecuteRequest,
    ScanPlanRequest,
    ScanPlanResponse,
    ScanRequest,
    ScanResponse,
    ScanSummary,
)
from app.ws import ws_manager

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

# Default model per AI provider
_DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "codellama:7b",
}

# ---------------------------------------------------------------------------
# Business test templates — site-type-specific test suggestions
# ---------------------------------------------------------------------------

BUSINESS_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "ecommerce": [
        {
            "requires_feature": "product_list",
            "name_en": "Product Browsing",
            "name_ko": "상품 탐색",
            "desc_en": "Browse product listings, verify product details load correctly",
            "desc_ko": "상품 목록을 탐색하고 상품 상세 페이지가 정상 로드되는지 확인",
            "priority": "high",
            "estimated_time": 30,
            "requires_auth": False,
        },
        {
            "requires_feature": "cart",
            "name_en": "Add to Cart Flow",
            "name_ko": "장바구니 추가 흐름",
            "desc_en": "Add a product to cart, verify cart count updates and cart page shows item",
            "desc_ko": "상품을 장바구니에 추가하고, 장바구니 수량 업데이트 및 장바구니 페이지에 상품이 표시되는지 확인",
            "priority": "high",
            "estimated_time": 40,
            "requires_auth": False,
        },
        {
            "requires_feature": "filter_sort",
            "name_en": "Filter and Sort Products",
            "name_ko": "상품 필터/정렬",
            "desc_en": "Apply filters and sorting options, verify product list updates accordingly",
            "desc_ko": "필터와 정렬 옵션을 적용하고 상품 목록이 올바르게 변경되는지 확인",
            "priority": "medium",
            "estimated_time": 30,
            "requires_auth": False,
        },
        {
            "requires_feature": "search",
            "name_en": "Product Search",
            "name_ko": "상품 검색",
            "desc_en": "Search for products and verify search results are relevant",
            "desc_ko": "상품을 검색하고 검색 결과가 적절한지 확인",
            "priority": "medium",
            "estimated_time": 20,
            "requires_auth": False,
        },
        {
            "requires_feature": "review_form",
            "name_en": "Write Product Review",
            "name_ko": "상품 리뷰 작성",
            "desc_en": "Write a product review with rating, verify it appears in review list",
            "desc_ko": "상품 리뷰를 작성하고 리뷰 목록에 표시되는지 확인",
            "priority": "medium",
            "estimated_time": 40,
            "requires_auth": True,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        },
    ],
    "blog": [
        {
            "requires_feature": "blog",
            "name_en": "Blog Post Navigation",
            "name_ko": "블로그 글 탐색",
            "desc_en": "Browse blog posts, click into articles, verify content loads",
            "desc_ko": "블로그 글 목록을 탐색하고, 글을 클릭해서 본문이 정상 로드되는지 확인",
            "priority": "high",
            "estimated_time": 25,
            "requires_auth": False,
        },
        {
            "requires_feature": "comment_form",
            "name_en": "Blog Comment",
            "name_ko": "블로그 댓글 작성",
            "desc_en": "Write a comment on a blog post, verify it appears",
            "desc_ko": "블로그 글에 댓글을 작성하고 댓글이 표시되는지 확인",
            "priority": "medium",
            "estimated_time": 30,
            "requires_auth": True,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        },
    ],
    "community": [
        {
            "requires_feature": "board_write",
            "name_en": "Create Post",
            "name_ko": "게시글 작성",
            "desc_en": "Create a new board post with title and content, verify it appears in list",
            "desc_ko": "게시판에 새 글을 작성하고 목록에 표시되는지 확인",
            "priority": "high",
            "estimated_time": 40,
            "requires_auth": True,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        },
        {
            "requires_feature": "comment_form",
            "name_en": "Post Comment",
            "name_ko": "댓글 작성",
            "desc_en": "Write a comment on a post, verify it appears",
            "desc_ko": "게시글에 댓글을 작성하고 댓글이 표시되는지 확인",
            "priority": "medium",
            "estimated_time": 30,
            "requires_auth": True,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        },
    ],
    "saas": [
        {
            "requires_feature": "login_form",
            "name_en": "Login and Dashboard Access",
            "name_ko": "로그인 및 대시보드 접근",
            "desc_en": "Login with credentials and verify dashboard loads correctly",
            "desc_ko": "로그인 후 대시보드가 정상적으로 로드되는지 확인",
            "priority": "high",
            "estimated_time": 30,
            "requires_auth": True,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        },
        {
            "requires_feature": "signup",
            "name_en": "Signup Flow",
            "name_ko": "회원가입 흐름",
            "desc_en": "Complete signup form and verify account creation flow",
            "desc_ko": "회원가입 폼을 작성하고 계정 생성 흐름을 확인",
            "priority": "high",
            "estimated_time": 40,
            "requires_auth": False,
            "test_data_fields": [
                {"key": "signup_email", "label": "Test Email", "placeholder": "test@example.com", "required": True},
                {"key": "signup_password", "label": "Test Password", "placeholder": "TestPass123!", "required": True},
            ],
        },
        {
            "requires_feature": "search",
            "name_en": "Search Functionality",
            "name_ko": "검색 기능",
            "desc_en": "Use search feature and verify results are displayed",
            "desc_ko": "검색 기능을 사용하고 결과가 표시되는지 확인",
            "priority": "medium",
            "estimated_time": 20,
            "requires_auth": False,
        },
    ],
    "corporate": [
        {
            "requires_feature": "newsletter",
            "name_en": "Newsletter Subscription",
            "name_ko": "뉴스레터 구독",
            "desc_en": "Subscribe to newsletter with email, verify confirmation",
            "desc_ko": "이메일로 뉴스레터를 구독하고 확인 메시지를 검증",
            "priority": "medium",
            "estimated_time": 20,
            "requires_auth": False,
            "test_data_fields": [
                {"key": "newsletter_email", "label": "Test Email", "placeholder": "test@example.com", "required": True},
            ],
        },
    ],
    "portfolio": [],
    "multilingual": [
        {
            "requires_feature": "multilingual",
            "name_en": "Language Switch Test",
            "name_ko": "언어 전환 테스트",
            "desc_en": "Switch site language and verify page content changes accordingly without broken layout",
            "desc_ko": "사이트 언어를 전환하고 페이지 콘텐츠가 깨지지 않고 올바르게 변경되는지 확인",
            "priority": "medium",
            "estimated_time": 30,
            "requires_auth": False,
        },
    ],
}


def _parse_json(text: str | None) -> Any:
    """Safely parse JSON text."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _scan_to_response(scan: Scan) -> dict:
    """Convert Scan ORM to response dict."""
    summary = _parse_json(scan.summary_json)
    return {
        "id": scan.id,
        "target_url": scan.target_url,
        "status": scan.status,
        "summary": ScanSummary(**summary) if summary else None,
        "pages": _parse_json(scan.pages_json),
        "broken_links": _parse_json(scan.broken_links_json),
        "detected_features": _parse_json(scan.detected_features) or [],
        "observations": _parse_json(getattr(scan, "observations_json", None)) or [],
        "error_message": scan.error_message,
        "created_at": scan.created_at,
        "completed_at": scan.completed_at,
    }


# ---------------------------------------------------------------------------
# POST /api/scan — start crawling
# ---------------------------------------------------------------------------


@router.post("", response_model=ScanResponse, status_code=201)
async def start_scan(
    body: ScanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a smart scan on the target URL."""
    # Apply tier limits
    tier_limits = get_scan_limits(user.tier.value)
    max_pages = min(body.max_pages, tier_limits["max_pages"])
    max_depth = min(body.max_depth, tier_limits["max_depth"])

    scan = Scan(
        user_id=user.id,
        target_url=str(body.target_url),
        status=ScanStatus.SCANNING,
        max_pages=max_pages,
        max_depth=max_depth,
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    scan_id = scan.id

    # Run crawl in background
    async def _run_crawl() -> None:
        try:
            result = await crawl_site(
                str(body.target_url),
                scan_id,
                max_pages=max_pages,
                max_depth=max_depth,
                total_timeout=float(tier_limits["timeout"]),
                screenshot_limit=tier_limits["screenshots"],
                ws=ws_manager,
            )

            # Update DB with results FIRST, then broadcast
            from app.database import async_session

            async with async_session() as session:
                s = (await session.execute(
                    select(Scan).where(Scan.id == scan_id)
                )).scalar_one()

                if "error" in result:
                    s.status = ScanStatus.FAILED
                    s.error_message = result["error"]
                else:
                    s.status = ScanStatus.COMPLETED
                    s.summary_json = json.dumps(result["summary"])
                    s.pages_json = json.dumps(result["pages"])
                    s.broken_links_json = json.dumps(result["broken_links"])
                    s.detected_features = json.dumps(result["detected_features"])
                    # Store observations if available
                    if result.get("observations"):
                        s.observations_json = json.dumps(result["observations"])
                s.completed_at = datetime.now(timezone.utc)
                await session.commit()

            # Broadcast scan_complete AFTER DB commit so /plan endpoint sees COMPLETED status
            if "error" in result:
                await ws_manager.broadcast(scan_id, {
                    "type": "scan_error",
                    "error": result["error"],
                })
            else:
                await ws_manager.broadcast(scan_id, {
                    "type": "scan_complete",
                    "summary": result["summary"],
                })

        except Exception as exc:
            logger.exception("Scan %d failed", scan_id)
            from app.database import async_session

            async with async_session() as session:
                s = (await session.execute(
                    select(Scan).where(Scan.id == scan_id)
                )).scalar_one()
                s.status = ScanStatus.FAILED
                s.error_message = str(exc)[:500]
                s.completed_at = datetime.now(timezone.utc)
                await session.commit()

            await ws_manager.broadcast(scan_id, {
                "type": "scan_error",
                "error": str(exc)[:500],
            })

    asyncio.create_task(_run_crawl())

    return _scan_to_response(scan)


# ---------------------------------------------------------------------------
# GET /api/scan/{scan_id} — get scan result
# ---------------------------------------------------------------------------


@router.get("/{scan_id}", response_model=ScanResponse)
async def get_scan(
    scan_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get scan result by ID."""
    query = select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id)
    scan = (await db.execute(query)).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _scan_to_response(scan)


# ---------------------------------------------------------------------------
# POST /api/scan/{scan_id}/plan — AI test plan generation
# ---------------------------------------------------------------------------

_PLAN_PROMPT = """\
You are a senior QA engineer creating a test plan based on actual crawl data and \
**real interaction observations**.

CRITICAL RULES:
1. ONLY reference elements, selectors, URLs, and text that actually exist in the crawl data.
2. NEVER invent elements that don't exist (no "menu1", no fake selectors).
3. Use EXACT text strings from the crawl data (copy-paste, do not paraphrase).
4. Group tests by category with clear priority.
5. For all text assertions, set case_insensitive: true to handle dynamic casing.
6. Respond in {language}.
7. FORM FIELD RULE: For tests involving forms, reference the EXACT field data from crawl data:
   - Use placeholder text as-is (e.g., if placeholder is "이메일", use "이메일" NOT "Email")
   - Use label text as-is (e.g., if label is "비밀번호", keep "비밀번호" NOT "Password")
   - For auth_fields, set the "label" to match the actual form field label/placeholder from crawl data
   - NEVER translate form field labels or placeholders into another language
8. For auth_fields in test entries: copy the exact label/placeholder from the crawl data forms.
   Example: if crawl shows {{placeholder: "이메일", label: "이메일 주소"}}, then auth_fields should be:
   {{"key": "email", "label": "이메일 주소", "type": "email", "required": true}}
9. **OBSERVATION-BASED PLANNING**: The "Interaction Observations" section below contains
   REAL results from actually clicking each element. DO NOT GUESS what happens —
   use the observed change type (page_navigation, modal_opened, anchor_scroll, section_change)
   to decide how to assert test results:
   - page_navigation → assert URL change
   - modal_opened → assert new modal text is visible (use new_text from observation)
   - anchor_scroll → assert section text is visible (NOT URL change)
   - section_change → assert new content is visible (use new_text from observation)

## Site Info
- URL: {target_url}
- Pages scanned: {total_pages}
- Detected features: {detected_features}
- Site type: {site_type} (confidence: {site_type_confidence})

## Crawl Data

### Navigation Menus
{nav_menus_json}

### Forms
{forms_json}

### Buttons
{buttons_json}

### Links (sample)
{links_json}

### Broken Links
{broken_links_json}

### Interaction Observations (REAL click results — DO NOT GUESS)
{observations_json}

## Business Test Hints (based on site type)
{business_hints}

## Reference Documents
{reference_documents}

## Special Instructions
{special_instructions}

## Generate Test Plan

Create a JSON test plan with these categories. Only include categories that have matching data:

CATEGORY "basic" - Basic Health Check (auto_selected: true):
- broken_link_check: Check all broken links found ({broken_count} found)
- nav_menu_test: Click each navigation menu item and verify page loads
- page_load_test: Verify all scanned pages load without errors

CATEGORY "forms" - Form Validation (auto_selected: true, only if forms found):
- For each form found, generate an input validation test
- Use actual field names and selectors

CATEGORY "auth" - Authentication (only if login_form detected):
- Login flow test — requires_auth: true
- Mark auth_fields needed

CATEGORY "business" - Business Flows (based on detected features):
- Only for features actually detected in the crawl
- Use the business test hints above as guidance
- Test names and descriptions MUST reflect actual observed behavior, NOT generic labels
- WRONG: "Product Browsing Test" (generic — no "product" in observations)
- RIGHT: "기능 섹션 네비게이션 테스트" (references actual observed element)

IMPORTANT — SELECTOR-FIRST RULE:
- For each test, include the exact CSS selectors from the observation data in "actual_elements".
- The selectors from observations are PROVEN to work (they were actually clicked during crawling).
- Tests will use these selectors to find elements, NOT text matching.
- Include the access path: how to reach each element (e.g., "homepage → click a[href='#login'] → modal").

For each test provide:
{{
    "id": "t1",
    "name": "Test name",
    "description": "What this test does",
    "priority": "high" | "medium" | "low",
    "estimated_time": 30,
    "requires_auth": false,
    "selected": true/false,
    "auth_fields": [],
    "test_data_fields": [],
    "actual_elements": ["selector or text used"],
    "access_path": "homepage → click selector → result"
}}

Return ONLY valid JSON in this exact structure:
{{
    "categories": [
        {{
            "id": "basic",
            "name": "Category Name",
            "auto_selected": true,
            "tests": [...]
        }}
    ]
}}\
"""


@router.post("/{scan_id}/plan", response_model=ScanPlanResponse)
async def generate_plan(
    scan_id: int,
    body: ScanPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate an AI test plan from scan results."""
    query = select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id)
    scan = (await db.execute(query)).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status not in (ScanStatus.COMPLETED, ScanStatus.PLANNED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate plan in '{scan.status.value}' status",
        )

    pages = _parse_json(scan.pages_json) or []
    broken = _parse_json(scan.broken_links_json) or []
    features = _parse_json(scan.detected_features) or []
    summary = _parse_json(scan.summary_json) or {}
    observations = _parse_json(getattr(scan, "observations_json", None)) or []

    # Collect elements for the prompt
    nav_menus = []
    forms = []
    buttons = []
    links_sample = []
    for p in pages:
        nav_menus.extend(p.get("nav_menus", []))
        forms.extend(p.get("forms", []))
        buttons.extend(p.get("buttons", []))
        for link in p.get("links", [])[:10]:
            links_sample.append({"text": link.get("text", ""), "href": link.get("href", "")})
        # Also collect per-page observations
        if not observations:
            observations.extend(p.get("observations", []))

    # Truncate for prompt size
    def _trunc_json(obj: Any, limit: int = 3000) -> str:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s[:limit] if len(s) > limit else s

    # Build site type info for prompt
    site_type_info = summary.get("site_type") or {}
    site_type_name = site_type_info.get("type", "unknown") if isinstance(site_type_info, dict) else "unknown"
    site_type_conf = site_type_info.get("confidence", 0.0) if isinstance(site_type_info, dict) else 0.0

    # Build business hints from templates (site-type + cross-cutting)
    business_hints_lines = []
    hint_covered: set[str] = set()
    for st in [site_type_name] + [k for k in BUSINESS_TEMPLATES if k != site_type_name]:
        for tmpl in BUSINESS_TEMPLATES.get(st, []):
            req_feat = tmpl.get("requires_feature", "")
            if req_feat and req_feat not in features:
                continue
            if req_feat in hint_covered:
                continue
            if req_feat:
                hint_covered.add(req_feat)
            name = tmpl.get("name_en", "")
            desc = tmpl.get("desc_en", "")
            business_hints_lines.append(f"- {name}: {desc}")
    business_hints = "\n".join(business_hints_lines) if business_hints_lines else "No specific business tests for this site type."

    # Build special instructions based on detected features
    special_parts: list[str] = []
    if "spa" in features:
        special_parts.append(
            "SPA SITE DETECTED:\n"
            "- Do NOT assert URL changes after menu/link clicks.\n"
            "- Instead, assert that the target section text is visible (text_visible).\n"
            "- For anchor links (#section), only verify the section content is visible.\n"
            "- Consider modal-based login (overlay popup, not page navigation).\n"
            "- Anchor links scroll within the same page — do NOT treat them as page navigations."
        )
    if "sticky_header" in features:
        special_parts.append(
            "STICKY/FIXED HEADER DETECTED:\n"
            "- Menu items may be hidden behind the sticky header after scrolling.\n"
            "- Add a scroll_to_top (scroll 0,0,0) step before clicking header navigation items."
        )
    special_parts.append(
        "TEST INDEPENDENCE:\n"
        "- Each test MUST start with a navigate step to the base URL.\n"
        "- Tests are independent — a previous test failure must NOT affect the next test.\n"
        "- For login tests, always start from the home page."
    )

    # Add pattern summary to tell AI what's already covered
    matched_patterns = match_elements_to_patterns(pages, observations)
    pattern_hint = build_pattern_summary(matched_patterns)
    if pattern_hint:
        special_parts.append(pattern_hint)

    special_instructions = "\n\n".join(special_parts)

    # Fetch user reference documents
    from app.routers.documents import get_user_doc_text

    ref_docs = await get_user_doc_text(user.id, db)

    # Build AI prompt
    lang = "Korean" if body.language == "ko" else "English"
    prompt = _PLAN_PROMPT.format(
        language=lang,
        target_url=scan.target_url,
        total_pages=summary.get("total_pages", len(pages)),
        detected_features=", ".join(features) if features else "none",
        site_type=site_type_name,
        site_type_confidence=f"{site_type_conf:.0%}",
        nav_menus_json=_trunc_json(nav_menus),
        forms_json=_trunc_json(forms),
        buttons_json=_trunc_json(buttons),
        links_json=_trunc_json(links_sample),
        broken_links_json=_trunc_json(broken),
        broken_count=len(broken),
        observations_json=_build_observation_table(observations) if observations else "No observations collected.",
        business_hints=business_hints,
        reference_documents=ref_docs or "No reference documents provided.",
        special_instructions=special_instructions,
    )

    # Try AI plan generation, fall back to default plan on failure
    plan = None
    lang = body.language or "en"

    try:
        from aat.core.models import AIConfig
        from aat.adapters import ADAPTER_REGISTRY

        ai_config = AIConfig(
            provider=settings.ai_provider,
            api_key=settings.ai_api_key,
            model=settings.ai_model or _DEFAULT_MODELS.get(settings.ai_provider, ""),
        )
        adapter_cls = ADAPTER_REGISTRY.get(ai_config.provider)
        if adapter_cls is None:
            raise ValueError(f"Unknown AI provider: {ai_config.provider}")

        adapter = adapter_cls(ai_config)
        raw_response = await _ai_raw_call(adapter, prompt)
        plan = _extract_json(raw_response)

        categories = plan.get("categories", [])
        if not categories:
            logger.warning("AI returned no categories, using default plan")
            plan = None
    except Exception as exc:
        logger.warning("AI plan generation failed (%s), using default plan", exc)
        plan = None

    # Fallback: generate plan from crawl data without AI
    if plan is None:
        plan = _generate_default_plan(
            scan, pages, broken, features, summary, lang, observations,
        )

    categories = plan.get("categories", [])

    # Save plan to DB
    scan.plan_json = json.dumps(plan, ensure_ascii=False)
    scan.status = ScanStatus.PLANNED
    await db.commit()

    return {"scan_id": scan_id, "categories": categories}


async def _ai_raw_call(adapter: Any, prompt: str) -> str:
    """Call AI adapter for raw text response."""
    client = getattr(adapter, "_client", None)
    config = getattr(adapter, "_config", None)
    model = config.model if config else ""

    # Anthropic-style (ClaudeAdapter._client = AsyncAnthropic)
    if client and hasattr(client, "messages") and hasattr(client.messages, "create"):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    # OpenAI-style (OpenAIAdapter._client = AsyncOpenAI)
    if client and hasattr(client, "chat"):
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    raise NotImplementedError("Adapter does not support raw text generation")


def _generate_default_plan(
    scan: Any,
    pages: list,
    broken: list,
    features: list,
    summary: dict,
    language: str,
    observations: list | None = None,
) -> dict:
    """Generate a default test plan from crawl data without AI."""
    ko = language == "ko"
    categories = []

    # 1. Basic health check (always)
    basic_tests = []
    tid = 1

    # Broken links
    if broken:
        basic_tests.append({
            "id": f"t{tid}",
            "name": "깨진 링크 검사" if ko else "Broken Link Check",
            "description": (
                f"{len(broken)}개의 깨진 링크를 확인합니다" if ko
                else f"Verify {len(broken)} broken link(s) are fixed"
            ),
            "priority": "high",
            "estimated_time": 10 * len(broken),
            "requires_auth": False,
            "selected": True,
            "actual_elements": [b.get("url", "") for b in broken[:5]],
        })
        tid += 1

    # Nav menu tests
    nav_items = []
    for p in pages:
        for nav in p.get("nav_menus", []):
            for item in nav.get("items", []):
                text = (item.get("text") or "").strip()
                href = item.get("href", "")
                if text and href and len(text) < 50:
                    nav_items.append({"text": text, "href": href})
    # Deduplicate by href
    seen_hrefs: set[str] = set()
    unique_nav: list[dict] = []
    for item in nav_items:
        if item["href"] not in seen_hrefs:
            seen_hrefs.add(item["href"])
            unique_nav.append(item)

    if unique_nav:
        basic_tests.append({
            "id": f"t{tid}",
            "name": "네비게이션 메뉴 테스트" if ko else "Navigation Menu Test",
            "description": (
                f"{len(unique_nav)}개 메뉴 항목을 각각 클릭하여 페이지 로딩 확인"
                if ko
                else f"Click each of {len(unique_nav)} menu items and verify page loads"
            ),
            "priority": "high",
            "estimated_time": 10 * len(unique_nav),
            "requires_auth": False,
            "selected": True,
            "actual_elements": [f"{n['text']} ({n['href']})" for n in unique_nav[:10]],
        })
        tid += 1

    # Page load test
    basic_tests.append({
        "id": f"t{tid}",
        "name": "페이지 로딩 테스트" if ko else "Page Load Test",
        "description": (
            f"스캔된 {len(pages)}개 페이지가 정상적으로 로딩되는지 확인"
            if ko
            else f"Verify all {len(pages)} scanned pages load without errors"
        ),
        "priority": "medium",
        "estimated_time": 5 * len(pages),
        "requires_auth": False,
        "selected": True,
        "actual_elements": [p.get("url", "") for p in pages[:5]],
    })
    tid += 1

    categories.append({
        "id": "basic",
        "name": "기본 상태 점검" if ko else "Basic Health Check",
        "auto_selected": True,
        "tests": basic_tests,
    })

    # 2. Forms (if any)
    all_forms = []
    for p in pages:
        for form in p.get("forms", []):
            fields = form.get("fields", [])
            if fields:
                all_forms.append(form)

    if all_forms:
        form_tests = []
        for i, form in enumerate(all_forms[:5]):
            field_names = [f.get("name") or f.get("placeholder") or "field" for f in form.get("fields", [])]
            form_tests.append({
                "id": f"t{tid}",
                "name": f"폼 입력 테스트 #{i + 1}" if ko else f"Form Input Test #{i + 1}",
                "description": (
                    f"필드: {', '.join(field_names[:5])}" if ko
                    else f"Fields: {', '.join(field_names[:5])}"
                ),
                "priority": "medium",
                "estimated_time": 20,
                "requires_auth": False,
                "selected": True,
                "actual_elements": [form.get("selector") or form.get("action", "")],
            })
            tid += 1

        categories.append({
            "id": "forms",
            "name": "폼 검증" if ko else "Form Validation",
            "auto_selected": True,
            "tests": form_tests,
        })

    # 3. Business tests from templates (based on site type + cross-cutting features)
    site_type_info = summary.get("site_type") or {}
    site_type_name = site_type_info.get("type", "unknown") if isinstance(site_type_info, dict) else "unknown"
    feature_set = set(features)

    def _add_template(tmpl: dict, covered: set[str]) -> dict[str, Any] | None:
        """Convert a template to a test entry if its required feature is detected."""
        req_feat = tmpl.get("requires_feature", "")
        if req_feat and req_feat not in feature_set:
            return None
        if req_feat in covered:
            return None  # already covered
        if req_feat:
            covered.add(req_feat)
        return tmpl

    covered_features: set[str] = set()
    business_tests = []

    # Phase 1: site-type-specific templates
    for tmpl in BUSINESS_TEMPLATES.get(site_type_name, []):
        if _add_template(tmpl, covered_features) is None:
            continue
        test_entry: dict[str, Any] = {
            "id": f"t{tid}",
            "name": tmpl["name_ko"] if ko else tmpl["name_en"],
            "description": tmpl["desc_ko"] if ko else tmpl["desc_en"],
            "priority": tmpl.get("priority", "medium"),
            "estimated_time": tmpl.get("estimated_time", 30),
            "requires_auth": tmpl.get("requires_auth", False),
            "selected": not tmpl.get("requires_auth", False),
        }
        if tmpl.get("auth_fields"):
            test_entry["auth_fields"] = tmpl["auth_fields"]
        if tmpl.get("test_data_fields"):
            test_entry["test_data_fields"] = tmpl["test_data_fields"]
        business_tests.append(test_entry)
        tid += 1

    # Phase 2: cross-cutting — scan ALL site types for uncovered detected features
    for other_type, other_templates in BUSINESS_TEMPLATES.items():
        if other_type == site_type_name:
            continue  # already processed
        for tmpl in other_templates:
            if _add_template(tmpl, covered_features) is None:
                continue
            test_entry = {
                "id": f"t{tid}",
                "name": tmpl["name_ko"] if ko else tmpl["name_en"],
                "description": tmpl["desc_ko"] if ko else tmpl["desc_en"],
                "priority": tmpl.get("priority", "medium"),
                "estimated_time": tmpl.get("estimated_time", 30),
                "requires_auth": tmpl.get("requires_auth", False),
                "selected": not tmpl.get("requires_auth", False),
            }
            if tmpl.get("auth_fields"):
                test_entry["auth_fields"] = tmpl["auth_fields"]
            if tmpl.get("test_data_fields"):
                test_entry["test_data_fields"] = tmpl["test_data_fields"]
            business_tests.append(test_entry)
            tid += 1

    if business_tests:
        categories.append({
            "id": "business",
            "name": "비즈니스 흐름" if ko else "Business Flows",
            "auto_selected": False,
            "tests": business_tests,
        })

    # 4. Standard element test patterns
    matched = match_elements_to_patterns(pages, observations or [])
    pattern_category = build_pattern_tests(matched, language)
    if pattern_category:
        categories.append(pattern_category)

    return {"categories": categories}


def _extract_json(text: str) -> dict:
    """Extract JSON object from AI response text."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown code fence
    import re
    patterns = [
        r"```json\s*([\s\S]*?)```",
        r"```\s*([\s\S]*?)```",
        r"\{[\s\S]*\}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1) if match.lastindex else match.group(0)
            try:
                return json.loads(candidate.strip())
            except json.JSONDecodeError:
                continue

    raise ValueError(f"No valid JSON found in response: {text[:200]}")


def _build_observation_table(observations: list[dict]) -> str:
    """Convert raw observations into a structured reference table for AI.

    Produces a human-readable table that maps:
    - Element selector + text → what happens when clicked
    - Observed new_text → what to assert
    - Modal form fields → selectors for input targeting
    """
    if not observations:
        return "No observations collected. Use crawl data forms/buttons for targets."

    lines: list[str] = []
    for i, obs in enumerate(observations, 1):
        elem = obs.get("element", {})
        change = obs.get("observed_change", {})
        change_type = change.get("type", "unknown")

        # Skip no_change observations
        if change_type == "no_change":
            continue

        sel = elem.get("selector") or "NONE"
        txt = elem.get("text") or ""
        etype = elem.get("type") or ""

        lines.append(f"### Observation {i}: {txt}")
        lines.append(f"  - element.selector: {sel}")
        lines.append(f"  - element.text: {txt}")
        lines.append(f"  - element.type: {etype}")
        lines.append(f"  - change_type: {change_type}")
        lines.append(f"  - before_url: {obs.get('before', {}).get('url', '')}")
        lines.append(f"  - after_url: {obs.get('after', {}).get('url', '')}")
        lines.append(f"  - access_path: {obs.get('access_path', '')}")

        # New text (for assertions)
        new_text = change.get("new_text", [])
        if new_text:
            lines.append(f"  - OBSERVED new_text (use for assert): {json.dumps(new_text[:10], ensure_ascii=False)}")

        # Modal form fields (for find_and_type targets)
        modal_fields = change.get("modal_form_fields", [])
        if modal_fields:
            lines.append("  - MODAL FORM FIELDS (use these selectors for input):")
            for f in modal_fields:
                f_sel = f.get("selector") or "NONE"
                f_type = f.get("type", "")
                f_ph = f.get("placeholder", "")
                f_label = f.get("label", "")
                f_name = f.get("name", "")
                if f_type == "submit_button":
                    lines.append(f"    * SUBMIT BUTTON: selector={f_sel}, label={f_label!r}")
                else:
                    lines.append(
                        f"    * type={f_type}, selector={f_sel}, "
                        f"placeholder={f_ph!r}, label={f_label!r}, name={f_name!r}"
                    )

        # Accordion expanded content
        accordion_detail = obs.get("accordion_detail", {})
        if accordion_detail:
            expanded = accordion_detail.get("expanded_text", "")
            if expanded:
                lines.append(f"  - ACCORDION expanded_text: {expanded[:300]}")

        # New elements (modals/dialogs)
        new_elems = change.get("new_elements", [])
        if new_elems:
            lines.append(f"  - new_elements: {new_elems}")

        lines.append("")

    # Add summary of all available texts for assertions
    all_assert_texts: list[str] = []
    all_element_texts: list[str] = []
    for obs in observations:
        elem = obs.get("element", {})
        change = obs.get("observed_change", {})
        if change.get("type") == "no_change":
            continue
        txt = elem.get("text", "")
        if txt:
            all_element_texts.append(txt)
        for nt in change.get("new_text", []):
            if nt.strip():
                all_assert_texts.append(nt.strip())
    if all_assert_texts or all_element_texts:
        lines.append("### ===== AVAILABLE DATA SUMMARY =====")
        if all_element_texts:
            lines.append(f"Clickable element texts: {json.dumps(all_element_texts, ensure_ascii=False)}")
        if all_assert_texts:
            lines.append(f"Observable texts (valid for assert): {json.dumps(all_assert_texts, ensure_ascii=False)}")
        lines.append("REMINDER: Only use texts from above for assert values. NEVER invent text.")
        lines.append("")

    return "\n".join(lines) if lines else "No meaningful observations."


# ---------------------------------------------------------------------------
# POST /api/scan/{scan_id}/execute — run selected tests
# ---------------------------------------------------------------------------

_EXECUTE_PROMPT = """\
Generate AWT test scenario JSON for the selected tests below.

## ========== ABSOLUTE RULES (NEVER VIOLATE) ==========

1. **SELECTOR-FIRST**: Every click/type target MUST include "selector" from the observation data.
   WRONG: {{"text": "기능"}}
   RIGHT: {{"selector": "a[href=\\"#features\\"]", "text": "기능"}}

2. **ASSERT FROM OBSERVED DATA ONLY**: Assert values MUST come from the "OBSERVED new_text"
   field in the observation table below, or from crawl data text that actually exists.
   WRONG: assert value "제품 목록" (AI guess — this text does NOT exist in observation data)
   WRONG: assert value "Product Browsing" (from test name — test names are NOT data)
   RIGHT: assert value "클래스링의 핵심 기능" (copy-pasted from observation new_text)

3. **MODAL FORM FIELDS**: When observation shows modal_opened with modal_form_fields,
   use the EXACT selector/placeholder from modal_form_fields for find_and_type targets.
   observation: modal_form_fields: [{{"selector": "#email", "placeholder": "이메일을 입력하세요"}}]
   → target: {{"selector": "#email", "text": "이메일을 입력하세요"}}

4. **NEVER INVENT**: Do not use any text, selector, URL, or page name that is NOT
   in the Observation Reference Table or Crawl Data below. The selected test names
   are LABELS ONLY — do NOT derive step targets or assert values from them.

5. **WAIT AFTER MODAL**: After clicking an element that opens a modal (change_type: modal_opened),
   add a wait step (1000ms) before interacting with modal fields.

6. **CASE INSENSITIVE ASSERT**: All assert steps MUST set "case_insensitive": true.

7. **TEST INDEPENDENCE**: Each scenario MUST start with navigate to target URL.

8. **NO PHANTOM PAGES**: Do NOT assert URL changes to pages not seen in observations.
   If observation shows anchor_scroll or modal_opened, the URL does NOT change.
   Only assert URL change when observation change_type is "page_navigation".

## ========== END ABSOLUTE RULES ==========

{extra_instructions}

## Reference Documents
{reference_documents}

## Target URL: {target_url}

## Observation Reference Table
Each row = one observed interaction. Use these EXACT selectors and texts.
{observation_table}

## Crawl Data (forms with field selectors)
{crawl_data}

## Selected Tests (LABELS ONLY — do NOT use these names as test data)
{selected_tests}

## User-Provided Data
{user_data}

For empty user data fields, use reasonable dummy data:
- email: use "awttest@example.com"
- password: use "TestPass123!"
- text fields: use contextually appropriate text

## Output Format
Return ONLY a valid JSON array. Each object:
{{
  "id": "SC-001",
  "name": "Test name",
  "description": "Test description",
  "steps": [
    {{
      "step": 1,
      "action": "navigate",
      "value": "{target_url}",
      "description": "Navigate to homepage"
    }},
    {{
      "step": 2,
      "action": "find_and_click",
      "target": {{"selector": "a[href=\\"#login\\"]", "text": "로그인"}},
      "description": "Click login button"
    }},
    {{
      "step": 3,
      "action": "wait",
      "value": "1000",
      "description": "Wait for modal animation"
    }},
    {{
      "step": 4,
      "action": "find_and_type",
      "target": {{"selector": "#email", "text": "이메일"}},
      "value": "awttest@example.com",
      "description": "Enter email"
    }},
    {{
      "step": 5,
      "action": "assert",
      "assert_type": "text_visible",
      "value": "Welcome",
      "description": "Verify welcome text from OBSERVED new_text",
      "case_insensitive": true
    }}
  ]
}}

Actions: navigate, find_and_click, find_and_type, assert, wait, scroll
Target format: {{"selector": "CSS_FROM_OBSERVATION", "text": "VISIBLE_TEXT_FROM_OBSERVATION"}}

FINAL CHECK before responding: For every assert value, verify it appears verbatim
in the Observation Reference Table or Crawl Data. If not, REMOVE that assert step.

Return ONLY valid JSON array.\
"""


@router.post("/{scan_id}/execute")
async def execute_scan_tests(
    scan_id: int,
    body: ScanExecuteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate scenarios from selected tests and create a test execution."""
    query = select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id)
    scan = (await db.execute(query)).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status != ScanStatus.PLANNED:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot execute in '{scan.status.value}' status. Generate a plan first.",
        )

    plan = _parse_json(scan.plan_json)
    if not plan:
        raise HTTPException(status_code=422, detail="No test plan found")

    # Extract selected test details from plan
    selected_details = []
    for cat in plan.get("categories", []):
        for test in cat.get("tests", []):
            if test.get("id") in body.selected_tests:
                selected_details.append(test)

    if not selected_details:
        raise HTTPException(status_code=422, detail="No valid tests selected")

    # Gather crawl data for context
    pages = _parse_json(scan.pages_json) or []
    observations = _parse_json(getattr(scan, "observations_json", None)) or []
    crawl_context = {"nav_menus": [], "forms": [], "buttons": []}
    for p in pages[:5]:
        crawl_context["nav_menus"].extend(p.get("nav_menus", []))
        crawl_context["forms"].extend(p.get("forms", []))
        crawl_context["buttons"].extend(p.get("buttons", []))
        # Collect per-page observations as fallback
        if not observations:
            observations.extend(p.get("observations", []))

    user_data = {**body.auth_data, **body.test_data}

    # Generate scenarios via AI
    try:
        from aat.core.models import AIConfig, Scenario
        from aat.adapters import ADAPTER_REGISTRY
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"AAT core not installed: {exc}")

    ai_config = AIConfig(
        provider=settings.ai_provider,
        api_key=settings.ai_api_key,
        model=settings.ai_model or _DEFAULT_MODELS.get(settings.ai_provider, ""),
    )
    adapter_cls = ADAPTER_REGISTRY.get(ai_config.provider)
    if adapter_cls is None:
        raise HTTPException(status_code=503, detail=f"Unknown AI provider: {ai_config.provider}")

    adapter = adapter_cls(ai_config)

    def _trunc(obj: Any, limit: int = 4000) -> str:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s[:limit] if len(s) > limit else s

    # Build extra instructions based on detected features
    features = _parse_json(scan.detected_features) or []
    extra_parts: list[str] = []
    if "spa" in features:
        extra_parts.append(
            "SPA SITE: Do NOT assert URL changes. Use text_visible assertions. "
            "Anchor links scroll within the page — assert section content is visible."
        )
    if "sticky_header" in features:
        extra_parts.append(
            "STICKY HEADER: Add scroll(0,0,0) before clicking header menu items."
        )

    # Tell AI which elements already have standard tests
    matched_patterns = match_elements_to_patterns(pages, observations)
    pattern_hint = build_pattern_summary(matched_patterns)
    if pattern_hint:
        extra_parts.append(pattern_hint)

    extra_instructions = "\n".join(extra_parts) if extra_parts else ""

    # Build structured observation table for AI
    observation_table = _build_observation_table(observations)

    # Log observation data for debugging
    logger.info(
        "=== AI에 전달되는 관찰 데이터 (scan_id=%d) ===\n%s",
        scan_id,
        observation_table[:5000],
    )

    # Fetch user reference documents
    from app.routers.documents import get_user_doc_text

    ref_docs = await get_user_doc_text(user.id, db)

    prompt = _EXECUTE_PROMPT.format(
        target_url=scan.target_url,
        crawl_data=_trunc(crawl_context),
        observation_table=observation_table,
        selected_tests=_trunc(selected_details),
        user_data=json.dumps(user_data, ensure_ascii=False),
        extra_instructions=extra_instructions,
        reference_documents=ref_docs or "No reference documents provided.",
    )

    try:
        scenarios = await adapter.generate_scenarios(prompt)
    except Exception as exc:
        logger.exception("Scenario generation from scan failed")
        raise HTTPException(
            status_code=502,
            detail=f"AI scenario generation failed: {exc}",
        )

    if not scenarios:
        raise HTTPException(
            status_code=422, detail="AI generated no scenarios",
        )

    # Validate and retry if needed
    scenarios, validation = await validate_and_retry(
        scenarios, observations, pages, adapter, prompt,
    )

    # Compute validation summary
    verified = sum(1 for v in validation if v["status"] == "verified")
    total_v = len(validation)

    # Serialize to YAML
    scenario_dicts = [
        s.model_dump(mode="json", exclude_none=True)
        for s in scenarios
    ]
    scenario_yaml = yaml.safe_dump(
        scenario_dicts,
        default_flow_style=False,
        allow_unicode=True,
    )
    total_steps = sum(len(s.steps) for s in scenarios)

    # Clean up stuck tests for this user before creating a new one
    from app.models import Test, TestStatus

    stuck_cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.stuck_timeout_minutes
    )
    stuck_result = await db.execute(
        select(Test).where(
            Test.user_id == user.id,
            Test.status.in_([TestStatus.RUNNING, TestStatus.QUEUED]),
            Test.updated_at < stuck_cutoff,
        )
    )
    for stuck_test in stuck_result.scalars().all():
        stuck_test.status = TestStatus.FAILED
        stuck_test.error_message = f"Auto-cancelled: stuck {stuck_test.status.value} > {settings.stuck_timeout_minutes} min"
        stuck_test.updated_at = datetime.now(timezone.utc)
        logger.warning("Pre-exec cleanup: auto-failed stuck test %d for user %s", stuck_test.id, user.id)

    # Create a Test record with the generated YAML
    test = Test(
        user_id=user.id,
        target_url=scan.target_url,
        status=TestStatus.QUEUED,
        scenario_yaml=scenario_yaml,
        steps_total=total_steps,
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)

    return {
        "test_id": test.id,
        "scenario_yaml": scenario_yaml,
        "scenarios_count": len(scenarios),
        "steps_total": total_steps,
        "validation": validation,
        "validation_summary": {
            "verified": verified,
            "total": total_v,
            "percent": (
                round(verified / total_v * 100)
                if total_v > 0 else 100
            ),
        },
    }


# ---------------------------------------------------------------------------
# Scenario validation — verify targets against observation data
# ---------------------------------------------------------------------------


def validate_scenarios(
    scenarios: list,
    observations: list[dict],
    page_data: list[dict] | None = None,
) -> list[dict]:
    """Validate scenario step targets against observation/crawl data.

    Returns list of validation results per step:
    [{"scenario_idx": 0, "step": 1, "status": "verified"|"unverified",
      "target_text": "...", "closest_match": "..."|null}]
    """
    # Build lookup sets from observations and page data
    observed_texts: set[str] = set()
    observed_selectors: set[str] = set()
    observed_urls: set[str] = set()
    form_fields: set[str] = set()  # placeholder / label / name

    for obs in observations:
        elem = obs.get("element", {})
        txt = (elem.get("text") or "").strip().lower()
        sel = (elem.get("selector") or "").strip().lower()
        if txt:
            observed_texts.add(txt)
        if sel:
            observed_selectors.add(sel)
        # Collect new_text from observations
        for nt in obs.get("observed_change", {}).get("new_text", []):
            nt_lower = nt.strip().lower()
            if nt_lower:
                observed_texts.add(nt_lower)
        # URLs
        for key in ("before", "after"):
            u = obs.get(key, {}).get("url", "")
            if u:
                observed_urls.add(u.lower())

    # From page data (nav, buttons, links, forms)
    for pdata in (page_data or []):
        for nav in pdata.get("nav_menus", []):
            for item in nav.get("items", []):
                txt = (item.get("text") or "").strip().lower()
                if txt:
                    observed_texts.add(txt)
        for btn in pdata.get("buttons", []):
            txt = (btn.get("text") or "").strip().lower()
            if txt:
                observed_texts.add(txt)
        for link in pdata.get("links", []):
            txt = (link.get("text") or "").strip().lower()
            href = (link.get("href") or "").lower()
            if txt:
                observed_texts.add(txt)
            if href:
                observed_urls.add(href)
        for form in pdata.get("forms", []):
            for field in form.get("fields", []):
                for key in ("name", "placeholder", "label", "aria_label"):
                    val = (field.get(key) or "").strip().lower()
                    if val:
                        form_fields.add(val)
                        observed_texts.add(val)
                sel = (field.get("selector") or "").strip().lower()
                if sel:
                    observed_selectors.add(sel)

    results: list[dict] = []

    for si, scenario in enumerate(scenarios):
        steps = []
        if hasattr(scenario, "steps"):
            steps = scenario.steps
        elif isinstance(scenario, dict):
            steps = scenario.get("steps", [])

        for step in steps:
            # Extract target info
            if hasattr(step, "target"):
                target_obj = step.target
                action = step.action.value if hasattr(
                    step.action, "value"
                ) else str(step.action)
                step_num = step.step
                target_text = (
                    target_obj.text if target_obj else None
                )
                value = step.value
            else:
                target_obj = step.get("target")
                action = str(step.get("action", ""))
                step_num = step.get("step", 0)
                target_text = (
                    target_obj.get("text") if target_obj else None
                )
                value = step.get("value")

            # Skip steps that don't need validation
            if action in ("navigate", "wait", "screenshot"):
                # For navigate, check if URL is known
                if action == "navigate" and value:
                    results.append({
                        "scenario_idx": si,
                        "step": step_num,
                        "status": "verified",
                        "target_text": value,
                    })
                continue

            if not target_text:
                continue

            tt_lower = target_text.strip().lower()

            # Check exact match
            if tt_lower in observed_texts:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                })
                continue

            # Check partial match (target text contained in
            # observed text or vice versa)
            partial = None
            for ot in observed_texts:
                if tt_lower in ot or ot in tt_lower:
                    partial = ot
                    break

            if partial:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                    "closest_match": partial,
                })
                continue

            # Check form fields
            if tt_lower in form_fields:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                })
                continue

            # Not found — unverified
            # Find closest match for hint
            closest = _find_closest(tt_lower, observed_texts)
            results.append({
                "scenario_idx": si,
                "step": step_num,
                "status": "unverified",
                "target_text": target_text,
                "closest_match": closest,
            })

    return results


def _find_closest(
    target: str, candidates: set[str],
) -> str | None:
    """Find the most similar string from candidates."""
    if not candidates:
        return None
    best = None
    best_score = 0
    for c in candidates:
        # Simple overlap scoring
        common = sum(1 for ch in target if ch in c)
        score = common / max(len(target), len(c), 1)
        if score > best_score:
            best_score = score
            best = c
    return best if best_score > 0.3 else None


async def validate_and_retry(
    scenarios: list,
    observations: list[dict],
    page_data: list[dict] | None,
    adapter: Any,
    prompt_context: str,
) -> tuple[list, list[dict]]:
    """Validate scenarios and retry once if too many unverified.

    Returns (possibly_fixed_scenarios, validation_results).
    """
    results = validate_scenarios(scenarios, observations, page_data)
    unverified = [r for r in results if r["status"] == "unverified"]
    total_validated = len(results)

    # If > 30% unverified and we have observations, retry once
    if (
        total_validated > 0
        and len(unverified) / total_validated > 0.3
        and observations
    ):
        logger.info(
            "Validation: %d/%d unverified, retrying",
            len(unverified), total_validated,
        )
        # Build retry prompt
        retry_prompt = (
            f"{prompt_context}\n\n"
            "## VALIDATION FAILED — FIX REQUIRED\n"
            "The following targets were NOT found in the "
            "observation data:\n"
        )
        for uv in unverified:
            closest = uv.get("closest_match")
            hint = f" (closest: \"{closest}\")" if closest else ""
            retry_prompt += (
                f"- Step {uv['step']}: "
                f"\"{uv['target_text']}\"{hint}\n"
            )
        retry_prompt += (
            "\nFix these targets using ONLY elements from "
            "the observation data. Return the complete "
            "corrected scenario JSON array."
        )

        try:
            fixed = await adapter.generate_scenarios(retry_prompt)
            if fixed:
                scenarios = fixed
                results = validate_scenarios(
                    scenarios, observations, page_data,
                )
        except Exception as exc:
            logger.warning("Validation retry failed: %s", exc)

    return scenarios, results


# ---------------------------------------------------------------------------
# WebSocket — per-scan live progress
# ---------------------------------------------------------------------------


@router.websocket("/{scan_id}/ws")
async def scan_websocket(websocket: WebSocket, scan_id: int) -> None:
    """WebSocket for live scan progress.

    Events: scan_start, page_scanned, feature_detected, scan_complete, scan_error.
    """
    await ws_manager.connect(scan_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(scan_id, websocket)
