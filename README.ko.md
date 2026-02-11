# AAT (AI Auto Tester)

**AI 기반 DevQA Loop 오케스트레이터**

> 이미지 매칭으로 UI 테스트를 자동화하고, 실패 시 AI가 코드를 수정하고 재테스트하는 루프를 반복합니다.

| 항목 | 값 |
|------|----|
| 패키지명 | `aat-devqa` |
| 버전 | `0.2.0` |
| Python | `>= 3.11` |
| 라이선스 | AGPL-3.0-only |
| 상태 | Ultra-MVP 개발 중 |

---

## 주요 기능

- **이미지 매칭 파이프라인** -- Template, OCR, Feature, Hybrid 매처를 조합하여 UI 요소를 찾는다.
- **DevQA Loop** -- 테스트 실패 시 AI(Claude)가 원인을 분석하고 코드를 수정한 뒤 재테스트한다.
- **YAML 시나리오** -- 테스트 시나리오를 YAML로 선언적으로 작성한다.
- **플러그인 아키텍처** -- Engine, Matcher, Adapter, Parser, Reporter를 플러그인으로 교체할 수 있다.
- **인간화(Humanize)** -- Bezier 곡선 마우스 이동, 가변 속도 타이핑으로 봇 탐지를 우회한다.
- **학습 DB** -- 매칭 성공 이력을 SQLite에 저장하여 재매칭 속도를 높인다.

---

## 아키텍처

```
CLI (Typer)
 |
 v
+------------------+     +------------------+
|   ScenarioLoader |---->|   StepExecutor   |
|   (YAML 파싱)    |     |   (스텝 실행)    |
+------------------+     +--------+---------+
                                  |
                    +-------------+-------------+
                    |             |              |
               +----+----+  +----+----+  +------+------+
               | Engine  |  | Matcher |  | Comparator  |
               | (Web)   |  | (Hybrid)|  | (검증)      |
               +---------+  +---------+  +-------------+
                    |
                    v
            +-------+--------+
            |   DevQA Loop   |
            |  (실패 -> AI   |
            |   수정 -> 재실행)|
            +-------+--------+
                    |
          +---------+---------+
          |                   |
     +----+----+       +-----+-----+
     | Claude  |       | Reporter  |
     | Adapter |       | (Markdown)|
     +---------+       +-----------+
```

---

## 설치

### pip 설치

```bash
pip install aat-devqa
```

### 개발 환경 설치

```bash
git clone <repo-url> && cd AI_Auto_Tester
make dev
```

`make dev`는 다음을 수행한다:

1. 패키지를 editable 모드로 설치 (`pip install -e ".[dev]"`)
2. Playwright Chromium 브라우저 설치
3. pre-commit 훅 설치

### 시스템 의존성

pytesseract가 사용하는 Tesseract OCR 엔진을 별도로 설치해야 한다.

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr
```

---

## 빠른 시작

### 1. 프로젝트 초기화

```bash
aat init
```

`.aat/` 디렉토리와 기본 설정 파일(`config.yaml`)이 생성된다.

### 2. 설정 확인

```bash
aat config show
```

### 3. API 키 설정

```bash
export AAT_AI_API_KEY="sk-ant-..."
# 또는
aat config set ai.api_key "sk-ant-..."
```

### 4. 시나리오 작성

`scenarios/` 디렉토리에 YAML 파일을 작성한다.

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

### 5. 시나리오 검증

```bash
aat validate scenarios/SC-001_login.yaml
```

### 6. 단일 테스트 실행

```bash
aat run scenarios/SC-001_login.yaml
```

### 7. DevQA 루프 실행

```bash
aat loop scenarios/SC-001_login.yaml --max-iterations 5
```

테스트가 실패하면 AI가 원인을 분석하고 코드를 수정한 뒤 재테스트한다. `--max-iterations`로 최대 반복 횟수를 지정한다.

---

## CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `aat init` | 프로젝트 초기화 (`.aat/` 디렉토리, 기본 설정 생성) |
| `aat config show` | 현재 설정 출력 |
| `aat config set <key> <value>` | 설정값 변경 |
| `aat validate <scenario>` | 시나리오 YAML 문법 및 구조 검증 |
| `aat run <scenario>` | 단일 시나리오 테스트 실행 |
| `aat loop <scenario>` | DevQA 루프 실행 (실패 -> AI 수정 -> 재테스트) |
| `aat learn add <data>` | 학습 DB에 매칭 데이터 추가 |
| `aat analyze <document>` | 문서를 AI로 분석 |
| `aat generate <spec>` | AI 기반 시나리오 자동 생성 |

---

## 설정

`aat init` 실행 후 `.aat/config.yaml` 파일이 생성된다. 환경 변수로도 설정을 오버라이드할 수 있다.

| 설정 키 | 환경 변수 | 기본값 | 설명 |
|---------|-----------|--------|------|
| `ai.provider` | `AAT_AI_PROVIDER` | `claude` | AI 어댑터 (현재 claude만 지원) |
| `ai.api_key` | `AAT_AI_API_KEY` | -- | Claude API 키 |
| `ai.model` | `AAT_AI_MODEL` | `claude-sonnet-4-20250514` | 사용할 모델 |
| `engine.type` | `AAT_ENGINE_TYPE` | `web` | 엔진 타입 (현재 web만 지원) |
| `engine.headless` | `AAT_ENGINE_HEADLESS` | `false` | 헤드리스 모드 |
| `matcher.strategy` | `AAT_MATCHER_STRATEGY` | `hybrid` | 매칭 전략 |
| `matcher.confidence` | `AAT_MATCHER_CONFIDENCE` | `0.8` | 최소 매칭 신뢰도 (0.0-1.0) |

```bash
# 환경 변수로 API 키 설정
export AAT_AI_API_KEY="sk-ant-..."

