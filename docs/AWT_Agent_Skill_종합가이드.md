# AWT를 Agent Skill로 만들어 배포하기 — 종합 가이드

> 작성일: 2026-03-15 | AILoopLab

---

## 1. Agent Skill이란 무엇인가?

### 1-1. 한 줄 정의

Agent Skill은 **AI 코딩 도구에게 전문 지식을 가르치는 마크다운 파일(SKILL.md)**입니다.

개발자가 "이 사이트 테스트해줘"라고 말하면, AI가 AWT 스킬을 자동으로 불러와서 AWT의 방식대로 테스트를 수행합니다. 코드를 설치하는 것이 아니라, **AI의 행동 방식을 바꾸는 것**입니다.

### 1-2. 비유로 이해하기

| 비유 | 설명 |
|------|------|
| 신입 개발자에게 주는 온보딩 문서 | AI에게 "우리 팀은 이렇게 일해"를 알려주는 매뉴얼 |
| 요리 레시피 | AI가 따라할 수 있는 단계별 절차서 |
| USB 드라이버 | AI라는 컴퓨터에 새 기능을 꽂는 것 |

### 1-3. 핵심 특징

- **마크다운만으로 제작** — 코드 없이도 만들 수 있고, 스크립트를 포함할 수도 있음
- **Progressive Disclosure** — 메타데이터만 먼저 로딩(~100토큰), 필요할 때만 전체 내용 로딩(<5K 토큰)
- **호환성** — Agent Skills 오픈 표준(agentskills.io)을 따르면, 하나의 SKILL.md로 11개 도구에서 작동

### 1-4. 호환 AI 코딩 도구 (2026년 3월 기준)

| 도구 | 개발사 | 스킬 경로 | 실행 방식 |
|------|--------|-----------|-----------|
| **Claude Code** | Anthropic | `.claude/skills/` | `/skill-name` |
| **Codex CLI** | OpenAI | `.codex/skills/` | 프롬프트에서 호출 |
| **Gemini CLI** | Google | `.gemini/skills/` | 프롬프트에서 호출 |
| **Cursor** | Cursor | `.cursor/skills/` | `@skill-name` |
| **GitHub Copilot** | Microsoft | `.github/skills/` | VS Code에서 자동 |
| **Antigravity IDE** | Google | `.gemini/antigravity/skills/` | Agent Mode |
| **Kiro CLI/IDE** | AWS | `.kiro/skills/` | 자동 로딩 |
| **OpenCode** | 오픈소스 | `.agents/skills/` | `opencode run @skill` |
| **Windsurf** | Codeium | `.windsurf/skills/` | 자동 로딩 |
| **Aider** | 오픈소스 | 설정 경로 | 프롬프트 |
| **Augment** | Augment | 설정 경로 | 자동 로딩 |

**핵심: AWT 스킬을 한번 만들면 11개 도구의 사용자 전부가 잠재 고객이 됩니다.**

---

## 2. AWT Skill 제작 방법

### 2-1. 디렉토리 구조

```
awt-skill/
├── SKILL.md              # 핵심 파일 (필수)
├── scripts/              # 실행 가능한 스크립트 (선택)
│   ├── scan.sh           # 사이트 스캔 스크립트
│   ├── run-test.sh       # 테스트 실행 스크립트
│   └── setup.sh          # AWT 설치/설정 스크립트
├── references/           # 참고 문서 (선택, 필요할 때만 로딩)
│   ├── YAML_SCHEMA.md    # YAML 시나리오 형식 가이드
│   ├── TROUBLESHOOT.md   # 자주 발생하는 오류와 해결법
│   └── EXAMPLES.md       # 시나리오 예시 모음
├── templates/            # 템플릿 파일 (선택)
│   └── scenario.yaml     # 기본 시나리오 템플릿
└── LICENSE               # AGPL-3.0
```

### 2-2. SKILL.md 구조 상세

SKILL.md는 **두 파트**로 구성됩니다:

