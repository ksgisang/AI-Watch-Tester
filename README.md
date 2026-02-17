<p align="center">
  <br/>
  <strong>AWT — AI Watch Tester</strong>
  <br/>
  <em>AI-powered E2E testing — just enter a URL, AI does the rest.</em>
  <br/><br/>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/ksgisang/AI-Watch-Tester/actions"><img src="https://img.shields.io/github/actions/workflow/status/ksgisang/AI-Watch-Tester/ci.yml?label=tests" alt="Tests"></a>
  <a href="https://github.com/ksgisang/AI-Watch-Tester/stargazers"><img src="https://img.shields.io/github/stars/ksgisang/AI-Watch-Tester?style=flat" alt="GitHub Stars"></a>
</p>

---

## Demo

<p align="center">
  <img src="https://via.placeholder.com/800x400?text=Demo+Coming+Soon" alt="AWT Demo" width="800">
  <br/>
  <em>Watch AI generate test scenarios, execute them, and report results — all from a single URL.</em>
</p>

---

## Features

- **AI-Powered Scenario Generation** — OpenAI, Claude, or Ollama analyze your app and generate E2E test scenarios automatically
- **Real Browser Testing** — Playwright drives a real Chromium browser with humanized mouse movements and typing
- **Self-Healing DevQA Loop** — When tests fail, AI analyzes the failure, fixes the code, and re-runs
- **Cloud or Local** — Cloud mode (no install, browser-based) or Local mode (full visibility, real browser)
- **CI/CD API** — One-line integration with GitHub Actions, GitLab CI, or any pipeline
- **Document-Based Generation** — Upload PDF/DOCX/MD specs and AI generates test scenarios from them
- **i18n Ready** — Multi-language support for the web dashboard

---

## Quick Start

### Cloud (No Install)

```
1. Visit https://awt.dev (coming soon)
2. Sign up → Enter URL → Watch AI test your site
```

### Local

```bash
pip install aat-devqa
aat serve
# Open http://localhost:9500
```

### CI/CD

```bash
curl -X POST https://awt.dev/api/v1/tests?wait=true \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://your-staging.com", "mode": "auto"}'
```

---

## How It Works

```
1. Enter your target URL
       ↓
2. AI analyzes the page and generates E2E test scenarios
       ↓
3. Review and edit scenarios (or skip with Quick Test)
       ↓
4. Watch AI execute tests with live screenshots
       ↓
5. Get detailed results with pass/fail per step
```

If a test fails, the **DevQA Loop** kicks in: AI reads the failure, suggests or applies a fix, and re-runs — automatically.

---

## Cloud vs Local

|  | Cloud | Local |
|---|-------|-------|
| **Install** | Not required | `pip install aat-devqa` |
| **Run** | Browser | `aat serve` |
| **Observe** | Live screenshot streaming | Real browser + mouse movement |
| **Best for** | CI/CD, teams, quick trial | Debugging, scenario development |

---

## Supported AI Providers

| Provider | Models | Setup |
|----------|--------|-------|
| **Ollama** | codellama, llama3 | `ollama serve` (free, local) |
| **OpenAI** | gpt-4o, gpt-4o-mini | `OPENAI_API_KEY=sk-...` |
| **Anthropic** | claude-sonnet | `ANTHROPIC_API_KEY=sk-ant-...` |

---

## Development

### Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (`brew install tesseract` / `apt install tesseract-ocr`)
- Git

### Setup

```bash
git clone https://github.com/ksgisang/AI-Watch-Tester.git
cd AI-Watch-Tester
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest
```

Or use the Makefile shortcut:

```bash
make dev    # install + playwright + pre-commit
make test   # run all tests
make lint   # ruff check
```

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Setting up the dev environment
- Code style (ruff, mypy strict)
- Writing tests
- Submitting pull requests

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Documentation

- [Quick Start Guide](docs/QUICK_START.md) — Install, configure, and run your first test
- [API Reference](docs/API_REFERENCE.md) — Full REST API and WebSocket documentation
- [FAQ](docs/FAQ.md) — Common questions and answers
- [CI/CD Integration Guide](cloud/docs/CI_CD_GUIDE.md) — Pipeline setup with GitHub Actions
- [Backup & Recovery](cloud/BACKUP_RECOVERY.md) — Database and file backup
- [Cloud Backend](cloud/README.md) — Self-hosting the cloud backend
