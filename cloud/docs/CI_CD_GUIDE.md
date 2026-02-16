# CI/CD Integration Guide

Run AWT Cloud tests from your CI/CD pipeline using the REST API.

## 1. Generate an API Key

1. Log in to AWT Cloud
2. Go to **Settings** > **API Keys**
3. Click **Generate**, copy the key (shown only once)

## 2. API Reference

### Create & Run Test

```bash
# Async mode — returns immediately with test ID
curl -X POST https://your-awt-cloud.com/api/v1/tests \
  -H "X-API-Key: awt_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "mode": "auto"}'

# Sync mode — waits until DONE/FAILED (up to 300s)
curl -X POST "https://your-awt-cloud.com/api/v1/tests?wait=true" \
  -H "X-API-Key: awt_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "mode": "auto"}'
```

### Check Test Status

```bash
curl https://your-awt-cloud.com/api/v1/tests/{test_id} \
  -H "X-API-Key: awt_your_key_here"
```

### Response Format

```json
{
  "id": 42,
  "status": "done",
  "target_url": "https://example.com",
  "result_json": "...",
  "steps_total": 5,
  "steps_completed": 5,
  "created_at": "2026-02-17T12:00:00Z",
  "updated_at": "2026-02-17T12:01:30Z"
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `generating` | AI is generating test scenarios |
| `review` | Scenarios ready for review |
| `queued` | Waiting for execution |
| `running` | Test in progress |
| `done` | Test completed successfully |
| `failed` | Test failed |

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 201 | Test created |
| 200 | Test retrieved |
| 401 | Invalid or missing API key |
| 408 | Timeout (wait mode only) |
| 429 | Rate limit exceeded |

## 3. GitHub Actions Example

```yaml
name: E2E Tests
on:
  push:
    branches: [main]
  pull_request:

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - name: Run AWT E2E Test
        env:
          AWT_API_KEY: ${{ secrets.AWT_API_KEY }}
          TARGET_URL: https://staging.example.com
        run: |
          RESPONSE=$(curl -sf -X POST "${{ vars.AWT_CLOUD_URL }}/api/v1/tests?wait=true" \
            -H "X-API-Key: $AWT_API_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"target_url\": \"$TARGET_URL\", \"mode\": \"auto\"}")

          STATUS=$(echo "$RESPONSE" | jq -r '.status')
          echo "Test status: $STATUS"

          if [ "$STATUS" != "done" ]; then
            echo "::error::E2E test failed"
            echo "$RESPONSE" | jq .
            exit 1
          fi
```

## 4. API Key Management

```bash
# List keys (requires JWT auth, not API key)
curl https://your-awt-cloud.com/api/keys \
  -H "Authorization: Bearer $JWT_TOKEN"

# Revoke a key
curl -X DELETE https://your-awt-cloud.com/api/keys/{key_id} \
  -H "Authorization: Bearer $JWT_TOKEN"
```

## 5. Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `AWT_API_TIMEOUT` | 300 | Wait mode timeout (seconds) |
| `AWT_RATE_LIMIT_FREE` | 5 | Monthly test limit (Free tier) |
| `AWT_RATE_LIMIT_PRO` | -1 | Monthly test limit (Pro tier, -1 = unlimited) |
