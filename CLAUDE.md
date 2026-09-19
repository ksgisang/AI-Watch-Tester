# AAT (AI Auto Tester) — Project Guide

## Overview

AI 기반 DevQA Loop 오케스트레이터. 이미지 매칭으로 UI 테스트를 자동화하고, 실패 시 AI가 코드를 수정하고 재테스트하는 루프를 반복한다.

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
- [x] **AAT-015** FeatureMatcher — ORB/SIFT (4h) — 완료 2026-02-11
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
- [x] **AAT-052** VisionAIMatcher — stub (2h) — 완료 2026-02-11
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
- [x] **AAT-081** DesktopEngine — PyAutoGUI + Playwright 하이브리드 — 완료 2026-02-12
  - PyAutoGUI (OS-level 마우스/키보드/스크린샷) + Playwright (브라우저 네비게이션)
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

- **현재 단계**: Coordinate Learning 신뢰성 수정 완료 (AAT-109)
- **완료**: Phase 1~6 (Ultra-MVP) + AAT-060~065 + AAT-070~076 + AAT-080~081 + AAT-090~092 + AAT-093~095 + AAT-100~109 (Post-MVP)
- **블로커**: 없음
- **Python**: 3.12.12 (.venv), `source .venv/bin/activate`
- **GitHub**: https://github.com/ksgisang/AI-Watch-Tester (public)
