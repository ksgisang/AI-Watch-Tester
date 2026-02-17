# API Reference

AWT Cloud exposes a REST API for managing tests, API keys, and real-time events via WebSocket.

**Base URL:** `https://awt.dev` (cloud) or `http://localhost:8000` (local)

---

## Authentication

AWT supports two authentication methods:

### JWT Bearer Token (Supabase Auth)

```
Authorization: Bearer <token>
```

Obtain a token by signing up/in through Supabase Auth. Tokens are ES256/HS256 signed JWTs.

### API Key

```
X-API-Key: awt_xxxxxxxxxxxx
```

Generate API keys via the dashboard or `POST /api/keys`. Keys use the format `awt_<32-hex-chars>`.

> **Priority:** If both headers are present, API Key is checked first.

---

## Rate Limits

Rate limits are enforced on test creation endpoints (`POST /api/tests`, `POST /api/v1/tests`).

| Tier | Monthly Limit | Daily Limit |
|------|--------------|-------------|
| Free | 10 tests | — |
| Pro | 100 tests | 20 tests |

Response headers on rate-limited endpoints:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 2026-03-01T00:00:00+00:00
```

---

## Test Status Values

| Status | Description |
|--------|-------------|
| `generating` | AI is generating test scenarios |
| `review` | Scenarios ready for review/edit |
| `queued` | Approved, waiting for execution |
| `running` | Test in progress |
| `done` | Test completed successfully |
| `failed` | Test failed |

---

## Endpoints

### Health Check

#### `GET /health`

Simple health check for load balancers. No auth required.

```bash
curl https://awt.dev/health
```

```json
{
  "status": "ok"
}
```

#### `GET /api/health`

Detailed health check with DB, worker, and AI provider status. No auth required.

```bash
curl https://awt.dev/api/health
```

#### `GET /api/worker/status`

Background worker status. No auth required.

```bash
curl https://awt.dev/api/worker/status
```

```json
{
  "running": true,
  "active_tests": 1,
  "max_concurrent": 3
}
```

---

### Tests

#### `POST /api/tests`

Create a new test. AI will generate scenarios for the target URL.

**Auth:** JWT or API Key

```bash
curl -X POST https://awt.dev/api/tests \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "mode": "review"}'
```

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `target_url` | string | Yes | — | URL to test |
| `mode` | string | No | `"review"` | `"review"` (pause for approval) or `"auto"` (run immediately) |

**Response:** `201 Created`

```json
{
  "id": 1,
  "user_id": "uuid-string",
  "target_url": "https://example.com",
  "status": "generating",
  "result_json": null,
  "scenario_yaml": null,
  "doc_text": null,
  "error_message": null,
  "steps_total": 0,
  "steps_completed": 0,
  "created_at": "2026-02-17T12:00:00Z",
  "updated_at": "2026-02-17T12:00:00Z"
}
```

**Error Responses:**

| Status | Description |
|--------|-------------|
| 401 | Invalid or missing authentication |
| 429 | Rate limit exceeded |
| 503 | Supabase not configured |

---

#### `GET /api/tests`

List your tests with pagination.

**Auth:** JWT or API Key

```bash
curl "https://awt.dev/api/tests?page=1&page_size=20" \
  -H "Authorization: Bearer <token>"
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number (min: 1) |
| `page_size` | int | 20 | Items per page (1–100) |

**Response:** `200 OK`

```json
{
  "tests": [
    {
      "id": 1,
      "user_id": "uuid-string",
      "target_url": "https://example.com",
      "status": "done",
      "result_json": "...",
      "scenario_yaml": "...",
      "doc_text": null,
      "error_message": null,
      "steps_total": 5,
      "steps_completed": 5,
      "created_at": "2026-02-17T12:00:00Z",
      "updated_at": "2026-02-17T12:01:30Z"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

---

#### `GET /api/tests/{test_id}`

Get details of a specific test.

**Auth:** JWT or API Key

```bash
curl https://awt.dev/api/tests/1 \
  -H "Authorization: Bearer <token>"
```

**Response:** `200 OK`

```json
{
  "id": 1,
  "user_id": "uuid-string",
  "target_url": "https://example.com",
  "status": "done",
  "result_json": "{...}",
  "scenario_yaml": "id: SC-001\nname: ...",
  "doc_text": null,
  "error_message": null,
  "steps_total": 5,
  "steps_completed": 5,
  "created_at": "2026-02-17T12:00:00Z",
  "updated_at": "2026-02-17T12:01:30Z"
}
```

| Status | Description |
|--------|-------------|
| 404 | Test not found or belongs to another user |

---

#### `PUT /api/tests/{test_id}/scenarios`

Edit scenarios before approving. Test must be in `review` status.

**Auth:** JWT or API Key

```bash
curl -X PUT https://awt.dev/api/tests/1/scenarios \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"scenario_yaml": "id: SC-001\nname: Login test\nsteps:\n  - step: 1\n    action: navigate\n    value: /login"}'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario_yaml` | string | Yes | Valid YAML scenario content |

**Response:** `200 OK` (updated TestResponse)

