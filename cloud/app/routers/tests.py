"""Test CRUD + WebSocket endpoints."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC
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
from app.scenario_utils import (
    DEFAULT_AI_MODELS as _DEFAULT_MODELS,
)
from app.scenario_utils import (
    compress_observations_for_ai,
    ensure_post_submit_assert,
    fix_field_targets,
    fix_form_submit_steps,
    validate_and_retry,
)
from app.scenario_utils import (
    parse_json as _parse_json,
)
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
            raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc
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
            raise HTTPException(status_code=422, detail=f"Scenario validation error: {exc}") from exc

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
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc
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
        raise HTTPException(status_code=422, detail=f"Scenario validation error: {exc}") from exc

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
    from datetime import datetime
    test.updated_at = datetime.now(UTC)
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
            detail="Unsupported file type. Allowed: .md, .txt, .pdf, .docx",
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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

_CONVERT_PROMPT = """\
You are an E2E test scenario generator.

## ========== #1 PRIORITY: USER REQUEST (OVERRIDE ALL OTHER RULES) ==========

The user's request below is the SINGLE MOST IMPORTANT instruction.
Generate scenarios ONLY for what the user asked. Do NOT test other features.

- "회원가입 테스트 해줘" → Generate ONLY signup test scenarios. Do NOT test login,
  navigation, about page, blog, help, or any other feature.
- "로그인 테스트 해줘" → Generate ONLY login test scenarios.
- "전체 테스트 해줘" / "사이트 테스트 해줘" → Test all features found.

If the user asks for a SPECIFIC feature, your response MUST contain:
  1. Navigate to homepage
  2. Click the element that leads to the requested feature
  3. Interact with the feature (fill form fields, click buttons, etc.)
  4. Assert the expected result
If you generate tests for features the user did NOT ask for, your response is WRONG.

## Target
- URL: {url}

## User Request
{user_prompt}

## Element Summary
{element_summary}

## Actual Page Data (from real browser visit)
{page_data}

## Interaction Observations (REAL click results — DO NOT GUESS)
{observations}

## Reference Documents
{reference_documents}

## ========== RULES ==========

1. **USER REQUEST FIRST**: Generate scenarios ONLY for the user's requested feature.
   The "TEST ALL ELEMENTS" rule ONLY applies when the user asks for broad testing
   (e.g., "전체 테스트", "사이트 테스트", "모든 기능 테스트").
   For specific requests like "회원가입 테스트", generate ONLY that feature's test.

2. **FORM INTERACTION IS REQUIRED**: When the user requests a form-based feature
   (signup, login, search, payment), the scenario MUST include:
   a. navigate to homepage
   b. find_and_click the element that opens the form page/modal
   c. find_and_type into EACH form field (use selectors from Form Fields section)
   d. find_and_click the SUBMIT[form] button
   e. wait 1500ms (for page transition after submit)
   f. assert the OUTCOME (see Rule 11 — this is MANDATORY, not optional)
   A scenario with ONLY navigation + assert (no find_and_type) is INCOMPLETE and WRONG.
   A scenario that ends at the submit click WITHOUT a final assert is ALSO WRONG.

3. **FORM SUBMIT BUTTON — CRITICAL**:
   After filling form fields, the NEXT click MUST be SUBMIT[form], NOT SUBMIT[nav].
   - SUBMIT[form] = button INSIDE the form → USE THIS
   - SUBMIT[nav] = navigation menu link → NEVER use after form input
   Example: SUBMIT[form](button.btn, '다음') and SUBMIT[nav](a.nav, '가입')
   → After filling email/password, click '다음' (SUBMIT[form]), NOT '가입' (SUBMIT[nav])

4. **USE ONLY OBSERVED DATA**: Every text, selector, URL MUST come from the
   Page Data or Interaction Observations sections above.
   - NEVER invent text — copy-paste from data.
   - NEVER guess button labels or field names.

5. **SELECTOR-FIRST**: Every click/type target MUST include BOTH "selector" AND "text":
   {{"selector": "a[href='#login']", "text": "로그인"}}

6. **ACCESS PATH**: Include navigation steps matching the observed access path.
   If observation shows "click '가입' → navigate to /register with form fields",
   the scenario MUST: navigate homepage → click '가입' → fill form → submit.

