# Documentation Sync Guide

When code changes, the corresponding documentation must be updated in the same PR. This guide maps every document to its role and every change type to the documents it affects.

---

## Document Inventory

| File | Role |
|------|------|
| `README.md` | GitHub landing page — features, quick start, badges, links |
| `CONTRIBUTING.md` | Developer onboarding — setup, code style, PR process, architecture |
| `docs/QUICK_START.md` | End-user setup — install, AI provider config, CLI reference |
| `docs/API_REFERENCE.md` | Full REST API + WebSocket docs with schemas and curl examples |
| `docs/FAQ.md` | Common questions — comparisons, pricing, self-hosting, licensing |
| `cloud/docs/CI_CD_GUIDE.md` | CI/CD pipeline integration — GitHub Actions example, API key usage |
| `cloud/BACKUP_RECOVERY.md` | Database and file backup/restore procedures |
| `cloud/frontend/messages/en.json` | Frontend UI strings (English, source of truth) |
| `cloud/frontend/messages/ko.json` | Frontend UI strings (Korean, must mirror en.json keys) |
| `awt-skill/awt/SKILL.md` | Agent skill instructions — workflow, scenario rules (action table generated) |
| `awt-skill/awt/references/scenario-schema.md` | **Generated** from `src/aat/core/models.py`; never edit by hand |
| `mcp/README.md`, `mcp/server.py` docstrings | What the MCP tools promise to the calling AI |

---

## Change Trigger → Document Update Map

| What Changed | Update These Documents |
|---|---|
| API endpoint added/modified | `API_REFERENCE.md`, `CI_CD_GUIDE.md`, `README.md` (if user-facing) |
| Frontend UI text added/changed | `en.json`, `ko.json` (keep keys in sync) |
| Frontend page added | `en.json`, `ko.json`, `README.md` |
| CLI command added/changed | `QUICK_START.md`, `README.md` |
| AI provider added | `README.md` (Providers table), `QUICK_START.md`, `FAQ.md` |
| Pricing/tier changed | `README.md`, `FAQ.md`, `en.json` (landing.pricing*) |
| Environment variable added | `QUICK_START.md`, `API_REFERENCE.md` |
| DB schema changed | `BACKUP_RECOVERY.md` |
| Auth mechanism changed | `API_REFERENCE.md`, `CI_CD_GUIDE.md` |
| New feature added | `README.md` (Features), `QUICK_START.md`, `FAQ.md` |
| Dependency added/removed | `README.md` (Development), `CONTRIBUTING.md` |
| Rate limit changed | `API_REFERENCE.md`, `FAQ.md`, `CI_CD_GUIDE.md` |
| WebSocket event added | `API_REFERENCE.md` |
| File upload limits changed | `API_REFERENCE.md`, `en.json` (fileUpload.formats) |
| Scenario model / enum changed (`core/models.py`) | Run `python scripts/gen_scenario_schema.py` — see below |
| DEVQA block fields changed (`core/diagnosis.py`) | `awt-skill/awt/references/cli-reference.md`, `awt-skill/awt/SKILL.md`, `mcp/server.py`, `mcp/README.md` |

---

## Scenario Schema Rules

`src/aat/core/models.py` is the **source of truth** for what a scenario may
contain. The agent skill's reference is generated from it:

```bash
python scripts/gen_scenario_schema.py          # regenerate
python scripts/gen_scenario_schema.py --check  # fail if out of date
```

This writes `awt-skill/awt/references/scenario-schema.md` in full, and the
action table inside `awt-skill/awt/SKILL.md` between the `BEGIN GENERATED` and
`END GENERATED` markers. Everything else in `SKILL.md` stays hand-written.

Only prose that has no home in the code — what an action is for, what its value
looks like — lives in the generator. Adding an enum member without adding its
row there makes generation fail, on purpose.

`tests/test_docs_sync.py` runs the check in CI, and skips when the `awt-skill`
submodule is not checked out.

---

## i18n Sync Rules

`en.json` is the **source of truth**. When adding or removing keys:

1. Add the key with the English value to `en.json`
2. Add the **same key** to `ko.json` (value can be empty string `""` until translated)
3. Never add a key to `ko.json` that doesn't exist in `en.json`
4. Run `docs/check_sync.sh` to verify key parity

---

## Verification

Run the sync check script before submitting a PR:

```bash
bash docs/check_sync.sh
```

This checks:
- `en.json` and `ko.json` have identical key structures
- Endpoints listed in `API_REFERENCE.md` exist in the actual router files
- The agent skill's scenario docs match `src/aat/core/models.py`
