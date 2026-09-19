# AWT MCP Server

AWT를 [Model Context Protocol (MCP)](https://modelcontextprotocol.io) 서버로 사용하면,
Claude Code, Claude Desktop, Cursor, Windsurf 등 MCP 지원 도구에서 AWT를 직접 호출할 수 있습니다.

## 사전 요구사항

```bash
# AWT 설치 (아직 안 했다면)
pip install aat-devqa
playwright install chromium

# MCP SDK 설치
pip install mcp[cli]
```

## 제공 도구 (Tools)

| Tool | 설명 |
|------|------|
| `aat_devqa` | **All-in-one**: 스캔→시나리오생성→승인대기→실행→자동수정 전체 루프 |
| `aat_scan` | **Step 1**: URL 스캔, 인터랙티브 요소 수집 (scan_result.json 생성) |
| `aat_run` | **Step 3**: 시나리오 파일 실행 (사용자 승인 후에만 호출) |
| `aat_run_skill_mode` | **Step 3**: 스킬 모드 실행 (구조화된 실패 진단 포함) |
| `aat_doctor` | 환경 진단 (Python, Playwright, Tesseract, AI 연결) |
| `aat_list_scenarios` | 현재 디렉토리의 시나리오 파일 목록 |
| `aat_validate` | YAML 시나리오 스키마 검증 |
| `aat_cost` | AI API 비용 조회 |

## ⛔ 필수 사용 순서 (AI 에이전트 필독)

AWT 도구를 사용할 때 반드시 아래 순서를 지켜야 합니다:

1. **`aat_scan`** → 결과를 사용자에게 요약 보고 → **승인 대기**
2. 시나리오 YAML 작성 → 사용자에게 보여주기 → **승인 대기**
3. **`aat_run` 또는 `aat_run_skill_mode`** → 승인 후에만 실행 → 실패 시 보고 → **지시 대기**
4. 결과 보고

**금지:** `-y`/`--auto-approve` (해당 플래그 없음), 사용자 승인 없이 실행, 자동 코드 수정

## 설치 방법

### Claude Code

```bash
claude mcp add awt -- python /path/to/AI-Watch-Tester/mcp/server.py
```

확인:
```bash
claude mcp list
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) 또는
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "awt": {
      "command": "python",
      "args": ["/path/to/AI-Watch-Tester/mcp/server.py"]
    }
  }
}
```

### Cursor

프로젝트 루트에 `.cursor/mcp.json` 생성:

```json
{
  "mcpServers": {
    "awt": {
      "command": "python",
      "args": ["/path/to/AI-Watch-Tester/mcp/server.py"]
    }
  }
}
```

### Windsurf

`~/.windsurf/mcp.json`:

```json
{
  "mcpServers": {
    "awt": {
      "command": "python",
      "args": ["/path/to/AI-Watch-Tester/mcp/server.py"]
    }
  }
}
```

> `/path/to/AI-Watch-Tester`를 실제 경로로 변경하세요.

## 사용 예시

MCP 등록 후 AI 도구에서:

```
"로그인 테스트해줘"              → aat_devqa("로그인 테스트", url="http://localhost:3000")
"시나리오 목록 보여줘"           → aat_list_scenarios 호출
"login 시나리오 실행해줘"        → aat_run("scenarios/login.yaml")
"환경 진단해줘"                 → aat_doctor 호출
"비용 얼마 썼어?"               → aat_cost 호출
"스킬 모드로 테스트 돌려줘"      → aat_run_skill_mode("scenarios/login.yaml")
```

### verbosity / screenshots 옵션

```
aat_run("scenarios/login.yaml", verbosity="concise", screenshots="on-failure")
aat_run("scenarios/login.yaml", verbosity="detailed", screenshots="all")
aat_devqa("회원가입 테스트", url="http://localhost:3000", screenshots="before-after")
```

| verbosity | 설명 |
|-----------|------|
| `concise` | wait/screenshot 스텝 스킵, 빠름 (기본값) |
| `detailed` | 모든 스텝 실행 |

| screenshots | 설명 |
|-------------|------|
| `before-after` | 액션 전후만 저장, ~70% 파일 감소 (기본값) |
| `all` | 매 스텝마다 저장 |
| `on-failure` | 실패 시에만 저장 (CI/CD 최적) |

### report 옵션 — 남겨서 전달할 수 있는 리포트

```
aat_run("scenarios/login.yaml", report="pdf")
aat_run_skill_mode("scenarios/login.yaml", report="markdown")
```

| report | 설명 |
|--------|------|
| `""` | 리포트를 쓰지 않음 (기본값) |
| `pdf` | `reports/<시나리오 id>/report.pdf` — 실패·경고 단계의 스크린샷이 파일 안에 포함됨 |
| `markdown` | 같은 위치에 `report.md` |

작성된 경로는 표준 출력에 `Report: ...`로 찍히므로, 호출한 AI가 사용자에게
파일 위치를 그대로 알려줄 수 있습니다. 리포트 작성이 실패하더라도 종료코드는
바뀌지 않습니다. 종료코드는 시험 결과를 말해야 하기 때문입니다.

### DevQA Loop (스킬 모드)

`aat_run_skill_mode`는 실패 시 구조화된 블록을 반환합니다:

```
=== AWT SKILL DEVQA ===
SCENARIO: scenarios/login.yaml
FAILED_STEP: 3 - find_and_click
ERROR: Target 'Login' not found
SCREENSHOT: .aat/screenshots/fail_step3.png
POSSIBLE_CAUSE: Target text/selector changed or not yet rendered
RETRY_CMD: aat run --skill-mode scenarios/login.yaml
ATTEMPTS: 1/5
=======================
```

치명(critical) 스텝이 실패하면 `ACTUAL_CAUSE` 줄이 함께 출력됩니다.

```
=== AWT SKILL DEVQA ===
SCENARIO: scenarios/login.yaml
FAILED_STEP: 5 - assert_url
ERROR: 로그인 후에는 대시보드가 떠야 합니다
ACTUAL_CAUSE: Bounced to the login page: https://app.example.com/login?next=/dashboard
SCREENSHOT: .aat/screenshots/fail_step5.png
POSSIBLE_CAUSE: Expected content not found on page
RETRY_CMD: aat run --skill-mode scenarios/login.yaml
ATTEMPTS: 1/5
=======================
```

`ERROR`는 시나리오 작성자가 실행 이전에 적어 둔 기대 문구이고, `ACTUAL_CAUSE`는
브라우저에서 실제로 벌어진 일입니다. 두 값이 다를 때만 `ACTUAL_CAUSE`가 출력되며,
이 줄이 있으면 반드시 이쪽을 근거로 원인을 판단해야 합니다. 위 예시에서 `ERROR`만
읽으면 "대시보드 화면이 깨졌다"라는 정반대 진단이 나오지만, 실제 원인은 세션이
수립되지 않아 로그인 화면으로 되돌아간 것입니다.

AI 도구가 이 블록을 파싱해서 시나리오를 수정하고 재실행하는 자동 루프를 수행합니다.

## 직접 테스트

```bash
# MCP Inspector로 서버 테스트
mcp dev mcp/server.py

# 또는 직접 실행 (stdio 모드)
python mcp/server.py
```