7. **CASE INSENSITIVE ASSERT**: All assert steps MUST set "case_insensitive": true.

8. **NO-SUBSTITUTION RULE**: If the requested feature does NOT exist in the data,
   return an EMPTY array []. NEVER substitute a different feature.
   "회원가입" requested but only "로그인" exists → return [], NOT a login test.

9. **TEST INDEPENDENCE**: Each scenario MUST start with navigate to {{{{url}}}}.

10. For form fields, use EXACT selectors/placeholders from the Form Fields section.
    For dummy data: email → "awttest@example.com", password → "TestPass123!"
    For confirm password fields, use THE SAME value as the password: "TestPass123!"

11. **OUTCOME VERIFICATION — MANDATORY (NEVER SKIP)**:
    Every form-based scenario MUST end with an assert step AFTER the submit click.
    A test that clicks submit and stops is MEANINGLESS — it only proves the button exists.
    The assert verifies the RESULT of the submission:

    After SUBMIT[form] click → wait 1500ms → assert ONE of:
    a. url_contains: verify URL changed (e.g., "/step2", "/success", "/dashboard")
    b. text_visible: verify NEW content appeared (success message, next step heading)
    c. text_visible: verify the form page CHANGED (step 2 content replaced step 1)

    Example for multi-step signup (step 1 → step 2):
    step N:   find_and_click SUBMIT[form] '다음'
    step N+1: wait 1500ms
    step N+2: assert text_visible — text from the NEXT page/step
              (use assert_texts from observation data, or a keyword like "완료", "인증")

    Example for login:
    step N:   find_and_click SUBMIT[form] '로그인'
    step N+1: wait 1500ms
    step N+2: assert url_contains "/dashboard" OR text_visible "환영합니다"

    If you don't know the exact post-submit text, assert url_contains with the
    form page path (e.g., the URL should NO LONGER be the same as before submit).

    WRONG: scenario ends with find_and_click '다음' → NO assert → test "passes"
    RIGHT: scenario ends with find_and_click '다음' → wait → assert text_visible "..."

Return the scenarios as a JSON array. Each step target should include:
- "selector": CSS selector from observation data (preferred)
- "text": visible text label (fallback)

FINAL CHECK: Before responding, verify:
1. Does every scenario match the user's request? (NOT other features)
2. Does every form-feature test include find_and_type steps?
3. Does the submit click use SUBMIT[form], not SUBMIT[nav]?
4. Does every form scenario have an assert step AFTER the submit click?
   If the last step is find_and_click (submit) → ADD wait + assert.
