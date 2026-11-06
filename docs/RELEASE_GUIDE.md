# AWT 배포 가이드

> 세션이 바뀌어도 동일한 절차로 배포할 수 있도록 정리한 가이드입니다.
> 모든 담당자(이대리)는 이 문서를 따릅니다.

## 배포 대상 5곳

| # | 대상 | 자동/수동 | 트리거 |
|---|---|---|---|
| 1 | **GitHub 저장소** | 자동 | `git push origin main` |
| 2 | **PyPI** (aat-devqa) | 반자동 | `git tag v*` → push → CI가 빌드+업로드 |
| 3 | **README.md** | 수동 | 기능 추가 시 직접 수정 후 커밋 |
| 4 | **플러그인 번들** (`awt-skill`, 스킬 전용) | 자동 | 번들의 `main`에 푸시 → 디렉터리가 집어 감 |
| 5 | **MCP Registry** | 자동 | 이 저장소의 `server.json` 버전 올려 푸시 → OIDC 워크플로가 게시 |

---

## 1. GitHub 저장소 배포 (매 작업 완료 시)

```bash
# 1. 테스트 통과 확인
make lint && make typecheck && make test

# 2. 커밋 & 푸시
git add <files>
git commit -m "feat(...): 설명"
git push origin main

# 3. CI 통과 확인
gh run list --limit 1
# status가 "completed/success"여야 함
```

**규칙:**
- 커밋당 10개 이하 파일 변경
- CI 실패 시 수정 후 재시도
- main 브랜치에서 직접 작업

---

## 2. PyPI 배포 (큰 기능 완성 시)

### 배포 조건
- 하루 작업 마무리 시
- 큰 기능(Phase 단위) 완성 시
- 안정성 확인 후 (CI 통과 + 로컬 테스트 완료)

### 절차

```bash
# 1. pyproject.toml 버전 올리기
# 현재 버전 확인:
grep '^version' pyproject.toml
# version = "1.6.1"

# 버전 규칙: major.minor.patch
# - patch: 버그 수정, 작은 개선
# - minor: 새 기능 추가
# - major: 호환성 깨지는 변경

# 2. 버전 수정
# pyproject.toml의 version = "X.Y.Z" 수정
# src/aat/__init__.py의 __version__도 같이 올립니다 (둘이 어긋나면 시험이 잡습니다)

# 2-1. 릴리스 노트 (선택이지만, 동작이 달라지는 판에서는 필수)
# docs/releases/vX.Y.Z.md 를 작성합니다. 이 파일이 있으면 publish.yml이
# 자동 생성 커밋 목록 '위에' 붙여 줍니다. 없으면 예전과 똑같이 동작합니다.
# 통과가 실패로 바뀔 수 있는 판은 첫 줄에 그 사실을 적습니다.

# 3. 커밋
git add pyproject.toml src/aat/__init__.py docs/releases/
git commit -m "chore: bump version to X.Y.Z"
git push origin main

# 4. CI 통과 확인
gh run list --limit 1
# ⚠️ CI 통과 전에 태그 금지!

# 5. 태그 생성 & 푸시 (CI 자동 배포 트리거)
git tag vX.Y.Z
git push origin vX.Y.Z

# 6. 배포 확인
gh run list --limit 1 --workflow publish.yml
# status가 "completed/success"여야 함

# 7. PyPI에서 확인
# https://pypi.org/project/aat-devqa/
```

### 배포 CI 동작 (`.github/workflows/publish.yml`)
1. 태그(v*) 푸시 감지
2. lint + typecheck + test 실행
3. `python -m build` → wheel/sdist 생성
4. 태그와 pyproject.toml 버전 일치 검증
5. twine으로 PyPI 업로드
6. GitHub Release 자동 생성 (--latest)

### ⚠️ 주의사항
- **태그와 pyproject.toml 버전이 반드시 일치해야 합니다** (v1.7.0 ↔ version = "1.7.0")
- 개발 중에는 editable 모드 사용: `pip install -e ".[dev]"`
- 다른 프로젝트에서 테스트 시: `bash ~/Documents/Projects/AI_Auto_Tester/install-dev.sh`

