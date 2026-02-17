# Quick Start Guide

Get AWT running in under 5 minutes.

---

## Local Mode

### 1. Install

```bash
pip install aat-devqa
```

### 2. Configure AI Provider

Pick one of the supported providers:

**Ollama (Free, Local)**

```bash
# Install and start Ollama
brew install ollama    # macOS
ollama serve           # Start the server
ollama pull codellama  # Download the model
```

No API key needed. AWT connects to `http://localhost:11434` by default.

**OpenAI**

```bash
export OPENAI_API_KEY="sk-..."
```

**Anthropic (Claude)**

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Start AWT

```bash
aat serve
```

Open **http://localhost:9500** in your browser.

### 4. Run Your First Test

1. Enter the URL you want to test (e.g. `https://example.com`)
2. Click **Generate Scenarios** — AI analyzes the page and creates test steps
3. **Review** the generated scenarios, edit if needed
4. Click **Run Test** — watch the browser execute each step
5. View results with pass/fail status per step

### 5. View Results

After the test completes, AWT generates a detailed report with:

- Pass/fail status for each step
- Screenshots (before and after actions)
- Error details for failed steps
- AI-suggested fixes (if DevQA Loop is enabled)

---

## Cloud Mode

> Cloud mode is coming soon at [awt.dev](https://awt.dev).

### How It Will Work

1. **Sign up** at https://awt.dev
2. **Enter a URL** — the target site you want to test
3. **AI generates scenarios** — review and approve them
4. **Watch tests run** — live screenshot streaming in your browser
5. **View results** — detailed reports with full history

### Cloud Advantages

- No installation required
- Tests run on cloud infrastructure
- Real-time screenshot streaming
- Team collaboration and shared test history
- CI/CD integration with API keys

---

## CLI Quick Reference

| Command | Description |
|---------|-------------|
| `aat init` | Initialize project (creates `.aat/` config) |
| `aat config show` | Display current configuration |
| `aat config set <key> <value>` | Update a config value |
| `aat validate <scenario>` | Validate a YAML scenario file |
| `aat run <scenario>` | Run a single test scenario |
| `aat loop <scenario>` | Run DevQA Loop (fail → AI fix → retest) |
| `aat analyze <document>` | Analyze a document with AI |
| `aat generate <spec>` | Auto-generate scenarios from a spec |
| `aat start` | Interactive guided mode |
| `aat serve` | Start the web dashboard |

---

## Next Steps

- [API Reference](API_REFERENCE.md) — Full endpoint documentation
- [FAQ](FAQ.md) — Common questions and answers
- [CI/CD Guide](../cloud/docs/CI_CD_GUIDE.md) — Pipeline integration