```
┌─────────────────────────────────────┐
│ 1. YAML Frontmatter (메타데이터)     │ ← AI가 "언제 이 스킬을 쓸지" 판단
│    name, description 등              │
├─────────────────────────────────────┤
│ 2. Markdown Content (지시사항)       │ ← AI가 "어떻게 할지" 따라감
│    사용법, 워크플로, 예시 등           │
└─────────────────────────────────────┘
```

### 2-3. SKILL.md 실제 작성 예시 (AWT용)

```markdown
---
name: awt
description: >
  AI-powered web application testing tool. Use when asked to test a website, 
  run E2E tests, generate test scenarios, or validate web app quality. 
  Supports URL-based scanning, YAML scenario generation, Playwright execution, 
  self-healing tests, and AI-driven fix suggestions. Use when user says 
  "test this site", "run E2E tests", "check if my app works", 
  "generate test scenarios", or "find bugs in my web app".
version: 1.0.0
---

# AI Watch Tester (AWT) — AI-Powered Web Testing Skill

## Overview

AWT는 URL 하나로 웹 앱을 자동 테스트하는 도구입니다.
스캔 → 시나리오 생성 → 테스트 실행 → 결과 분석 → 코드 수정 제안까지
전체 QA 루프를 AI가 자동으로 처리합니다.

## Prerequisites

AWT CLI가 설치되어 있어야 합니다:
\`\`\`bash
# AWT 설치 확인
npx awt --version

# 설치되지 않은 경우
npm install -g ai-watch-tester
\`\`\`

## Quick Start

\`\`\`bash
# 기본 사용법: URL만 입력하면 전체 테스트 자동 실행
npx awt test https://example.com

# 스캔만 실행 (시나리오 생성 전 사이트 분석)
npx awt scan https://example.com

# 기존 YAML 시나리오로 테스트 실행
npx awt run ./scenarios/login-flow.yaml
\`\`\`

## 5-Step Workflow

사용자의 요청에 따라 아래 단계를 순서대로 실행합니다:

### Step 1: Scan
대상 URL의 DOM을 분석하고 페이지 구조를 파악합니다.
\`\`\`bash
npx awt scan $URL --output ./awt-scan-result.json
\`\`\`

### Step 2: Plan
스캔 결과를 바탕으로 YAML 테스트 시나리오를 자동 생성합니다.
\`\`\`bash
npx awt plan ./awt-scan-result.json --output ./scenarios/
\`\`\`

### Step 3: Review
생성된 시나리오를 사용자에게 보여주고 수정을 요청합니다.
**항상 사용자에게 시나리오를 확인시킨 후 실행하세요.**

### Step 4: Execute
Playwright 기반 실제 브라우저에서 테스트를 실행합니다.
\`\`\`bash
npx awt run ./scenarios/ --headed
\`\`\`

### Step 5: Results
결과를 분석하고, 실패한 테스트에 대해 수정안을 제시합니다.

## YAML Scenario Format

AWT는 선언형 YAML로 테스트를 정의합니다. 코드 작성이 불필요합니다:

\`\`\`yaml
name: 로그인 플로우 테스트
url: https://example.com/login
steps:
  - action: fill
    selector: "#email"
    value: "test@example.com"
  - action: fill
    selector: "#password"
    value: "password123"
  - action: click
    selector: "button[type='submit']"
  - action: assert
    selector: ".dashboard"
    condition: visible
\`\`\`

## Key Features

- **자동 치유 (Self-Healing)**: 셀렉터가 바뀌어도 자동 복구
- **비전 AI 매칭**: OpenCV로 UI를 시각적으로 검증 (셀렉터 무관)
- **패턴 학습**: 과거 실패를 기억하여 점점 정확해짐
- **DevQA Loop**: 실패 → AI 분석 → PR 생성 → 재테스트 자동화

## When NOT to use this skill

- 단순 유닛 테스트 → Jest/Vitest 사용
- API 테스트만 필요 → Postman/Insomnia 사용
- 정적 분석만 필요 → ESLint/SonarQube 사용

## Troubleshooting

문제 발생 시 references/TROUBLESHOOT.md를 참조하세요.

## More Info

- GitHub: https://github.com/ksgisang/AI-Watch-Tester
- 문서: https://ai-watch-tester.onrender.com/docs
```

