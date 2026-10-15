<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-light.png">
    <img alt="AWT Logo" src="docs/assets/logo-light.png" width="300">
  </picture>
  <br/>
  <strong>AWT — AI Watch Tester</strong>
  <br/>
  <em>E2E 테스트 짜는 게 지겨워서, 직접 테스트를 만들고 고치는 도구를 만들었습니다.</em>
  <br/><br/>
  <a href="https://github.com/ksgisang/AI-Watch-Tester/actions"><img src="https://img.shields.io/github/actions/workflow/status/ksgisang/AI-Watch-Tester/ci.yml?label=CI&logo=github" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?logo=opensourceinitiative&logoColor=white" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://ai-watch-tester.vercel.app"><img src="https://img.shields.io/badge/Cloud-바로_시작-00d4aa?logo=vercel&logoColor=white" alt="Cloud"></a>
  <a href="https://github.com/ksgisang/awt-skill"><img src="https://img.shields.io/badge/Agent_Skill-사용_가능-brightgreen?logo=npm&logoColor=white" alt="Agent Skill"></a>
  <a href="https://github.com/ksgisang/AI-Watch-Tester/stargazers"><img src="https://img.shields.io/github/stars/ksgisang/AI-Watch-Tester?style=flat&logo=github" alt="GitHub Stars"></a>
</p>

---

<p align="center">
  <a href="docs/assets/demo.mp4">
    <img src="docs/assets/demo.gif" alt="AWT 데모 — 설치, 실행, 자가 수복" width="860">
  </a>
  <br/>
  <sub><em>30초 데모: 설치 → 테스트 실행 → AI 자가 수복</em></sub>
</p>

---

## 왜 만들었나

Flutter 웹 앱을 개발하고 있었습니다. UI가 바뀔 때마다 Playwright 테스트가 깨졌습니다. 셀렉터 고치고, 플로우 다시 녹화하고, assert 업데이트하고 — 매주 몇 시간씩 날아갔습니다.

그래서 페이지를 보고 스스로 테스트를 만들고, 테스트가 깨지면 원인을 분석해서 혼자 고치는 도구를 만들기 시작했습니다.

그게 AWT입니다.

완벽하진 않습니다. OCR 기반 매칭은 특정 폰트에서 오작동하기도 합니다. 자가 수복 루프가 가끔 엉뚱한 곳을 건드리기도 합니다. 그래도 제 일상적인 QA 작업에서는 — 특히 Cypress도 못 건드리는 Canvas/Flutter Web 앱에서는 — 충분히 잘 동작해서, 테스트 코드를 직접 짜는 일을 완전히 그만뒀습니다.

**같은 고통을 겪고 있는 분이 있을 것 같아서 공유합니다. 셀렉터 고치는 데 오후를 통째로 날려본 적 있다면, 시간을 아낄 수 있을 겁니다.**

---

## 뭘 하는 도구인가

URL을 주면 AWT가 실제 Chrome 창을 열고, 페이지를 읽고, 테스트 스텝을 작성하고, 실행하고, 통과/실패 결과를 알려줍니다. 뭔가 깨지면 **DevQA Loop**가 작동합니다 — AI가 에러를 읽고, 테스트를 패치하고, 자동으로 재시도합니다 (최대 5회).

**테스트 코드를 직접 짤 필요 없습니다. 녹화 세션도 없습니다. UI가 바뀌어도 수동 업데이트가 없습니다.**

---

## 5분 안에 시작하기

### 방법 1 — Agent Skill (Claude Code, Cursor, Copilot 등과 함께)

```bash
# 한 줄 설치
npx skills add ksgisang/awt-skill --skill awt -g

# 그 다음 AI 도구에게:
"http://localhost:3000 로그인 플로우 테스트해줘"
"회원가입 폼 잘 작동하는지 확인해줘"
"마지막 커밋 이후 회귀 테스트 돌려줘"
# → AWT가 스캔, 스텝 생성, 실행, 리포트
```

### 방법 2 — MCP 서버 (Claude Desktop, Cursor, Windsurf)

```bash
# 설치
pip install aat-devqa

# Claude Code — 플러그인 하나로 스킬과 MCP 서버가 함께 들어옵니다
claude plugin marketplace add ksgisang/awt-skill
claude plugin install ai-watch-tester@awt

# 사용 가능한 도구: aat_devqa, aat_scan, aat_run, aat_run_skill_mode, aat_doctor,
#                  aat_list_scenarios, aat_validate, aat_cost,
#                  aat_generate_from_doc, aat_snapshot, aat_diff, aat_watch
```

