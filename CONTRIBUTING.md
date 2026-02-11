# Contributing Guide

Thank you for contributing to AAT! This guide covers everything from setting up your development environment to submitting a PR.

[한국어 가이드](CONTRIBUTING.ko.md)

---

## Development Setup

### Prerequisites

- Python 3.11+
- Tesseract OCR (`brew install tesseract` or `apt-get install tesseract-ocr`)
- Git

### Installation

```bash
git clone https://github.com/ksgisang/AI-Watch-Tester.git
cd AI-Watch-Tester
make dev
```

`make dev` runs:

```makefile
dev:
    pip install -e ".[dev]"    # Install package + dev dependencies
    playwright install chromium # Install Chromium browser
    pre-commit install          # Install pre-commit hooks
```

### Virtual Environment (Recommended)

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
make dev
```

---

## Code Style

### ruff (Linter + Formatter)

The project uses ruff as its linter and formatter. Configuration is in `pyproject.toml`.

```toml
[tool.ruff]
target-version = "py311"
line-length = 99
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]
```

Key rules:

| Code | Description |
|------|-------------|
| `E`, `F` | pyflakes, pycodestyle basics |
| `I` | Import sorting (isort) |
| `N` | Naming conventions |
| `UP` | Upgrade to Python 3.11+ syntax |
| `B` | Bugbear (potential bugs) |
| `SIM` | Code simplification |
| `TCH` | TYPE_CHECKING block usage |

```bash
# Lint check
make lint

# Auto-format + auto-fix
make format
```

### mypy (Type Checking)

Runs in strict mode. All functions must have type annotations.

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
```

```bash
make typecheck
```

### pre-commit

Ruff lint and format run automatically on commit. Defined in `.pre-commit-config.yaml`.

```bash
# Manual run (all files)
pre-commit run --all-files
```

---

## Testing

### Running Tests

```bash
# All tests
make test

# With coverage
make test-cov
```

`make test-cov` generates both terminal and HTML reports (`htmlcov/`).

### Test Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"
```

- `asyncio_mode = "auto"` — Automatically detects async test functions. No `@pytest.mark.asyncio` decorator needed.
- `addopts = "-v --tb=short"` — Verbose output, short tracebacks.

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

### Test Writing Rules

- File name: `test_<module>.py`
- Function name: `test_<action>_<condition>_<expected>` (e.g., `test_match_with_low_confidence_returns_none`)
- Use fixtures: Define common setup in `conftest.py`.
- Mock external dependencies (APIs, browsers).

---

## PR Process

### 1. Create a Branch

```bash
git checkout -b feat/<feature>      # New feature
git checkout -b fix/<bug>           # Bug fix
git checkout -b refactor/<target>   # Refactoring
```

### 2. Develop and Verify

```bash
# After writing code
make format      # Format + auto-fix
make lint        # Lint check
make typecheck   # Type check
make test        # Tests
```

All four checks must pass before submitting a PR.

### 3. Commit

Commit message format:

```
<type>(<scope>): <subject>

<body>
```

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Refactoring (no behavior change) |
| `test` | Add/modify tests |
| `docs` | Documentation changes |
| `chore` | Build, CI, dependencies, etc. |

Example:

```
feat(matchers): add FeatureMatcher with ORB descriptor

Implements ORB-based feature matching for scale/rotation invariant matching.
```

### 4. Submit PR

- PR title follows the same format as commit messages.
- Describe changes, test methods, and related issues in the body.
- Attach screenshots or logs when possible.

---

## Architecture Overview

AAT follows a plugin-based architecture. Each module extends an ABC (Abstract Base Class) and is registered in a Registry.

### Plugin Structure

```
BaseEngine (ABC)         --> ENGINE_REGISTRY
├── WebEngine            (Playwright)
└── (future) DesktopEngine

BaseMatcher (ABC)        --> MATCHER_REGISTRY
├── TemplateMatcher      (cv2.matchTemplate)
├── OCRMatcher           (pytesseract)
├── FeatureMatcher       (ORB/SIFT)
└── HybridMatcher        (chain orchestrator)

AIAdapter (ABC)          --> ADAPTER_REGISTRY
└── ClaudeAdapter        (anthropic SDK)

BaseParser (ABC)         --> PARSER_REGISTRY
└── MarkdownParser

BaseReporter (ABC)       --> REPORTER_REGISTRY
└── MarkdownReporter     (Jinja2)
```

### Adding a New Plugin

1. Create a class extending the module's ABC.
2. Register it in the module's `__init__.py` Registry.
3. Write tests.

Example — Adding a new Matcher:

```python
# src/aat/matchers/my_matcher.py
from aat.matchers.base import BaseMatcher, MatchResult

class MyMatcher(BaseMatcher):
    name = "my_matcher"

    async def match(self, screenshot: bytes, target: MatchTarget) -> MatchResult | None:
        # Implementation
        ...
```

```python
# src/aat/matchers/__init__.py
from aat.matchers.my_matcher import MyMatcher

MATCHER_REGISTRY["my_matcher"] = MyMatcher
```

### Core Flow

1. **CLI** — Typer parses user commands.
2. **ScenarioLoader** — Converts YAML files to Pydantic models (`Scenario`).
3. **StepExecutor** — Runs each step in the scenario sequentially.
4. **Engine** — Controls the browser (navigate, click, type, etc.).
5. **Matcher** — Finds target UI element coordinates in screenshots.
6. **Comparator** — Compares expected vs actual results to determine Pass/Fail.
7. **DevQA Loop** — On failure, calls AI Adapter for a fix and re-runs.
8. **Reporter** — Generates Markdown reports from execution results.

---

## Make Commands

| Command | Description |
|---------|-------------|
| `make install` | Install runtime dependencies only |
| `make dev` | Full development environment setup |
| `make lint` | ruff lint check |
| `make format` | ruff format + auto-fix |
| `make typecheck` | mypy strict type check |
| `make test` | Run all pytest tests |
| `make test-cov` | pytest + coverage report |
| `make clean` | Clean caches and build artifacts |