### 2-4. 작성 시 핵심 원칙

| 원칙 | 설명 | AWT 적용 |
|------|------|----------|
| **description이 가장 중요** | AI가 이 스킬을 "언제 쓸지" 판단하는 유일한 기준 | "test", "E2E", "QA", "bug" 등 트리거 단어를 포함 |
| **Progressive Disclosure** | 모든 정보를 SKILL.md에 넣지 말고, 핵심만 넣고 나머지는 references/에 | YAML 스키마, 트러블슈팅은 별도 파일 |
| **예시를 반드시 포함** | AI는 예시가 있어야 정확하게 따라함 | YAML 시나리오 예시, CLI 명령어 예시 |
| **경계를 명확히** | 이 스킬이 "하지 않는 것"도 써야 함 | "유닛 테스트는 Jest 사용" |
| **5K 토큰 이내** | SKILL.md 본문이 너무 길면 컨텍스트를 낭비 | 핵심 워크플로만 넣고, 상세 문서는 references/ |

---

## 3. AWT Skill 배포 전략

### 3-1. 배포 채널 전체 맵

```
                     AWT Skill 배포 채널
                          │
         ┌────────────────┼────────────────┐
         │                │                │
    ① GitHub 직접     ② 마켓플레이스     ③ Awesome Lists
    (자체 레포)        등록              PR 제출
         │                │                │
    독립 레포 생성     SkillsMP.com      awesome-claude-skills
    README 정비       Claude 플러그인     awesome-agent-skills
    npx 설치 지원      LobeHub           antigravity-awesome-skills
                      claudeskills.info
```

### 3-2. 채널별 상세 실행 방법

#### ① GitHub 자체 레포지토리 (가장 먼저 해야 할 것)

AWT 스킬을 독립 GitHub 레포지토리로 만듭니다:

```
ai-watch-tester-skill/        ← 새 레포 이름
├── .claude-plugin/
│   └── marketplace.json       ← Claude Code 플러그인 마켓플레이스용
├── skills/
│   └── awt/
│       ├── SKILL.md
│       ├── scripts/
│       ├── references/
│       └── templates/
├── README.md                  ← 설치 방법, 데모 GIF, 비교표
├── CONTRIBUTING.md
├── LICENSE                    ← AGPL-3.0
└── package.json               ← npx 설치 지원용
```

**marketplace.json** (Claude Code 플러그인 등록용):
```json
{
  "name": "awt-skill",
  "displayName": "AI Watch Tester",
  "description": "AI-powered web application testing with auto-healing and DevQA Loop",
  "version": "1.0.0",
  "skills": ["skills/awt"]
}
```

**설치 명령어**:
```bash
# Claude Code 플러그인으로 설치 (스킬 + MCP 서버)
claude plugin marketplace add ksgisang/awt-skill
claude plugin install ai-watch-tester@awt

# 또는 npx로 스킬만 설치 (Cursor·Codex·Gemini CLI 등도 함께 지원)
npx skills add ksgisang/awt-skill --skill awt -g

# 또는 수동 설치
git clone https://github.com/ksgisang/awt-skill.git
cp -r awt-skill/skills/awt ~/.claude/skills/
```

#### ② Awesome Lists에 PR 제출 (가장 효과적인 무료 홍보)

아래 3개 리포지토리에 **Pull Request**를 보내서 AWT 스킬을 등록합니다:

| 리포지토리 | GitHub Stars | 설명 |
|-----------|-------------|------|
| **sickn33/antigravity-awesome-skills** | ⭐ 22,000+ | 1,259+ 스킬, 가장 큰 컬렉션 |
| **travisvn/awesome-claude-skills** | ⭐ 41,000+ | Claude 특화, 가장 유명한 목록 |
| **VoltAgent/awesome-agent-skills** | 활발한 커뮤니티 | 큐레이션 품질 높음 |

