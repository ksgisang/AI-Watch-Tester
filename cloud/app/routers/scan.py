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
3. Use exact selectors and text from the crawl data.
4. Group tests by category with clear priority.
5. Respond in {language}.

## Site Info
- URL: {target_url}
- Pages scanned: {total_pages}
- Detected features: {detected_features}

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
- cart → add to cart flow
- review_form → review submission
- board_write → post creation
- comment_form → comment submission

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

    # Build AI prompt
    lang = "Korean" if body.language == "ko" else "English"
    prompt = _PLAN_PROMPT.format(
        language=lang,
        target_url=scan.target_url,
        total_pages=summary.get("total_pages", len(pages)),
        detected_features=", ".join(features) if features else "none",
        nav_menus_json=_trunc_json(nav_menus),
        forms_json=_trunc_json(forms),
        buttons_json=_trunc_json(buttons),
        links_json=_trunc_json(links_sample),
        broken_links_json=_trunc_json(broken),
        broken_count=len(broken),
    )

    # Call AI
    try:
        from aat.core.models import AIConfig
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

    try:
        # Use generate_scenarios but parse the JSON response directly
        raw_response = await adapter.generate_raw(prompt)
    except AttributeError:
        # Fallback: use generate_scenarios and convert
        try:
            raw_response = await _ai_raw_call(adapter, prompt)
        except Exception as exc:
            logger.exception("AI plan generation failed")
            raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}")
    except Exception as exc:
        logger.exception("AI plan generation failed")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}")

    # Parse AI response as JSON
    try:
        plan = _extract_json(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse AI plan: %s", exc)
        raise HTTPException(status_code=502, detail="AI returned invalid plan format")

    categories = plan.get("categories", [])
    if not categories:
        raise HTTPException(status_code=502, detail="AI generated no test categories")

    # Save plan to DB
    scan.plan_json = json.dumps(plan, ensure_ascii=False)
    scan.status = ScanStatus.PLANNED
    await db.commit()

    return {"scan_id": scan_id, "categories": categories}


async def _ai_raw_call(adapter: Any, prompt: str) -> str:
    """Call AI adapter for raw text response (fallback for adapters without generate_raw)."""
    # Try the internal client directly
    if hasattr(adapter, "client"):
        client = adapter.client
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            # OpenAI-style
            response = await client.chat.completions.create(
                model=adapter.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content or ""

    if hasattr(adapter, "_client"):
        client = adapter._client
        # Anthropic-style
        if hasattr(client, "messages"):
            response = await client.messages.create(
                model=adapter.config.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else ""

    # Last resort: use generate_scenarios which returns Scenario objects
    # and extract what we need
    raise NotImplementedError("Adapter does not support raw text generation")


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

CRITICAL: Use ONLY the actual selectors, URLs, and element text from the crawl data.
NEVER invent selectors or elements that don't exist in the crawl data.

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
For assert, use "text" field with text to verify.

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