| Status | Description |
|--------|-------------|
| 409 | Test is not in `review` status |
| 422 | Invalid YAML or scenario validation error |

---

#### `POST /api/tests/{test_id}/approve`

Approve scenarios and queue the test for execution. Test must be in `review` status.

**Auth:** JWT or API Key

```bash
curl -X POST https://awt.dev/api/tests/1/approve \
  -H "Authorization: Bearer <token>"
```

**Response:** `200 OK` (TestResponse with `status: "queued"`)

| Status | Description |
|--------|-------------|
| 409 | Test is not in `review` status |
| 422 | No scenarios to approve |

---

#### `POST /api/tests/{test_id}/upload`

Upload a document (PDF, DOCX, MD, TXT) to provide context for scenario generation. Test must be in `generating` or `review` status.

**Auth:** JWT or API Key

```bash
curl -X POST https://awt.dev/api/tests/1/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@spec.pdf"
```

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | binary | Yes | Document file (.md, .txt, .pdf, .docx) |

**Limits:** Max 10 MB per file.

**Response:** `200 OK`

```json
{
  "filename": "spec.pdf",
  "size": 245760,
  "extracted_chars": 12500
}
```

| Status | Description |
|--------|-------------|
| 409 | Test is not in `generating` or `review` status |
| 413 | File exceeds size limit |
| 422 | Unsupported file type or text extraction error |

---

### WebSocket

#### `WS /api/tests/{test_id}/ws`

Real-time test progress events via WebSocket.

**Auth:** None (public)

```javascript
const ws = new WebSocket("wss://awt.dev/api/tests/1/ws");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.event, data);
};
```

**Events:**

| Event | Description |
|-------|-------------|
| `test_start` | Test execution started |
| `scenarios_generated` | AI finished generating scenarios |
| `step_start` | A test step is starting |
| `step_done` | A test step completed successfully |
| `step_fail` | A test step failed |
| `test_complete` | All steps finished successfully |
| `test_fail` | Test failed |

---

### API Keys

#### `POST /api/keys`

Generate a new API key. **JWT auth only** (API keys cannot create other keys).

**Auth:** JWT only

```bash
curl -X POST https://awt.dev/api/keys \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "CI Pipeline"}'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Label for the key |

**Response:** `201 Created`

```json
{
  "id": 1,
  "key": "awt_a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "prefix": "awt_a1b2",
  "name": "CI Pipeline",
  "created_at": "2026-02-17T12:00:00Z"
}
```

> **Important:** The full `key` value is shown **only once**. Store it securely.

---

#### `GET /api/keys`

List your API keys. Only prefixes are returned (not full keys).

**Auth:** JWT or API Key

```bash
curl https://awt.dev/api/keys \
  -H "Authorization: Bearer <token>"
```

**Response:** `200 OK`

```json
[
  {
    "id": 1,
    "prefix": "awt_a1b2",
    "name": "CI Pipeline",
    "created_at": "2026-02-17T12:00:00Z",
    "last_used_at": "2026-02-17T14:30:00Z"
  }
]
```

---

#### `DELETE /api/keys/{key_id}`

Revoke an API key.

**Auth:** JWT or API Key (owner only)

```bash
curl -X DELETE https://awt.dev/api/keys/1 \
  -H "Authorization: Bearer <token>"
```

**Response:** `204 No Content`

| Status | Description |
|--------|-------------|
| 404 | Key not found or belongs to another user |

---

### CI/CD API (v1)

#### `POST /api/v1/tests`

Create and optionally wait for a test to complete. Designed for CI/CD pipelines.

**Auth:** API Key (recommended) or JWT

```bash
# Async — returns immediately
curl -X POST https://awt.dev/api/v1/tests \
  -H "X-API-Key: awt_your_key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://staging.example.com", "mode": "auto"}'

# Sync — waits until done or failed
curl -X POST "https://awt.dev/api/v1/tests?wait=true" \
  -H "X-API-Key: awt_your_key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://staging.example.com", "mode": "auto"}'
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `wait` | bool | false | Wait for test completion (blocks up to 300s) |

**Request Body:** Same as `POST /api/tests`

**Response (async, wait=false):** `201 Created` (TestResponse)

**Response (sync, wait=true):** `200 OK` (TestResponse with final status)

| Status | Description |
|--------|-------------|
| 408 | Timeout — test did not complete within the wait period |

---

#### `GET /api/v1/tests/{test_id}`

Retrieve test results. Same as `GET /api/tests/{test_id}`.

**Auth:** API Key or JWT

```bash
curl https://awt.dev/api/v1/tests/1 \
  -H "X-API-Key: awt_your_key"
```

**Response:** `200 OK` (TestResponse)

---

## Error Format

All errors return a JSON object with a `detail` field:

```json
{
  "detail": "Test not found"
}
```

## Status Code Summary

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 204 | No Content (successful delete) |
| 401 | Unauthorized |
| 404 | Not Found |
| 408 | Request Timeout (sync wait) |
| 409 | Conflict (wrong test status) |
| 413 | Payload Too Large |
| 422 | Unprocessable Entity (validation) |
| 429 | Too Many Requests (rate limit) |
| 503 | Service Unavailable |