**PR 작성 예시** (awesome-claude-skills에 제출):
```markdown
## Testing & QA

- [AI Watch Tester](https://github.com/ksgisang/awt-skill) - 
  AI-powered E2E testing with declarative YAML scenarios, self-healing tests, 
  vision AI matching (OpenCV), and DevQA Loop (test failure → AI fix → auto PR → retest). 
  Supports OpenAI, Claude, DeepSeek, Ollama.
```

#### ③ 스킬 검색 플랫폼 등록

| 플랫폼 | URL | 특징 |
|--------|-----|------|
| **SkillsMP** | skillsmp.com | 400,000+ 스킬 검색엔진, 카테고리 필터 |
| **LobeHub** | lobehub.com/skills | 스킬 마켓플레이스, 설치 가이드 포함 |
| **claudeskills.info** | claudeskills.info | Claude 전용 스킬 허브 |

---

## 4. 홍보 전략

### 4-1. 홍보 채널 우선순위

```
[효과 높음 / 비용 0원]
├── ① GitHub Awesome Lists PR → 수만 명의 개발자에게 자동 노출
├── ② GeekNews(긱뉴스) 포스트 → 한국 개발자 커뮤니티 핵심
├── ③ DEV.to / Hashnode 블로그 → 영문 개발자 커뮤니티
├── ④ Reddit (r/ClaudeAI, r/coding) → 바이럴 가능성
│
[효과 높음 / 약간의 노력]
├── ⑤ Hacker News "Show HN" → 글로벌 개발자 최대 채널
├── ⑥ YouTube 데모 영상 → 시각적 설득력
├── ⑦ 디스콰이엇 → 한국 스타트업 커뮤니티
│
[장기적 효과]
├── ⑧ npm 패키지 등록 (npx awt-skill) → 설치 편의성
└── ⑨ Product Hunt 런칭 → 글로벌 노출
```

### 4-2. 핵심 메시지 (모든 홍보에 일관되게 사용)

**한 줄 피치:**
> "URL 하나로 웹앱을 테스트하고, 실패하면 AI가 코드까지 고쳐주는 스킬"

**3줄 설명:**
> 기존 webapp-testing 스킬은 Playwright 헬퍼 수준입니다.
> AWT 스킬은 선언형 YAML 시나리오 + 자동 치유 + 비전 AI + 패턴 학습을 제공합니다.
> 한 번 설치하면 Claude Code, Cursor, Codex 등 11개 도구에서 작동합니다.

**차별점 비교표** (README와 블로그에 포함):

| 기능 | webapp-testing | playwright-skill | **AWT** |
|------|:---:|:---:|:---:|
| Playwright 실행 | ✅ | ✅ | ✅ |
| 코드 없이 테스트 (YAML) | ❌ | ❌ | ✅ |
| 자동 치유 (Self-Healing) | ❌ | ❌ | ✅ |
| 비전 AI 매칭 (OpenCV) | ❌ | ❌ | ✅ |
| 패턴 학습 (SQLite) | ❌ | ❌ | ✅ |
| 실패 → AI 수정 → PR | ❌ | ❌ | ✅ |
| 멀티 AI (OpenAI/Claude/DeepSeek) | ❌ | ❌ | ✅ |
| 봇 감지 우회 (Humanizer) | ❌ | ❌ | ✅ |

### 4-3. 채널별 콘텐츠 전략

#### GeekNews (긱뉴스)

**제목:** `Show GN: AWT – AI가 웹앱 테스트하고 코드까지 고쳐주는 오픈소스 스킬`

**내용 구조:**
1. 문제 정의 (AI가 만든 코드, 누가 검증?)
2. AWT가 해결하는 방법 (5-Step 워크플로)
3. webapp-testing과의 차이점 (비교표)
4. 설치 한 줄 (`npx skills add ...`)
5. GitHub 링크

#### DEV.to / Hashnode

**제목:** `I built an Agent Skill that tests your web app and fixes bugs automatically`

**내용:**
- 기존 도구의 한계 (Playwright = 코드 작성 필수)
- AWT의 접근법 (YAML 선언형 + AI 자동화)
- 실제 데모 GIF or 스크린샷
- 성능 수치 (테스트당 $0.02~$0.05)
- 설치 방법
- 로드맵 (DevQA Loop, Cloud SaaS)

