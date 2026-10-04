# AAT (AI Auto Tester) — Project Guide

## 🎯 최종 목표 (대표님 확정 2026-10-03)

> **플러그인 마켓에 등재하고, 쓰는 사람이 불편함을 느끼지 않게 만드는 것.**
> 수익은 **비목표**다. 인지도를 얻는 것이 목적이고, 수익화는 이용자가 어느 정도 모인 뒤에 검토한다.

판단이 갈릴 때 이 기준으로 결정한다 — **"작동하는가"가 아니라 "처음 쓰는 사람이 막히지 않는가".**

- **인수 시험은 단위 시험이 아니라 콜드 스타트 경로다.** 빈 가상환경에 설치해서 첫 통과까지 가는 길. 단위 시험 전부가 녹색인 상태에서도 신규 사용자는 첫 5분에 막힐 수 있다(실측됨).
- **추적 지표는 매출이 아니라 첫 실행 성공률이다.**
- **과장은 더 위험하다.** 수익 모델이 없으면 환불도 영업 사과도 없고, 남는 것은 평판뿐이다. 기능을 실제보다 크게 적지 않는다.
- 근거·파생 조치: `decisions/2026-10-03_최종목표_확정.md`, `docs/awt_project_analysis_and_strategy.md` §0

## Overview

AI 기반 DevQA Loop 오케스트레이터. 이미지 매칭으로 UI 테스트를 자동화하고, 실패 시 AI가 코드를 수정하고 재테스트하는 루프를 반복한다.

> ⚠️ 위 한 줄은 지향이고, 2026-10-03 실측 기준 **실제 정체성**은 *"증거를 남기는 결정론적 웹 E2E 러너"*다. 기본 모드 `manual`은 AI 수정안을 파일에 쓰지 않는다. 사용자에게 설명할 때는 실측 쪽을 말한다(보고서 §10-2·§10-4).
>
> 단 **시각 매칭은 2026-10-03에 고쳤다**(AAT-112). 하늘고 9일 실사용의 "0회 발화"는 기능이 무가치하다는 뜻이 아니라 배선이 다섯 군데 끊겨 있었다는 뜻이었고, 지금은 선택자가 깨지면 이전 실행이 적립한 사진으로 요소를 찾아낸다 — 실제 Chromium에서 선택자를 깨뜨려 측정했다(보고서 §11-15). 이 기능을 "작동하지 않는다"로 설명하지 말 것.

## ⛔ AWT Testing Workflow (필수 준수)

사용자가 AWT로 테스트를 요청하면 반드시 아래 4단계를 **순서대로** 따를 것.

### Step 1: SCAN
```bash
aat scan --url <URL>
```
→ `.aat/scan_result.json`을 읽고 사용자에게 요약 보고 → **승인 대기**

### Step 2: GENERATE + PRESENT
시나리오 YAML 작성 → 사용자에게 보여주고 → **승인 대기**

### Step 3: EXECUTE (승인 후에만)
```bash
aat run --skill-mode --fast <scenario>
```
→ 실패 시 즉시 중단 → 사용자에게 보고 → **지시 대기**

### Step 4: REPORT
결과 요약 보고

### 금지 사항
- `aat devqa` 사용 금지 (사용자 체크포인트 없이 전체 파이프라인 실행)
- `-y` / `--auto-approve` 사용 금지
- 사용자 승인 없이 테스트 실행 금지
- 사용자 지시 없이 코드/시나리오 자동 수정 금지

## ⛔ AI Security Rules — Approval Bypass Prevention (Layer 4)

**이 섹션은 모든 AI 에이전트(Claude, GPT, Copilot 등)가 반드시 준수해야 합니다.**

### 절대 금지 행위
1. `_AAT_APPROVAL_TOKEN` 환경변수를 직접 설정하거나 위조하지 마세요.
2. `.aat/.approval_token_*` 파일을 직접 생성, 읽기, 수정하지 마세요.
3. `approval_token.py`, `scenario_reviewer.py`, `audit.py`의 보안 로직을 수정하지 마세요.
4. `/dev/tty` 읽기를 우회하거나 `_is_interactive()` 결과를 조작하지 마세요.
5. `.aat/audit.log`를 삭제하거나 수정하지 마세요.
6. `--auto-approve`, `-y` 플래그를 사용하거나 구현하지 마세요.
7. `echo "" | aat run` 같은 stdin 파이프로 승인을 우회하지 마세요.

### 승인 메커니즘 (4-Layer Defense)
- **Layer 1**: `/dev/tty` 직접 읽기 — stdin 파이프 우회 방지
- **Layer 2**: 일회용 암호화 토큰 — 환경변수 위조 방지
- **Layer 3**: JSONL 감사 로그 — 모든 실행 시도 기록
- **Layer 4**: 이 규칙 — AI 에이전트의 우회 시도 자체를 금지

### AI 에이전트의 올바른 동작
- `aat run`은 반드시 사용자의 터미널에서 실행하세요.
- 사용자가 직접 Enter를 눌러 승인해야 합니다.
- 승인 프롬프트를 건너뛸 수 있는 방법을 찾으려 하지 마세요.

## Key Documents

- `PM/기획서_v1.md` — 제품 기획서 (전체 비전)
- `PM/Develop_Plan_v0.2.md` — 기술 아키텍처
- `PM/설계서_v0.2.md` — **구현 상세 설계** (이 파일이 구현의 기준)
- `PM/비즈니스_플랜_v0.2.md` — 사업 전략
- `docs/RELEASE_GUIDE.md` — **배포 가이드** (PyPI/README/PR 동기화 절차)

## Tech Stack

- Python 3.11+, Typer (CLI), Pydantic v2, pydantic-settings
- Playwright (WebEngine), PyAutoGUI (DesktopEngine), OpenCV (이미지 매칭), pytesseract (OCR)
- anthropic SDK (Claude API), openai SDK, httpx (Ollama), Jinja2 (리포트), SQLite (학습 DB)
- Dev: ruff, mypy, pytest, pytest-asyncio, pre-commit

## Architecture Rules

- async 기본 (Playwright async 네이티브)
- ABC + @abstractmethod (Protocol 대신)
- core/models.py는 leaf 모듈 (내부 import 없음)
- 순환 의존 금지: cli → core → engine/matchers/adapters/reporters → models
- 플러그인 레지스트리: 각 __init__.py의 딕셔너리 기반

## 작업 완료 절차

코드를 수정한 모든 작업은 아래 절차를 완료한 후에만 "완료"로 보고한다:

1. 로컬 테스트 실행 (관련 테스트가 있는 경우)
2. `git commit` & `git push`
3. GitHub Actions CI 통과 확인 (`gh run list --limit 1`으로 status 확인)
4. CI가 실패하면 에러를 수정하고 1번부터 반복
5. CI가 `"completed/success"`일 때만 작업 완료 보고

커밋은 Phase나 기능 단위로 나눠서 한다. 한 번에 10개 이상 파일을 변경하는 커밋은 피한다.

**배포가 필요한 경우** `docs/RELEASE_GUIDE.md`의 체크리스트를 따른다.
특히 MCP 도구 변경 시 Anthropic Skills PR과 MCP Servers PR 동기화를 잊지 말 것.

## Commands

- `make dev` — 개발 환경 설치
- `make lint` — ruff check
- `make format` — ruff format + fix
- `make typecheck` — mypy strict
- `make test` — pytest
- `make test-cov` — pytest + coverage

---

## WBS Progress Tracker

> 각 태스크 완료 시 `[ ]` → `[x]`로 변경하고 완료일 기록

### Phase 1: Foundation (Week 1, ~17h)

- [x] **AAT-001** 프로젝트 스켈레톤 (2h) — 완료 2026-02-11
  - git init, pyproject.toml, 디렉토리 구조, Makefile, pre-commit
  - 완료 기준: `make lint && make typecheck && make test` 통과
- [x] **AAT-003** Enum 정의 (1h) — 완료 2026-02-11
  - ActionType, LabelPosition, AssertType, MatchMethod, Severity, StepStatus
