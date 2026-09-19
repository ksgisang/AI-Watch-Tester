# AWT 배포 가이드

> 세션이 바뀌어도 동일한 절차로 배포할 수 있도록 정리한 가이드입니다.
> 모든 담당자(이대리)는 이 문서를 따릅니다.

## 배포 대상 5곳

| # | 대상 | 자동/수동 | 트리거 |
|---|---|---|---|
| 1 | **GitHub 저장소** | 자동 | `git push origin main` |
| 2 | **PyPI** (aat-devqa) | 반자동 | `git tag v*` → push → CI가 빌드+업로드 |
| 3 | **README.md** | 수동 | 기능 추가 시 직접 수정 후 커밋 |
| 4 | **Anthropic Skills PR** | 수동 | PR 업데이트 또는 새 PR 생성 |
| 5 | **MCP Servers PR** | 수동 | PR 업데이트 또는 새 PR 생성 |

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

# 3. 커밋
git add pyproject.toml
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

### README 반영 현황 (2026-09-19 기준)

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

## 4. Anthropic Skills PR 업데이트

### 현황
- 저장소: `anthropics/skills`
- PR: #822
- 상태: 리뷰 대기 중 (2026-04-04 기준)

### 업데이트가 필요한 경우
- MCP 도구에 새 파라미터 추가 시
- 새 MCP 도구 추가 시
- 스킬 설명/instructions 변경 시

### 절차

```bash
# 1. awt-skill 저장소에서 수정
cd ~/Documents/Projects/awt-skill  # 또는 해당 브랜치

# 2. mcp/server.py의 도구 정의 동기화
# AWT 본체의 mcp/server.py와 동일하게 유지

# 3. 커밋 & 푸시
git add .
git commit -m "feat: sync with AWT v1.X.X — add responsive/console/open"
git push

# 4. PR #822에 코멘트로 변경사항 알림
gh pr comment 822 --repo anthropics/skills --body "Updated to match AWT v1.X.X"
```

### ⚠️ 주의
- anthropics/skills PR이 아직 머지 안 된 상태
- 머지 전에 로컬 스킬로 먼저 사용 가능: `~/.claude/skills/awt/`
- PR이 오래 방치되면 close 후 새 PR 제출 고려

---

## 5. MCP Servers PR 업데이트

### 현황
- 저장소: `modelcontextprotocol/servers`
- PR: #3766
- 상태: 리뷰 대기 중 (2026-04-04 기준)

### 절차

```bash
# 1. 해당 포크에서 수정
# mcp/server.py 도구 정의 동기화

# 2. 커밋 & 푸시 → PR 자동 업데이트

# 3. PR에 코멘트
gh pr comment 3766 --repo modelcontextprotocol/servers \
  --body "Updated: added responsive/console/open parameters"
```

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
- [ ] Anthropic Skills PR 동기화 (MCP 변경 시)
- [ ] MCP Servers PR 동기화 (MCP 변경 시)
```

---

## 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|---|---|---|
| 1.7.0 | 2026-09-19 | PDF 리포트 (`aat run --report pdf`, MCP `report` 인자), 학습 좌표 신뢰성 수정(AAT-109) |
| 1.6.2 | — | MCP Registry 등록, 승인 우회 방지 4계층 |
| 1.6.1 | — | visual regression, watch mode, responsive/console/open |
| (이전) | — | Phase 1~6, Post-MVP features |

> 이 문서는 기능이 추가되거나 배포 방식이 변경될 때 업데이트합니다.
