# AAT (AI Auto Tester)

**AI-Powered DevQA Loop Orchestrator**

> Automates UI testing with image matching. When tests fail, AI analyzes the failure, fixes the code, and re-runs — in a continuous loop.

[한국어 README](README.ko.md)

| | |
|---|---|
| Package | `aat-devqa` |
| Version | `0.2.0` |
| Python | `>= 3.11` |
| License | AGPL-3.0-only |
| Status | Ultra-MVP |

---

## Key Features

- **Image Matching Pipeline** — Combines Template, OCR, Feature, and Hybrid matchers to locate UI elements.
- **DevQA Loop** — When a test fails, AI (Claude) analyzes the root cause, patches the code, and re-tests automatically.
- **YAML Scenarios** — Write test scenarios declaratively in YAML.
- **Plugin Architecture** — Engine, Matcher, Adapter, Parser, and Reporter are all swappable plugins.
- **Humanized Actions** — Bezier curve mouse movements and variable-speed typing to avoid bot detection.
- **Learning DB** — Stores successful match history in SQLite for faster re-matching.

---

## Architecture

```
CLI (Typer)
 |
 v
+------------------+     +------------------+
|  ScenarioLoader  |---->|   StepExecutor   |
|  (YAML parsing)  |     |  (step runner)   |
+------------------+     +--------+---------+
                                  |
                    +-------------+-------------+
                    |             |              |
               +----+----+  +----+----+  +------+------+
               | Engine  |  | Matcher |  | Comparator  |
               | (Web)   |  | (Hybrid)|  | (assertion) |
               +---------+  +---------+  +-------------+
                    |
                    v
            +-------+--------+
            |   DevQA Loop   |
            | (fail -> AI    |
            |  fix -> rerun) |
            +-------+--------+
                    |
          +---------+---------+
          |                   |
     +----+----+       +-----+-----+
     |   AI    |       | Reporter  |
     | Adapter |       | (Markdown)|
     +---------+       +-----------+
     Claude|OpenAI|Ollama
```

---

## Installation

### pip

```bash
pip install aat-devqa
```

### Development Setup

```bash
git clone https://github.com/ksgisang/AI-Watch-Tester.git
cd AI-Watch-Tester
make dev
```

`make dev` will:

1. Install the package in editable mode (`pip install -e ".[dev]"`)
2. Install Playwright Chromium browser
3. Set up pre-commit hooks

### System Dependencies

Tesseract OCR engine is required by pytesseract:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr
```

---

## Quick Start

### 1. Initialize Project

```bash
aat init
```

Creates `.aat/` directory with a default `config.yaml`.

### 2. Check Configuration

```bash
aat config show
```

### 3. Set API Key

```bash
export AAT_AI_API_KEY="sk-ant-..."
# or
aat config set ai.api_key "sk-ant-..."
```

### 4. Write a Scenario

Create a YAML file in `scenarios/`:

```yaml
id: "SC-001"
name: "User login flow"
description: "Test login with valid credentials"
tags: ["login", "smoke"]

steps:
  - step: 1
    action: navigate
    value: "{{url}}/login"
    description: "Navigate to login page"

  - step: 2
    action: find_and_click
    target:
      image: "assets/buttons/login_button.png"
      text: "Login"
    description: "Click login button"
    humanize: true
    screenshot_after: true

  - step: 3
    action: assert
    assert_type: url_contains
    value: "/dashboard"
    description: "Verify redirect to dashboard"
    timeout_ms: 10000

expected_result:
  - type: text_visible
    value: "Welcome"
  - type: url_contains
    value: "/dashboard"
```

### 5. Validate Scenario

```bash
aat validate scenarios/SC-001_login.yaml
```

### 6. Run a Test

```bash
aat run scenarios/SC-001_login.yaml
```

### 7. Run DevQA Loop

```bash
aat loop scenarios/SC-001_login.yaml --max-iterations 5
```

When a test fails, AI analyzes the failure, fixes the code, and re-runs. Use `--max-iterations` to limit loop count.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `aat init` | Initialize project (`.aat/` directory, default config) |
| `aat config show` | Display current configuration |
| `aat config set <key> <value>` | Update a config value |
| `aat validate <scenario>` | Validate scenario YAML syntax and structure |
| `aat run <scenario>` | Run a single test scenario |
| `aat loop <scenario>` | Run DevQA loop (fail -> AI fix -> retest) |
| `aat learn add <data>` | Add match data to learning DB |
| `aat analyze <document>` | Analyze a document with AI |
| `aat generate <spec>` | Auto-generate scenarios with AI |

---

## Configuration

After `aat init`, a `.aat/config.yaml` file is created. Settings can also be overridden via environment variables.

| Config Key | Env Variable | Default | Description |
|------------|-------------|---------|-------------|
| `ai.provider` | `AAT_AI_PROVIDER` | `claude` | AI adapter: `claude`, `openai`, or `ollama` |
| `ai.api_key` | `AAT_AI_API_KEY` | -- | API key (Claude/OpenAI) or Ollama URL |
| `ai.model` | `AAT_AI_MODEL` | `claude-sonnet-4-20250514` | Model to use (e.g. `gpt-4o`, `codellama:7b`) |
| `engine.type` | `AAT_ENGINE_TYPE` | `web` | Engine type (currently web only) |
| `engine.headless` | `AAT_ENGINE_HEADLESS` | `false` | Headless mode |
| `matching.confidence_threshold` | `AAT_MATCHING_CONFIDENCE` | `0.85` | Minimum match confidence (0.0-1.0) |

```bash
# Set API key via environment variable
export AAT_AI_API_KEY="sk-ant-..."

