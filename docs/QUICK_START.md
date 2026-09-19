# Quick Start Guide

Get AWT running in under 5 minutes.

---

## Local Mode

### 1. Install

```bash
pip install aat-devqa
```

### 2. Configure AI Provider

Pick one of the supported providers:

**Ollama (Free, Local)**

```bash
# Install and start Ollama
brew install ollama    # macOS
ollama serve           # Start the server
ollama pull codellama  # Download the model
```

No API key needed. AWT connects to `http://localhost:11434` by default.

**OpenAI**

```bash
export OPENAI_API_KEY="sk-..."
```

**Anthropic (Claude)**

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Start AWT

```bash
aat serve
```

Open **http://localhost:9500** in your browser.

### 4. Run Your First Test

1. Enter the URL you want to test (e.g. `https://example.com`)
2. Click **Generate Scenarios** — AI analyzes the page and creates test steps
3. **Review** the generated scenarios, edit if needed
4. Click **Run Test** — watch the browser execute each step
5. View results with pass/fail status per step

### 5. View Results

After the test completes, AWT generates a detailed report with:

- Pass/fail status for each step
- Screenshots (before and after actions)
- Error details for failed steps
- AI-suggested fixes (if DevQA Loop is enabled)

---

## Running a Test from the CLI

`aat run` never opens a browser until a human says so. There is no
`--auto-approve` and no `-y`: the approval prompt is the only way through, and
it reads `/dev/tty` directly rather than stdin, so piping input at it does
nothing. An AI agent driving your terminal cannot answer it — you have to.

The one exception is `--skill-mode`, which an AI tool passes when it runs AWT
for you. It does not remove the gate, it relocates it: your approval of the
tool call is what stands in for the keypress, so the agent has to show you the
scenario and hear a real "yes" before it calls anything. The run is recorded as
`approval_method: skill` in the audit log.

```bash
aat run scenarios/SC-002_login.yaml
```

### 1. The review screen appears first

Before anything is launched, AWT prints the scenario in readable form:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Scenario Review  [SC-002 · 5 steps]
 Login Flow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 🌐 navigate        https://example.com
  2. ⌨  find_and_type   "Email" → "test@example.com"
  3. ⌨  find_and_type   "Password" → "********"
  4. 🖱  find_and_click  "Log in"  ⛔stop
  5. ✅ assert_url      /dashboard  ⛔stop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 [Enter] Run    [e] Edit YAML    [n] Cancel
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶
```

Fields that look like passwords are masked. `⛔stop` marks a step that halts the
run on failure (`critical: true` or `on_fail: stop`). Point `aat run` at a
directory and each scenario is reviewed separately, with a
`(1/3 approved — next: SC-003)` line between them.

### 2. Three ways out

| Key | What happens |
|---|---|
| **Enter** (or `y`) | Approved — the run starts |
| **`e`** | Opens the YAML in `$EDITOR` (`nano` if unset). Saving and quitting runs the **edited** scenario immediately — it does not ask again |
| **`n`** | Cancelled. Nothing is launched; exit code 0 |
| **Ctrl+C** | Same as `n` |

### 3. The decision is recorded

Every attempt appends one JSONL line to `.aat/audit.log`, approvals and
cancellations alike:

```json
{"timestamp": "2026-09-15T13:40:02Z", "action": "run",
 "approval_method": "interactive", "approved": true, "is_tty": true,
 "scenarios": ["SC-002"], "token_prefix": null, "user": "you"}
```

`approval_method` says how it was approved: `interactive` (you pressed a key),
`skill` (an AI tool called it through the MCP server, where approval happened at
the tool-call level), or `token` (a one-time token issued by a parent `devqa` /
`watch` process — forging the environment variable fails, because it is checked
against a file on disk).

### 4. Then the browser opens

Chromium launches visibly — `headless: true` is not allowed — and the steps run
in order, with screenshots per step and human-like mouse and typing. Add
`--fast` to speed the movement up. Any `teardown:` steps run afterwards whether
the test passed or failed, unless you pass `--skip-teardown`.

### 5. Exit codes

| Code | Meaning |
|---|---|
| `0` | All steps passed — or you cancelled at the prompt |
| `1` | A step failed |
| `2` | A critical step failed and stopped the run |
| `3` | Every step ran, but at least one changed nothing on screen |

Code `3` is the "it clicked, but nothing happened" case. The step is reported as
`WARNING` rather than `PASSED`, because a click that moves no pixel has almost
certainly missed its target, and the real failure would otherwise surface
several steps later as if the product were broken. Check the screenshot for the
warned step and the target it was given.

### 6. A report you can send to someone

```bash
aat run scenarios/ --report pdf
```

This writes `reports/<scenario id>/report.pdf` after the run, alongside the
`report.html` it was printed from. Every step is listed with its status and how
long it took, and the screenshots of failed and warned steps are embedded in the
file itself, so the PDF explains itself away from your terminal. Use
`--report markdown` for the plain-text version instead.

The cover follows the same rule as the exit codes: a run whose steps all passed
but produced a warning is titled `PASS WITH WARNINGS`, never `PASS`. Printing
uses the Chromium that Playwright already installed, so there is nothing further
to install. `aat loop --report-format pdf` does the same for a healing loop,
including each iteration's analysis and fix.

With `--skill-mode`, a failure also prints an `=== AWT SKILL DEVQA ===` block
for an AI tool to read. Note that `ERROR` in that block is the scenario author's
expected outcome, while `ACTUAL_CAUSE` — present only when the two differ — is
what actually happened. Diagnose from `ACTUAL_CAUSE`.

---

## Cloud Mode

> Cloud mode is coming soon at [awt.dev](https://awt.dev).

### How It Will Work

1. **Sign up** at https://awt.dev
2. **Enter a URL** — the target site you want to test
3. **AI generates scenarios** — review and approve them
4. **Watch tests run** — live screenshot streaming in your browser
5. **View results** — detailed reports with full history

### Cloud Advantages

- No installation required
- Tests run on cloud infrastructure
- Real-time screenshot streaming
- Team collaboration and shared test history
- CI/CD integration with API keys

---

## CLI Quick Reference

| Command | Description |
|---------|-------------|
| `aat init` | Initialize project (creates `.aat/` config) |
| `aat config show` | Display current configuration |
| `aat config set <key> <value>` | Update a config value |
| `aat validate <scenario>` | Validate a YAML scenario file |
| `aat run <scenario>` | Run a single test scenario |
| `aat loop <scenario>` | Run DevQA Loop (fail → AI fix → retest) |
| `aat analyze <document>` | Analyze a document with AI |
| `aat generate <spec>` | Auto-generate scenarios from a spec |
| `aat start` | Interactive guided mode |
| `aat serve` | Start the web dashboard |

---

## Next Steps

- [API Reference](API_REFERENCE.md) — Full endpoint documentation
- [FAQ](FAQ.md) — Common questions and answers
- [CI/CD Guide](../cloud/docs/CI_CD_GUIDE.md) — Pipeline integration