- [x] **AAT-002** Pydantic 모델 전체 (4h) — 완료 2026-02-11
  - Config 모델, 시나리오 모델, 결과 모델, 학습 모델 + validator
  - 완료 기준: test_models.py 통과
- [x] **AAT-007** 예외 계층 (1h) — 완료 2026-02-11
  - AATError 기반 10개 커스텀 예외
- [x] **AAT-004** Config + pydantic-settings (3h) — 완료 2026-02-11
  - YAML + env var + CLI flag 3계층 머지
- [x] **AAT-005** 5개 ABC 인터페이스 (3h) — 완료 2026-02-11
  - BaseEngine, BaseMatcher, AIAdapter, BaseParser, BaseReporter
- [x] **AAT-006** Scenario YAML 로더 (3h) — 완료 2026-02-11
  - YAML → Scenario, 디렉토리 스캔, 변수 치환

### Phase 2: Engine + Matchers (Week 2~3, ~33h)

- [x] **AAT-010** WebEngine — Playwright (6h) — 완료 2026-02-11
- [x] **AAT-011** Humanizer — Bezier 마우스, 가변 타이핑 (4h) — 완료 2026-02-11
- [x] **AAT-012** Waiter — 폴링 + 해시 안정화 (4h) — 완료 2026-02-11
- [x] **AAT-013** TemplateMatcher — cv2.matchTemplate (5h) — 완료 2026-02-11
- [x] **AAT-014** OCRMatcher — pytesseract (6h) — 완료 2026-02-11
- [x] **AAT-015** FeatureMatcher — **ORB만** (4h) — 완료 2026-02-11
  - 2026-10-03 정정: SIFT는 구현되지 않았습니다. `matchers/feature.py:39`는 `cv2.ORB_create`만 호출합니다
- [x] **AAT-016** HybridMatcher — 체인 오케스트레이터 (4h) — 완료 2026-02-11

### Phase 3: Executor + CLI (Week 3~4, ~26h)

- [x] **AAT-020** StepExecutor (6h) — 완료 2026-02-11
- [x] **AAT-021** Comparator (4h) — 완료 2026-02-11
- [x] **AAT-022** CLI — init, config (4h) — 완료 2026-02-11
- [x] **AAT-023** CLI — validate (3h) — 완료 2026-02-11
- [x] **AAT-024** CLI — run (5h) — 완료 2026-02-11
- [x] **AAT-025** CLI — report, learned (4h) — 완료 2026-02-11 (stub)

### Phase 4: AI + Loop (Week 5~6, ~16h)

- [x] **AAT-030** ClaudeAdapter (4h) — 완료 2026-02-11
- [x] **AAT-031** MarkdownReporter (3h) — 완료 2026-02-11
- [x] **AAT-032** DevQALoop (6h) — 완료 2026-02-11
- [x] **AAT-033** CLI — loop (3h) — 완료 2026-02-11

### Phase 5: Analysis + Generation (Week 6~7, ~16h)

- [x] **AAT-040** MarkdownParser (3h) — 완료 2026-02-11
- [x] **AAT-041** CLI — learn (4h) — 완료 2026-02-11
- [x] **AAT-042** CLI — analyze (5h) — 완료 2026-02-11
- [x] **AAT-043** CLI — generate (4h) — 완료 2026-02-11

### Phase 6: Learning + Polish (Week 7~8, ~22h)

- [x] **AAT-050** LearnedStore — SQLite (4h) — 완료 2026-02-11
- [x] **AAT-051** LearnedMatcher (3h) — 완료 2026-02-11
- [x] **AAT-052** VisionAIMatcher — **완전 구현** (2h) — 완료 2026-02-11
  - 2026-10-03 정정: "stub"이 아닙니다. `matchers/vision_ai.py` 360행에 Claude·OpenAI호환·Gemini 세 경로 + 응답 검증 + 비용 로깅이 들어 있습니다. **문서가 제품을 과소평가한 자리**입니다
- [x] **AAT-053** README + CONTRIBUTING (4h) — 완료 2026-02-11
- [x] **AAT-054** 통합 테스트 (6h) — 완료 2026-02-11
- [x] **AAT-055** CI/CD + 릴리스 준비 (3h) — 완료 2026-02-11

### Post-MVP: 품질 강화 + 확장

- [x] **AAT-060** GitHub 저장소 생성 + 초기 푸시 — 완료 2026-02-11
- [x] **AAT-061** CI/CD 파이프라인 수정 (tesseract, playwright, pandas, ANSI) — 완료 2026-02-11
- [x] **AAT-062** 영문화 — 에러 메시지, README, CONTRIBUTING 영어 전환 — 완료 2026-02-11
- [x] **AAT-063** TemplateMatcher 버그 수정 — 1.0x 스케일 누락 문제 — 완료 2026-02-11
- [x] **AAT-064** OllamaAdapter — 로컬 LLM 연동 (codellama:7b) — 완료 2026-02-12
- [x] **AAT-065** OpenAIAdapter — GPT-4o Vision 지원 — 완료 2026-02-12

### Post-MVP: 가이드 모드 + UX (AAT-070~076)

- [x] **AAT-070** 이벤트/알림 시스템 — 메신저 연동 대비 EventEmitter 패턴
  - CLIHandler (터미널 출력), MessageBuffer (메신저 배치 전송), 향후 TelegramHandler/DiscordHandler 확장
- [x] **AAT-071** AI Provider 연결 테스트 — API 키 입력 후 즉시 연결 확인
  - Claude: 간단한 API 호출, OpenAI: 모델 목록 조회, Ollama: /api/tags 확인
- [x] **AAT-072** 폴더 일괄 문서 분석 — 디렉토리 지정 시 전체 파일 스캔+분석
- [x] **AAT-073** URL 접속 확인 — 테스트 대상 URL 응답 체크
- [x] **AAT-074** 테스트 중 취소 기능 — Ctrl+C로 즉시 중단 + 부분 결과 저장
- [x] **AAT-075** `aat start` 가이드 모드 — 전체 흐름을 하나의 대화형 명령으로
  - 설정→문서분석→시나리오생성→테스트→루프→리포트 일괄 진행
- [x] **AAT-076** 가이드 모드 테스트 (events, connection, start_cmd)

### Post-MVP: 엔진 + 승인 모드 (AAT-080~081)

- [x] **AAT-080** 3-Tier Approval Mode — Git 브랜치 격리 기반 승인 모드 — 완료 2026-02-12
  - ApprovalMode enum (manual/branch/auto), GitOps async subprocess 래퍼
  - DevQALoop 모드별 핸들러 (`_handle_manual/branch/auto`), `_read_source_files`
  - `--approval-mode/-a` CLI 옵션, `skip_engine_lifecycle`, start_cmd 중복 제거
  - MarkdownReporter 브랜치/커밋 정보 렌더링
- [x] **AAT-081** DesktopEngine — **화면 좌표로 클릭할 수 있으나 입력은 브라우저로 갑니다** — 완료 2026-02-12
  - 2026-10-03 정정 (경계를 정확히): `desktop.py:92`가 **Playwright 브라우저를 항상 헤드풀로 띄웁니다.** 그 위에서 두 경로가 갈립니다
  - **할 수 있는 것** — 단계에 `target.image`가 있으면 `find_on_screen` → `click_on_screen`으로 **PyAutoGUI의 OS 수준 클릭**이 나갑니다(`executor.py:1220,1352-1363`). 브라우저 창 밖도 누를 수 있습니다. 전체화면 캡처·마우스 이동·스크롤도 PyAutoGUI입니다
  - **할 수 없는 것** — 타이핑은 **언제나** `page.keyboard`(`desktop.py:284`)이므로 네이티브 창에 글자를 넣을 수 없고, `navigate`는 브라우저 페이지를 요구합니다. 즉 **"클릭은 OS, 입력은 브라우저"** 인 반쪽 하이브리드입니다
  - 데스크톱 앱 자동화를 기대하고 고르면 클릭까지는 되고 입력에서 막힙니다
  - ENGINE_REGISTRY 등록, CLI 동적 엔진 선택 (`config.engine.type: web | desktop`)

### Post-MVP: 웹 대시보드 (AAT-090~091)