#### Reddit

**서브레딧:** r/ClaudeAI, r/ChatGPTCoding, r/webdev, r/SideProject

**포맷:** "I made X" 스타일의 짧고 임팩트 있는 포스트 + 댓글에서 기술 상세 설명

---

## 5. 무료 스킬 → SaaS 유료 전환 전략

### 5-1. 퍼널 설계

```
무료 스킬 설치 (11개 도구)
    │
    ├── 기본 기능 사용 (로컬 실행, YAML 생성, 테스트)
    │       │
    │       ▼
    ├── 한계 체감 (클라우드 실행 없음, PR 자동화 없음, 팀 공유 불가)
    │       │
    │       ▼
    └── AWT Cloud SaaS 가입 유도
            │
            ├── Free: $0 (월 5회, 스킬과 동일)
            ├── Pro: $28.99/월 (월 100회, CI/CD, 자동 PR)
            └── Team: $98.99/월 (월 500회, 팀 대시보드)
```

### 5-2. 무료 vs 유료 기능 분리

| 기능 | 스킬 (무료) | Cloud Free | Cloud Pro | Cloud Team |
|------|:---:|:---:|:---:|:---:|
| 사이트 스캔 | ✅ | ✅ | ✅ | ✅ |
| YAML 시나리오 생성 | ✅ | ✅ | ✅ | ✅ |
| 로컬 테스트 실행 | ✅ | ✅ | ✅ | ✅ |
| Self-Healing | ✅ | ✅ | ✅ | ✅ |
| 비전 AI 매칭 | ✅ | ✅ | ✅ | ✅ |
| 월 테스트 횟수 | 무제한(로컬) | 5회 | 100회 | 500회 |
| **클라우드 실행** | ❌ | ❌ | ✅ | ✅ |
| **CI/CD API 키** | ❌ | ❌ | ✅ | ✅ |
| **소스코드 분석** | ❌ | ❌ | ✅ | ✅ |
| **AI 자동 수정 PR** | ❌ | ❌ | ✅ | ✅ |
| **팀 대시보드** | ❌ | ❌ | ❌ | ✅ |
| **우선 지원** | ❌ | ❌ | ❌ | ✅ |

**핵심 원칙:** 로컬에서 혼자 쓰는 건 완전 무료, 클라우드/팀/자동화는 유료.

### 5-3. 전환 유도 방법

스킬 실행 결과 마지막에 자연스럽게 노출:

```
✅ Test Results: 12 passed, 3 failed

💡 Want auto-fix PRs for failed tests? 
   Try AWT Cloud Pro → https://ai-watch-tester.onrender.com/pricing
```

---

## 6. 실행 로드맵

### Phase 1: 스킬 제작 (1~2일)

- [ ] SKILL.md 작성 (위 예시 기반)
- [ ] scripts/ 디렉토리 정리 (scan.sh, run-test.sh, setup.sh)
- [ ] references/ 디렉토리 정리 (YAML 스키마, 트러블슈팅, 예시)
- [ ] 로컬에서 Claude Code로 테스트
- [ ] GitHub 레포 생성 (ai-watch-tester-skill)
- [ ] marketplace.json 추가 (Claude Code 플러그인용)
- [ ] README.md 작성 (데모 GIF, 비교표, 설치 방법)

### Phase 2: 배포 (1일)

- [ ] GitHub 레포 공개
- [ ] awesome-claude-skills에 PR 제출
- [ ] awesome-agent-skills에 PR 제출
- [ ] antigravity-awesome-skills에 PR 제출
- [ ] SkillsMP, LobeHub, claudeskills.info 등록

### Phase 3: 홍보 (1주)

- [ ] GeekNews 포스트 게시
- [ ] DEV.to 영문 블로그 게시
- [ ] Hashnode 영문 블로그 게시
- [ ] Reddit 포스트 (r/ClaudeAI, r/webdev)
- [ ] 디스콰이엇 업데이트
- [ ] GitHub Actions 런치 모니터로 반응 추적