서버를 손으로 등록하거나 Claude Desktop·Cursor·Windsurf에서 쓰시려면
[`mcp/README.md`](mcp/README.md)를 보십시오. 서버 파일 자체는 플러그인 번들의
[`awt-skill/mcp/server.py`](https://github.com/ksgisang/awt-skill/blob/main/mcp/server.py)
한 벌뿐입니다.

> **클라우드 & 로컬 CLI** 버전은 현재 개발 중이며 별도로 공개 예정입니다.

---

## 동작 방식

```
URL을 입력하면
        │
        ▼
  🔍 SCAN — Chrome을 열고 버튼, 입력창, 링크를 모두 읽는다
        │
        ▼
  📝 GENERATE — AI가 단계별 테스트 플랜 작성 (검토 후 승인)
        │
        ▼
  ▶️  RUN — 실제 사용자처럼 클릭, 타이핑, 네비게이션
        │
        ├── ✅ 모두 통과 → 스크린샷 리포트 저장
        │
        └── ❌ 실패
                    │
                    ▼
            🔄 DEVQA LOOP — AI가 실패를 읽고,
               테스트(또는 소스 코드)를 수정하고,
               재시도 (최대 5회)
```

---

## DevQA Loop — 핵심 기능

대부분의 테스트 도구는 실패하면 멈추고 사람을 기다립니다. **AWT는 계속 진행합니다.**

스텝이 실패하면 AWT는:
1. 브라우저 화면 스크린샷 캡처
2. 에러 메시지와 화면에 보이는 콘텐츠 분석
3. 페이지 재스캔 — 요소가 이동하거나 변경됐는지 확인
4. 실패한 특정 스텝만 패치하고 재시도

실패 원인이 **셀렉터 문제가 아닌 소스 코드 버그**라면, AWT가 라우트 핸들러, 컴포넌트, API 엔드포인트까지 추적해서 수정안을 제안하거나 직접 적용할 수 있습니다.

```bash
# 루프 실행 실시간으로 보기
aat devqa "체크아웃 플로우 테스트" --url http://localhost:3000

# AI 코딩 도구와 함께 사용 (Claude Code, Cursor, Copilot...)
# "회원가입 페이지 테스트해줘" → AWT가 스캔, 생성, 실행, 수정
```

---

## 4가지 사용 방법

| | **클라우드** | **로컬 CLI** | **Agent Skill** | **MCP 서버** |
|---|-----------|---------------|-----------------|----------------|
| **시작 방법** | [ai-watch-tester.vercel.app](https://ai-watch-tester.vercel.app) 회원가입 | `pip install aat-devqa` | `npx skills add ksgisang/awt-skill` | `pip install aat-devqa mcp` |
| **브라우저** | 헤드리스 (서버) | 내 머신의 실제 Chrome | 내 머신의 실제 Chrome | 내 머신의 실제 Chrome |
| **AI 키 필요** | 불필요 (서버 제공 또는 BYOK) | 필요 (OpenAI / Anthropic / Ollama) | **불필요** — AI 도구가 두뇌 역할 | **불필요** |
| **적합한 용도** | 빠른 테스트, 기획자, PM | 개발자, CI/CD | AI 보조 개발 | Claude Desktop, Cursor, Windsurf |
| **가격** | 무료 (5회/월) · Pro $28.99 · Team $98.99 | 영구 무료 (MIT) | 영구 무료 | 영구 무료 |

### Agent Skill — AI 코딩 도구가 AWT를 직접 제어

```bash
# 한 줄 설치
npx skills add ksgisang/awt-skill --skill awt -g

# 그 다음 AI 도구에게:
"http://localhost:3000 로그인 플로우 테스트해줘"
"회원가입 폼 잘 작동하는지 확인해줘"
"마지막 커밋 이후 회귀 테스트 돌려줘"
# → AWT가 스캔, 테스트 스텝 생성, 실행, 리포트
```

### MCP 서버 — 프로토콜 네이티브

```bash
# Claude Code에 추가
claude plugin marketplace add ksgisang/awt-skill
claude plugin install ai-watch-tester@awt

# 사용 가능한 도구: aat_devqa, aat_scan, aat_run, aat_run_skill_mode, aat_doctor,
#                  aat_list_scenarios, aat_validate, aat_cost,
#                  aat_generate_from_doc, aat_snapshot, aat_diff, aat_watch
```

---

## AI 하네스의 Quality Gate로 AWT 사용하기

**GSD (Get Shit Done)**, **Cursor Rules**, **CLAUDE.md** 등 어떤 AI 코딩 워크플로우를 쓰든 — AWT는 AI가 놓친 것을 잡아내는 **Verify 단계**로 연결됩니다.

### GSD 워크플로우 연동

```
Discuss → Plan → Execute → Verify (AWT)
                              │
                    aat_generate_from_doc(PLAN.md)
                              │
                    → 시나리오 자동 생성
                    → aat_run_skill_mode 실행
                    → 통과/실패 리포트
```

```bash
# MCP: GSD 플랜 파일로 테스트 시나리오 생성
"PLAN.md로 테스트 시나리오 만들고 실행해줘"
# → AWT가 플랜을 읽고, E2E 테스트를 만들어 실제 Chrome에서 실행

# CLI: 같은 동작
aat generate --from PLAN.md
aat run scenarios/
```

### CLAUDE.md / Cursor Rules에 AWT 추가하기

```markdown
## QA 검증 (AWT)
- 코드 작성 후 커밋 전에 반드시 AWT로 검증할 것.
- 실행: aat scan --url {URL} → 시나리오 확인 → aat run
- 모든 테스트 통과 전에는 태스크를 완료로 표시하지 말 것.
```

이렇게 하면 AWT가 **자동화된 품질 게이트** 역할을 합니다 — AI가 코드를 짜고, AWT가 동작을 검증하고, 전부 통과할 때까지 루프가 계속됩니다.

### 종료 코드

| 코드 | 의미 |
|------|------|
| `0` | 모든 단계가 통과했고 검증까지 되었습니다 |
| `1` | 단계가 실패했습니다 (`--strict`에서는 건너뛴 단계도 포함됩니다) |
| `2` | `critical: true`로 표시한 단계가 실패해서 거기서 중단했습니다 |
| `3` | 실패한 단계는 없지만 실제로 검증되지 않은 것이 있습니다 |

파이프라인에 연결할 가치가 있는 것은 `3`입니다. 예전에 AWT가 통과로 보고하던
경우들이 여기에 들어갑니다: 화면을 전혀 움직이지 못한 클릭, 단계가 지목한 칸이
아닌 다른 칸으로 들어간 글자, `disabled`이거나 `readonly`였던 표적, 그리고
평범한 문장으로 적혀서 아무것도 검사되지 않은 대본 수준의 `expected_result`.
`3`을 실패로 취급하는 편이 더 엄격하고 쓸모 있으며, 통과로 취급하면 이전과
같은 동작이 됩니다.

---

## 비주얼 리그레션 — UI 변경을 자동으로 감지

코드 수정 전후 스크린샷을 비교해서 의도하지 않은 UI 변경을 잡아냅니다. **AI 토큰 제로** — 순수 Playwright + OpenCV.

```bash
# 1단계: 기준선 캡처 (코드 수정 전)
aat snapshot scenarios/login.yaml --url http://localhost:3000

# 2단계: 코드 수정 후 비교
aat diff scenarios/login.yaml --url http://localhost:3000

# 결과:
# step001  99.8%  ✅ PASS
# step002  87.3%  ❌ FAIL  ← UI 변경 감지
# step003 100.0%  ✅ PASS
```

### 반응형 — 3종 뷰포트 한번에 테스트

```bash
# 모바일 + 태블릿 + 데스크톱 기준선 캡처
aat snapshot scenarios/ --url http://localhost:3000 --responsive

# 3종 뷰포트 비교
aat diff scenarios/ --url http://localhost:3000 --responsive

# 단일 커스텀 뷰포트 지정
aat snapshot scenarios/ --viewport 414x896
```

| 뷰포트 | 크기 | 용도 |
|----------|------|----------|
| mobile | 375×812 | iPhone급 기기 |
| tablet | 768×1024 | iPad급 기기 |
| desktop | 1280×720 | 일반 데스크톱 |

### 콘솔 에러 수집

```bash
# 기준선 캡처하면서 JS 에러 체크
aat snapshot scenarios/ --url http://localhost:3000 --console

# 콘솔 에러가 있으면 실패 처리
aat snapshot scenarios/ --url http://localhost:3000 --console-fail
```

시각적 검사를 통과해도 숨어있는 JS 에러를 잡아냅니다 — `TypeError`, 네트워크 404, 미처리 예외.

### diff 이미지 자동 열기

```bash
# 실패한 diff 이미지를 시스템 뷰어로 자동 열기
aat diff scenarios/ --url http://localhost:3000 --open

# → macOS: Preview로 열기
# → Linux: xdg-open으로 열기
```

### Watch 모드 — 파일 저장 시 자동 테스트

```bash
aat watch scenarios/ --url http://localhost:3000
# → 파일 저장하면 테스트 자동 실행
# → 기준선 있으면 비주얼 diff 포함
# → Ctrl+C로 종료
```

- 시나리오 파일 변경 → 해당 시나리오만 재실행
- 소스 파일 변경 → 전체 시나리오 실행 (전체 리그레션)
- [watchfiles](https://github.com/samuelcolvin/watchfiles) (Rust 기반) 사용, 폴링 폴백 지원

### PR 코멘트 (GitHub Action)

```bash
# PR 코멘트용 마크다운 출력
aat diff scenarios/ --format=github

# JSON 출력 (다른 도구 연동용)
aat diff scenarios/ --format=json
```

`.github/workflows/visual-regression.yml` 템플릿이 포함되어 있습니다 — 저장소에 넣으면 모든 PR에 자동으로 비주얼 리그레션 코멘트가 달립니다.

---

## AWT가 잘하는 것

| | 기능 | 설명 |
|---|---------|-------------|
| 🤖 | **제로 코드 테스트 생성** | URL만 입력하면 AI가 실제 셀렉터 포함 완전한 테스트 스텝 생성 |
| 🔄 | **자가 수복 DevQA Loop** | 테스트 실패? AI가 자동으로 수정하고 재시도 (최대 5회) |
| 👁️ | **시각적 검증** | 모든 액션 전후 스크린샷 — DOM 체크만이 아님 |
| 🌐 | **실제 브라우저** | 인간 같은 마우스 움직임과 타이핑 속도의 Chrome |
| 📱 | **Flutter 지원** | CanvasKit + Semantics 감지 — Flutter Web 앱도 테스트 가능 |
| 📄 | **문서 기반 생성** | PDF/DOCX 스펙을 주면 AI가 요구사항에서 테스트를 생성 |
| ⚡ | **속도 모드** | React/Next.js는 `fast` · Flutter/애니메이션은 `slow` |
| 📸 | **스마트 스크린샷** | `all` / `before-after` / `on-failure` — 필요에 맞게 선택 |
| 🔌 | **플러그인 아키텍처** | 엔진, 매처, AI 제공자를 레지스트리로 교체 가능 |
| 📊 | **비주얼 리그레션** | SSIM 기반 스크린샷 비교 — AI 토큰 제로, 순수 OpenCV |
| 📱 | **반응형 테스트** | 모바일/태블릿/데스크톱 뷰포트를 한 명령으로 (`--responsive`) |
| 🖥️ | **Watch 모드** | 파일 저장 시 자동 테스트 — 즉각적인 피드백 루프 |
| 🔍 | **콘솔 에러 캡처** | 시각적 검사를 통과해도 숨은 JS 에러를 잡아냄 (`--console`) |

---

## 알려진 한계 (솔직하게)

저는 잘 쓰고 있지만, 아직 완전히 해결하지 못한 부분이 있습니다:

- **OCR 매칭**은 커스텀 폰트나 저대비 UI에서 오작동할 수 있습니다 — 이럴 때는 DOM 셀렉터로 대체하세요
- **자가 수복 루프**가 가끔 엉뚱한 요소에 집착하기도 합니다. `--max-attempts 3`으로 무한 루프를 방지하세요
- **애니메이션이 많은 SPA**는 `--verbosity=detailed`와 더 긴 대기 시간이 필요할 수 있습니다
- **첫 시나리오 생성** 품질은 페이지의 접근성 트리 품질에 달려 있습니다 — HTML 구조가 엉망이면 결과도 엉망입니다

뭔가 잘 안 되면 [이슈를 열어주세요](https://github.com/ksgisang/AI-Watch-Tester/issues). 빠르게 고칩니다.

---

## 다른 도구와 비교

### vs Playwright / Cypress

Playwright와 Cypress는 훌륭한 도구입니다 — AWT도 Playwright 위에 만들어졌습니다. 차이는 **누가 테스트를 작성하느냐**입니다:

| | **AWT** | **Playwright / Cypress** |
|---|---------|--------------------------|
| 테스트 작성자 | AI (URL에서 자동 생성) | 개발자 (코드 작성) |
| UI 변경 시 유지보수 | AI가 자동으로 수복 | 셀렉터를 수동으로 업데이트 |
| 러닝커브 | 없음 — URL만 붙여넣기 | 중간 (프레임워크 API + JS/TS) |
| 유연성 | 높음 (YAML 시나리오) | 최대 (완전한 코드 제어) |

**완전한 프로그래밍 제어**가 필요하면 Playwright/Cypress를 쓰세요. **테스트를 직접 짜고 싶지 않을 때** AWT를 쓰세요.

### vs testRigor

| | **AWT** | **testRigor** |
|---|---------|---------------|
| 테스트 작성 | AI가 URL에서 자동 생성 — 아무것도 안 써도 됨 | 평이한 영어로 명령 작성 |
| 자가 수복 | DevQA Loop (AI가 자동 재생성) | 내장 자동 유지보수 |
| 가격 | 무료 (MIT, 셀프 호스팅) | 엔터프라이즈 (~$800+/월) |
| 오픈소스 | ✅ MIT 라이선스 | ❌ |

### vs Applitools

Applitools는 AI 기반 **비주얼 리그레션**에 특화되어 있습니다. AWT도 이제 자체 비주얼 리그레션(SSIM 기반, AI 토큰 제로)을 갖추고 있으며, **기능 테스트**까지 함께 합니다. 브라우저/뷰포트 간 픽셀 퍼펙트 비교가 필요하면 Applitools가 더 성숙합니다. 하지만 AWT는 기능 + 시각 테스트를 하나의 무료 도구로 제공합니다.

---

## 속도 & 스크린샷 모드

꼼꼼함과 속도 사이의 균형을 조절하세요:

```bash
# CI/CD — 가장 빠름, 저장 최소화
aat run --verbosity=concise --screenshots=on-failure scenarios/

# 일반 QA — 균형 (권장)
aat run --verbosity=concise --screenshots=before-after scenarios/

# 전체 감사 — 모든 스텝 기록
aat run --verbosity=detailed --screenshots=all scenarios/
```

| 모드 | 스텝 수 | 스크린샷 수 | 소요 시간 | 용도 |
|------|-------|-------------|-------|---------|
| `concise` + `on-failure` | 12–15 | 0–1 | ~1분 | CI/CD 게이트 |
| `concise` + `before-after` | 12–15 | 24 | ~2분 | 일상 QA |
| `detailed` + `all` | 60–80 | 68 | ~5분 | 컴플라이언스 / 감사 |

---

## 지원하는 AI 제공자

| 제공자 | 모델 | 비용 | 설정 |
|----------|--------|------|-------|
| **OpenAI** | gpt-4o, gpt-4o-mini | 사용량 과금 | `export OPENAI_API_KEY=sk-...` |
| **Anthropic** | Claude Sonnet 4 | 사용량 과금 | `export ANTHROPIC_API_KEY=sk-ant-...` |
| **Ollama** | codellama, llama3, mistral | 무료 (로컬) | `ollama serve` |

```yaml
# aat.yaml
ai:
  provider: openai        # openai | anthropic | ollama
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
```

---

## 아키텍처

```
aat devqa / aat run / aat snapshot / aat diff / aat watch
              │
              ▼
    ┌─────────────────────────────────────┐
    │           CLI (Typer)               │
    ├─────────────────────────────────────┤
    │         Core Orchestrator           │
    │  Executor · Comparator · DevQALoop  │
    ├────────────┬──────────┬─────────────┤
    │   Engine   │ Matcher  │  AI Adapter │
    │ web/desktop│ocr/cv/ai │ openai/etc. │
    ├────────────┴──────────┴─────────────┤
    │  Visual Regression · Watch Mode     │
    ├─────────────────────────────────────┤
    │  Pydantic v2 Models · SQLite Learn  │
    └─────────────────────────────────────┘
```

모든 모듈은 **플러그인 레지스트리** 패턴을 따릅니다 — 베이스 클래스 하나 구현하고 `__init__.py`에 등록하면 새 엔진, 매처, AI 제공자를 추가할 수 있습니다.

---

## 개발 환경

### 사전 요구사항

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract): `brew install tesseract` / `apt install tesseract-ocr`

### 명령어

| 명령어 | 설명 |
|---------|-------------|
| `make dev` | 전체 의존성 + Playwright + pre-commit 설치 |
| `make lint` | 코드 스타일 검사 (ruff) |
| `make format` | 자동 포매팅 |
| `make typecheck` | 엄격한 타입 검사 (mypy) |
| `make test` | 전체 테스트 실행 (pytest) |
| `make test-cov` | 테스트 + 커버리지 리포트 |

```bash
git clone https://github.com/ksgisang/AI-Watch-Tester.git
cd AI-Watch-Tester
python -m venv .venv && source .venv/bin/activate
make dev
make test        # 정상 동작 확인
aat dashboard    # http://localhost:9500 에서 실행
```

---

## 기여하기

기여, 버그 리포트, 새 플러그인 모두 환영합니다 — [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

PR 전에 이슈를 먼저 열어주세요. 같이 방향을 잡는 게 더 빠릅니다.

```bash
git checkout -b feat/my-feature
make format && make lint && make typecheck && make test
git commit -m "feat(scope): description"
```

---

## FAQ

<details>
<summary><strong>코딩을 몰라도 쓸 수 있나요?</strong></summary>
<br/>

네. <a href="https://ai-watch-tester.vercel.app">ai-watch-tester.vercel.app</a> 클라우드 버전은 브라우저만 있으면 됩니다. 로컬 CLI는 터미널 명령어 한 줄로 설치할 수 있습니다.

AWT에게 필요한 건 URL과 (선택적으로) 무엇을 테스트할지 설명뿐입니다.
</details>

<details>
<summary><strong>"자가 수복"이 뭔가요?</strong></summary>
<br/>

웹 앱이 바뀌면 — 버튼 위치가 바뀌거나, 라벨이 달라지거나, 새 폼 필드가 생기거나 — 기존 테스트는 깨지고 누군가 수동으로 고치기 전까지 계속 깨진 상태입니다.

AWT의 DevQA Loop는 실패 후 페이지를 재스캔하고, 업데이트된 요소를 찾아서 테스트 스텝을 자동으로 패치합니다. 테스트 파일을 직접 건드릴 필요가 없습니다.
</details>

<details>
<summary><strong>aat devqa와 aat loop의 차이가 뭔가요?</strong></summary>
<br/>

| | `aat devqa` | `aat loop` |
|--|-------------|------------|
| 시작점 | 설명 + URL | 기존 시나리오 파일 |
| 테스트 생성 | 자동 (스캔 후 작성) | 파일 사용 |
| 실패 수정 | 테스트 YAML 패치 | **소스 코드** AI 패치 |
| 적합한 용도 | 첫 실행, 빠른 테스트 | 코드 수정 포함 반복 개발 |

처음 시작할 때는 `aat devqa`, 앱 코드도 함께 고치고 싶을 때는 `aat loop`.
</details>

<details>
<summary><strong>비주얼 리그레션 테스트가 뭔가요?</strong></summary>
<br/>

코드 수정 전후 스크린샷을 비교해서 UI가 의도치 않게 바뀌었는지 확인하는 것입니다 — 레이아웃 밀림, 요소 누락, 색상 변경 등.

```bash
aat snapshot scenarios/ --url http://localhost:3000   # 수정 전
# ... 코드 수정 ...
aat diff scenarios/ --url http://localhost:3000        # 비교
```

AWT는 SSIM(구조적 유사도 지수)을 사용합니다 — AI 토큰이 필요 없습니다. `--responsive`를 추가하면 모바일, 태블릿, 데스크톱 뷰포트를 한번에 테스트할 수 있습니다.
</details>

<details>
<summary><strong>클라우드 버전 요금은?</strong></summary>
<br/>

| 플랜 | 가격 | 테스트/월 |
|------|-------|-------------|
| **Free** | $0 | 5회 |
| **Pro** | $28.99/월 | 100회 |
| **Team** | $98.99/월 | 500회 |

로컬 CLI는 제한 없이 영구 무료입니다.
</details>

<details>
<summary><strong>데이터는 안전한가요?</strong></summary>
<br/>

- 모든 트래픽 HTTPS/TLS 암호화
- BYOK API 키: Fernet 암호화 (AES-128-CBC + HMAC-SHA256) 저장
- 스크린샷: 7일 후 자동 삭제
- 로컬 모드: 아무것도 외부로 나가지 않음
</details>

---

## 라이선스

[MIT](LICENSE) — 개인 및 상업적 용도 모두 무료.

---

<p align="center">
  <sub>Playwright, OpenCV, 그리고 깨진 셀렉터에 대한 수많은 짜증으로 만들어졌습니다.<br/>만든 사람: <a href="https://github.com/ksgisang">@ksgisang</a> — 피드백과 이슈 언제든 환영합니다.</sub>
</p>