# CLI로 설정 변경
aat config set matcher.confidence 0.85
```

---

## 프로젝트 구조

```
AI_Auto_Tester/
├── pyproject.toml
├── Makefile
├── LICENSE
├── README.md
├── CONTRIBUTING.md
├── .pre-commit-config.yaml
├── .gitignore
│
├── src/aat/
│   ├── __init__.py                   # __version__
│   ├── cli/                          # CLI (Typer)
│   │   ├── main.py                   # 엔트리포인트
│   │   └── commands/                 # 명령어별 모듈
│   │       ├── init_cmd.py
│   │       ├── config_cmd.py
│   │       ├── validate_cmd.py
│   │       ├── run_cmd.py
│   │       ├── loop_cmd.py
│   │       ├── learn_cmd.py
│   │       ├── analyze_cmd.py
│   │       └── generate_cmd.py
│   │
│   ├── core/                         # 핵심 로직
│   │   ├── models.py                 # Pydantic 모델, Enum
│   │   ├── config.py                 # pydantic-settings 기반 설정
│   │   ├── exceptions.py             # 예외 계층
│   │   ├── loop.py                   # DevQA Loop 오케스트레이터
│   │   └── scenario_loader.py        # YAML -> Scenario 변환
│   │
│   ├── engine/                       # 테스트 실행 엔진 (플러그인)
│   │   ├── base.py                   # BaseEngine ABC
│   │   ├── web.py                    # WebEngine (Playwright)
│   │   ├── executor.py               # StepExecutor
│   │   ├── humanizer.py              # 인간화 동작
│   │   ├── waiter.py                 # 폴링 + 안정화 감지
│   │   └── comparator.py             # ExpectedResult 평가
│   │
│   ├── matchers/                     # 이미지 매칭 (플러그인)
│   │   ├── base.py                   # BaseMatcher ABC
│   │   ├── template.py               # TemplateMatcher (cv2.matchTemplate)
│   │   ├── ocr.py                    # OCRMatcher (pytesseract)
│   │   ├── feature.py                # FeatureMatcher (ORB/SIFT)
│   │   └── hybrid.py                 # HybridMatcher (체인 오케스트레이터)
│   │
│   ├── adapters/                     # AI Adapter (플러그인)
│   │   ├── base.py                   # AIAdapter ABC
│   │   └── claude.py                 # ClaudeAdapter
│   │
│   ├── parsers/                      # 문서 파서 (플러그인)
│   │   ├── base.py                   # BaseParser ABC
│   │   └── markdown_parser.py        # MarkdownParser
│   │
│   ├── reporters/                    # 리포트 생성 (플러그인)
│   │   ├── base.py                   # BaseReporter ABC
│   │   └── markdown.py               # MarkdownReporter
│   │
│   └── learning/                     # 학습 DB
│       ├── store.py                  # LearnedStore (SQLite)
│       └── matcher.py                # LearnedMatcher
│
├── tests/
│   ├── conftest.py                   # 공통 fixtures
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

## 의존성

### 런타임

| 패키지 | 용도 |
|--------|------|
| `typer[all] >=0.9` | CLI 프레임워크 |
| `pydantic >=2.5` / `pydantic-settings >=2.1` | 데이터 모델, 설정 관리 |
| `pyyaml >=6.0` | YAML 시나리오 파싱 |
| `playwright >=1.40` | 웹 브라우저 자동화 엔진 |
| `opencv-python-headless >=4.8` | 이미지 템플릿 매칭, 특징점 매칭 |
| `numpy >=1.24` | 이미지 배열 연산 |
| `pillow >=10.0` | 이미지 로드/변환 |
| `pytesseract >=0.3.10` | OCR (텍스트 인식) |
| `anthropic >=0.40` | Claude API 클라이언트 |
| `jinja2 >=3.1` | 리포트 템플릿 렌더링 |
| `rich >=13.0` | 터미널 출력 포맷팅 |

### 개발

| 패키지 | 용도 |
|--------|------|
| `ruff >=0.4` | 린터 + 포매터 |
| `mypy >=1.8` | 정적 타입 검사 (strict 모드) |
| `pytest >=8.0` | 테스트 프레임워크 |
| `pytest-asyncio >=0.23` | 비동기 테스트 지원 |
| `pytest-cov >=4.0` | 커버리지 측정 |
| `pytest-mock >=3.12` | Mock 유틸리티 |
| `pre-commit >=3.6` | Git 훅 자동화 |
| `types-PyYAML >=6.0` | PyYAML 타입 스텁 |

---

## 라이선스

이 프로젝트는 [AGPL-3.0-only](https://www.gnu.org/licenses/agpl-3.0.html) 라이선스로 배포된다.