### Phase 4: 피드백 & 개선 (지속)

- [ ] GitHub Issues로 피드백 수집
- [ ] DevQA Loop 기능 구현 (핵심 차별점)
- [ ] 데모 영상 제작 (YouTube)
- [ ] Hacker News "Show HN" 게시
- [ ] Product Hunt 런칭 준비

---

## 7. 경쟁 스킬 현황 분석

2026년 3월 현재, 웹 테스팅 관련 스킬 생태계:

### 기존 경쟁 스킬

| 스킬 이름 | 특징 | AWT 대비 약점 |
|-----------|------|---------------|
| **webapp-testing** (Anthropic 번들) | Playwright Python 헬퍼, 블랙박스 스크립트 | 시나리오 형식 없음, 실패 처리 없음, 학습 없음 |
| **playwright-skill** (lackeyjb) | Playwright JS 자동화, 실시간 브라우저 | 사전정의 시나리오 없음, 수정 제안 없음 |
| **Playwright Skill** (testdino-hq) | 70+ 가이드, 패턴 교육 | 교육 자료 위주, 자동화 엔진 아님 |
| **playwright-cli Skill** | CLI 기반, 토큰 효율적 | 대화형 단계 실행, 전체 자동화 아님 |
| **e2e-testing** (커뮤니티) | Playwright E2E 러너 | AWT의 YAML/비전AI/학습 없음 |
| **browser-compatibility-tester** | 크로스 브라우저 | BrowserStack 의존, 범용 테스팅 아님 |

### AWT의 포지셔닝

```
                    자동화 수준
                      높음
                       │
                   ◆ AWT
                       │    (YAML + 자동 치유 + 비전 AI + 학습 + PR)
                       │
          ─────────────┼─────────────
          수동          │          자동
          (코드 작성)    │          (코드 불필요)
                       │
             ◆ playwright-skill
             ◆ webapp-testing
                       │
                      낮음
```

**결론: "코드 없이 테스트 + AI가 고쳐줌" 포지션은 AWT만 차지하고 있습니다.**

---

## 8. 주의사항 & 팁

### 보안

- SKILL.md에 API 키, 비밀번호 절대 포함 금지
- 스크립트가 외부 API를 호출하면 README에 명시
- AGPL-3.0 라이선스 명확히 표기

### description 작성 팁

description은 200자 이내, AI가 검색하는 키워드를 최대한 포함:

```yaml
# 나쁜 예 (너무 모호)
description: A testing tool for web apps

# 좋은 예 (트리거 키워드 포함)
description: >
  AI-powered web application testing with YAML scenarios, 
  self-healing, and auto-fix PRs. Use when asked to test a website, 
  run E2E tests, generate test scenarios, find bugs, or validate 
  web app quality.
```

### 토큰 효율

- SKILL.md 본문: 5K 토큰 이내 (핵심만)
- 상세 문서: references/ 디렉토리에 분리
- AI는 references/를 필요할 때만 로딩하므로 컨텍스트 낭비 없음

### 테스트 방법

```bash
# Claude Code에서 스킬 테스트
cd my-project
mkdir -p .claude/skills/
cp -r path/to/awt-skill .claude/skills/awt

# Claude Code 실행 후
/awt https://my-test-site.com
```

---

## 부록: 참고 자료

| 자료 | URL |
|------|-----|
| Agent Skills 공식 스펙 | agentskills.io/specification |
| Anthropic 스킬 제작 가이드 | support.claude.com/en/articles/12512198 |
| Claude Code 스킬 문서 | code.claude.com/docs/en/skills |
| Anthropic 공식 스킬 레포 | github.com/anthropics/skills |
| Awesome Claude Skills | github.com/travisvn/awesome-claude-skills |
| Awesome Agent Skills | github.com/VoltAgent/awesome-agent-skills |
| Antigravity Awesome Skills | github.com/sickn33/antigravity-awesome-skills |
| SkillsMP 마켓플레이스 | skillsmp.com |
| 스킬 제작 심층 가이드 (PDF) | resources.anthropic.com (The Complete Guide) |
