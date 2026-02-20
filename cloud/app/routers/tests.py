"""Test CRUD + WebSocket endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.docparse import allowed_extension, extract_text
from app.middleware import check_rate_limit
from app.models import Test, TestStatus, User
from app.schemas import (
    ConvertScenarioRequest,
    ConvertScenarioResponse,
    ScenarioUpdate,
    TestCreate,
    TestListResponse,
    TestResponse,
    UploadResponse,
)
from app.ws import ws_manager

router = APIRouter(prefix="/api/tests", tags=["tests"])


@router.post("", response_model=TestResponse, status_code=201)
async def create_test(
    body: TestCreate,
    user: User = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Create a new test.

    mode=review → GENERATING (AI generates, user reviews before execution)
    mode=auto → QUEUED (generate + execute immediately)
    scenario_yaml provided → QUEUED with pre-built scenarios (skip generation)
    """
    # Pre-built scenario: validate and go straight to QUEUED
    steps_total = 0
    if body.scenario_yaml:
        try:
            parsed = yaml.safe_load(body.scenario_yaml)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")
        if not parsed:
            raise HTTPException(status_code=422, detail="Empty scenario YAML")
        try:
            from aat.core.models import Scenario

            items = parsed if isinstance(parsed, list) else [parsed]
            scenarios = [Scenario.model_validate(item) for item in items]
            steps_total = sum(len(s.steps) for s in scenarios)
        except ImportError:
            pass
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Scenario validation error: {exc}")

    if body.scenario_yaml:
        initial_status = TestStatus.QUEUED
    else:
        initial_status = (
            TestStatus.GENERATING if body.mode == "review" else TestStatus.QUEUED
        )

    test = Test(
        user_id=user.id,
        target_url=str(body.target_url),
        status=initial_status,
        scenario_yaml=body.scenario_yaml,
        steps_total=steps_total,
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return test


@router.get("", response_model=TestListResponse)
async def list_tests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict:
    """List current user's tests (newest first, paginated)."""
    # Total count
    count_q = select(func.count()).select_from(Test).where(Test.user_id == user.id)
    total = (await db.execute(count_q)).scalar() or 0

    # Paginated results
    offset = (page - 1) * page_size
    query = (
        select(Test)
        .where(Test.user_id == user.id)
        .order_by(Test.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    tests = list(result.scalars().all())

    return {
        "tests": tests,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Get a single test by ID (must belong to current user)."""
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    result = await db.execute(query)
    test = result.scalar_one_or_none()

    if test is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Test not found")

    return test


@router.put("/{test_id}/scenarios", response_model=TestResponse)
async def update_scenarios(
    test_id: int,
    body: ScenarioUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Update scenario YAML (only allowed in REVIEW status)."""
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    test = (await db.execute(query)).scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")
    if test.status != TestStatus.REVIEW:
        raise HTTPException(
            status_code=409, detail=f"Cannot edit scenarios in '{test.status.value}' status"
        )

    # Validate YAML syntax
    try:
        parsed = yaml.safe_load(body.scenario_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")
    if not parsed:
        raise HTTPException(status_code=422, detail="Empty scenario YAML")

    # Validate with Scenario model
    try:
        from aat.core.models import Scenario

        items = parsed if isinstance(parsed, list) else [parsed]
        scenarios = [Scenario.model_validate(item) for item in items]
    except ImportError:
        pass  # AAT not installed — skip model validation
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Scenario validation error: {exc}")

    test.scenario_yaml = body.scenario_yaml
    test.steps_total = sum(
        len(s.steps) for s in scenarios
    ) if "scenarios" in dir() else test.steps_total
    await db.commit()
    await db.refresh(test)
    return test


@router.post("/{test_id}/approve", response_model=TestResponse)
async def approve_test(
    test_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Approve scenarios and queue test for execution (REVIEW → QUEUED)."""
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    test = (await db.execute(query)).scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")
    if test.status != TestStatus.REVIEW:
        raise HTTPException(
            status_code=409, detail=f"Cannot approve test in '{test.status.value}' status"
        )
    if not test.scenario_yaml:
        raise HTTPException(status_code=422, detail="No scenarios to approve")

    test.status = TestStatus.QUEUED
    await db.commit()
    await db.refresh(test)
    return test


@router.post("/{test_id}/cancel", response_model=TestResponse)
async def cancel_test(
    test_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Cancel a test that is generating, queued, or running."""
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    test = (await db.execute(query)).scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")

    cancellable = {TestStatus.GENERATING, TestStatus.REVIEW, TestStatus.QUEUED, TestStatus.RUNNING}
    if test.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel test in '{test.status.value}' status",
        )

    test.status = TestStatus.FAILED
    test.error_message = "Cancelled by user"
    from datetime import datetime, timezone
    test.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(test)

    # Notify WebSocket clients
    from app.ws import ws_manager
    await ws_manager.broadcast(test_id, {
        "type": "test_fail",
        "test_id": test_id,
        "error": "Cancelled by user",
    })

    return test


@router.post("/{test_id}/upload", response_model=UploadResponse)
async def upload_document(
    test_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a document for AI-assisted scenario generation.

    Supported formats: .md, .txt, .pdf, .docx. Max 10MB.
    Extracts text and appends to test.doc_text.
    """
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    test = (await db.execute(query)).scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")
    if test.status not in (TestStatus.GENERATING, TestStatus.REVIEW):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot upload documents in '{test.status.value}' status",
        )

    # Validate filename
    filename = file.filename or "unknown"
    if not allowed_extension(filename):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: .md, .txt, .pdf, .docx",
        )

    # Read file content with size check
    content = await file.read()
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.upload_max_bytes // (1024*1024)}MB",
        )

    # Save file to disk
    upload_dir = Path(settings.upload_dir) / str(test_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(content)

    # Extract text
    try:
        text = extract_text(file_path)
    except ValueError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))

    # Append to doc_text (support multiple uploads)
    header = f"\n\n--- {filename} ---\n\n"
    if test.doc_text:
        test.doc_text += header + text
    else:
        test.doc_text = f"--- {filename} ---\n\n" + text
    await db.commit()

    return {
        "filename": filename,
        "size": len(content),
        "extracted_chars": len(text),
    }


# ---------------------------------------------------------------------------
# Scenario conversion — natural language → YAML
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Default model per AI provider (mirrors executor.py)
_DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "codellama:7b",
}

_CONVERT_PROMPT = """\
You are an E2E test scenario generator.

The user wants to test the following on their website.

## Target
- URL: {url}

## User Request
{user_prompt}

## Actual Page Data (from real browser visit)
{page_data}

## Interaction Observations (REAL click results — DO NOT GUESS)
{observations}

## Reference Documents
{reference_documents}

## CRITICAL Rules
1. Convert the user's natural language description into concrete E2E test scenarios
2. Generate 1-5 test scenarios covering the described flows
3. Each scenario should have clear steps: navigate, click, type, assert
4. **Use EXACT text from the "Actual Page Data" and "Interaction Observations"**
   - Use real button labels, link text, menu names exactly as they appear
   - NEVER use generic placeholders like "menu1", "menu2", "button1"
   - NEVER guess what happens — use observed change types and new_text
5. **SELECTOR-FIRST RULE**: For click/type targets, include BOTH "selector" AND "text":
   - "selector": CSS selector from observation data (e.g., "a[href='#features']")
   - "text": visible label text as fallback
   - The test engine tries selector first, text as fallback
   - Example: {{"selector": "a[href='#login']", "text": "로그인"}}
6. For assertions, use the observed results:
   - If observation shows modal_opened → assert the observed new_text
   - If observation shows page_navigation → assert URL change
   - If observation shows anchor_scroll → assert section text visible
7. For form fields, use exact selectors/placeholders from page data
8. Keep steps concise and actionable
9. Use {{{{url}}}} as the base URL placeholder in navigate actions
10. **ACCESS PATH**: Include navigation steps that match the observed access path.
    If observation shows "click a[href='#login'] on homepage → modal opens",
    the scenario MUST include: navigate → click a[href='#login'] → interact with modal

Return the scenarios as a JSON array. Each step target should include:
- "selector": CSS selector from observation data (preferred)
- "text": visible text label (fallback)
Follow the format specified in the system instructions.\
"""


@router.post("/convert", response_model=ConvertScenarioResponse)
async def convert_scenario(
    body: ConvertScenarioRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Convert natural language to AWT YAML scenario.

    Visits the target URL, extracts page data, observes interactions
    related to user keywords, then generates scenarios with real data.
    """
    import json

    try:
        from aat.core.models import AIConfig, EngineConfig
        from aat.adapters import ADAPTER_REGISTRY
        from aat.engine.web import WebEngine
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"AAT core not installed: {exc}",
        ) from exc

    from app.crawler import (
        _extract_page_data,
        _observe_interactions,
    )

    ai_config = AIConfig(
        provider=settings.ai_provider,
        api_key=settings.ai_api_key,
        model=settings.ai_model or _DEFAULT_MODELS.get(
            settings.ai_provider, ""
        ),
    )
    adapter_cls = ADAPTER_REGISTRY.get(ai_config.provider)
    if adapter_cls is None:
        raise HTTPException(
            status_code=503,
            detail=f"Unknown AI provider: {ai_config.provider}",
        )
    adapter = adapter_cls(ai_config)

    # --- Quick page observation ---
    page_data_str = "Page visit failed — using user prompt only."
    observations_str = "No observations."
    observations_raw: list[dict] = []
    pdata_raw: dict | None = None
    engine_config = EngineConfig(
        type="web", headless=settings.playwright_headless,
    )
    engine = WebEngine(engine_config)

    try:
        await engine.start()
        page = engine.page
        await page.goto(
            str(body.target_url),
            wait_until="domcontentloaded",
            timeout=12000,
        )
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=5000,
            )
        except Exception:
            pass

        # Extract page data (single page, no full crawl)
        pdata_raw = await _extract_page_data(
            page, str(body.target_url), take_screenshot=False,
        )

        # Filter clickable elements by user keywords for
        # targeted observation (not full scan)
        keywords = _extract_keywords(body.user_prompt)
        filtered_data = _filter_by_keywords(pdata_raw, keywords)

        # Observe only keyword-relevant elements
        observations_raw = await _observe_interactions(
            page, filtered_data, str(body.target_url),
            max_interactions=10,
        )

        # Serialize for prompt (strip screenshots)
        pdata_raw.pop("screenshot_base64", None)
        page_data_str = json.dumps(
            pdata_raw, ensure_ascii=False, indent=2,
        )[:6000]
        if observations_raw:
            from app.routers.scan import _build_observation_table
            observations_str = _build_observation_table(observations_raw)
    except Exception as exc:
        logger.warning(
            "Page observation failed for convert: %s", exc,
        )
    finally:
        try:
            await engine.stop()
        except Exception:
            pass

    # Fetch user reference documents
    from app.routers.documents import get_user_doc_text

    ref_docs = await get_user_doc_text(user.id, db)

    prompt = _CONVERT_PROMPT.format(
        url=body.target_url,
        user_prompt=body.user_prompt,
        page_data=page_data_str,
        observations=observations_str,
        reference_documents=ref_docs or "No reference documents provided.",
    )

    try:
        scenarios = await adapter.generate_scenarios(prompt)
    except Exception as exc:
        logger.exception("Scenario conversion failed")
        raise HTTPException(
            status_code=502, detail=f"AI generation failed: {exc}",
        ) from exc

    if not scenarios:
        raise HTTPException(
            status_code=422, detail="AI generated no scenarios",
        )

    # Validate against observation data and retry if needed
    from app.routers.scan import validate_and_retry

    page_list = [pdata_raw] if pdata_raw else None
    scenarios, validation = await validate_and_retry(
        scenarios, observations_raw, page_list, adapter, prompt,
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

    return {
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


def _extract_keywords(user_prompt: str) -> list[str]:
    """Extract test-relevant keywords from user prompt."""
    # Common Korean/English test-related words to filter on
    stop_words = {
        "테스트", "확인", "해줘", "해주세요", "후", "에서",
        "되는지", "하고", "test", "check", "verify", "the",
        "then", "and", "that", "from", "with", "after",
        "before", "click", "type", "go", "to", "if", "is",
        "a", "an", "on", "in", "it", "do", "can", "should",
    }
    words = user_prompt.replace(",", " ").replace(".", " ").split()
    keywords = []
    for w in words:
        w = w.strip().lower()
        if len(w) > 1 and w not in stop_words:
            keywords.append(w)
    return keywords[:15]


def _filter_by_keywords(
    page_data: dict, keywords: list[str],
) -> dict:
    """Return a copy of page_data with elements filtered by keywords.

    If no keywords match anything, returns the original data
    (so the observation still happens on nav items).
    """
    if not keywords:
        return page_data

    def _matches(text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in keywords)

    filtered = {**page_data}

    # Filter links by keyword relevance
    links = page_data.get("links", [])
    matched_links = [
        l for l in links
        if _matches(l.get("text", "")) or _matches(l.get("href", ""))
    ]
    # Filter buttons
    buttons = page_data.get("buttons", [])
    matched_buttons = [
        b for b in buttons if _matches(b.get("text", ""))
    ]

    # Always keep nav menus (they're important for context)
    # but also include keyword-matched nav items
    filtered["links"] = matched_links if matched_links else links[:20]
    filtered["buttons"] = (
        matched_buttons if matched_buttons else buttons[:10]
    )

    return filtered


# ---------------------------------------------------------------------------
# WebSocket — per-test live progress
# ---------------------------------------------------------------------------


@router.websocket("/{test_id}/ws")
async def test_websocket(websocket: WebSocket, test_id: int) -> None:
    """WebSocket for live test progress.

    Events sent: test_start, scenarios_generated, step_start, step_done,
    step_fail, test_complete, test_fail.
    """
    await ws_manager.connect(test_id, websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(test_id, websocket)
