# Privacy

**AWT runs on your machine. This page says exactly what leaves it.**

Every claim below names the file and line that backs it, so you can check rather
than trust. Line numbers refer to AWT 1.8.0.

---

## Short version

- **No telemetry, no analytics, no crash reporting.** None is collected, so none
  is sent.
- AWT makes **one** network request on its own initiative: a daily check for a
  newer release. It carries no payload and no identifier.
- Everything else goes only where you pointed it: the site you are testing, the
  AI provider you configured, the endpoints your own scenarios call.
- Screenshots, reports, and learned data stay in local files. Nothing uploads
  them.

---

## The one call AWT makes by itself

`src/aat/cli/main.py:20-60`

Once every 24 hours, the CLI asks GitHub what the latest release is:

```
GET https://api.github.com/repos/ksgisang/awt-skill/releases/latest
Accept: application/vnd.github.v3+json
```

- **No request body.** The only header is `Accept`.
- **No identifier.** No account, no machine id, no installation id, no version
  string, nothing about what you are testing. The request is identical for
  every user.
- **This is a public, unauthenticated endpoint.** The same URL works in your
  browser.
- **3-second timeout, and every failure is swallowed** (`main.py:59-60`). Offline
  machines and locked-down networks are unaffected.
- The answer is cached in `~/.aat/update_check.json` so the call happens at most
  once a day.

Its only purpose is the hint printed when a newer version exists.

**There is currently no flag to disable it.** Blocking `api.github.com` at your
firewall is sufficient and breaks nothing: the check fails silently and the CLI
carries on.

---

## Everything else is a destination you chose

| Traffic | Goes to | Triggered by | Code |
|---|---|---|---|
| Page loads, clicks, typing | The site under test | The `url` in your scenario | Playwright, on your machine |
| AI prompts | The one provider in your config | Only commands that use AI | `src/aat/adapters/` |
| URL reachability check | The URL you typed | `aat doctor`, `aat start` | `core/connection.py:147` |
| Dev-server detection | `http://localhost:<port>` only | `aat devqa` | `cli/commands/devqa_cmd.py:265` |
| Teardown `api_call` steps | The endpoint you wrote | Your own scenario | `core/teardown.py:91` |

### About AI providers

AWT is **bring-your-own-key**. There is no AWT-operated AI service in the CLI.

- Your key is read from `.aat/config.yaml` or an `AAT_AI__API_KEY` environment
  variable, and is sent **only** to the provider it belongs to.
- The provider is whichever one you configured: Anthropic, OpenAI, Google Gemini,
  DeepSeek, or Ollama. Ollama runs on `localhost`, so that path never leaves your
  machine at all.
- Whatever you send is then governed by that provider's own policy, not this one.

**The commands most people run use no AI.** `aat scan`, `aat run`, `aat snapshot`,
and `aat diff` are deterministic: a browser, OpenCV, and Tesseract. AI is involved
only in scenario generation (`aat generate`, `aat devqa`), the DevQA fix loop, and
the optional vision matcher.

---

## What AWT writes to disk, and where it stays

Nothing in this list is uploaded anywhere by AWT.

| Path | Contents |
|---|---|
| `.aat/screenshots/` | Step screenshots of the site you tested |
| `.aat/scan_result.json`, `.aat/last_run.json`, `.aat/runs/` | Scan and run results |
| `.aat/baselines/` | Visual-regression baseline images |
| `.aat/audit.log` | Local record of execution attempts and approvals |
| `.aat/learned.db` | SQLite: element coordinates learned from past runs |
| `reports/` | Markdown and PDF reports |
| `~/.awt/templates/<host>/` | Element images saved for self-healing, partitioned by host, expiring after 30 days |
| `~/.aat/update_check.json` | Timestamp and version string from the update check |

Screenshots and PDF reports **do** capture whatever was on the page, which may
include test accounts, personal data, or secrets visible in your application.
Treat the output directories the way you treat the application itself: they are
as sensitive as what you pointed AWT at. They are ordinary files, so deleting
them deletes them.

---

## The MCP server and the Claude Code plugin

The bundled MCP server (`mcp/server.py`) reads no credentials of its own. It
builds `aat` command lines and runs them as subprocesses; anything about keys is
handled by the CLI exactly as described above. The server speaks stdio to your
local MCP client and opens no network connections.

The plugin's skill files are documentation. `references/cli-reference.md` and
`references/config-reference.md` show `export AAT_AI__API_KEY=...` as **guidance
for configuring your own key**. They are Markdown; they do not execute, and
nothing in AWT reads a key in order to send it anywhere but the provider.

---

## AWT Cloud is a separate thing

[ai-watch-tester.vercel.app](https://ai-watch-tester.vercel.app) is a hosted
service you have to sign up for. Installing the CLI or the plugin does not create
an account, contact it, or send it anything. If you do use it: traffic is over
HTTPS, BYOK keys are encrypted at rest (Fernet, AES-128-CBC + HMAC-SHA256), and
screenshots are deleted after 7 days.

---

## Changes and contact

Material changes to this page will appear in the release notes for the version
that carries them.

Questions, or something here that does not match what you observe:
[open an issue](https://github.com/ksgisang/AI-Watch-Tester/issues).

Last reviewed against the source on 2026-10-16, for AWT 1.8.0.
