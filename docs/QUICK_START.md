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

There is a fourth way out that is not a key, because nobody pressed anything:
if the process has **no terminal** to ask at, the gate cannot be answered and
the run exits **4**, not 0. See *Exit codes* below — "nobody was asked" is a
different event from "someone said no".

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
| `4` | **Nothing ran.** Approval needed a terminal and there was none |

Codes `0`–`3` are all verdicts about a run that happened. Code `4` is outside
that range on purpose: it says no browser opened and nothing was checked, so a
CI job cannot print a green tick over a suite it never executed. If you see it,
run `aat run` from your own terminal — there is no flag that skips approval.

Code `3` is the "it ran, but nothing happened" case. The step is reported as
`WARNING` rather than `PASSED`, because a click that moves no pixel has almost
certainly missed its target, and the real failure would otherwise surface
several steps later as if the product were broken. Check the screenshot for the
warned step and the target it was given.

Typing is held to the same rule. A `find_and_type` step whose field is a
`<select>`, is `readonly`, is `disabled`, or is still empty afterwards is a
`WARNING`, not a pass — the step did run, and the text went nowhere. The warning
names which of those it was and what to use instead, so you do not have to open
the screenshot to find out.

Typing into the *wrong* field is the same verdict, and it is the one a long form
produces. When a step names a field by text, AWT checks the field it named
against the field that actually received the text, and reports the step rather
than counting it:

```
Step 7: WARNING  '에이더블유티점검' went into input#school (labelled '학교'), not into
                 input#name which the step named — input#name is still '';
                 name the field with `target.selector` to say which you mean
Step 10: WARNING '…' went into input#password-confirm, which step 9 already filled
                 for target '비밀번호' — '비밀번호 확인' and '비밀번호' resolved to one
                 field, so one of the two never got its own
```

Those two happen for one reason: a target text can be a substring of a
*different* field's placeholder — '이름' is inside '학교 이름을 입력하세요', and
'비밀번호' matches the placeholder of the confirm box but not of the password box.
AWT also logs the ambiguity at the moment it picks, naming both candidates.
Giving the step a `target.selector` settles it permanently.

These stay quiet where they cannot tell: a form with no `<label>`, `aria-label`
or label-wrapped field says nothing about which box a text meant, and a field
that reformats what you type (phone masks, `maxlength`, uppercase) is not
compared against the keystrokes at all.

Codes `3` and `4` are the same principle applied at two scales: a step that
changed nothing is not a pass, and a suite that ran nothing is not a pass
either.

### 5-1. `UNVERIFIED` — the step ran, and it proves nothing

A scenario is a sequence. If step 6 fails to create the account, the steps after
it are not testing the dashboard; they are running against a login screen, and
they can pass there. Counting those passes gives you a line like "22 of 24
passed" for a run in which the thing under test never happened once.

So once a scenario has failed, every later step that would have passed is
reported as `UNVERIFIED` and left out of the pass count, with a note saying
which step broke. The summary prints how many there were. Read the first failure
and run again; the unverified steps have nothing to tell you until you do.

This never changes an exit code. An `UNVERIFIED` step can only exist alongside a
failure, and the failure has already set the code to `1`. If you would rather the
scenario stop at the break instead of running on, mark that step
`critical: true` — then it exits `2` and nothing runs after it.

### 6. A report you can send to someone

```bash
aat run scenarios/ --report pdf
```

This writes `reports/<scenario id>/report.pdf` after the run, alongside the
`report.html` it was printed from. Every step is listed with its status and how
long it took, and the screenshots of failed and warned steps are embedded in the
file itself, so the PDF explains itself away from your terminal. Use
`--report markdown` for the plain-text version instead.

By default only the failed and warned steps bring their screenshots, which means
a report of a clean run carries no pictures at all. When the point is to show
that the product works — a hand-off, a demo, a record for someone who was not
there — ask for all of them:

```bash
aat run scenarios/ --report pdf --report-screenshots all
```

`--report-screenshots none` goes the other way and keeps the file small.

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

## Letting AWT fix it

`aat loop` runs a scenario, asks an AI model what went wrong, applies a fix, and
tests again until it passes or runs out of tries. How much it is allowed to touch
is up to you:

```bash
aat loop scenarios/login.yaml                        # default: shows fixes, writes nothing
aat loop scenarios/login.yaml -a branch              # applies each fix on a throwaway git branch
aat loop scenarios/login.yaml -a auto                # writes straight into your files
```

- **`manual`** (default) prints the proposed fix and asks. **Answering `y` still
  writes nothing** — the loop simply tries again and fails the same way. It is a way
  to read what the model would do, not a way to have it done.
- **`branch`** is the one to use if you want the fix actually applied. Each iteration
  creates `aat/fix-NNN`, commits there, re-tests there, and puts you back on your own
  branch. Your working copy never changes. `git branch -D aat/fix-NNN` erases it.
- **`auto`** edits your files in place with nobody reviewing in between. The command
  prints a warning saying so before it starts.

Before writing anything, AWT refuses a proposed change that guts a file, breaks its
syntax, or deletes a check (an `assert`, a `raise`/`throw`, or every `if`/`except`)
without putting something in its place. Refused files are named in the summary and
never written. **This catches wreckage, not cheating** — AWT cannot tell a genuine
repair from a change that merely stops the test complaining. That is the reason
`branch` exists, and the reason the default writes nothing.

Every loop ends with the same summary written twice. The first part is plain:

```
The test passes now. AWT changed something to get there — see below.
Changed 1 file: src/auth.py
The changes are on aat/fix-001, not in your working copy. To keep them:
git merge aat/fix-001. To throw them away: git branch -D aat/fix-001
```

Underneath it, `Details for a developer:` lists iterations, failing steps, written
and refused paths, branches, commits, and where the report went. When the loop
cannot fix the problem it says exactly that — *"a person needs to look at this"* —
rather than reporting a pass.

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
| `aat loop <scenario>` | Run DevQA Loop (fail → AI fix → retest). See *Letting AWT fix it* above |
| `aat analyze <document>` | Analyze a document with AI |
| `aat generate <spec>` | Auto-generate scenarios from a spec |
| `aat start` | Interactive guided mode |
| `aat serve` | Start the web dashboard |

---

## Next Steps

- [API Reference](API_REFERENCE.md) — Full endpoint documentation
- [FAQ](FAQ.md) — Common questions and answers
- [CI/CD Guide](../cloud/docs/CI_CD_GUIDE.md) — Pipeline integration
