"""Smart Scan endpoints — site crawling, AI test plan, execution."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
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
You are a senior QA engineer creating a test plan based on actual crawl data.

CRITICAL RULES:
1. ONLY reference elements, selectors, URLs, and text that actually exist in the crawl data.
2. NEVER invent elements that don't exist (no "menu1", no fake selectors).
3. Use EXACT text strings from the crawl data (copy-paste, do not paraphrase).
4. Group tests by category with clear priority.
5. For all text assertions, set case_insensitive: true to handle dynamic casing.
6. Respond in {language}.

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

## Business Test Hints (based on site type)
{business_hints}

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
    "actual_elements": ["selector or text used"]
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

    # Truncate for prompt size
    def _trunc_json(obj: Any, limit: int = 3000) -> str:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s[:limit] if len(s) > limit else s

    # Build site type info for prompt
    site_type_info = summary.get("site_type") or {}
    site_type_name = site_type_info.get("type", "unknown") if isinstance(site_type_info, dict) else "unknown"
    site_type_conf = site_type_info.get("confidence", 0.0) if isinstance(site_type_info, dict) else 0.0

    # Build business hints from templates
    business_hints_lines = []
    templates = BUSINESS_TEMPLATES.get(site_type_name, [])
    for tmpl in templates:
        req_feat = tmpl.get("requires_feature", "")
        if not req_feat or req_feat in features:
            name = tmpl.get("name_en", "")
            desc = tmpl.get("desc_en", "")
            business_hints_lines.append(f"- {name}: {desc}")
    business_hints = "\n".join(business_hints_lines) if business_hints_lines else "No specific business tests for this site type."

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
        business_hints=business_hints,
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
        plan = _generate_default_plan(scan, pages, broken, features, summary, lang)

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

    # 3. Business tests from templates (based on site type)
    site_type_info = summary.get("site_type") or {}
    site_type_name = site_type_info.get("type", "unknown") if isinstance(site_type_info, dict) else "unknown"
    feature_set = set(features)

    templates = BUSINESS_TEMPLATES.get(site_type_name, [])
    business_tests = []
    for tmpl in templates:
        req_feat = tmpl.get("requires_feature", "")
        if req_feat and req_feat not in feature_set:
            continue  # skip if required feature not detected

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

    # Fallback: if no business templates matched, check for login_form feature
    if not business_tests and "login_form" in feature_set:
        business_tests.append({
            "id": f"t{tid}",
            "name": "로그인 흐름 테스트" if ko else "Login Flow Test",
            "description": "로그인 페이지 접근 및 폼 동작 확인" if ko else "Access login page and verify form works",
            "priority": "high",
            "estimated_time": 30,
            "requires_auth": True,
            "selected": False,
            "auth_fields": [
                {"key": "email", "label": "Email", "type": "email", "required": True},
                {"key": "password", "label": "Password", "type": "password", "required": True},
            ],
        })
        tid += 1

    if business_tests:
        categories.append({
            "id": "business",
            "name": "비즈니스 흐름" if ko else "Business Flows",
            "auto_selected": False,
            "tests": business_tests,
        })

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


# ---------------------------------------------------------------------------
# POST /api/scan/{scan_id}/execute — run selected tests
# ---------------------------------------------------------------------------

_EXECUTE_PROMPT = """\
Generate AWT test scenario YAML for the selected tests below.

CRITICAL RULES:
1. Use ONLY the actual selectors, URLs, and element text from the crawl data below.
2. NEVER invent selectors or elements that don't exist in the crawl data.
3. For click/type targets, prefer using "text" field with the EXACT visible text from crawl data.
4. For all assert steps, ALWAYS set "case_insensitive": true to handle dynamic casing.
5. Copy text strings EXACTLY from the crawl data — do not paraphrase or translate.

## Target URL: {target_url}

## Crawl Data (navigation menus, forms, buttons)
{crawl_data}

## Selected Tests
{selected_tests}

## User-Provided Data
{user_data}

For empty user data fields, use reasonable dummy data:
- email: use "awttest@example.com"
- text fields: use contextually appropriate text
- numbers: use reasonable values

Generate scenario YAML as a JSON array of objects, each with:
- id: string
- name: string
- steps: array of step objects with action, target, value, description

Step actions: navigate, click, type, assert, wait
For click/type, use "text" field with exact visible text, or "selector" field with CSS selector.
For assert, use "text" field with text to verify and always include "case_insensitive": true.

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
    crawl_context = {"nav_menus": [], "forms": [], "buttons": []}
    for p in pages[:5]:
        crawl_context["nav_menus"].extend(p.get("nav_menus", []))
        crawl_context["forms"].extend(p.get("forms", []))
        crawl_context["buttons"].extend(p.get("buttons", []))

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

    def _trunc(obj: Any, limit: int = 3000) -> str:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s[:limit]

    prompt = _EXECUTE_PROMPT.format(
        target_url=scan.target_url,
        crawl_data=_trunc(crawl_context),
        selected_tests=_trunc(selected_details),
        user_data=json.dumps(user_data, ensure_ascii=False),
    )

    try:
        scenarios = await adapter.generate_scenarios(prompt)
    except Exception as exc:
        logger.exception("Scenario generation from scan failed")
        raise HTTPException(status_code=502, detail=f"AI scenario generation failed: {exc}")

    if not scenarios:
        raise HTTPException(status_code=422, detail="AI generated no scenarios")

    # Serialize to YAML
    scenario_dicts = [s.model_dump(mode="json", exclude_none=True) for s in scenarios]
    scenario_yaml = yaml.safe_dump(
        scenario_dicts, default_flow_style=False, allow_unicode=True
    )
    total_steps = sum(len(s.steps) for s in scenarios)

    # Create a Test record with the generated YAML
    from app.models import Test, TestStatus

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
    }


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