---

## 3. README.md 업데이트 (기능 추가 시)

### 업데이트가 필요한 경우
- 새 CLI 명령 추가 시
- 새 옵션(flag) 추가 시
- 새 MCP 도구 추가 시
- 지원 플랫폼/도구 변경 시

### README 반영 현황 (2026-10-15 기준)

| 기능 | README 반영 여부 |
|---|---|
| `aat snapshot` / `aat diff` / `aat baseline` | ✅ 반영 |
| `aat watch` | ✅ 반영 |
| `--responsive` / `--viewport` | ✅ 반영 |
| `--console` / `--console-fail` | ✅ 반영 |
| `--open` | ✅ 반영 |
| MCP 도구: `aat_snapshot`, `aat_diff`, `aat_watch` | ✅ 반영 |
| GitHub Action: visual-regression.yml | ✅ 반영 |
| `--report pdf` / MCP `report` 인자 | ✅ 반영 |
| 종료 코드 표 (`0`/`1`/`2`/`3`) | ✅ 반영 (1.8.0) |
| `aat learned list` / `aat learned clear --templates` | ⬜ 해당 없음 — README에는 `aat` 명령 목록이 없습니다. 정본은 `awt-skill/skills/awt/references/cli-reference.md`이고 거기에 반영되어 있습니다 |

> 이 표는 배포할 때마다 실제 README를 확인해 갱신합니다. 오래된 ❌ 목록은
> 이미 끝난 일을 남은 일처럼 보이게 만들어, 다음 배포에서 헛일을 부릅니다.

### README 업데이트 절차

```bash
# 1. README.md 수정
# "What it does" 또는 "Features" 섹션에 추가

# 2. 한국어 README도 동기화 (있는 경우)
# README.ko.md

# 3. 커밋
git add README.md README.ko.md
git commit -m "docs(readme): add visual regression & enhancement features"
git push origin main
```

### README 구조 가이드
- 새 기능은 "What it does" 섹션 하단에 추가
- CLI 사용법은 코드 블록으로
- 비교표(vs 경쟁사)에 해당하면 업데이트
- FAQ에 자주 묻는 질문 추가

---

## 4. 플러그인 번들 갱신 (기존 "Anthropic Skills PR"을 대체)

### 현황
- **`anthropics/skills` PR #822는 더 이상 경로가 아닙니다.** 그 저장소는
  디렉터리 역할을 넘겼고, 스킬은 단독 제출 항목이 아니라 **플러그인 번들의 일부**로
  등재됩니다. PR은 닫고 포털 경로를 안내합니다.
- 번들: `awt-skill` 저장소 **하나**이고, 싣는 것은 **스킬(`skills/awt/`)뿐입니다.**
  디렉터리가 **사용자 기기에서 실행되는 MCP 서버를 Verified 조직에서만** 받으므로
  번들에서 서버를 내렸습니다. 서버 파일의 정본은 이제 **본체 저장소의
  `mcp/server.py`** 이고 사용자가 손으로 등록합니다(§5, `mcp/README.md`).
- 매니페스트: `awt-skill/.claude-plugin/plugin.json`,
  마켓플레이스 항목: `awt-skill/.claude-plugin/marketplace.json`
- 플러그인 이름 `ai-watch-tester`는 **바꾸지 않습니다** — 이름을 바꾸면 이미 설치한
  모든 사용자에게 다른 플러그인이 되어 갱신이 끊깁니다.

### 업데이트가 필요한 경우
- 스킬 본문·참조 문서·템플릿을 고쳤을 때
- 새 CLI 플래그를 스킬에 노출할 때

MCP 도구만 바뀐 경우에는 번들을 건드리지 않습니다. 서버는 본체에 있으므로
§5만 따릅니다.

### 절차

