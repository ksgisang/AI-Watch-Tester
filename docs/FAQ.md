# Frequently Asked Questions

## What is AWT?

AWT (AI Watch Tester) is an AI-powered end-to-end testing tool. You give it a URL, and AI generates test scenarios, executes them in a real browser, and reports the results. If a test fails, the DevQA Loop can automatically analyze the failure and re-run.

## How is AWT different from Playwright/Cypress?

Playwright and Cypress are browser automation *frameworks* — you write test code manually. AWT is a testing *orchestrator* that uses AI to:

- **Generate** test scenarios automatically from a URL or document
- **Execute** them using Playwright under the hood
- **Self-heal** via the DevQA Loop (AI analyzes failures and retries)

Think of it this way: Playwright is the engine, AWT is the driver.

## Which AI providers are supported?

| Provider | Models | Cost |
|----------|--------|------|
| **Ollama** | codellama, llama3, etc. | Free (runs locally) |
| **OpenAI** | gpt-4o, gpt-4o-mini | Pay per token |
| **Anthropic** | claude-sonnet | Pay per token |

Ollama is recommended for getting started since it's free and runs entirely on your machine.

## Is AWT free? What are the pricing tiers?

**Local mode** is free and open source (MIT License). Run it on your own machine with no limits.

**Cloud mode** (coming soon) will have:

| Tier | Monthly Tests | Price |
|------|--------------|-------|
| Free | 10 | $0 |
| Pro | 100 | TBD |

## Can I use AWT in CI/CD?

Yes. Use the REST API with an API key:

```bash
curl -X POST "https://awt.dev/api/v1/tests?wait=true" \
  -H "X-API-Key: awt_your_key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://staging.example.com", "mode": "auto"}'
```

The `?wait=true` parameter makes it synchronous — the request blocks until the test finishes, so your pipeline can check the result and fail the build if needed.

See the [CI/CD Guide](../cloud/docs/CI_CD_GUIDE.md) for GitHub Actions examples.

## Can I test localhost URLs?

**Local mode:** Yes, AWT runs on your machine and can access `localhost` directly.

**Cloud mode:** Not directly. Cloud tests run on remote servers that cannot reach your local network. You would need to expose your local server via a tunnel (e.g. ngrok) or deploy to a staging environment.

## What browsers does AWT support?

AWT uses **Playwright** as its browser engine, which supports:

- **Chromium** (default)
- Firefox and WebKit are supported by Playwright but not yet enabled in AWT

AWT also offers two engine modes:

| Engine | Description |
|--------|-------------|
| **WebEngine** | Playwright-only. Controls the browser viewport. Default. |
| **DesktopEngine** | PyAutoGUI + Playwright. OS-level mouse/keyboard with full screen capture. |

## How does the DevQA Loop work?

The DevQA Loop is an automated test-fix-retest cycle:

```
1. Run test scenario
       ↓
2. Test fails
       ↓
3. AI analyzes the failure (screenshots, error logs, page state)
       ↓
4. AI suggests or applies a code fix
       ↓
5. Re-run the test
       ↓
6. Repeat until pass or max iterations reached
```

Use it via CLI:

```bash
aat loop scenarios/SC-001_login.yaml --max-iterations 5
```

## Can I self-host AWT?

Yes. AWT is fully open source. For the cloud backend:

```bash
cd cloud
pip install -r requirements.txt
export AWT_SUPABASE_JWT_SECRET="your-secret"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For the frontend:

```bash
cd cloud/frontend
npm install && npm run build && npm start
```

See [cloud/README.md](../cloud/README.md) for full setup instructions including Supabase Auth configuration.

## Is AWT open source? What license?

Yes, AWT is open source under the **MIT License**. You can use, modify, and distribute it freely. See the [LICENSE](../LICENSE) file for details.

Contributions are welcome — check [CONTRIBUTING.md](../CONTRIBUTING.md) to get started.