- [x] **AAT-090** Web Dashboard (`aat dashboard`) — 완료 2026-02-12
  - FastAPI + WebSocket 기반 실시간 대시보드
  - 5영역 UI: Scenarios | Config | Execution | Live Screenshot | Event Log
  - SubprocessManager, WebSocketEventHandler, ConnectionManager
  - REST API: config CRUD, scenario list, run/loop/stop, status, logs, screenshots
  - 실시간 스크린샷 (960x540 JPEG 60% → base64 WS), 승인 모달, 프로그레스 바
  - pyproject.toml `[web]` optional dependency (fastapi, uvicorn, websockets)
  - 다크 테마 (#1a1a2e/#16213e/#e0e0e0, 틸 #00d4aa)
- [x] **AAT-091** Dashboard UI/UX 전면 개선 — 3-step Z-패턴 레이아웃 — 완료 2026-02-13
  - 5-panel grid → 3-step Z-패턴 (Setup → Prepare → Execute)
  - 서버 제어: SubprocessManager `start_raw(cmd, cwd)` + `on_line` 콜백 + 포트 자동 추출
  - 서버 엔드포인트 4개 (start/stop/status/logs), 문서 업로드 2개 (upload/list)
  - 드래그&드롭 문서 업로드, 미니 로그 + Event Log 이중 표시
  - python-multipart 의존성 추가, 반응형 (1100px 이하 1열 스택)
- [x] **AAT-092** 시나리오 관리 기능 개선 — 완료 2026-02-13
  - 커스텀 경로 지원: `GET /api/scenarios?path=` 쿼리 파라미터
  - 시나리오 YAML 업로드: `POST /api/scenarios/upload` (.yaml/.yml 전용)
  - 선택적 실행: `scenario_ids` 파라미터로 선택된 시나리오만 run/loop
  - UI: 경로 입력+Load, Select All/Clear, 선택 카운트, 동적 버튼 라벨

### Post-MVP: State Teardown (AAT-093~095)

- [x] **AAT-093** 동적 변수 치환 — `{{timestamp}}`, `{{datetime}}`, `{{random}}`, `{{uuid}}`, `{{env.VAR}}` — 완료 2026-03-26
  - `_resolve_var()` + `_DYNAMIC_VARS` frozenset, `find_unresolved_vars()` 제외 로직
  - 16개 테스트 통과

- [x] **AAT-094** teardown 섹션 파싱 — TeardownStep 모델 + Scenario 필드 — 완료 2026-03-26
  - TeardownStep: api_call | db_query | shell 공용 모델
  - Scenario.teardown: list[TeardownStep] = [] (하위 호환)
  - 12개 테스트, {{timestamp}} YAML 치환 포함

- [x] **AAT-095** TeardownExecutor 실행 엔진 + 실전 검증 — 완료 2026-03-26
  - TeardownExecutor: api_call(httpx) / db_query(asyncpg+sqlite3) / shell(subprocess)
  - run(): 실패 swallow (로그만) — 테스트 결과에 영향 없음
  - run_cmd.py 통합 + `--skip-teardown` 옵션
  - SC-CR001_register.yaml: 동적 이메일(`test+{{timestamp}}@ailooplab.com`) + `{{random}}` 학원명
  - scripts/cleanup_firebase_user.py: Admin SDK + REST API (credentials 없으면 no-op)
  - tests/test-teardown-loop.sh: N회 연속 실행 스크립트
  - 실증: 3회 연속 실행 30/30 성공 (이메일 중복 없음)

### Post-MVP: Visual Regression (AAT-100~102)

- [x] **AAT-100** VisualComparator — OpenCV SSIM + diff 이미지 생성 — 완료 2026-04-03
  - SSIM (Wang et al. 2004): OpenCV 직접 구현, 외부 의존성 없음
  - 3-panel diff 이미지: Baseline | Current | Diff (빨간 오버레이)
  - 단일 diff overlay 이미지 생성

- [x] **AAT-101** BaselineStore + 모델 — 기준선 저장/로드/관리 — 완료 2026-04-03
  - `.aat/baselines/{scenario_id}/` 구조, meta.json 포함
  - StepDiffResult, VisualDiffReport, BaselineMeta Pydantic 모델
  - save/load/list/clear/clear_all 메서드

- [x] **AAT-102** CLI 커맨드 (snapshot, diff, baseline) + MCP 도구 — 완료 2026-04-03
  - `aat snapshot <path>` — 시나리오 실행 후 기준선 캡처
  - `aat diff <path> --threshold 0.95` — 기준선 대비 비교 + Rich 테이블
  - `aat baseline list/clear` — 기준선 관리
  - MCP: `aat_snapshot`, `aat_diff` 도구 추가
  - 20개 단위 테스트 통과

- [x] **AAT-103** PR 코멘트 GitHub Action + `--format=github` — 완료 2026-04-03
  - `aat diff --format=github` → PR 코멘트용 마크다운 출력
  - `aat diff --format=json` → JSON 출력
  - `.github/workflows/visual-regression.yml` 템플릿
  - PR 코멘트: 자동 생성/갱신 (기존 코멘트 업데이트, 스팸 방지)
  - 24개 단위 테스트 통과

- [x] **AAT-104** Watch 모드 — 파일 변경 감지 + 자동 테스트 실행 — 완료 2026-04-03
  - `aat watch <scenarios> --url <URL>` — 파일 변경 시 자동 테스트
  - watchfiles (Rust 기반) + polling fallback
  - 시나리오 변경 → 해당 시나리오만, 소스 변경 → 전체 시나리오 실행
  - 기준선 존재 시 자동 visual diff 포함
  - MCP: `aat_watch` 도구 추가
  - `[watch]` optional dependency (watchfiles)
  - 18개 단위 테스트 통과

### Post-MVP: Enhancement (AAT-105~107)

- [x] **AAT-105** 반응형 스크린샷 `--responsive` / `--viewport` — 완료 2026-04-04
  - 3종 뷰포트: mobile (375x812), tablet (768x1024), desktop (1280x720)
  - `aat snapshot --responsive` / `aat diff --responsive` — 3종 한번에 캡처/비교
  - `--viewport 375x812` 단일 지정도 지원
  - BaselineStore viewport suffix: `step001-mobile_after.png`
  - RESPONSIVE_VIEWPORTS 상수 (gstack 호환)

- [x] **AAT-106** 콘솔 에러 수집 `--console` / `--console-fail` — 완료 2026-04-04
  - Playwright `page.on('console')` / `page.on('pageerror')` 기반
  - 스크린샷 통과해도 JS 에러 있으면 ⚠️ 경고
  - `--console-fail`: 에러 있으면 FAIL 처리
  - ConsoleCollector 클래스 (visual/console_collector.py)

- [x] **AAT-107** diff 결과 자동 열기 `--open` — 완료 2026-04-04
  - `aat diff --open` → FAIL diff 이미지를 macOS Preview / xdg-open으로 자동 열기
  - MCP: `aat_snapshot`, `aat_diff` 파라미터 추가
  - 25개 단위 테스트 통과 (test_enhancements.py)

### Post-MVP: Approval Security (AAT-108)

- [x] **AAT-108** 4-Layer Approval Security — AI 에이전트 승인 우회 방지 — 완료 2026-04-04
  - Layer 1: `/dev/tty` 직접 읽기 — stdin 파이프 우회 방지 (`scenario_reviewer.py`, `loop.py`)
  - Layer 2: 일회용 암호화 토큰 — `_AAT_DEVQA_APPROVED` 환경변수 → `_AAT_APPROVAL_TOKEN` + 디스크 파일 검증
  - Layer 3: JSONL 감사 로그 — `.aat/audit.log`에 모든 실행 시도 기록
  - Layer 4: CLAUDE.md + MCP instructions에 AI 보안 규칙 명시
  - `approval_token.py`: `generate_token()`, `store_token()`, `validate_and_consume()`
  - `audit.py`: `AuditEntry` Pydantic 모델, `log_audit()`, `read_audit()`
  - `run_cmd.py`, `devqa_cmd.py`, `watch_cmd.py` 통합
  - 17개 보안 테스트 통과 (test_approval_security.py)

### Post-MVP: Coordinate Learning 신뢰성 (AAT-109)

- [x] **AAT-109** 학습 좌표가 실패를 통과로 보고하던 결함 수정 — 완료 2026-09-19
  - 배경: 하늘고 스터디 웹앱 아홉 대본 실행 중 확정 (`BUG_REPORT_learned_coords.md`)
  - 명시 우선: 학습 좌표를 CSS selector **뒤**(Priority 0.4)로 이동 — 대본이 지목한 요소를 추측이 덮어쓰지 못한다
  - 효과 검증 후 학습: `_pending_learn` → `_settle_pending_learn()`, 화면 변화가 없으면 저장하지 않고 기존 좌표는 신뢰도 차감(`penalize_coords`, 0.5 미만 삭제)
  - `StepStatus.WARNING` 신설 — 헛클릭은 PASSED가 아니며 종료코드 3으로 파이프라인에 드러난다 (`_exit_code()`)
  - 스위치: `aat run --no-learn`, 단계별 `learn: false`, `aat learn reset [이름] / --all`
  - `load_session`: 세션 나이 로그 + `max_age_min` 상한, 진단문 `session_expired`를 `auth_error`에서 분리
  - 검증: 실제 Chromium 통합 시험 12개(`tests/integration/test_learned_coords.py`) + 단위 시험, 네 가지 역변이(mutation)로 음성 시험이 실제로 잡는지 확인

### Post-MVP: PDF 리포트 (AAT-110)

- [x] **AAT-110** 테스트 결과를 PDF로 보고하는 기능 — 완료 2026-09-19
  - `PDFReporter` (`src/aat/reporters/pdf.py`): Jinja2로 HTML을 렌더링한 뒤 Playwright의 `page.pdf()`로 인쇄 — 새 의존성 없음 (이미 설치된 Chromium 사용)
  - 실패·경고 단계의 스크린샷을 base64 `data:` URI로 파일 안에 넣어, 리포트 한 장만 전달해도 내용이 설명됨 (`screenshots="failures" | "all" | "none"`)
  - 경고가 있는 실행은 표지에 `PASS WITH WARNINGS`로 표기 — AAT-109의 원칙(헛클릭은 통과가 아니다)을 리포트 표면에서도 유지
  - `aat run --report pdf|markdown` (시나리오별 `reports/<id>/`), `aat loop --report-format pdf|markdown`
  - 알 수 없는 형식은 브라우저를 열기 전에 거부하고, 리포트 작성 실패는 종료코드에 영향을 주지 않음
  - 스킬·MCP 동일 노출: `SKILL.md`(CLI Commands·Key Flags)와 `cli-reference.md`에 `--report` 기재, MCP `aat_run`·`aat_run_skill_mode`에 `report` 인자 추가(`_run_command()` 공용 조립기)
  - 시험: HTML 단위 13개(`tests/test_reporters/test_pdf.py`), 실제 Chromium 통합 3개(`tests/integration/test_pdf_report.py`), CLI 배선 시험, MCP 명령 조립 시험 4개(`tests/test_mcp_server.py`, MCP SDK 없으면 건너뜀)

- [x] **AAT-111** 리포트 실사용 결함 두 가지 수정 (대표님 시험 보고) — 완료 2026-09-19
  - 상대 경로에서 PDF가 조용히 실패하던 문제: `Path.as_uri()`는 상대 경로를 변환하지 않고 예외를 냅니다. `reports_dir`의 **기본값이 상대 경로 `"reports"`**(`core/models.py`)이므로 절대 경로를 따로 적어 두지 않은 모든 사용자가 HTML만 받고 PDF를 받지 못했습니다. `html_path.resolve().as_uri()`로 수정
  - 통과한 단계의 화면을 보여줄 방법이 없던 문제: `--report-screenshots failures|all|none` 신설. 리포터에는 이미 정책이 구현되어 있었으나 명령줄로 통하는 길이 없었습니다
  - `build_reporter()`(`reporters/__init__.py`) 신설 — `run`과 `loop`이 같은 조립기를 쓰므로 형식이 옵션을 얻을 때 한쪽만 갱신되는 일이 없습니다. 형식·정책 모두 브라우저를 열기 전에 검증
  - 세 표면 동시 반영: CLI(`aat run`·`aat loop`), 스킬(`SKILL.md`·`cli-reference.md`), MCP(`aat_run`·`aat_run_skill_mode`의 `report_screenshots` 인자)
  - 시험: 상대 경로 통합 시험(역변이로 결함 재현 확인), `build_reporter` 단위 5개(`tests/test_reporters/test_registry.py`), CLI 정책 전달·거부 시험, MCP 조립 시험 2개 추가

### Post-MVP: 자기 치유 — 시각 매칭을 실제로 작동하게 (AAT-112)

- [x] **AAT-112** 선택자가 깨지면 적립한 사진으로 요소를 찾는다 — 완료 2026-10-03
  - 배경: 하늘고 9일 실사용에서 시각 매칭 **0회 발화**(보고서 §5). 대표님 지시로 과녁이 *주장을 낮추는 것*에서 *기능을 작동시키는 것*으로 바뀌었습니다 — *"서비스 차별점을 없애면 왜 만드는 거야?"* 끊긴 자리는 다섯 군데였습니다 (기록: `docs/awt_project_analysis_and_strategy.md` §11-15)
  - **③ 라벨 먼저** — `_act_at_pos`가 호출자 열 곳 모두에 `MatchMethod.OCR`을 찍고 있었습니다. `match_history`의 `ocr` 237행은 Tesseract를 거친 적이 없습니다. `MatchMethod.PLAYWRIGHT` 신설 + 각 경로가 자기 출처를 넘깁니다. 측정이 안 되면 나머지를 고쳐도 고쳐졌는지 알 수 없습니다
  - **① 적립** — DOM 성공 경로가 `bounding_box()`의 `width`·`height`를 버려서 `_auto_save_template`이 즉시 반환했습니다. 추가 스크린샷 0장으로 적립합니다
  - **② 치유** — `--fast`가 체인 **앞에서** `MatchError`를 던졌습니다(README·스킬·MCP가 모두 권하는 기본 명령입니다). 그리고 적립은 `text or selector`, 조회는 `text or image`로 **열쇠가 달라** 선택자만 지닌 단계에 대해 저장소가 **쓰기 전용**이었습니다 — 바로 치유가 존재하는 대상입니다. `template_store.name_for()` 하나로 통일
  - **저장소** — `~/.aat/templates/<host>/`로 호스트별 격리, 30일 만료, 호스트당 300장 상한, `aat learn templates list/clear`. 홈 디렉토리에 쌓인 107장 정리
  - **⑤ 증명** — 실제 Chromium에서 `?id=grade` → `?id=grade-v2`로 선택자만 깨뜨리는 시험(`tests/fixtures/selector_rename_server.py`). **이 시험이 치유가 죽은 코드였음을 찾아냈습니다** — 학습 좌표(우선순위 0.4)가 치유보다 먼저 답했고, 1회차가 사진과 위치를 함께 남기므로 2회차는 위치로 통과하며 치유는 실행되지 않았습니다. 모의 시험 18건은 전부 초록이었습니다. **적립한 사진(0.9)을 학습 좌표(1.0) 앞으로** 옮겼습니다 — 사진은 관측이고 좌표는 추측입니다
  - **파생 수정 — 학습 좌표를 모든 DOM 경로 뒤로**: AAT-109는 「추측이 관측을 덮어쓰지 못한다」를 선언하면서 **선택자 한 경로에만** 적용해 두었습니다(우선순위 0.4 — 입력란 탐색·글자 검색보다 앞). 사진을 좌표 앞에 두자 좌표가 모든 DOM 경로 뒤로 내려가고, AAT-109 시험 다섯 건이 **DOM이 찾아낸 진짜 버튼을 눌러** 통과했습니다. 순서를 되돌리지 않고 그 다섯 건이 원래 측정하려던 경로에 닿도록 고쳐 썼습니다. **부작용은 라벨뿐입니다** — 전에 `learned`로 통과했던 단계가 `playwright`나 `saved_template`으로 보고합니다(같은 클릭, 더 나은 근거)
  - **파생 수정 — `_blind_the_search`가 아무것도 가리지 않고 있었음**: 「DOM 경로를 전부 가려 기억한 위치만 남긴다」는 시험 보조 함수가 `find_text_position`을 가렸지만, 같은 작업의 ①이 적립을 위해 도입한 `find_text_box`(실행기가 **먼저** 쓰는 쪽)는 가리지 않았습니다. 그 위의 양성 시험 두 건이 **기억한 위치로 클릭했다고 주장하면서 DOM이 일하는 동안 초록**이었습니다. **시험은 빨개지지 않으면서 속이 빌 수 있습니다** — 탐색 경로를 추가하면 그것을 가리는 쪽도 같이 갱신해야 합니다
  - 치유 성공은 `MatchMethod.SAVED_TEMPLATE` + 전략 `healed_from_bank`로 분리(치유 발화는 *대본이 낡았다*는 조언이지 매칭 조언이 아닙니다). 치유한 사진은 다시 적립하지 않습니다(잘린 영역이 요소 밖으로 걸어 나갑니다)
  - ~~**남은 결함(미수정, 기록됨)**: `LearnedStore`는 좌표에 **호스트 구획이 없습니다**~~ → **AAT-115 ①에서 수리 완료**(2026-10-03). `xfail`을 걸어 둔 덕에 고치는 순간 시험이 알려 주었습니다
  - 시험: 실제 Chromium 통합 8건(`tests/integration/test_self_healing.py`, 1건 xfail), 실행기 8건, 체인 9건. 역변이 6종 전부 잡힘
  - 네 표면 동시 반영: CLI 도움말, `SKILL.md`, `cli-reference.md`·`scenario-schema.md`, MCP

### Post-MVP: 실패 위의 유료 권유 문구 제거 (AAT-113)

- [x] **AAT-113** 세 번 실패한 사용자에게만 보이던 광고를 제거 — 완료 2026-10-03
  - 대표님 승인. 지워진 곳은 `run_cmd.py`의 `_save_skill_attempt` — **상태를 파일에 쓰는 함수**였고, 그래서 실패 경로를 검토한 사람이 아무도 찾지 못했습니다
  - 발화 조건이 `attempt >= 3 and total_failed > 0`이었습니다. 보여서는 안 되는 유일한 사람에게만 보였고, 그 실패는 자주 **AWT 자신의 결함**이었습니다(`navigate` + `critical` 거짓 실패, AAT-112 이전) — 제품 자신의 고장을 근거로 제품을 팔았습니다. §0이 확정한 대로 수익은 목표가 아닙니다
  - **대체 문구를 넣지 않았습니다.** `diagnosis.py`가 이미 `SCREENSHOT`·`URL`·`CATEGORY`·`POSSIBLE_CAUSE`·`ATTEMPTS`를 출력합니다. 막힌 사용자에게 필요한 것은 그 줄들을 읽는 것입니다
  - `total_failed` 인자도 제거 — 그 값을 읽은 유일한 용도가 광고 여부 판단이었으므로, 남기면 「사용자가 얼마나 못하고 있는지에 따라 출력하는」 고리를 다음 사람에게 물려줍니다
  - 시험 3건(`TestSkillAttemptState`): 상태만 쓰고 한 글자도 내지 않음 / 서명에 `total_failed` 없음 / `src/aat` 전체에 `awt.dev`·`AWT Cloud` 없음. 역변이로 2건 빨개짐
  - 기록: 보고서 §11-16

### Post-MVP: 「통과했다 ≠ 검사했다」를 코드로 막기 (AAT-114)

- [x] **AAT-114** CLI 시험 40건 + 글자 단정의 맹점 고정 + `text_equals`를 쓸 수 있게 — 완료 2026-10-03
  - 보고서 3순위 두 항목(§7-2 CLI 커버리지, §9-2 부분일치)을 닫고, 작업 중에 **셋째 겹**을 찾았습니다
  - **CLI 시험 40건**(`tests/test_cli/test_run_devqa_internals.py`). `aat run` 15% / `aat devqa` 9%였습니다. 어려워서가 아니라 **브라우저를 요구하는 비동기 본문 밑에 깔린 작은 함수들**이라 아무도 찾아가지 않았습니다. 시험이 **한 번도 호출한 적 없는 코드**에서 결함 두 개가 나왔습니다
    - `_js_str`가 줄바꿈을 통과시켜 JS `SyntaxError`를 만들었고, 호출자의 `except Exception: pass`가 삼켜 **오버레이가 조용히 집계를 멈췄습니다.** `json.dumps`로 교체 — U+2028·U+2029도 함께 막힙니다
    - devqa 자동 수정기가 주석을 `+=`로 붙여 ㉮ 시도마다 **누적**(실재) ㉯ `#`가 YAML 주석처럼 보이나 실제로는 `description` 값 ㉰ 키 부재 시 `KeyError`(잠재 — `description`은 필수 필드이고 `_generate_scenario`가 전부 채웁니다). ㉰을 "잠재"로 적은 것은 시험을 쓰다가 스스로 잡은 과장 정정입니다
  - **`text_equals`는 광고되어 있고 사용 불가였습니다.** `comparator.py`가 `get_page_text()`(= `inner_text("body")`)와 비교했으므로 **페이지 전체가 그 값과 같을 것**을 요구했습니다. AI 어댑터 프롬프트 세 곳이 이 타입을 유효하다고 제시하므로 생성된 대본에 실제로 들어가고, 선택자가 있으면 무조건 실패했습니다. 이제 `target.selector`가 있으면 **그 요소의 글자와 정확히 비교**합니다 — 노출(`\(\text{질량}\)`)을 잡는 유일한 단정입니다. 선택자 + `text_equals`는 이전에 무조건 실패했으므로 **깨뜨리는 변경이 아닙니다**(그 논거도 시험으로 고정)
  - **`text_visible`은 일부러 좁히지 않았습니다.** 페이지 전체 부분일치가 그 타입의 존재 이유이고, 좁히면 통과하던 대본이 빨개집니다. 이 결정도 시험에 적어 두었습니다
  - **파생 수리**: `check`의 여덟 `raise`가 전부 `step=0`을 넘겨 **7번 단계 실패가 `Step 0 (assert)`로 보고**되었습니다 — 콘솔·`last_run.json`·PDF 전부. `_check_as_step`이 `raw_message`로 재부착합니다
  - ~~**신규 발견(미수정, 기록됨)**: `Scenario.expected_result`는 **아무도 읽지 않습니다.** … `display:none` 글자 통과도 같은 성질입니다~~ → **AAT-115 ②③에서 수리 완료**(2026-10-03). 산문 문제는 「산문을 정리한다 / 필드를 폐기한다」가 아니라 **표시를 남겨 그 항목만 경고로 보고**하는 길로 풀었습니다
  - 시험: 실제 Chromium 통합 21건 + `xfail` 2건(`tests/integration/test_text_assertions.py`, 픽스처 `rendered_text_server.py`), CLI 40건. 역변이 18종 전부 잡힘(CLI 9 + 비교기/엔진 9)
  - 표면: CLI 플래그는 늘지 않았으므로(`cli-reference.md` 해당 없음) `SKILL.md`에 절 추가, `scenario-schema.md`·`scenario-template.yaml`은 **생성기(`scripts/gen_scenario_schema.py`)를 통해** 갱신 — `tests/test_docs_sync.py`가 모델과 대조하므로 손질은 다음 생성에서 지워집니다
  - 기록: 보고서 §11-17

### Post-MVP: 판단 대기 세 건 전량 마감 (AAT-115)

- [x] **AAT-115** 보류되어 있던 세 결함을 대표님 지시로 전부 수리 — 완료 2026-10-03
  - 셋 다 「고치면 지금 통과하는 대본이 빨개진다」는 이유로 `xfail(strict=True)`로 못 박아 두었던 것입니다. **지금 저장소에 `xfail`은 한 건도 없습니다** — 세 번 모두 고친 쪽이 아니라 **시험 쪽이 먼저 빨개져서** 「여기를 건드렸다」를 알려 주었습니다
  - **① 학습 좌표의 호스트 구획** (`b65c572`) — 사진 저장소는 AAT-112부터 호스트별로 격리했는데 좌표는 아니어서, `127.0.0.1`에서 배운 클릭이 `localhost`에서, 한 노트북 위의 **다른 제품**에서 재생되었습니다. `host`를 **열쇠의 일부**로 넣었고 **갱신·삽입 조회에도** 넣었습니다 — 조회에서 빠뜨리면 다른 호스트의 행을 덮어쓰면서 이쪽에는 자기 행이 생기지 않아 **둘째 앱에서 학습이 조용히 영영 성립하지 않습니다.** 기존 DB는 `ALTER`로 이관(사용자 학습 보존)하되 그 행들은 `_unscoped`가 아니라 **빈 문자열**입니다 — 「호스트 없는 곳에서 배웠다」와 「어디서 왔는지 모른다」는 다른 주장이고, 출처 불명 좌표에 안전한 처리는 재사용하지 않는 것뿐입니다. `aat learned list`에 `(not reused)`로 보입니다. 시험 중 발견: 넓힌 `state_coords` 인덱스가 열 추가보다 먼저 만들어지고 있었습니다(이관 경로에서만 드러남)
  - **② `expected_result` 평가** (`bbe08b3` + `93de782`) — 보고서가 적어 둔 세 선택지(산문 정리 후 켜기 / 폐기 / 현상 유지)를 **전부 택하지 않고 넷째 길**로 갔습니다. 막힌 자리는 `coerce_expected_result`가 평범한 문장을 `text_visible`로 바꿔 넣어 **저자가 손으로 적은 단정과 구별되지 않는다**는 것이었습니다. `ExpectedResult.from_prose` 한 칸으로 표시를 남겨, 산문 항목만 **경고(종료코드 3)** 로 보고합니다 — 조용히 통과는 원래의 결함이고 실패는 저자의 영어 문장을 탓하는 것이며, 「여기서는 아무것도 검사되지 않았다」만이 사실입니다(AAT-109의 `StepStatus.WARNING` 선례)
  - ②의 설계 결정: **티어다운보다 먼저** 평가(티어다운이 기대가 들여다볼 행과 화면을 지웁니다) / **마지막 단계 번호 다음부터** 번호(같은 리포트를 공유하므로 1부터 다시 세면 읽는 사람이 헷갈립니다) / 치명적 실패로 끝난 대본은 **`SKIPPED`**(아무도 의도하지 않은 자리에서 판정하는 것은 아무도 묻지 않은 질문에 답하는 일입니다) / `aat run`과 `aat loop`이 **같은 평가기**(`evaluate_scenario_expectations`)를 씁니다. AI 어댑터 프롬프트 세 곳에도 "문자열 항목은 경고"를 명시했습니다 — 고치지 않으면 생성기가 계속 산문을 만들어 경고가 가라앉지 않습니다
  - **③ `display:none` 글자** (`dd788c5` + `3ab3635`) — Playwright `innerText`는 **렌더된 요소 위에서는** 숨은 자손을 제외하지만 요소 자체가 렌더되지 않으면 `textContent`로 후퇴하므로, 선택자 경로는 맨 위 요소의 가시성만 물으면 됩니다. `get_by_text(exact=False)`는 숨은 마디까지 집어 오므로 무선택자 경로는 후보를 걸어 확인합니다(`_any_visible_match`). **첫 후보만 보면 안 됩니다** — 낡은 숨은 사본이 문서 순서상 살아 있는 화면보다 **위에** 오는 경우가 흔하고, 그때 멀쩡한 페이지를 실패시킵니다(픽스처에 숨은 것을 먼저 둔 두 벌을 넣은 이유)
  - **모의(mock)의 한계가 다시 드러난 자리**: ③에서 깨진 단위 시험 네 건은 가짜 로케이터에 `is_visible()`·`nth()`가 없어서 깨진 것이지 제품이 틀려서가 아니었습니다. 모의는 시험이 시키는 대로만 대답하므로, 이 수리의 증거는 실제 Chromium 통합 시험이 집니다
  - **일부러 쓰지 않은 시험**: `run_cmd` 배선의 끝에서 끝까지 도는 CLI 시험은 `/dev/tty` 승인 관문을 통과해야 닿고, 보안 규칙이 그 우회를 금지합니다. 대신 소스를 검색해 두 실행기가 평가기를 호출하는지 확인하는 시험을 두고, 설명문에 무엇을 증명할 수 없는지 적어 두었습니다(원래 결함이 **부재**였으므로 부재를 겨냥하는 것이 맞습니다)
  - 검증: ②에서 역변이 7종 전부 잡힘, 전체 **1,184건 통과·`xfail` 0건**, `ruff`·`mypy` 깨끗. 역변이 실행 뒤 `git status`로 작업 트리 청결 확인
  - 기록: 보고서 §11-18

### Post-MVP: Flutter CanvasKit 세 겹 (AAT-116~118)

- [x] **AAT-116** 광고된 OCR 후퇴가 한 번도 적중한 적이 없던 결함 수리 — 완료 2026-10-03
  - 배경: 대표님 지시로 ClasRing(Flutter 웹)을 AWT로 시험 — 23/23 통과했는데 **증거 사진이 전부 □□□(두부)** 였습니다. 통과는 진짜였고(실제 계정 로그인 + 관리자 화면 넷), 읽을 수 없었던 것은 AWT가 남긴 사진입니다. 「통과했다」와 「통과를 보여 줄 수 있다」는 다릅니다
  - `text_visible`은 DOM에서 못 찾으면 사진을 OCR로 읽는다고 문서·스킬·플랫폼 조언이 말합니다. 캔버스 앱은 글자가 **픽셀로만** 있으므로 바로 이 상황을 위한 기능인데, 결함 셋이 겹쳐 **0건 적중**이었습니다
  - **`lang` 미전달** — `image_to_string(img)`은 영어로 읽습니다. 한국어에 대해 구조적으로 불가능한 호출이었고 `MatchingConfig.ocr_languages`는 이 경로에 닿지 않았습니다. `Comparator.__init__`이 언어를 받고 **생성하는 여덟 자리 전부** 넘깁니다
  - **PSM 기본값(3, 전자동)** — 실측: 사진 네 벌(이미지 2종 × 언어 2종)에서 PSM 3은 목표 두 문구를 **하나도** 찾지 못했습니다. 네 벌 전부 적중한 유일한 모드가 6이고 4·11은 6이 놓치는 경우를 건집니다 → `(6, 4, 11)`
  - **공백 미접힘** — Tesseract는 한국어에서 공백을 넣고 뺍니다(`계 정 이`, `학원관리시스템`). 양쪽을 접어 비교합니다
  - **선제적으로 막은 거짓 통과**: AWT 자신의 진행 막대 `#awt-overlay`에 `Text '<기대값>' not visible on page`가 **기대값 글자 그대로** 찍힙니다. OCR이 그것을 읽으면 **실패를 근거로 통과를 보고**합니다. 캡처 전 숨기고 `finally`에서 복원
  - **전처리는 수리가 아니라 거래였습니다**: 역변이 「전처리 제거」가 잡히지 않아 전체 행렬을 실측했더니, 같은 사진에서 한 문구를 건지고 **다른 문구를 잃었습니다.** "더 좋은 이미지"가 아니라 **둘째 이미지**이므로 평범한 흑백을 먼저 쓰고 2배 확대본은 게으르게 만듭니다(첫 벌에서 맞으면 0.5초→1.1초 비용을 내지 않음). 시험은 전처리의 존재가 아니라 **순서 결정**을 고정합니다
  - 실증: `[AWT DEBUG] OCR fallback matched with lang=eng+kor psm=6` / `text_visible '학원 관리 시스템' satisfied by OCR, not the DOM`

- [x] **AAT-117** 늦게 오는 폰트와 그것이 일으키는 다시 그리기를 기다린다 — 완료 2026-10-03
  - 두부의 직접 원인입니다. 한국어 폰트를 등재하지 않은 CanvasKit 앱은 실행 중에 `fonts.gstatic.com`에서 Noto Sans KR을 받아 **다시 그립니다.** 그 전 사진은 두부이고 **DOM은 아무 말도 하지 않습니다** — Semantics 트리는 이미 완전하고 정확합니다. 이 창의 모든 사진이 영향을 받습니다: 증거 이미지·PDF 리포트·시각 회귀 기준선·AAT-116의 OCR이 읽을 사진 자신
  - 실측 기동 시간표(실제 앱): `navigate()` 반환 0.42s → `is_flutter_page` 첫 참 2.57s → 첫 폰트 3개 2.59s(**`done == total`로 끝난 듯 보임**) → 나머지 8개 3.92s(총 11개)
  - **셋째 줄이 구현을 다시 쓰게 만들었습니다.** 「요청한 폰트가 전부 응답했다」는 「요청이 끝났다」와 다릅니다 → 개수가 **1.5초 동안 변하지 않을 것**(`quiet`)까지 요구. 픽셀 안정화 판정은 쓸 수 없습니다(로딩 회전판은 영원히 안정되지 않습니다)
  - 반대 함정: 첫 조회 0건으로 「웹폰트 안 씀」을 결론 내리면 **기다림이 필요한 앱에서만 정확히 건너뜁니다**(CanvasKit은 WASM을 띄우고서야 요청). 첫 요청을 5초까지 기다리고(`appear_timeout`) 폰트를 묶어 넣은 앱은 전체 시한을 물지 않습니다
  - 배선 두 곳: `executor.py`의 navigate 후크(Semantics 활성화 뒤), `scan_cmd.py`는 **스크린샷을 Flutter 감지 뒤로 이동**(전에는 1단계에서 먼저 찍었습니다)

- [x] **AAT-118** Flutter 후크가 콜드 로드에서 **한 번도** 실행된 적이 없었음 — 완료 2026-10-03
  - AAT-117을 배선해도 로그가 나오지 않아 두 번 더 파고든 끝에 나온 **선재(pre-existing) 결함**입니다. navigate 후크가 `is_flutter_page`로 자신을 보호하는데, 그 검사는 **2.57초**에 처음 참이 되고 후크는 **0.42초**에 묻습니다. 아니라는 답을 듣고 Semantics 활성화도 폰트 대기도 하지 않습니다 — **기능 출시 이후 콜드 로드에서 단 한 번도 실행된 적이 없습니다**
  - **왜 아무도 몰랐는가가 핵심입니다.** Flutter를 건드리는 모든 대본에 손으로 맞춘 `wait: "10000"`이 있었습니다. 우회가 **모든 대본에** 있었으므로 구멍이 보이지 않았습니다. 저자는 "Flutter는 느리니 기다려야 한다"고 배웠고 실제로는 "AWT가 기다려 주지 않으니 네가 기다려라"였습니다
  - `wait_until_flutter_ready` 신설 — `flutter_bootstrap.js`(구버전 `main.dart.js`·`flutter.js`)가 **서버가 보낸 HTML에 첫 바이트부터** 있습니다. 없으면 즉시 반환하므로 평범한 사이트는 `evaluate` 한 번 외에 비용이 없습니다(시험으로 고정)
  - **플랫폼 조언 정정**: Flutter 조언 첫 줄이 *"`find_and_type` 대신 `click_at`+`type_text`를 쓰라(입력란이 숨어 있다)"* 였습니다. 실측이 뒤집었습니다 — `find_and_type`이 모든 입력란에 닿아 23/23. 조언이 **작동하는 길에서 사용자를 떼어내어** 화면이 조금만 흐르면 깨지는 손좌표로 보내고 있었습니다
  - **사용자에게 돌아간 몫**: `SC-901`과 같은 흐름에서 **`wait` 단계를 전부 뺀** 대본으로 **5/5 통과·29,981ms**, 마지막 사진은 또렷한 한국어. §0 기준에서 보면 이 세 겹의 결과는 **대본에서 숫자 하나를 지운 것**입니다
  - **제가 넣은 결함 하나**: `_FONT_URL_RE`를 r-문자열로 바꾸면서 JS에 `\\.`(역슬래시 + 임의 문자)를 내보냈습니다. 기존 시험은 자원 0건 페이지에서만 돌아 잡지 못했습니다. 실제 `.woff2`를 내려 주고 탐침이 찾도록 강화한 뒤 역변이로 확인 — **파이썬에 맞게 탈출한 정규식은 JS로서도 유효하고, 유효한 채로 아무것도 매칭하지 않습니다**
  - 검증: 역변이 3종(후크를 `is_flutter_page`로 되돌리기 / 로더 없는 페이지도 기다리게 하기 / 기동 반복문 제거) 전부 잡힘. 전체 **1,209건 통과**(수리 전 1,184건), `ruff`·`mypy` 깨끗
  - 시험: OCR 후퇴 11건(`tests/test_engine/test_comparator.py`, 실패 화면을 잘라낸 픽스처 사진 포함), 폰트·기동 대기 14건(`tests/test_engine/test_flutter_fonts.py`, 실제 Chromium 탐침 1건 포함)
  - 기록: 보고서 §11-19

- [x] **AAT-119** 언어 데이터가 없으면 `doctor`가 말해 준다 — 완료 2026-10-03
  - **CI가 사용자의 실패를 그대로 재현해 주었습니다.** AAT-116을 올리자 한국어 OCR 증명 시험 다섯 건이 `Text '학원 관리 시스템' not visible on page`로 빨개졌습니다 — 러너가 `tesseract-ocr`만 깔고 `tesseract-ocr-kor`를 깔지 않았기 때문입니다. **그 문장이 사용자가 보는 문장과 똑같습니다**
  - 이것은 AAT-114·§11-14가 두 번 만난 「초록불이 빨간불로 갈 수 없는」 자리입니다. `_check_tesseract`는 **실행 파일이 있는지만** 물었고, Tesseract는 문서가 다루는 모든 플랫폼에서 **영어만** 깔립니다. 묶음이 없으면 `image_to_string`이 예외를 내고 후퇴가 그것을 삼켜 「글자가 안 보인다」로 보고합니다 — 페이지는 멀쩡한데 **진단이 페이지를 탓합니다**
  - `doctor`가 `matching.ocr_languages`를 `tesseract --list-langs`와 대조하고, 없는 언어와 **증상 문구**("reads as 'not visible on page'")를 함께 알립니다 — 증상을 적지 않으면 사용자가 지금 보고 있는 실패와 연결하지 못합니다
  - **경고이고 실패가 아닙니다.** 영어만 쓰는 앱에 영어만 깔린 것은 **올바른 설치**이고, 거기에 빨간불을 켜면 아무 문제 없는 사람의 `doctor`가 0이 아닌 값으로 끝납니다. `--list-langs`를 읽을 수 없으면 **아무 말도 하지 않습니다**(묶음이 있을 수도 있으므로, 가진 것을 설치하라고 보내는 것보다 침묵이 낫습니다)
  - CI 두 워크플로에 `tesseract-ocr-kor` 추가 + 시험에 `requires_korean_ocr` 건너뛰기. **건너뛰기는 CI가 아니라 기여자를 위한 것입니다** — apt 목록이 모자란 사람에게 「네 코드가 틀렸다」고 말하는 빨간 시험은 시험을 무시하는 습관을 가르칩니다
  - 시험 6건(`TestTesseractLanguageCheck`): 없는 언어 보고 / 다 있으면 **침묵** / 물을 수 없으면 침묵 / 머리글 줄 제외 파싱 / 설정에서 읽기 / **묶음이 없어도 `_check_tesseract`는 통과**
  - 기록: 보고서 §11-19 ④

### Post-MVP: 두 좌표계를 한 변수에 담고 있던 결함 (AAT-120)

- [x] **AAT-120** 화면 픽셀이 뷰포트 클릭으로 흘러가 엉뚱한 곳을 누르고 성공으로 보고하던 결함 수리 — 완료 2026-10-04
  - **발견 경로가 대표님의 반론입니다.** 네이티브 앱 질문에 제가 "시뮬레이터 화면은 DOM이 없으니 안 된다"고 틀리게 답했고, 대표님이 *"OCR과 tesseract로 이미지를 읽어서 필요한 요소들을 찾아내는 방식은 동일한거 아냐?"* 라고 되물으셨습니다. 맞는 지적입니다 — OCR은 **DOM이 필요 없는 바로 그 경로**입니다. 확인하러 코드를 다시 읽다가 이 결함이 나왔습니다
  - 좌표계가 둘입니다. `engine.click()`은 **뷰포트 CSS 픽셀**, `engine.screenshot()`은 엔진이 찍을 수 있는 것 — `DesktopEngine`은 **화면 전체를 물리 해상도로** 찍습니다. **그 차이에 이름이 없어서** 실행기가 모든 스크린샷을 뷰포트로 취급했고, 화면 픽셀이 `page.mouse.click`에 들어가 **엉뚱한 클릭을 매칭 성공으로 보고**했습니다. 실측: `pag.size()` 1680×1050 vs `pag.screenshot()` 3360×2100 = 2.0배. `desktop.py:183`의 `_device_pixel_ratio`는 **아무도 읽지 않는 죽은 필드**였습니다
  - **여섯 겹** — ①매처 체인의 클릭 ②치유의 클릭 ③**사진 적립의 잘라내기**(CSS 상자로 화면 사진을 잘라 엉뚱한 영역을 「이 요소의 사진」으로 저장 → 다음 실행이 거기서 치유해 잘못된 클릭을 재현하고 통과로 보고. AAT-112가 경고해 둔 고리입니다) ④뷰포트·내비 경고가 화면 좌표마다 발화 ⑤좌표 학습에 두 공간 혼재 ⑥**선재 결함** `find_on_screen` → `click_on_screen`이 물리 픽셀을 논리 점으로 넘겨 HiDPI에서 2배 어긋남
  - **좌표계를 엔진이 선언**합니다(`ScreenshotSpace.VIEWPORT | SCREEN`) — 자기 창이 화면 어디에 있고 논리 1점이 몇 픽셀인지 아는 것은 엔진뿐입니다. `BaseEngine`에 **항등 변환 + `VIEWPORT` 기본값**을 두어 `WebEngine`과 모든 시험 대역은 한 글자도 고치지 않았습니다. 버린 대안: `DesktopEngine.screenshot()`을 페이지 공간으로 바꾸기 — 수치는 맞지만 **대표님이 짚으신 전체 화면 OCR의 문을 닫습니다**
  - **축척은 측정합니다.** `window.devicePixelRatio`는 두 번 틀립니다 — *페이지의* 비율이어서 브라우저 확대가 움직이지만 디스플레이 배킹 축척은 움직이지 않고, 헤드풀 브라우저는 **다른 모니터 위에 있을 수** 있습니다. 두 축의 비가 어긋나면(다중 디스플레이 캡처) 1.0으로 물러나고 그 상황을 이름으로 적습니다
  - ⑤는 변환하지 않고 **저장하지 않습니다.** `state_coords`에는 위치 열이 한 쌍뿐이고 `_act_on_learned_coords`가 `click()`으로 재생하므로, 모호하게 저장하면 AAT-109의 조용한 헛클릭이 뒷문으로 돌아옵니다
  - **왜 아무도 몰랐는가**: 뷰포트 엔진에서는 **두 갈래가 같은 일을 합니다.** 공간이 갈라지는 유일한 엔진은 거의 아무도 쓰지 않는 쪽이라, 1,215건이 초록인 채로 살아 있었습니다 — §11-14의 「초록불이 빨간불로 갈 수 없는」 네 번째 자리입니다
  - **철회한 혐의**: `_crop_to_region`도 처음에 올렸으나, `_crop_screenshot`(`executor.py:3502`)은 **이미지 자신의 `h, w`를 쓰고** `viewport` 인자를 읽지 않습니다. 잘라내기는 원래 옳았고 남은 것은 죽은 인자뿐입니다
  - 시험 25건(`tests/test_engine/test_coordinate_space.py`). 화면 공간 엔진 대역은 **손으로 썼습니다** — `MagicMock`은 `screenshot_space`에 모의로 답하고 그것은 `ScreenshotSpace`가 아니므로, 실행기가 뷰포트로 읽어 **아무것도 재지 않으면서 초록**이 됩니다
  - 검증: 역변이 7종 전부 잡힘, 전체 **1,240건 통과**(수리 전 1,215건), `ruff`·`mypy` 깨끗
  - 기록: 보고서 §11-20

---

## 협업 프로젝트 연동 (ClasRing + DSL)

### 나의 역할
김대리(ClasRing)와 DSL이 만든 코드를 AWT로 E2E 테스트하는 것이
협업에서의 주 역할. 테스트 결과를 shared 디렉토리에 전달한다.

### 공유 디렉토리 경로
- 내가 받는 곳:
  - `~/Documents/Projects/shared/handoff/dsl-to-lee/`
    → DSL이 생성한 코드 변형이 여기 들어옴.
      AWT로 E2E 테스트를 수행해야 함.
  - `~/Documents/Projects/shared/handoff/kim-to-lee/`
    → 김대리가 직접 테스트 요청한 코드가 여기 들어옴.

- 내가 보내는 곳:
  - `~/Documents/Projects/shared/handoff/lee-to-dsl/`
    → AWT 테스트 결과(last_run.json, 스크린샷)를 여기에 넣음.
      DSL이 이걸 점수에 반영함.
  - `~/Documents/Projects/shared/handoff/lee-to-kim/`
    → 김대리에게 전달할 테스트 결과를 여기에 넣음.

### 테스트 결과 전달 규칙
- 결과를 넣을 때는 반드시 아래 구조를 따를 것:
  ```
  lee-to-dsl/ 또는 lee-to-kim/
  └── page-name_YYYYMMDD/       (예: admin-dashboard_20260327)
      ├── last_run.json          (AWT 실행 결과)
      ├── screenshots/           (스텝별 스크린샷)
      └── summary.md             (통과/실패 요약, 발견된 문제점)
  ```

---

## Branch Strategy

- **main**: 단일 개발+배포 브랜치. 모든 작업은 main에서 직접 진행.
- **dev**: 보관용 (더 이상 사용하지 않음). main과 동기화된 상태로 유지.
- 작업 시작 전 반드시 `git checkout main` 확인.
- Vercel: main = Production
- Render: main auto-deploy

---

## Current Status

- **현재 단계**: 보고서(`docs/awt_project_analysis_and_strategy.md`) **1~3순위 + 판단 대기 3건 전량 마감**(AAT-115까지), 그 위에 **Flutter CanvasKit 세 겹 수리**(AAT-116~118)와 그 CI가 드러낸 `doctor` 결손(AAT-119), 그리고 대표님의 반론이 드러낸 **좌표계 혼용**(AAT-120)을 더했습니다. 다음 작업은 품질 수리가 아니라 **등재와 홍보**이고, 미결 사항은 **`1.8.0` 배포 승인**입니다
- **완료**: Phase 1~6 (Ultra-MVP) + AAT-060~065 + AAT-070~076 + AAT-080~081 + AAT-090~092 + AAT-093~095 + AAT-100~120 (Post-MVP)
- **블로커**: 없음. 판단 대기도 없습니다 — 세 건 모두 AAT-115에서 수리했고, 저장소에 `xfail(strict=True)`는 **한 건도 남아 있지 않습니다**
- **Flutter 웹 실측 상태**(2026-10-03): ClasRing CanvasKit 앱에서 **23/23 통과**, `wait` 단계를 전부 뺀 대본도 **5/5 통과**, 증거 사진의 한국어가 또렷합니다. Semantics 라벨 기반 `find_and_click`·`find_and_type`를 권하십시오 — 손좌표를 권하던 이전 조언은 실측으로 뒤집혔습니다(AAT-118)
- **Python**: 3.12.12 (.venv), `source .venv/bin/activate`
- **GitHub**: https://github.com/ksgisang/AI-Watch-Tester (public)
