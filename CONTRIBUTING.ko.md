# 기여 가이드

AAT 프로젝트에 기여해 주셔서 감사합니다. 이 문서는 개발 환경 설정부터 PR 제출까지의 과정을 설명합니다.

---

## 개발 환경 설정

### 필수 조건

- Python 3.11 이상
- Tesseract OCR (`brew install tesseract` 또는 `apt-get install tesseract-ocr`)
- Git

### 설치

```bash
git clone <repo-url> && cd AI_Auto_Tester
make dev
```

`make dev`는 다음을 수행한다:

```makefile
dev:
    pip install -e ".[dev]"    # 패키지 + 개발 의존성 설치
    playwright install chromium # Chromium 브라우저 설치
    pre-commit install          # pre-commit 훅 설치
```

### 가상 환경 (권장)

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
make dev
```

---

## 코드 스타일

### ruff (린터 + 포매터)

프로젝트는 ruff를 린터와 포매터로 사용한다. 설정은 `pyproject.toml`에 정의되어 있다.

```toml
[tool.ruff]
target-version = "py311"
line-length = 99
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]
```

주요 규칙:

| 코드 | 설명 |
|------|------|
| `E`, `F` | pyflakes, pycodestyle 기본 규칙 |
| `I` | import 정렬 (isort) |
| `N` | 네이밍 컨벤션 |
| `UP` | Python 3.11+ 문법으로 업그레이드 |
| `B` | bugbear (잠재적 버그) |
| `SIM` | 코드 단순화 |
| `TCH` | TYPE_CHECKING 블록 사용 |

```bash
# 린트 검사
make lint

# 자동 포맷 + 자동 수정
make format
```

### mypy (타입 검사)

strict 모드로 동작한다. 모든 함수에 타입 힌트를 작성해야 한다.

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

커밋 시 ruff 린트와 포맷이 자동으로 실행된다. `.pre-commit-config.yaml`에 정의되어 있다.

```bash
# 수동 실행 (전체 파일)
pre-commit run --all-files
```

---

## 테스트

### 테스트 실행

```bash
# 전체 테스트
make test

# 커버리지 포함
make test-cov
```

`make test-cov`는 터미널 리포트와 HTML 리포트(`htmlcov/`)를 모두 생성한다.

### 테스트 설정

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"
```

- `asyncio_mode = "auto"` -- async 테스트 함수를 자동으로 감지한다. `@pytest.mark.asyncio` 데코레이터가 필요 없다.
- `addopts = "-v --tb=short"` -- 상세 출력, 짧은 트레이스백.

### 테스트 구조

```
tests/
├── conftest.py            # 공통 fixtures
├── test_engine/           # engine 모듈 테스트
├── test_matchers/         # matchers 모듈 테스트
├── test_adapters/         # adapters 모듈 테스트
├── test_learning/         # learning 모듈 테스트
└── integration/           # 통합 테스트
```

### 테스트 작성 규칙

- 파일명: `test_<모듈명>.py`
- 함수명: `test_<동작>_<조건>_<기대결과>` (예: `test_match_with_low_confidence_returns_none`)
- fixture 활용: 공통 setup은 `conftest.py`에 정의한다.
- 외부 의존성(API, 브라우저)은 mock으로 대체한다.

---

## PR 프로세스

### 1. 브랜치 생성

```bash
git checkout -b feat/<기능명>    # 기능 추가
git checkout -b fix/<버그명>     # 버그 수정
git checkout -b refactor/<대상>  # 리팩토링
```

### 2. 개발 및 검증

```bash
# 코드 작성 후
make format      # 포맷 + 린트 자동 수정
make lint        # 린트 검사
make typecheck   # 타입 검사
make test        # 테스트
```

네 가지 검사를 모두 통과해야 PR을 제출할 수 있다.

### 3. 커밋

커밋 메시지 형식:

```
<type>(<scope>): <subject>

<body>
```

| type | 설명 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `test` | 테스트 추가/수정 |
| `docs` | 문서 변경 |
| `chore` | 빌드, CI, 의존성 등 |

예시:

```
feat(matchers): add FeatureMatcher with ORB descriptor

ORB 기반 특징점 매칭을 구현한다. 스케일/회전 변환에 강건한 매칭이 가능해진다.
```

### 4. PR 제출

- PR 제목은 커밋 메시지와 동일한 형식을 따른다.
- 변경 내용, 테스트 방법, 관련 이슈를 본문에 기술한다.
- 가능하면 스크린샷이나 로그를 첨부한다.

---

## 아키텍처 개요

AAT는 플러그인 기반 아키텍처를 따른다. 각 모듈은 ABC(추상 기본 클래스)를 상속받아 구현하며, Registry에 등록하여 사용한다.

### 플러그인 구조

```
BaseEngine (ABC)         --> ENGINE_REGISTRY
├── WebEngine            (Playwright)
└── (향후) DesktopEngine

BaseMatcher (ABC)        --> MATCHER_REGISTRY
├── TemplateMatcher      (cv2.matchTemplate)
├── OCRMatcher           (pytesseract)
├── FeatureMatcher       (ORB/SIFT)
└── HybridMatcher        (체인 오케스트레이터)

AIAdapter (ABC)          --> ADAPTER_REGISTRY
└── ClaudeAdapter        (anthropic SDK)

BaseParser (ABC)         --> PARSER_REGISTRY
└── MarkdownParser

BaseReporter (ABC)       --> REPORTER_REGISTRY
└── MarkdownReporter     (Jinja2)
```

### 새 플러그인 추가 방법

1. 해당 모듈의 ABC를 상속받는 클래스를 작성한다.
2. 모듈의 `__init__.py`에 정의된 Registry에 등록한다.
3. 테스트를 작성한다.

예시 -- 새 Matcher 추가:

```python
# src/aat/matchers/my_matcher.py
from aat.matchers.base import BaseMatcher, MatchResult

class MyMatcher(BaseMatcher):
    name = "my_matcher"

    async def match(self, screenshot: bytes, target: MatchTarget) -> MatchResult | None:
        # 구현
        ...
```

```python
# src/aat/matchers/__init__.py
from aat.matchers.my_matcher import MyMatcher

MATCHER_REGISTRY["my_matcher"] = MyMatcher
```

### 핵심 흐름

1. **CLI** -- Typer가 사용자 명령을 파싱한다.
2. **ScenarioLoader** -- YAML 파일을 Pydantic 모델(`Scenario`)로 변환한다.
3. **StepExecutor** -- 시나리오의 각 스텝을 순서대로 실행한다.
4. **Engine** -- 브라우저를 제어한다 (navigate, click, type 등).
5. **Matcher** -- 스크린샷에서 대상 UI 요소의 좌표를 찾는다.
6. **Comparator** -- 기대 결과와 실제 결과를 비교하여 Pass/Fail을 판정한다.
7. **DevQA Loop** -- 실패 시 AI Adapter를 호출하여 수정안을 받고 재실행한다.
8. **Reporter** -- 실행 결과를 Markdown 리포트로 생성한다.

---

## Make 명령어 요약

| 명령어 | 설명 |
|--------|------|
| `make install` | 런타임 의존성만 설치 |
| `make dev` | 개발 환경 전체 설정 |
| `make lint` | ruff 린트 검사 |
| `make format` | ruff 포맷 + 자동 수정 |
| `make typecheck` | mypy strict 타입 검사 |
| `make test` | pytest 전체 실행 |
| `make test-cov` | pytest + 커버리지 리포트 |
| `make clean` | 캐시, 빌드 산출물 정리 |
