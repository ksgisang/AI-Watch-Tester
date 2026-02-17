# Contributing to AWT

Thank you for your interest in contributing! This guide covers everything you need to get started.

---

## Development Setup

### Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (`brew install tesseract` / `apt install tesseract-ocr`)
- Git

### Installation

```bash
git clone https://github.com/ksgisang/AI-Watch-Tester.git
cd AI-Watch-Tester
python -m venv .venv && source .venv/bin/activate
make dev
```

`make dev` will:

1. Install the package in editable mode with dev dependencies
2. Install Playwright Chromium browser
3. Set up pre-commit hooks

---

## Code Style

### ruff (Linter + Formatter)

```bash
make lint     # Check for issues
make format   # Auto-format + auto-fix
```

Key rules enforced: pyflakes, pycodestyle, import sorting, naming conventions, Python 3.11+ syntax, bugbear, and code simplification.

Configuration is in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py311"
line-length = 99

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]
```

### mypy (Type Checking)

Runs in **strict mode**. All functions must have type annotations.

```bash
make typecheck
```

### pre-commit

Ruff lint and format run automatically on every commit via `.pre-commit-config.yaml`.

```bash
# Run manually on all files
pre-commit run --all-files
```

---

## Testing

```bash
make test       # Run all tests
make test-cov   # Run with coverage report
```

### Test Writing Rules

- File name: `test_<module>.py`
- Function name: `test_<action>_<condition>_<expected>`
- Use fixtures from `conftest.py` for common setup
- Mock external dependencies (APIs, browsers)
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator needed

### Test Structure

```
tests/
├── conftest.py            # Shared fixtures
├── test_engine/           # Engine module tests
├── test_matchers/         # Matchers module tests
├── test_adapters/         # Adapters module tests
├── test_learning/         # Learning module tests
└── integration/           # Integration tests
```

---

## Pull Request Process

### 1. Create a Branch

```bash
git checkout -b feat/<feature>      # New feature
git checkout -b fix/<bug>           # Bug fix
git checkout -b refactor/<target>   # Refactoring
```

### 2. Verify Before Submitting

All four checks must pass:

```bash
make format      # Format + auto-fix
make lint        # Lint check
make typecheck   # Type check
make test        # Tests
```

### 3. Commit Message Format

```
<type>(<scope>): <subject>
```

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Refactoring (no behavior change) |
| `test` | Add/modify tests |
| `docs` | Documentation changes |
| `chore` | Build, CI, dependencies |

Example:

```
feat(matchers): add FeatureMatcher with ORB descriptor
```

### 4. Submit PR

- Keep the title short and descriptive
- Describe what changed and why in the body
- Attach screenshots or logs when relevant

---

## Architecture Overview

AWT uses a plugin-based architecture. Each module extends an ABC and is registered in a dictionary-based registry.

```
BaseEngine (ABC)         → ENGINE_REGISTRY
├── WebEngine            (Playwright)
└── DesktopEngine        (PyAutoGUI + Playwright)

BaseMatcher (ABC)        → MATCHER_REGISTRY
├── TemplateMatcher      (cv2.matchTemplate)
├── OCRMatcher           (pytesseract)
├── FeatureMatcher       (ORB/SIFT)
└── HybridMatcher        (chain orchestrator)

AIAdapter (ABC)          → ADAPTER_REGISTRY
├── ClaudeAdapter        (anthropic SDK)
├── OpenAIAdapter        (openai SDK)
└── OllamaAdapter        (httpx)

BaseParser (ABC)         → PARSER_REGISTRY
└── MarkdownParser

BaseReporter (ABC)       → REPORTER_REGISTRY
└── MarkdownReporter     (Jinja2)
```

### Adding a New Plugin

1. Create a class extending the module's ABC
2. Register it in the module's `__init__.py` registry
3. Write tests

```python
# src/aat/matchers/my_matcher.py
from aat.matchers.base import BaseMatcher, MatchResult

class MyMatcher(BaseMatcher):
    name = "my_matcher"

    async def match(self, screenshot: bytes, target: MatchTarget) -> MatchResult | None:
        ...
```

```python
# src/aat/matchers/__init__.py
from aat.matchers.my_matcher import MyMatcher

MATCHER_REGISTRY["my_matcher"] = MyMatcher
```

---

## Make Commands

| Command | Description |
|---------|-------------|
| `make dev` | Full development environment setup |
| `make lint` | ruff lint check |
| `make format` | ruff format + auto-fix |
| `make typecheck` | mypy strict type check |
| `make test` | Run all pytest tests |
| `make test-cov` | pytest + coverage report |
| `make clean` | Clean caches and build artifacts |