# Update config via CLI
aat config set matching.confidence_threshold 0.85
```

---

## Project Structure

```
AI-Watch-Tester/
├── pyproject.toml
├── Makefile
├── README.md                        # English
├── README.ko.md                     # Korean
├── CONTRIBUTING.md
├── .pre-commit-config.yaml
├── .gitignore
│
├── src/aat/
│   ├── __init__.py                  # __version__
│   ├── cli/                         # CLI (Typer)
│   │   ├── main.py                  # Entry point
│   │   └── commands/                # Command modules
│   │
│   ├── core/                        # Core logic
│   │   ├── models.py                # Pydantic models, Enums
│   │   ├── config.py                # pydantic-settings config
│   │   ├── exceptions.py            # Exception hierarchy
│   │   ├── loop.py                  # DevQA Loop orchestrator
│   │   └── scenario_loader.py       # YAML -> Scenario
│   │
│   ├── engine/                      # Test engine (plugin)
│   │   ├── base.py                  # BaseEngine ABC
│   │   ├── web.py                   # WebEngine (Playwright)
│   │   ├── executor.py              # StepExecutor
│   │   ├── humanizer.py             # Humanized actions
│   │   ├── waiter.py                # Polling + stability detection
│   │   └── comparator.py            # Expected result evaluation
│   │
│   ├── matchers/                    # Image matching (plugin)
│   │   ├── base.py                  # BaseMatcher ABC
│   │   ├── template.py              # TemplateMatcher (cv2)
│   │   ├── ocr.py                   # OCRMatcher (pytesseract)
│   │   ├── feature.py               # FeatureMatcher (ORB/SIFT)
│   │   └── hybrid.py                # HybridMatcher (chain)
│   │
│   ├── adapters/                    # AI Adapter (plugin)
│   │   ├── base.py                  # AIAdapter ABC
│   │   ├── claude.py                # ClaudeAdapter
│   │   ├── openai_adapter.py        # OpenAIAdapter
│   │   └── ollama.py                # OllamaAdapter
│   │
│   ├── parsers/                     # Document parser (plugin)
│   │   ├── base.py                  # BaseParser ABC
│   │   └── markdown_parser.py       # MarkdownParser
│   │
│   ├── reporters/                   # Report generator (plugin)
│   │   ├── base.py                  # BaseReporter ABC
│   │   └── markdown.py              # MarkdownReporter
│   │
│   └── learning/                    # Learning DB
│       ├── store.py                 # LearnedStore (SQLite)
│       └── matcher.py               # LearnedMatcher
│
├── tests/
│   ├── conftest.py                  # Shared fixtures
│   ├── test_engine/
│   ├── test_matchers/
│   ├── test_adapters/
│   ├── test_learning/
│   └── integration/
│
└── scenarios/
    └── examples/
        └── SC-001_login.yaml
```

---

## Dependencies

### Runtime

| Package | Purpose |
|---------|---------|
| `typer[all] >=0.9` | CLI framework |
| `pydantic >=2.5` / `pydantic-settings >=2.1` | Data models, config management |
| `pyyaml >=6.0` | YAML scenario parsing |
| `playwright >=1.40` | Web browser automation engine |
| `opencv-python-headless >=4.8` | Template matching, feature matching |
| `numpy >=1.24` | Image array operations |
| `pillow >=10.0` | Image loading/conversion |
| `pytesseract >=0.3.10` | OCR (text recognition) |
| `anthropic >=0.40` | Claude API client |
| `openai >=1.0` | OpenAI GPT API client |
| `httpx >=0.27` | HTTP client (Ollama) |
| `jinja2 >=3.1` | Report template rendering |
| `rich >=13.0` | Terminal output formatting |

### Development

| Package | Purpose |
|---------|---------|
| `ruff >=0.4` | Linter + formatter |
| `mypy >=1.8` | Static type checking (strict mode) |
| `pytest >=8.0` | Test framework |
| `pytest-asyncio >=0.23` | Async test support |
| `pytest-cov >=4.0` | Coverage measurement |
| `pytest-mock >=3.12` | Mock utilities |
| `pre-commit >=3.6` | Git hook automation |
| `types-PyYAML >=6.0` | PyYAML type stubs |

---

## License

This project is licensed under [AGPL-3.0-only](https://www.gnu.org/licenses/agpl-3.0.html).