```bash
# 1. 번들(서브모듈)에서 수정합니다.
cd awt-skill
#    - skills/awt/**          스킬 본문·참조 문서
#    - .claude-plugin/plugin.json 의 "version"

# 2. 형식 검증 — 인자는 **플러그인 폴더**(= 저장소 최상위)이지 `.claude-plugin`이
#    아닙니다. `.claude-plugin`을 주면 그 안에서 매니페스트를 다시 찾아 실패합니다.
cd .. && claude plugin validate ./awt-skill && cd awt-skill

# 3. 커밋 & 푸시 (번들 → 본체 포인터 순서)
git add . && git commit -m "feat: sync with AWT v1.X.X" && git push
cd .. && git add awt-skill && git commit -m "chore: bump the awt-skill pointer" && git push

# 4. 설치해서 실제로 들어왔는지 확인합니다.
claude plugin update ai-watch-tester@awt
claude plugin details ai-watch-tester@awt   # Skills (1) awt, MCP servers (0)
```

`MCP servers`는 **0이 정상입니다.** 번들은 서버를 싣지 않습니다.

### 디렉터리 등재 (최초 1회, 대표님 계정)
- 제출처: `claude.ai/directory/manage` — **유료 claude.ai 플랜의 브라우저**에서
  대표님이 직접 하셔야 합니다. CLI 경로가 없습니다.
- **제출한 조직이 등재의 영구 소유자**가 됩니다. 저장소와 폴더 조합은 한 조직에
  하나뿐이고, **제출 뒤에는 저장소·폴더를 바꿀 수 없습니다**(바꾸려면 새 제출).
- **GitHub 계정을 claude.ai에 연결**해 두어야 하고, 포털이 그 계정의 **푸시 권한**을
  확인합니다. 다른 Claude 조직에서 연결한 것은 넘어오지 않습니다.
- 양식에서 **Plugin bundle**을 고르고, 저장소에 `ksgisang/awt-skill`을 넣습니다.
  **Plugin path는 비웁니다**(플러그인이 최상위에 있습니다). **Branch는 비우면
  기본 브랜치 `main`** 을 따릅니다 — 이것이 **추적 브랜치**입니다.
- 제출물은 보안 스캔을 통과해야 하고, **첫 제출이 스캔에서 걸리면 반려**입니다.
  그래서 `awt-skill/README.md`에 "What this plugin runs, sends, and fetches"
  절을 두어 실행·기록·전송·내려받기를 전부 적어 두었습니다. 서버가 하는 일이
  바뀌면 **그 절을 같이 고쳐야 합니다.**

#### 거부 이력과 열린 문의 (2026-11-06, AAT-130)
- **첫 제출(2026-10-16)은 거부되었습니다.** 사유는 하나이고 품질과 무관합니다 —
  *"The directory accepts MCP servers that run on the user's computer only from
  Verified organizations, and your organization isn't one, so this version is
  refused."* 보안 스캔은 이미 통과한 상태였습니다.
- **Verified는 신청할 수 있는 등급이 아닙니다.** `docs/directory/publish`와
  `docs/connectors/verification`이 둘 다 *"There's no separate application for
  the Verified label"*, *"Anthropic decides both during review"* 라고 적습니다.
  그래서 「Verified를 먼저 받는다」는 길은 **존재하지 않습니다.**
- 대응은 **번들을 스킬 전용으로** 만드는 것이었습니다(위 「현황」). 그래서 지금
  제출물에는 로컬 MCP 서버 선언이 한 줄도 없습니다.
- **열린 문의가 하나 있습니다(미해결).** 문서 세 벌이 서로 어긋납니다 —
  `docs/directory/publish`는 *"To distribute a local MCP server through the
  directory, include it in a plugin bundle"* 이라고 **그 방법을 지시**하고,
  `docs/plugins/pre-submission-checklist`의 로컬 MCP 두 항목은 결말이
  **`Held for a reviewer`**(거부가 아님)이며 "Verified organization"이라는 말이
  **한 번도 나오지 않고**, 디렉터리 정책 문서는 로컬 MCP를 「의존성을 최신으로」로만
  다룹니다. **문서가 지시한 경로를 그대로 따랐는데 거부된 것**이므로, 「Verified가
  아닌 게시자는 그 경로를 어떻게 따라야 하는가」를 포털로 묻습니다. 답이 오면
  서버를 번들로 되돌릴 수 있을지가 갈립니다 — **답이 오기 전에는 되돌리지 마십시오.**

