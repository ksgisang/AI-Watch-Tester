"""Tests for POST/GET /api/tests endpoints."""

from __future__ import annotations

import io

import pytest
from app.models import Test, TestStatus
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Create test — mode=review (default) → GENERATING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_test_default_review(client: AsyncClient) -> None:
    """POST /api/tests (default mode=review) creates a GENERATING test."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["target_url"] == "https://example.com/"
    assert data["status"] == "generating"
    assert data["user_id"] == "test-uid-001"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_test_auto_mode(client: AsyncClient) -> None:
    """POST /api/tests with mode=auto creates a QUEUED test."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com", "mode": "auto"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_create_test_invalid_url(client: AsyncClient) -> None:
    """POST /api/tests with invalid URL returns 422."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "not-a-url"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_test_no_body(client: AsyncClient) -> None:
    """POST /api/tests with no body returns 422."""
    resp = await client.post("/api/tests")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List / Get tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tests_empty(client: AsyncClient) -> None:
    """GET /api/tests returns empty list initially."""
    resp = await client.get("/api/tests")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tests"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_tests_after_create(client: AsyncClient) -> None:
    """GET /api/tests returns created tests."""
    await client.post("/api/tests", json={"target_url": "https://a.com"})
    await client.post("/api/tests", json={"target_url": "https://b.com"})

    resp = await client.get("/api/tests")
    data = resp.json()
    assert data["total"] == 2
    assert len(data["tests"]) == 2
    # Newest first
    assert data["tests"][0]["target_url"] == "https://b.com/"


@pytest.mark.asyncio
async def test_list_tests_pagination(client: AsyncClient) -> None:
    """GET /api/tests supports pagination."""
    for i in range(3):
        await client.post("/api/tests", json={"target_url": f"https://{i}.com"})

    resp = await client.get("/api/tests", params={"page": 1, "page_size": 2})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["tests"]) == 2
    assert data["page"] == 1

    resp2 = await client.get("/api/tests", params={"page": 2, "page_size": 2})
    data2 = resp2.json()
    assert len(data2["tests"]) == 1


@pytest.mark.asyncio
async def test_get_test_by_id(client: AsyncClient) -> None:
    """GET /api/tests/{id} returns a single test."""
    create_resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    test_id = create_resp.json()["id"]

    resp = await client.get(f"/api/tests/{test_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_id


@pytest.mark.asyncio
async def test_get_test_not_found(client: AsyncClient) -> None:
    """GET /api/tests/{id} returns 404 for nonexistent test."""
    resp = await client.get("/api/tests/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helper: transition test to REVIEW in test DB
# ---------------------------------------------------------------------------

_VALID_YAML = """\
- id: SC-001
  name: Login test
  steps:
    - step: 1
      action: navigate
      value: https://example.com
      description: Open homepage
"""


async def _set_review(db: AsyncSession, test_id: int, yaml: str | None = None) -> None:
    """Transition a test to REVIEW status in the test DB session."""
    test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
    test.status = TestStatus.REVIEW
    if yaml is not None:
        test.scenario_yaml = yaml
    await db.commit()


# ---------------------------------------------------------------------------
# PUT /api/tests/{id}/scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_scenarios_in_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """PUT /scenarios succeeds when test is in REVIEW status."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    await _set_review(db_session, test_id, "initial yaml")

    resp = await client.put(
        f"/api/tests/{test_id}/scenarios",
        json={"scenario_yaml": _VALID_YAML},
    )
    assert resp.status_code == 200
    assert resp.json()["scenario_yaml"] == _VALID_YAML


@pytest.mark.asyncio
async def test_update_scenarios_wrong_status(client: AsyncClient) -> None:
    """PUT /scenarios returns 409 when test is not in REVIEW status."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    # Status is GENERATING (default), not REVIEW
    resp = await client.put(
        f"/api/tests/{test_id}/scenarios",
        json={"scenario_yaml": _VALID_YAML},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_scenarios_invalid_yaml(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """PUT /scenarios returns 422 for invalid YAML."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    await _set_review(db_session, test_id)

    resp = await client.put(
        f"/api/tests/{test_id}/scenarios",
        json={"scenario_yaml": ": invalid: [yaml"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/tests/{id}/approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_test(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /approve transitions REVIEW → QUEUED."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    await _set_review(db_session, test_id, _VALID_YAML)

    resp = await client.post(f"/api/tests/{test_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_approve_test_wrong_status(client: AsyncClient) -> None:
    """POST /approve returns 409 when test is not in REVIEW status."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    # Status is GENERATING, not REVIEW
    resp = await client.post(f"/api/tests/{test_id}/approve")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_approve_test_no_scenarios(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /approve returns 422 when no scenario_yaml exists."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]
    await _set_review(db_session, test_id)  # No yaml

    resp = await client.post(f"/api/tests/{test_id}/approve")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/tests/{id}/upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_md_file(client: AsyncClient) -> None:
    """POST /upload accepts .md file and extracts text."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]

    content = b"# Login Spec\n\nUser enters email and password."
    resp = await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("spec.md", io.BytesIO(content), "text/markdown")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "spec.md"
    assert data["size"] == len(content)
    assert data["extracted_chars"] > 0


@pytest.mark.asyncio
async def test_upload_txt_file(client: AsyncClient) -> None:
    """POST /upload accepts .txt file."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]

    content = b"Simple test specification"
    resp = await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("spec.txt", io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["extracted_chars"] == len(content.decode())


@pytest.mark.asyncio
async def test_upload_unsupported_type(client: AsyncClient) -> None:
    """POST /upload rejects unsupported file types."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]

    # .exe is not in _ALLOWED_EXTENSIONS
    resp = await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("malware.exe", io.BytesIO(b"\x00\x00"), "application/octet-stream")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_wrong_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /upload rejects uploads when test is not in GENERATING/REVIEW."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com", "mode": "auto"}
    )
    test_id = create_resp.json()["id"]
    # Status is QUEUED, not GENERATING/REVIEW

    resp = await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("spec.md", io.BytesIO(b"test"), "text/markdown")},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_upload_multiple_files_appends(client: AsyncClient) -> None:
    """Multiple uploads append to doc_text."""
    create_resp = await client.post(
        "/api/tests", json={"target_url": "https://example.com"}
    )
    test_id = create_resp.json()["id"]

    await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("a.md", io.BytesIO(b"First doc"), "text/markdown")},
    )
    await client.post(
        f"/api/tests/{test_id}/upload",
        files={"file": ("b.txt", io.BytesIO(b"Second doc"), "text/plain")},
    )

    # Verify doc_text contains both
    resp = await client.get(f"/api/tests/{test_id}")
    data = resp.json()
    assert "First doc" in (data["doc_text"] or "")
    assert "Second doc" in (data["doc_text"] or "")