Remove any scenario that tests a feature the user did NOT request.\
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
        from aat.adapters import ADAPTER_REGISTRY
        from aat.core.models import AIConfig, EngineConfig
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

    # --- Gather page data + observations ---
    page_data_str = "Page visit failed — using user prompt only."
    observations_str = "No observations."
    element_summary = "No element data available."
    observations_raw: list[dict] = []
    pdata_raw: dict | None = None
    page_list_for_validation: list[dict] | None = None

    # If scan_id provided, use existing scan data (much richer than fresh visit)
    if body.scan_id:
        from app.models import Scan, ScanStatus

        scan_q = select(Scan).where(
            Scan.id == body.scan_id, Scan.user_id == user.id,
        )
        scan = (await db.execute(scan_q)).scalar_one_or_none()
        if scan and scan.status in (ScanStatus.COMPLETED, ScanStatus.PLANNED):
            pages = _parse_json(scan.pages_json) or []
            observations_raw = _parse_json(
                getattr(scan, "observations_json", None),
            ) or []
            # Collect per-page observations as fallback
            if not observations_raw:
                for p in pages:
                    observations_raw.extend(p.get("observations", []))

            # Build page data from all scanned pages
            all_page_data: dict = {
                "nav_menus": [], "forms": [], "buttons": [],
                "links": [], "images": [],
            }
            for p in pages:
                all_page_data["nav_menus"].extend(p.get("nav_menus", []))
                all_page_data["forms"].extend(p.get("forms", []))
                all_page_data["buttons"].extend(p.get("buttons", []))
                all_page_data["links"].extend(p.get("links", [])[:20])
                all_page_data["images"].extend(p.get("images", []))

            pdata_raw = all_page_data
            page_list_for_validation = pages
            page_data_str = json.dumps(
                all_page_data, ensure_ascii=False, indent=2,
            )[:8000]
            if observations_raw:
                observations_str = compress_observations_for_ai(observations_raw, max_tokens=10000)

            # Build element summary with counts
            element_summary = _build_element_summary(
                observations_raw, all_page_data,
            )
            logger.info(
                "Convert: using scan %d data — %d observations, %d pages",
                body.scan_id, len(observations_raw), len(pages),
            )

    # Fallback: fresh page visit (no scan data)
    if pdata_raw is None:
        engine_config = EngineConfig(
            type="web", headless=settings.playwright_headless,
            viewport_width=1920, viewport_height=1080,
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
            with contextlib.suppress(Exception):
                await page.wait_for_load_state(
                    "networkidle", timeout=5000,
                )

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
                observations_str = compress_observations_for_ai(observations_raw, max_tokens=10000)

            # Build element summary with counts
            element_summary = _build_element_summary(
                observations_raw, pdata_raw,
            )
        except Exception as exc:
            logger.warning(
                "Page observation failed for convert: %s", exc,
            )
        finally:
            with contextlib.suppress(Exception):
                await engine.stop()

    # Fetch user reference documents
    from app.routers.documents import get_user_doc_text

    ref_docs = await get_user_doc_text(user.id, db)

    # --- Pre-generation: check if the requested feature exists ---
    relevance_pre = validate_scenario_relevance(
        body.user_prompt, [], observations_raw, pdata_raw,
    )
    if relevance_pre.get("feature_missing"):
        # Feature doesn't exist on site — don't generate wrong scenario
        logger.info(
            "Convert: feature missing for request '%s'",
            body.user_prompt[:60],
        )
        return {
            "scenario_yaml": "",
            "scenarios_count": 0,
            "steps_total": 0,
            "validation": [],
            "validation_summary": {"verified": 0, "total": 0, "percent": 0},
            "relevance": relevance_pre,
        }

    prompt = _CONVERT_PROMPT.format(
        url=body.target_url,
        user_prompt=body.user_prompt,
        element_summary=element_summary,
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

    # --- Post-generation: validate relevance ---
    relevance = validate_scenario_relevance(
        body.user_prompt, scenarios, observations_raw, pdata_raw,
    )

    # If invalid (wrong scenario), retry once with stronger prompt
    if not relevance.get("valid") and not relevance.get("feature_missing"):
        logger.info(
            "Convert: relevance check failed (%s), retrying",
            relevance.get("reason", ""),
        )
        retry_prompt = (
            f"{prompt}\n\n"
            "## RELEVANCE CHECK FAILED — REGENERATE\n"
            f"Your previous response did NOT match the user's request.\n"
            f"User asked for: {body.user_prompt}\n"
            f"Problem: {relevance.get('reason', '')}\n"
            f"Warnings: {relevance.get('warnings', [])}\n\n"
            "REGENERATE the scenario to EXACTLY match the user's request.\n"
            "If the requested feature does not exist in the page data, "
            "return an EMPTY array [].\n"
            "Return ONLY valid JSON array."
        )
        try:
            retry_scenarios = await adapter.generate_scenarios(retry_prompt)
            if retry_scenarios:
                scenarios = retry_scenarios
                relevance = validate_scenario_relevance(
                    body.user_prompt, scenarios, observations_raw, pdata_raw,
                )
        except Exception as exc:
            logger.warning("Relevance retry failed: %s", exc)

    # Fix AI-generated field targets to use actual observed data
    scenarios = fix_field_targets(scenarios, observations_raw)

    # Fix form-submit-after-input: replace nav clicks with form submit buttons
    scenarios = fix_form_submit_steps(scenarios, observations_raw)

    # Ensure every form scenario has assert/wait after submit
    scenarios = ensure_post_submit_assert(scenarios)

    # Validate against observation data and retry if needed
    if page_list_for_validation is None:
        page_list_for_validation = [pdata_raw] if pdata_raw else None
    scenarios, validation = await validate_and_retry(
        scenarios, observations_raw, page_list_for_validation, adapter, prompt,
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
        "relevance": relevance,
    }


def _build_element_summary(
    observations: list[dict], page_data: dict,
) -> str:
    """Build a concise element count summary for the AI prompt.

    Tells the AI exactly how many elements exist so it generates
    tests for ALL of them, not just a sample.
    """
    lines: list[str] = []

    # Count observation types
    accordion_items: list[str] = []
    modal_items: list[str] = []
    nav_items: list[str] = []
    page_nav_items: list[str] = []
    other_items: list[str] = []

    for obs in observations:
        elem = obs.get("element", {})
        change = obs.get("observed_change", {})
        change_type = change.get("type", "")
        text = (elem.get("text") or "")[:60]

        if change_type == "no_change":
            continue
        elif change_type == "content_expanded" or elem.get("type") == "accordion":
            accordion_items.append(text)
        elif change_type == "modal_opened":
            modal_items.append(text)
        elif change_type == "anchor_scroll" or change_type == "section_change":
            nav_items.append(text)
        elif change_type == "page_navigation":
            page_nav_items.append(text)
        else:
            other_items.append(text)

    if accordion_items:
        lines.append(
            f"- Accordions: {len(accordion_items)} items — "
            f"test ALL: {json.dumps(accordion_items, ensure_ascii=False)}"
        )
    if modal_items:
        lines.append(
            f"- Modals: {len(modal_items)} triggers — "
            f"test ALL: {json.dumps(modal_items, ensure_ascii=False)}"
        )
    if page_nav_items:
        lines.append(
            f"- Page navigations: {len(page_nav_items)} links — "
            f"{json.dumps(page_nav_items, ensure_ascii=False)}"
        )

    # Count page data elements
    images = page_data.get("images", [])
    if images:
        img_alts = [
            (img.get("alt") or img.get("src", "").split("/")[-1])[:40]
            for img in images[:20]
        ]
        lines.append(
            f"- Images: {len(images)} total — "
            f"test ALL: {json.dumps(img_alts, ensure_ascii=False)}"
        )

    buttons = page_data.get("buttons", [])
    if buttons:
        btn_texts = [(b.get("text") or "")[:30] for b in buttons[:15]]
        lines.append(f"- Buttons: {len(buttons)} — {json.dumps(btn_texts, ensure_ascii=False)}")

    forms = page_data.get("forms", [])
    if forms:
        total_fields = sum(len(f.get("fields", [])) for f in forms)
        lines.append(f"- Forms: {len(forms)} forms, {total_fields} total fields")

    if not lines:
        return "No element data available."

    header = (
        "**You MUST generate test steps for ALL elements listed below.**\n"
        "Do NOT test only 2-3 samples — cover EVERY item.\n"
    )
    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# Scenario relevance validation — user request ↔ generated scenario match
# ---------------------------------------------------------------------------

_TEST_INTENTS: dict[str, dict] = {
    "signup": {
        "label": "회원가입",
        "request_kw": [
            "회원가입", "signup", "sign up", "register", "가입",
            "계정 생성", "계정생성", "registration",
        ],
        "scenario_kw": [
            "회원가입", "signup", "register", "가입", "sign up",
            "이름", "name",
        ],
        "anti_kw": ["로그인", "login", "sign in", "signin"],
        "observation_kw": [
            "회원가입", "signup", "register", "가입", "sign up",
        ],
        "min_step_types": ["page_or_modal", "field_input", "submit"],
    },
    "login": {
        "label": "로그인",
        "request_kw": [
            "로그인", "login", "sign in", "signin", "로그 인",
            "인증", "authentication",
        ],
        "scenario_kw": [
            "로그인", "login", "sign in", "signin",
        ],
        "anti_kw": ["회원가입", "signup", "register", "가입"],
        "observation_kw": [
            "로그인", "login", "sign in",
        ],
        "min_step_types": ["page_or_modal", "field_input", "submit"],
    },
    "search": {
        "label": "검색",
        "request_kw": [
            "검색", "search", "찾기", "검색어", "서치",
        ],
        "scenario_kw": [
            "검색", "search", "찾기", "서치",
        ],
        "anti_kw": [],
        "observation_kw": [
            "검색", "search",
        ],
        "min_step_types": ["field_input"],
    },
    "payment": {
        "label": "결제",
        "request_kw": [
            "결제", "payment", "checkout", "구매", "주문",
            "pay", "purchase", "order",
        ],
        "scenario_kw": [
            "결제", "payment", "checkout", "구매", "주문",
        ],
        "anti_kw": [],
        "observation_kw": [
            "결제", "payment", "checkout", "구매", "주문", "장바구니", "cart",
        ],
        "min_step_types": ["page_or_modal"],
    },
    "cart": {
        "label": "장바구니",
        "request_kw": [
            "장바구니", "cart", "basket", "담기",
        ],
        "scenario_kw": [
            "장바구니", "cart", "basket", "담기",
        ],
        "anti_kw": [],
        "observation_kw": [
            "장바구니", "cart", "basket",
        ],
        "min_step_types": ["page_or_modal"],
    },
}


def _detect_intent(user_request: str) -> dict | None:
    """Detect the user's test intent from their request text."""
    req_lower = user_request.lower()
    for intent_key, intent in _TEST_INTENTS.items():
        for kw in intent["request_kw"]:
            if kw.lower() in req_lower:
                return {**intent, "key": intent_key}
    return None


def _check_feature_exists(
    intent: dict,
    observations: list[dict],
    page_data: dict | None,
) -> bool:
    """Check if the requested feature exists in observation/page data."""
    obs_kw = intent["observation_kw"]

    # Check observations
    for obs in observations:
        elem = obs.get("element", {})
        change = obs.get("observed_change", {})
        searchable = " ".join([
            (elem.get("text") or ""),
            (elem.get("selector") or ""),
            str(change.get("new_text", [])),
            str(obs.get("access_path", "")),
            str(change.get("navigated_page_fields", [])),
        ]).lower()
        for kw in obs_kw:
            if kw.lower() in searchable:
                return True

    # Check page data (nav menus, buttons, links, forms)
    if page_data:
        for section in ["nav_menus", "buttons", "links", "forms"]:
            for item in page_data.get(section, []):
                item_str = json.dumps(item, ensure_ascii=False).lower()
                for kw in obs_kw:
                    if kw.lower() in item_str:
                        return True

    return False


def _check_scenario_matches_intent(
    intent: dict,
    scenarios: list,
) -> dict:
    """Check if generated scenarios match the detected intent.

    Returns {"matches": bool, "has_anti_only": bool, "missing_steps": list}
    """
    scenario_kw = [k.lower() for k in intent["scenario_kw"]]
    anti_kw = [k.lower() for k in intent["anti_kw"]]
    min_steps = intent.get("min_step_types", [])

    # Collect all text from scenarios
    all_texts: list[str] = []
    has_field_input = False
    has_submit = False
    has_page_or_modal = False

    for sc in scenarios:
        steps = []
        if hasattr(sc, "steps"):
            sc_name = getattr(sc, "name", "") or ""
            sc_desc = getattr(sc, "description", "") or ""
            steps = sc.steps
        elif isinstance(sc, dict):
            sc_name = sc.get("name", "")
            sc_desc = sc.get("description", "")
            steps = sc.get("steps", [])
        else:
            continue

        all_texts.extend([sc_name, sc_desc])

        for step in steps:
            if hasattr(step, "action"):
                action = step.action.value if hasattr(
                    step.action, "value"
                ) else str(step.action)
                target_text = (
                    step.target.text if step.target else ""
                ) or ""
                value = step.value or ""
                desc = step.description or ""
            else:
                action = str(step.get("action", ""))
                target_obj = step.get("target")
                target_text = (
                    target_obj.get("text", "") if target_obj else ""
                )
                value = step.get("value", "")
                desc = step.get("description", "")

            all_texts.extend([target_text, value, desc])

            if action == "find_and_type":
                has_field_input = True
            if action == "find_and_click":
                # Check if this is a submit-like button
                click_text = target_text.lower()
                if any(w in click_text for w in [
                    "가입", "등록", "submit", "register", "로그인",
                    "login", "sign", "검색", "search", "결제",
                    "pay", "구매", "주문", "확인",
                ]):
                    has_submit = True
            if action in ("navigate", "find_and_click"):
                has_page_or_modal = True

    combined = " ".join(all_texts).lower()

    # Check if scenario contains intent keywords
    has_intent_kw = any(kw in combined for kw in scenario_kw)

    # Check if scenario ONLY contains anti-keywords (wrong test)
    has_anti_only = False
    if anti_kw and not has_intent_kw:
        has_anti = any(kw in combined for kw in anti_kw)
        if has_anti:
            has_anti_only = True

    # Check minimum step requirements
    missing: list[str] = []
    step_map = {
        "page_or_modal": has_page_or_modal,
        "field_input": has_field_input,
        "submit": has_submit,
    }
    for req in min_steps:
        if not step_map.get(req, False):
            missing.append(req)

    matches = has_intent_kw and not has_anti_only and len(missing) == 0

    return {
        "matches": matches,
        "has_anti_only": has_anti_only,
        "missing_steps": missing,
        "has_intent_kw": has_intent_kw,
    }


def validate_scenario_relevance(
    user_request: str,
    scenarios: list,
    observations: list[dict],
    page_data: dict | None = None,
) -> dict:
    """Validate that generated scenarios match the user's request.

    Returns:
        {
            "valid": bool,
            "confidence": float,
            "reason": str,
            "feature_missing": bool,
            "warnings": list[str],
        }
    """
    intent = _detect_intent(user_request)
    if intent is None:
        return {
            "valid": True,
            "confidence": 0.5,
            "reason": "",
            "feature_missing": False,
            "warnings": [],
        }

    label = intent["label"]

    # B) Check if feature exists in site data
    feature_exists = _check_feature_exists(intent, observations, page_data)
    if not feature_exists:
        return {
            "valid": False,
            "confidence": 0.9,
            "reason": f"사이트에서 '{label}' 기능을 찾지 못했습니다.",
            "feature_missing": True,
            "warnings": [
                f"'{label}' 기능을 사이트에서 찾지 못했습니다.",
                f"'{label}' 페이지가 별도 URL인 경우 해당 URL을 직접 입력해주세요.",
                "외부 서비스(Google, Kakao 등)를 통한 경우 자동 테스트가 어려울 수 있습니다.",
            ],
        }

    # A + C) Check scenario content
    if not scenarios:
        return {
            "valid": False,
            "confidence": 0.8,
            "reason": "시나리오가 생성되지 않았습니다.",
            "feature_missing": False,
            "warnings": [],
        }

    match_result = _check_scenario_matches_intent(intent, scenarios)

    if match_result["has_anti_only"]:
        return {
            "valid": False,
            "confidence": 0.9,
            "reason": (
                f"'{label}' 테스트를 요청했지만 "
                f"다른 기능의 시나리오가 생성되었습니다."
            ),
            "feature_missing": False,
            "warnings": [
                f"요청: '{label}' 테스트",
                "생성된 시나리오가 요청과 다른 기능을 테스트합니다.",
                "재생성을 시도합니다.",
            ],
        }

    if not match_result["matches"]:
        warnings: list[str] = []
        if not match_result["has_intent_kw"]:
            warnings.append(
                f"시나리오에 '{label}' 관련 키워드가 포함되어 있지 않습니다."
            )
        if match_result["missing_steps"]:
            step_names = {
                "page_or_modal": "페이지/모달 진입",
                "field_input": "필드 입력",
                "submit": "제출 버튼 클릭",
            }
            missing_names = [
                step_names.get(s, s) for s in match_result["missing_steps"]
            ]
            warnings.append(
                f"필수 스텝 누락: {', '.join(missing_names)}"
            )
        return {
            "valid": False,
            "confidence": 0.7,
            "reason": f"'{label}' 테스트의 필수 요건을 충족하지 않습니다.",
            "feature_missing": False,
            "warnings": warnings,
        }

    return {
        "valid": True,
        "confidence": 0.9,
        "reason": "",
        "feature_missing": False,
        "warnings": [],
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
        lnk for lnk in links
        if _matches(lnk.get("text", "")) or _matches(lnk.get("href", ""))
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