#### 등재 뒤의 갱신 — 포털에 다시 들어갈 일은 없습니다
- **추적 브랜치(`main`)에 푸시하면 디렉터리가 알아서 집어 갑니다.** 위 「절차」의
  1~3번이 곧 릴리스이고, 포털은 **버전이 보류되거나 설정을 바꿀 때만** 엽니다.
- 다만 **처음 몇 판은 `Publish`를 눌러야 할 수 있습니다.** 기본값이 「매 버전을
  Anthropic 리뷰어가 게시」이고, 리뷰어가 승인하면서 자동 게시로 올려 줍니다.
  현재 설정은 플러그인 페이지 **Overview 탭의 `Auto-publish` 줄**에 적혀 있습니다.
- `plugin.json`의 `version`은 **릴리스마다 올려야 합니다.**
- 새 버전이 스캔에 걸려도 **이미 게시된 버전은 계속 서비스**됩니다.

### ⚠️ 주의
- **번들에 로컬 MCP 서버 선언을 되돌려 놓지 마십시오.** `.mcp.json`도,
  `plugin.json` 안의 인라인 `mcpServers`도, `transport: stdio`인 `server.json`도
  두지 않습니다. 디렉터리가 그 선언 하나를 근거로 **그 판을 거부**합니다
  (*"Remove every MCP server that runs on the user's computer, then push a new
  commit."*). URL로 접속하는 원격 서버는 예외이지만 AWT는 로컬 서버입니다.
- 플러그인 폴더는 **저장소 최상위**입니다. 그래서 추적되는 **모든 파일이 스캔
  대상이고 사용자에게 함께 배포**됩니다. 본체용 워크플로·매니페스트를 그 저장소에
  두면 안 되는 이유입니다.
- 전역 스킬(`~/.claude/skills/awt/`)을 따로 쓰고 계시면 플러그인과 **중복**됩니다.
  동기화 절차는 `docs/CROSS_SESSION_TESTING.md` §3입니다.

---

## 5. MCP Registry 갱신 (기존 "MCP Servers PR"을 대체)

### 현황
- `modelcontextprotocol/servers` PR #3766은 **2026-04-14에 닫혔습니다.**
  그 저장소가 서드파티 서버 목록을 README에서 폐지하고 MCP Registry로
  일원화했기 때문입니다(해당 저장소 이슈 #3950). **PR을 갱신할 대상이 더는
  없으므로, 그쪽에 커밋하거나 코멘트를 달 필요가 없습니다.**
- 대신 AWT는 Registry에 `io.github.ksgisang/awt`로 등록되어 있습니다.
- 매니페스트 위치: **이 저장소의 `server.json`** 입니다. 전에는 `awt-skill`에
  두었으나, 번들에서 로컬 서버 선언을 내리면서 워크플로와 함께 옮겨 왔습니다.
  네임스페이스는 영향을 받지 않습니다 — Registry의 OIDC 인증은
  `repository_owner` 하나만 보므로(`internal/api/handlers/v0/auth/github_oidc.go`),
  `ksgisang` 소유 저장소라면 어디서든 `io.github.ksgisang/*`를 게시할 수 있습니다.

### 절차

**게시는 자동입니다.** 이 저장소의 `.github/workflows/publish-mcp.yml`이
`server.json` 변경이 main에 푸시되면 게시합니다. 인증은 GitHub Actions의 OIDC라
저장할 비밀값도, 만료되는 로그인도 없습니다. 사람이 할 일은 버전을 올리는 것뿐입니다.

```bash
# 1. PyPI 배포가 끝난 뒤에 진행합니다.
#    매니페스트가 PyPI 패키지 버전을 가리키므로, 없는 버전을 가리키면 안 됩니다.
#    (워크플로가 이 조건을 검사해서 어기면 게시를 막습니다.)

# 2. server.json의 두 곳을 모두 새 버전으로 올립니다.
#    - 최상위 "version"
#    - packages[0]."version"  ← 빠뜨리기 쉬움 (워크플로가 불일치를 잡습니다)

# 3. 커밋·푸시하면 워크플로가 게시합니다.
git add server.json && git commit -m "chore: publish awt 1.X.X to the MCP Registry" && git push

# 4. 결과 확인
gh run list --workflow publish-mcp.yml --limit 1
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ksgisang/awt"
```

번들 판본(`plugin.json`)과 `server.json`의 판본은 **같을 필요가 없습니다.**
`server.json`은 PyPI 패키지를 가리키므로 **PyPI에 실제로 올라간 판본**이어야 하고,
번들은 스킬 문서만 싣기 때문에 PyPI와 무관하게 올릴 수 있습니다.

### ⚠️ 주의
- 워크플로가 실패했을 때만 `gh workflow run publish-mcp.yml`로 다시 돌립니다.
- **게시된 판본은 불변입니다.** 같은 판본을 다시 올리려 하면 게시가 실패하므로,
  워크플로가 먼저 Registry를 조회해 이미 있으면 건너뜁니다.
- 로컬 `mcp-publisher` 바이너리는 더 이상 필요하지 않습니다(저장소에 커밋되어
  있지도 않습니다). `login github`은 브라우저 인증이라 AI 에이전트가 대신 할 수
  없었고, 토큰이 만료되어 게시를 건너뛰는 일이 실제로 있었습니다. 그래서
  자동화했습니다.
- 과거에 `1.6.3` 항목이 PyPI `1.6.2`를 가리킨 채 등록된 적이 있습니다. 워크플로의
  두 검사(버전 일치·PyPI 존재)는 정확히 그 사고를 막기 위한 것입니다.

---

## 배포 체크리스트 (복사해서 사용)

새 기능 배포 시 아래 체크리스트를 따릅니다:

```markdown
### 배포 체크리스트 — [기능명]

- [ ] 로컬 테스트 통과 (make lint && make typecheck && make test)
- [ ] git commit & push
- [ ] CI 통과 확인 (gh run list --limit 1)
- [ ] CLAUDE.md WBS 업데이트
- [ ] README.md 업데이트 (해당 시)
- [ ] README.ko.md 동기화 (해당 시)
- [ ] lee-to-kim summary 업데이트 (협업 시)
- [ ] PyPI 버전 범프 + 태그 (배포 조건 충족 시)
- [ ] 플러그인 번들 동기화 (스킬 문서 변경 시)
- [ ] MCP Registry 갱신 (MCP 변경 시, PyPI 배포 이후)
```

---

## 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|---|---|---|
| 1.8.0 | 2026-10-15 | **통과가 실패로 바뀔 수 있는 판** — 검증되지 않은 단계를 `WARNING`(종료코드 3)·`UNVERIFIED`로 보고(AAT-115·123·124), `if_visible`이 접힌 용기 안 요소를 건너뜀(AAT-126). 통과할 수 없던 `assert_screen_changed` 수정(AAT-127), 자기 치유 실제 작동(AAT-112), Flutter CanvasKit 세 겹(AAT-116~118), 접힌 선 아래 탐색(AAT-121), 좌표계 분리(AAT-120), 자동 수정 안전장치(AAT-122), `aat learned list/clear --templates`, `.aat/runs/` 실행 이력 |
| 1.7.1 | 2026-09-19 | 상대 경로 `reports_dir`에서 PDF가 인쇄되지 않던 결함 수정, `--report-screenshots failures\|all\|none` 신설 |
| 1.7.0 | 2026-09-19 | PDF 리포트 (`aat run --report pdf`, MCP `report` 인자), 학습 좌표 신뢰성 수정(AAT-109) |
| 1.6.2 | — | MCP Registry 등록, 승인 우회 방지 4계층 |
| 1.6.1 | — | visual regression, watch mode, responsive/console/open |
| (이전) | — | Phase 1~6, Post-MVP features |

> 이 문서는 기능이 추가되거나 배포 방식이 변경될 때 업데이트합니다.
