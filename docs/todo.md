# AdCode — Build Checklist

> Historical build log. This file records implementation phases as they happened, including older layouts that have since been superseded. For the current architecture and stack layout, see `README.md` and `docs/architecture.md`.

Work is ordered chronologically. Each phase depends on the one before it. Check off items as they are completed.

---

## Phase 1 — Project Scaffold

- [x] Create `requirements.txt` with initial dependencies (`facebook-business`, `mcp`, `openpyxl`, `jsonschema`, `python-dotenv`, `anthropic`)
- [x] Create `.env.example` with required environment variables (`FB_APP_ID`, `FB_APP_SECRET`, `FB_ACCESS_TOKEN`, `FB_ACCOUNT_ID`, `ANTHROPIC_API_KEY`)
- [x] Create `.gitignore` (`.env`, `state/`, `__pycache__/`, `.pytest_cache/`)
- [x] Create top-level directory structure:
  - `src/` — all source modules
  - `src/api/` — platform API clients
  - `src/services/` — business logic services
  - `campaigns/` — JSON campaign definition files (committed to repo)
  - `state/` — state files written by traffic.py (committed to repo, gitignored pattern for `.lock` files)
  - `tests/` — all test files
- [x] Create `src/__init__.py`, `src/api/__init__.py`, `src/services/__init__.py`
- [x] Update `README.md` with project overview, setup instructions, and usage examples

---

## Phase 2 — Campaign JSON Schema

- [x] Create `schemas/campaign.schema.json` — JSON Schema (draft-07) for a complete campaign definition
  - Campaign-level fields: `name`, `objective`, `status`, `special_ad_categories`, `spend_cap`, `daily_budget`
  - Ad set-level fields: `name`, `status`, `targeting`, `billing_event`, `optimization_goal`, `bid_amount`, `daily_budget`, `lifetime_budget`, `start_time`, `end_time`
  - Ad-level fields: `name`, `status`, `creative`
  - Creative fields: `name`, `object_story_spec` (link data: `message`, `link`, `name`, `description`, `call_to_action`)
- [x] Create `schemas/state.schema.json` — schema for state files written after a push
  - Maps each campaign/adset/ad definition to its Facebook-assigned ID
  - Includes `last_pushed_at` timestamp and `account_id`
- [x] Create `campaigns/example.json` — a minimal but valid example campaign definition that passes schema validation
- [x] Write `tests/test_schema.py` — validate that `example.json` passes schema, and that malformed inputs fail with expected errors

---

## Phase 3 — Facebook API Client

- [x] Create `src/api/meta.py` — Facebook Marketing API client
  - `MetaClient.__init__(app_id, app_secret, access_token, account_id)` — initialize SDK, store account reference
  - `MetaClient.create_campaign(params: dict) -> str` — returns campaign ID
  - `MetaClient.update_campaign(campaign_id: str, params: dict) -> None`
  - `MetaClient.pause_campaign(campaign_id: str) -> None`
  - `MetaClient.get_campaign(campaign_id: str) -> dict` — returns raw API fields
  - `MetaClient.list_campaigns(account_id: str) -> list[dict]` — fetch all campaigns with key fields
  - `MetaClient.create_adset(campaign_id: str, params: dict) -> str`
  - `MetaClient.update_adset(adset_id: str, params: dict) -> None`
  - `MetaClient.get_adset(adset_id: str) -> dict`
  - `MetaClient.list_adsets(campaign_id: str) -> list[dict]`
  - `MetaClient.create_ad(adset_id: str, params: dict) -> str`
  - `MetaClient.update_ad(ad_id: str, params: dict) -> None`
  - `MetaClient.get_ad(ad_id: str) -> dict`
  - `MetaClient.list_ads(adset_id: str) -> list[dict]`
  - `MetaClient.create_creative(params: dict) -> str`
  - Rate limit: surface `x-fb-ads-insights-throttle` header in a logged warning; raise on `(#32) Page request limit reached`
- [x] Write `tests/test_meta_client.py` — unit tests using mocked `facebook_business` SDK responses
  - Test create/update/get for each object type
  - Test rate limit warning path
  - Test API error propagation

---

## Phase 4 — State File Service

- [x] Create `src/services/state.py` — state file read/write
  - `StateFile.load(account_id: str) -> StateFile` — reads `state/{account_id}.json`, returns empty state if not found
  - `StateFile.save(account_id: str) -> None` — writes state to `state/{account_id}.json`
  - `StateFile.get_campaign_id(campaign_name: str) -> str | None`
  - `StateFile.get_adset_id(campaign_name: str, adset_name: str) -> str | None`
  - `StateFile.get_ad_id(campaign_name: str, adset_name: str, ad_name: str) -> str | None`
  - `StateFile.upsert_campaign(campaign_name: str, fb_id: str, params: dict) -> None`
  - `StateFile.upsert_adset(...)`, `StateFile.upsert_ad(...)`
  - `StateFile.to_dict() -> dict` — serializable form for JSON write
- [x] Write `tests/test_state.py` — test load/save round-trip, upsert, and missing-key lookups

---

## Phase 5 — Apply Engine (`traffic.py`)

- [x] Create `src/traffic.py` — the apply engine
  - `load_campaign_json(path: str) -> dict` — read and schema-validate a campaign JSON file
  - `plan(campaign_json: dict, state: StateFile, client: MetaClient) -> Plan` — compute create/update/noop diff without making API calls; returns a `Plan` object listing operations
  - `apply(plan: Plan, client: MetaClient, state: StateFile) -> ApplyResult` — execute operations in order (campaigns first, then adsets, then ads); write state file after each successful create
  - `Plan` dataclass: list of `CreateCampaign`, `UpdateCampaign`, `CreateAdSet`, `UpdateAdSet`, `CreateAd`, `UpdateAd` operations
  - `ApplyResult` dataclass: list of succeeded operations, list of failed operations with error details
  - On failure of any individual operation: log the error, continue with remaining operations, report all failures in result (do not abort entire run)
  - `main()` — CLI entry point: `python traffic.py <campaign_file.json> [--dry-run]`
    - `--dry-run` runs `plan()` only and prints the plan without calling `apply()`
- [x] Write `tests/test_traffic.py`
  - Test `plan()` produces correct operations for a new campaign (all creates)
  - Test `plan()` produces correct operations when state file exists (updates where fields differ, noops where identical)
  - Test `apply()` calls API methods in correct order
  - Test `apply()` writes state file after successful creates
  - Test `apply()` continues after partial failure and reports errors
  - All tests use mocked `MetaClient`

---

## Phase 6 — Drift Detection (`reconcile.py`)

- [x] Create `src/reconcile.py` — drift detection
  - `fetch_actuals(account_id: str, client: MetaClient) -> dict` — pull all campaigns, adsets, and ads from Facebook for the account; normalize to the same shape as the state file
  - `diff_state(state: StateFile, actuals: dict) -> DriftReport` — compare state file to actuals; classify each difference as:
    - `MISSING_FROM_FACEBOOK` — in state file but not found in API (deleted externally?)
    - `MISSING_FROM_STATE` — in API but not in state file (created outside AdCode?)
    - `FIELD_MISMATCH` — exists in both but a field value differs (manual edit in Ads Manager?)
    - `IN_SYNC` — no difference
  - `DriftReport` dataclass: list of `DriftItem` (object_type, name, fb_id, drift_type, expected, actual)
  - `format_report(drift_report: DriftReport) -> str` — human-readable text summary of the report
  - `main()` — CLI entry point: `python reconcile.py <account_id>`
- [x] Write `tests/test_reconcile.py`
  - Test `diff_state()` correctly identifies each drift type
  - Test `diff_state()` returns empty report when state matches actuals
  - Test `format_report()` produces non-empty string for a non-empty report

---

## Phase 7 — Validation Service

- [x] Create `src/services/validate.py` — campaign JSON validation
  - `validate_schema(campaign_json: dict) -> list[ValidationError]` — run JSON Schema validation; return structured errors
  - `validate_policy(campaign_json: dict, ai_client) -> list[PolicyWarning]` — call Claude API with the campaign JSON and a policy-checking prompt; parse response into `PolicyWarning` objects
  - `PolicyWarning` dataclass: `severity` (ERROR | WARNING | INFO), `field`, `message`, `suggestion`
  - `validate_all(campaign_json: dict, ai_client) -> ValidationResult` — run both schema and policy checks; return combined result
  - `ValidationResult` dataclass: `schema_errors: list`, `policy_warnings: list`, `is_pushable: bool` (False if any schema errors or ERROR-severity policy warnings)
  - Policy prompt: covers prohibited content categories, Special Ad Category triggers, copy patterns that frequently cause rejection, missing landing page fields
- [x] Write `tests/test_validate.py`
  - Test schema validation catches missing required fields
  - Test schema validation passes for valid example.json
  - Test policy validation with mocked Claude API response
  - Test `is_pushable` logic

---

## Phase 8 — Excel Ingestion Service

- [x] Create `src/services/ingest.py` — Excel → JSON ingestion
  - `read_excel(path: str) -> dict` — read all sheets from an Excel file using `openpyxl`; return raw structure (sheet names, headers, rows) as a dict for passing to AI
  - `extract_campaigns(excel_data: dict, ai_client) -> IngestionResult` — call Claude API with the raw Excel structure and the campaign JSON schema; ask it to extract campaign definitions and flag ambiguities
  - `IngestionResult` dataclass: `campaigns: list[dict]` (extracted campaign JSONs), `ambiguities: list[Ambiguity]`, `confidence: float`
  - `Ambiguity` dataclass: `field`, `sheet`, `cell_ref`, `raw_value`, `question` (what the AI is unsure about)
  - `format_ambiguity_report(result: IngestionResult) -> str` — human-readable list of ambiguities for review
  - `main()` — CLI entry point: `python -m src.services.ingest <excel_file.xlsx> --output <output.json>`
- [x] Write `tests/test_ingest.py`
  - Test `read_excel()` with a fixture Excel file
  - Test `extract_campaigns()` with a mocked Claude API response
  - Test `format_ambiguity_report()` produces readable output for non-empty ambiguities

---

## Phase 9 — MCP Server

- [x] Create `src/mcp_server.py` — MCP server entry point
  - Initialize `MetaClient`, `StateFile`, AI client from environment variables at startup
  - Register all tools (see below)
  - `main()` — start the MCP server on stdio transport

- [x] Implement MCP tool: `plan_campaigns` (validate + diff, replaces `validate_campaigns` + `preview_diff`)
- [x] Implement MCP tool: `apply_campaigns` (replaces `push_campaigns`)
- [x] Implement MCP tool: `list_campaigns` (live Facebook fetch)
- [x] Implement MCP tool: `pause_campaigns`
- [x] Implement MCP tool: `get_local_state` (replaces `get_campaign_json`)
- [x] Implement MCP tool: `get_campaign_status`
- [x] Implement MCP tool: `get_drift_report`
- [x] Implement MCP tool: `ingest_excel`

- [x] Write `tests/test_mcp_server.py`
  - Test each tool is registered and callable
  - Test `push_campaigns` calls validate then apply in order
  - Test `push_campaigns` aborts push when `is_pushable` is False
  - Test `get_campaign_json` returns correct state data
  - Test `preview_diff` returns plan without calling apply
  - All tests use mocked `MetaClient` and mocked AI client
- [x] Update `tests/test_mcp_server.py` to reflect renamed tools (`apply_campaigns`, `plan_campaigns`, `get_local_state`, `list_campaigns`)

---

## Phase 10 — Integration & Hardening

- [x] Write `tests/test_integration.py` — end-to-end tests against the Facebook Marketing API sandbox account
  - Create a campaign, verify state file is written, verify actuals match state
  - Update a field, verify idempotent re-push produces an update not a create
  - Introduce manual drift (update directly via SDK), verify `get_drift_report` detects it
  - Pause a campaign, verify status in state file and actuals
- [x] Add retry logic with exponential backoff to `MetaClient` for rate limit errors (`#32`, `#17`, `#4`)
- [x] Add structured logging throughout (`src/logger.py`) — log to stdout as JSON for easy parsing; include `account_id`, `operation`, `object_type`, `fb_id` in every log line where applicable
- [x] Validate that all `state/` writes are atomic (write to `.tmp` then rename) to prevent corrupt state files on interrupt
- [x] Document MCP server setup in `README.md` — how to connect Gemini to the MCP server

---

## Out of Scope (V2)

- `src/api/google_ads.py` — Google Ads API client
- `schemas/google_campaign.schema.json`
- Multi-account batch operations

Note: Email bot promoted from V2 to Phase 14 (see below).

---

## Phase 11 — Unified Changeset (ADR-004)

See `docs/decisions/004-unified-changeset.md` for full design.

- [x] **Add delete operation types to `src/traffic.py`** — add `DeleteCampaign`, `DeleteAdSet`, `DeleteAd` dataclasses alongside the existing create/update types
- [x] **Extend `plan()` in `src/traffic.py`** — after computing creates/updates, iterate over state file entries not present in the JSON and emit delete ops (using fb_ids from state, not name-matching Facebook)
- [x] **Extend `apply()` in `src/traffic.py`** — execute delete ops leaf-first (ads → ad sets → campaigns) using `MetaClient.delete_*`; remove deleted entries from the state file and save
- [x] **Update `plan_campaigns` MCP tool** — surface delete ops in the plan output alongside creates and updates; format clearly (e.g. `DELETE campaign "X" (fb_id: 123)`)
- [x] **Update `apply_campaigns` MCP tool** — if the plan contains deletes, return the plan and require `confirm_deletes=true` before applying; if no deletes, apply immediately as today
- [x] **Remove `preview_teardown` and `teardown_campaigns` MCP tools** from `mcp_server.py`
- [x] **Delete `src/services/teardown.py`** — logic is now absorbed into `traffic.py`
- [x] **Update `tests/test_traffic.py`** — add tests for delete ops in `plan()` (state entries absent from JSON produce deletes) and `apply()` (deletes execute leaf-first, state file entries are removed)
- [x] **Update `tests/test_mcp_server.py`** — update `push_campaigns` tests for the confirm_deletes guard; remove tests for the retired teardown tools
- [x] **Implement SWE-5: `find_duplicates` MCP tool** — fetch all campaigns for an account keyed by fb_id (not name), group by name, return each duplicate with fb_id and created date
- [x] **`fb_id`-based correlation in plan engine** — `plan()` matches campaigns/adsets/ads by `fb_id` in the JSON before falling back to name-match; `UpdateCampaign/UpdateAdSet/UpdateAd` carry `old_*_name` so `apply()` migrates state entries on rename; `state.py` adds `get_*_by_fb_id()` lookups; `fb_id` fields added as optional to `schemas/campaign.schema.json`
- [x] **`import_adsets` MCP tool** — adopt untracked ad sets from Facebook (MISSING_FROM_STATE) into the campaign JSON and state file in one command; equivalent of `terraform import` for ad sets; ADR-005 documents the design

---

## Deferred — SaaS Multi-Tenancy

Phase 12 (customer registry, API key auth, GitHub API file storage, onboarding scripts) was scoped for a hosted-SaaS delivery model. Superseded by ADR-008 (contractor service model). Deferred until a real client integration establishes the right tenancy requirements.

---

## Backlog

- [x] Implement `get_campaign_export(account_id)` — fetch full campaign hierarchy from Facebook (campaigns + ad sets + ads) for a given account in a single MCP tool call; `get_campaign_status` returns campaign-level only
- [x] BOM-tolerant JSON loading (ADR-007) — `load_campaign_json` changed to `encoding="utf-8-sig"`; BOM stripped from `demo_v1.json`
- [x] Contractor service model and multi-tenant architecture documented (ADR-008) — one MCP server instance per customer, human review gate between plan and apply, state committed per customer repo

---

## Phase 13 — Per-Customer Config & State Structure (ADR-008)

Implement the directory layout and server configurability described in ADR-008. Each customer gets their own isolated working directory with credentials, campaigns, and state.

- [x] **Define `config.json` format** — schema for per-customer config: `customer_slug`, `account_id`, `campaigns_dir`, `state_dir`; create `schemas/customer_config.schema.json`
- [x] **Update `mcp_server.py` to accept `--config <path>`** — load `config.json` at startup; derive `campaigns_dir`, `state_dir`, and `account_id` from it; fall back to current env-var defaults when flag is absent (backwards compatible)
- [x] **Update `StateFile.load` / `save` paths** — accept an explicit base directory so state resolves relative to the customer folder, not the repo root
- [x] **Create `customers/` directory with `demo/` scaffold** — move `campaigns/demo/` and `state/act_000000000.json` under `customers/demo/`; add `customers/demo/config.json` and `customers/demo/.env.example`
- [x] **Update `.gitignore`** — add `customers/*/.env` so per-customer credential files are never committed
- [x] **Write `scripts/new_customer.py`** — onboarding script: accepts `customer_slug` and `account_id`, creates `customers/{slug}/` directory scaffold, copies `.env.example`, prints next steps
- [x] **Update README** — replace current setup instructions with customer-centric workflow; document `--config` flag and `new_customer.py`
- [x] **Update tests** — pass explicit `state_dir` to `StateFile` in test fixtures; add test for `--config` startup path in `test_mcp_server.py`

---

## Phase 14 — Email Bot (`src/email_bot.py`)

The client-facing interface for the contractor service model. Clients send media plans by email; the operator receives a plan for review; approved plans are applied to Facebook; clients receive confirmation. See ADR-008 for flow design.

**Architecture:** Cloudflare Email Routing receives inbound mail at `traffic@example.com`, an Email Worker POSTs the raw message to `https://api.example.com/inbound`, and a FastAPI app on Fly.io handles the pipeline. Resend sends all outbound email.

### Inbound handling

- [x] **Create `src/email_bot.py`** — FastAPI webhook server; `POST /inbound` receives raw email from Cloudflare Email Worker and dispatches through the pipeline
- [x] **Sender authentication** — match `From` address against `email_addresses` in customer config; reject unrecognized senders; log rejections
- [x] **Attachment extraction** — detect Excel (`.xlsx`) attachments and save to a temp path for ingestion; fall back to plain-text body parsing if no attachment
- [x] **Brief parsing** — if no Excel attachment, pass email body to `extract_from_text()` in `src/services/brief.py` via Claude; extract campaign intent and flag ambiguities
- [x] **Ambiguity handling** — if ingestion returns ambiguities, reply to sender listing them before proceeding

### Plan-review gate (operator flow)

- [x] **Generate plan** — run `plan()` on ingested JSON; format output as readable text
- [x] **Email operator with plan** — send plan to `operator_email` with subject `[AdCode Review] {pending_id} | {original_subject}`; operator replies GO or HOLD
- [x] **Parse operator reply** — detect `GO` / `HOLD` keyword in reply body; match pending file via `pending_id` in subject
- [x] **Apply on approval** — on `GO`, run `apply_plan()`; on `HOLD`, notify client and discard pending file

### Outbound confirmation

- [x] **Confirmation to client** — after successful apply, send client a summary via Resend
- [x] **Hold notice** — on HOLD, send client a polite hold notification

### Infrastructure

- [x] **Create `src/services/email.py`** — Resend outbound wrapper: `send_email(msg, api_key)` with `EmailMessage` dataclass
- [x] **Create `src/services/brief.py`** — plain-text brief extraction via Claude using `BRIEF_EXTRACT` prompt; returns same `IngestionResult` shape as `extract_campaigns()`
- [x] **Create `src/workers/inbound.js`** — Cloudflare Email Worker; POSTs raw email JSON to webhook URL with shared secret
- [x] **Create `Dockerfile`** — `python:3.12-slim`, installs requirements, runs `uvicorn src.email_bot:app`
- [x] **Create `fly.toml`** — Fly.io config; always-on, 256 MB, persistent volume mounted at `/app/customers`
- [x] **Add `BRIEF_EXTRACT` prompt to `src/prompts.py`**
- [x] **Update `schemas/customer_config.schema.json`** — add `email_addresses`, `operator_email`, `bot_email` fields
- [x] **Update `customers/demo/config.json`** — add email fields
- [x] **Update `.gitignore`** — add `customers/**/state/.pending_*`
- [x] **Write `tests/test_email_bot.py`** — 12 tests; mock Resend, MetaClient, Anthropic; test sender auth, ambiguity reply, plan gate, GO/HOLD flow, unknown sender rejection

### Deployment (one-time operator steps)

- [x] **Cloudflare Email Routing** — enabled on `example.com`; route `traffic@example.com` → `adcode-inbound-example` worker
- [x] **Deploy Email Worker** — deployed via Cloudflare dashboard; `WEBHOOK_URL` and `WEBHOOK_SECRET` secrets set
- [x] **Resend domain verification** — example sending domain verified; SPF/DKIM/DMARC records in DNS
- [x] **Fly.io app** — app `adcode` deployed; volume `adcode_data` mounted at `/app/customers`; all secrets set
- [x] **Cloudflare DNS** — A/AAAA records for `api.example.com` pointing to Fly.io; TLS cert issued by Let's Encrypt via `flyctl certs add`

---

## Phase 15 — Pending Brief Durability

Pending files (`.pending_{id}.json`) are stored on the Fly.io volume and lost if the machine restarts before the operator replies GO/HOLD. A brief submitted minutes before a deploy or machine restart is silently discarded — the client and operator both get no notification.

### Problem

- Fly.io machines restart on every `flyctl deploy` (rolling restart)
- Pending files in `state/` survive restarts (they're on the volume) ✓
- But if a restart happens *between* the operator receiving the plan email and replying, the pending file still exists on the volume — so this is actually less of a problem than it seemed
- The real risk: if the volume is destroyed or the app is redeployed to a new machine with a fresh volume, all pending files are lost with no notification

### Solution

- [x] **Pending file expiry check** — on startup, scan all `state/.pending_*.json` files; any older than 24 hours trigger an operator notification email
- [x] **Startup scan in `email_bot.py`** — FastAPI lifespan context manager calls `_scan_expired_pending()` on boot (replaces deprecated `@app.on_event`)
- [x] **`_scan_expired_pending()`** — load all customer configs; for each, scan `state_dir` for `.pending_*` files; if `created_at` is >24h ago, send operator email and delete
- [x] **Operator notification template** — subject: `[AdCode] Expired brief: {client_subject}`
- [x] **Write `tests/test_pending_expiry.py`** — 5 tests; all passing

---

## Phase 16 — Email Bot Bug Fixes (in progress)

Several bugs discovered during real-world testing of the email bot. None have resulted in a successful Facebook push via email yet.

### Bugs fixed

- [x] **AI code fence stripping** — Claude wraps JSON in ` ```json ``` ` fences; `json.loads()` failed on raw text. Fixed in `ingest.py` and `brief.py`
- [x] **Empty `to` field on Resend** — `_parse_raw_email("")` returned empty `from`; fixed by falling back to webhook envelope address
- [x] **Thread-aware extraction** — `BRIEF_EXTRACT` prompt updated to synthesise full quoted thread so client can reply with answers inline
- [x] **Anthropic 529 overload — Worker rejection** — 529 caused 500 → Worker rejected email to sender. Fixed: `max_retries=6` + catch `APIStatusError(529)` and return 200 with graceful client notice
- [x] **Opus model in `brief.py`** — `claude-opus-4-7` has much lower rate limits; switched to `claude-sonnet-4-6`
- [x] **Markdown rendering** — email HTML was raw markdown (asterisks); added `markdown` library with `nl2br` + `tables` extensions
- [x] **Account ID in ambiguity questions** — prompts were flagging missing `account_id` as an ambiguity; suppressed since it comes from `config.json`
- [x] **Ambiguity email format** — redesigned to multiple-choice lettered questions with suggested options; campaign summary as a table

---

## Phase 17 — Email Bot Refactor: Mailroom Architecture (ADR-010)

Decouple the email bot from the engine. The bot validates and routes submissions; the engine runs locally. See ADR-010 for full rationale.

### Documentation

- [x] **Write ADR-010** — `docs/decisions/010-mailroom-engine-split.md`; documents mailroom role, three submission paths, local engine rationale
- [x] **Update README** — operator workflow, updated email bot description, CLI smoke test examples

### Email bot refactor (`src/email_bot.py`)

- [x] **Remove engine imports** — remove `MetaClient`, `StateFile`, `plan`, `apply as apply_plan`, `validate_all` imports
- [x] **Remove pending file system** — delete `_scan_expired_pending()`, lifespan context manager, `.pending_*` file read/write, `PENDING_EXPIRY_HOURS`
- [x] **Remove GO/HOLD flow** — delete `_handle_operator_reply()`, operator reply routing, `_format_plan_text()`
- [x] **Remove clarification loop** — delete `_handle_clarification()`, `_APPLY_CLARIFICATIONS` prompt, `.clarifying_*` file logic
- [x] **Implement three-path routing** in `_handle_inbound()`:
  - Path 1 (valid JSON template): reply client ack + forward template to operator as attachment
  - Path 2 (JSON fails schema): reply client with specific `jsonschema` errors and fix instructions; do not forward
  - Path 3 (xlsx or plain text): seed template via `ingest_excel` / `extract_from_text`; reply client with `.json` attachment and review instructions
- [x] **Remove `_APPLY_CLARIFICATIONS` and related prompts** — clarification loop removed entirely

### Infrastructure

- [x] **Create `requirements-email.txt`** — copy of `requirements.txt` without `facebook-business` SDK; used by Fly.io image
- [x] **Update `Dockerfile`** — use `requirements-email.txt` instead of `requirements.txt`
- [x] **Update `entrypoint.sh`** if needed to reflect removed pending scan

### MCP server

- [x] **Add startup connection check** to `src/mcp_server.py` when `--config` is used — call `client.list_campaigns(account_id)` with a single result; log success or exit with clear error on failure
- [x] **Add `--skip-connection-check` flag** for offline/test use

### Tests

- [x] **Rewrite `tests/test_email_bot.py`** — covers three-path routing: valid template (operator forward + client ack), invalid template (errors returned), dirty Excel (seeded template returned); 27 tests passing
- [x] **Delete `tests/test_pending_expiry.py`** — pending file mechanism removed
- [x] **Add `--config` connection check test** to `tests/test_mcp_server.py`

---

## Phase 18 — Agnostic Email Bot (ADR-011)

Remove per-sender authentication and per-customer config lookup from the email bot. The bot accepts all inbound email, uses global env vars for its settings, and seeds templates with an `account_id` placeholder the client must fill in manually.

- [x] **Refactor `src/email_bot.py`** — remove `_load_all_configs`, `_find_customer`, `CUSTOMERS_DIR`; add `OPERATOR_EMAIL`/`BOT_EMAIL` module constants from `os.environ`; remove unknown-sender rejection from webhook; seed `account_id` placeholder in Path 3
- [x] **Clean `customers/demo/config.json`** — remove `email_addresses`, `operator_email`, `bot_email`
- [x] **Clean `schemas/customer_config.schema.json`** — remove `email_addresses`, `operator_email`, `bot_email`
- [x] **Rewrite `tests/test_email_bot.py`** — remove `DEMO_CONFIG`, `TestUnknownSenderRejected`, `_find_customer` tests; mock global env vars; add `TestAnySenderAccepted`; 27 tests passing
- [x] **Write ADR-011** — `docs/decisions/011-agnostic-email-bot.md`
- [x] **Update README** — email bot section updated to reflect sender-agnostic behaviour and new env var model

### Fly.io secrets to set after deploy

```
OPERATOR_EMAIL=operator@example.com
BOT_EMAIL=traffic@example.com
RESEND_API_KEY=...
ANTHROPIC_API_KEY=...
WEBHOOK_SECRET=...
```

---

## Phase 19 — Ad Stack Model (ADR-012)

Shift state files from account-scoped to stack-scoped. Each Ad Stack (`campaigns/<name>.json`) now has its own isolated state file (`state/<name>.json`). Applying one stack can never delete or drift-detect campaigns belonging to another stack. See ADR-012 for full rationale.

### Documentation

- [x] **Write ADR-012** — `docs/decisions/012-ad-stack-model.md`; documents the Ad Stack concept, stack isolation, file naming convention
- [x] **Update README** — "How it works" table, directory layout, tool table descriptions for `get_drift_report` and `get_local_state`
- [x] **Update `docs/demo/demo.md`** — new file paths (`campaigns/demo_v1.json`), Ad Stack terminology, updated Test 6/7/8 prompts

### Tests

- [x] **`tests/test_state.py`** — add 3 tests: `load` uses `stack_name` for path, `save` uses `stack_name`, two stacks same account are independent
- [x] **`tests/test_traffic.py`** — add test: `plan()` only emits deletes for campaigns in its own state, not campaigns from other stacks
- [x] **`tests/test_mcp_server.py`** — update existing tests to assert `stack_name` passed to `StateFile.load`; update `get_drift_report` and `get_local_state` tests to pass `json_path`

### Code

- [x] **`src/services/state.py`** — add `stack_name` param to `StateFile.__init__`, `.load()`, `.save()`; file path uses `stack_name` stem, not `account_id`
- [x] **`src/mcp_server.py`** — derive `stack_name = Path(json_path).stem` in all handlers; pass to `StateFile.load`; change `get_drift_report` and `get_local_state` input schemas from `account_id` to `json_path`

### Demo restructure

- [x] **Move** `customers/demo/campaigns/act_000000000/demo_v1.json` → `customers/demo/campaigns/demo_v1.json`
- [x] **Delete** `customers/demo/campaigns/act_000000000/` directory
- [x] **Rename** `customers/demo/state/act_000000000.json` → `customers/demo/state/demo_v1.json`

---

## Phase 20 — Terraform Stack Layout (ADR-013)

Co-locate template and state in a single stack folder, matching Terraform's convention. Each stack is a directory (`<stack-name>/`) containing `<stack-name>.json` (template) and `state.json`. State location is derived entirely from `json_path` — `_require_state_dir()` and `_state_dir` global removed.

### Documentation

- [x] **Write ADR-013** — `docs/decisions/013-terraform-stack-layout.md`
- [x] **Update README** — "How it works" table, repository layout, operator workflow, multi-tenant example
- [ ] **Update `docs/demo/demo.md`** — new paths (`demo_v1/demo_v1.json`, `demo_v1/state.json`)

### Tests

- [ ] **`tests/test_mcp_server.py`** — change `stack_name="example"` assertions → `stack_name="state"`; remove any `_require_state_dir` patches

### Code

- [ ] **`src/mcp_server.py`** — remove `_state_dir`, `_campaigns_dir`, `_require_state_dir()`; all handlers use `state_dir=Path(json_path).parent`, `stack_name="state"`
- [ ] **`schemas/customer_config.schema.json`** — remove `campaigns_dir` and `state_dir` properties
- [ ] **`scripts/new_customer.py`** — update scaffold to flat layout (no `campaigns/`/`state/` subdirs)

### Demo restructure

- [ ] **Create** `customers/demo/demo_v1/`
- [ ] **Move** `customers/demo/campaigns/demo_v1.json` → `customers/demo/demo_v1/demo_v1.json`
- [ ] **Rename** `customers/demo/state/demo_v1.json` → `customers/demo/demo_v1/state.json`
- [ ] **Delete** `customers/demo/campaigns/` and `customers/demo/state/` directories
- [ ] **Update** `customers/demo/config.json` — remove `campaigns_dir` and `state_dir`

---

## Phase 21 - Strict IaC MCP Surface (ADR-015)

Reshape the MCP server around stack-scoped infrastructure-as-code operations. Remove broad live account console tools and direct live writes from the public MCP surface.

### Documentation

- [x] **Write ADR-015** - document the strict MCP boundary and removed live account tools
- [x] **Update README** - replace campaign/live-account tool table with stack-oriented tool names

### Tests

- [x] **Rewrite `tests/test_mcp_server.py`** - assert the new tool list, retired tool removal, stack-scoped drift, import discovery, and ad set import behavior

### Code

- [x] **Rename stack tools** - expose `show_stack`, `validate_stack`, `plan_stack`, `apply_stack`, `drift_stack`, `show_state`, `generate_stack_from_excel`
- [x] **Remove broad live tools** - remove MCP exposure for pause, live list/status/export, and duplicate search
- [x] **Replace `import_adsets`** - add `search_import_candidates` and `import_resource(resource_type="adset")`
- [x] **Tighten drift** - `drift_stack` reports only stack-managed objects
- [x] **Remove startup live account check** - startup validates local stack config only; provider errors surface when provider-backed tools run

### Bug logged — MCP ad set import discovery (fixed)

- **Issue:** `search_import_candidates` and `import_resource` discovered candidates only through `diff_state` / `fetch_actuals`, where the live hierarchy is keyed by **Facebook campaign `name`**. When the template’s campaign name and Graph `name` diverged for the same **`fb_id`** (rename drift), live ad sets under that campaign did not surface as import candidates.
- **Expected behaviour:** Any ad set returned by `GET …/{campaign_fb_id}/adsets` for a template campaign that declares `fb_id` should be importable if missing from that campaign’s `ad_sets` in the template (match by ad set `fb_id` or `name`).
- **Fix:** Candidate discovery calls `MetaClient.list_adsets(campaign_fb_id)` per tracked campaign and diffs against the template; imported rows include `fb_id`. Code: `_missing_template_adsets`, `_adset_entry_from_live` in `src/mcp_server.py`; tests updated in `tests/test_mcp_server.py`.

---

## Phase 22 - Public Repository Sanitization (ADR-016)

Prepare the current tree for public GitHub visibility without rewriting history.

### Documentation

- [x] **Write ADR-016** - document current-tree sanitization, ignored private workspaces, and placeholder public examples
- [x] **Update README** - note that `customers/` is intentionally ignored and public examples use placeholder IDs only
- [x] **Update SECURITY.md** - use the current strict IaC MCP tool names: `plan_stack`, `apply_stack`, and `import_resource`

### Tests

- [x] **Add public-readiness tests** - scan tracked files for personal deployment details, tracked customer workspaces, tracked local AI config, and private credential/state files

### Sanitization

- [x] **Remove tracked local AI config** - delete `.claude/settings.local.json` and ignore `.claude/`
- [x] **Sanitize mailroom deployment docs** - replace personal email, domain, webhook URL, and Fly app examples with placeholders
- [x] **Sanitize demo Excel workbooks** - replace real-looking account and page IDs with public placeholders while preserving workbook names and sheets
- [x] **Verify current tree** - run scans and tests before commit

---

## Phase 23 — Policy as Code (ADR-017 Tier 1)

Introduce a declarative rule system evaluated at `validate_stack` and `plan_stack` time. Rules are files in a `policies/` directory — versioned, composable, and deterministic. AI policy review remains as a second pass. See ADR-017.

### Documentation

- [x] **Write design doc** — `docs/policy-rules.md`; document rule file format, evaluation order, error vs. warning severity, and how to add custom rules
- [x] **Update ADR-017** — mark policy as code as in progress
- [x] **Update README** — add `policies/` to repository layout; document `validate_stack` policy evaluation

### Schema

- [x] **Create `schemas/policy.schema.json`** — JSON Schema for a policy rule file: `id`, `description`, `severity` (ERROR | WARNING), `condition` (field path + operator + value)

### Code

- [x] **Create `src/services/policy.py`** — policy rule engine
  - `load_policies(stack_dir: Path) -> list[PolicyRule]` — load all `.json` rule files from `policies/` in the stack directory and any operator-level `policies/` directory; merge and deduplicate by `id`
  - `evaluate(template: dict, rules: list[PolicyRule]) -> list[PolicyViolation]` — evaluate each rule against the template; return violations with `rule_id`, `severity`, `field`, `message`
  - `PolicyRule` dataclass: `id`, `description`, `severity`, `condition`
  - `PolicyViolation` dataclass: `rule_id`, `severity`, `field`, `message`
  - Initial built-in rules: broadmatch detection (ad set with no interests, behaviors, or custom audiences), missing spend cap on campaign, missing `end_time` on ad set, invalid objective/optimization goal combination
- [x] **Update `src/services/validate.py`** — call `policy.evaluate()` after schema validation; merge `PolicyViolation` results into `ValidationResult`; ERROR-severity violations set `is_pushable=False`
- [x] **Update `src/mcp_server.py`** — surface policy violations in `validate_stack` and `plan_stack` output; format clearly (rule ID, severity, field, message)

### Built-in rule library

- [x] **`policies/builtin/broadmatch.json`** — flag ad sets with no targeting interests, behaviors, or custom audiences
- [x] **`policies/builtin/spend-cap-required.json`** — flag campaigns without a `spend_cap`
- [x] **`policies/builtin/end-time-required.json`** — flag ad sets without `end_time`
- [x] **`policies/builtin/objective-billing-compatibility.json`** — flag invalid objective/billing event/optimization goal combinations

### Tests

- [x] **`tests/test_policy.py`** — unit tests for `load_policies`, `evaluate`, built-in rules; test ERROR blocks apply, WARNING does not; test custom rule file loaded from stack `policies/` directory

---

## Phase 24 — Cost Estimation (ADR-017 Tier 1)

Surface the declared budget delta as part of plan output. Support an optional account-level budget cap that blocks apply if exceeded. No Facebook API call required — derived entirely from the template. See ADR-017.

### Documentation

- [x] **Update ADR-017** — mark cost estimation as in progress
- [x] **Update README** — document `ACCOUNT_BUDGET_CAP` / `CURRENCY` env vars and budget delta in plan output

### Code

- [x] **Create `src/services/budget.py`** — budget estimation
  - `estimate_delta(plan: Plan, state: StateFile, template: dict) -> BudgetDelta` — compute total declared spend added, removed, and net from the plan changeset
  - `check_cap(delta: BudgetDelta, template: dict, cap: int | None) -> CapResult` — compare projected total against optional cap; return OK or EXCEEDED with overage amount
  - `BudgetDelta` dataclass: `added`, `removed`, `net` (whole dollars)
  - `CapResult` dataclass: `exceeded: bool`, `cap`, `projected`, `overage` (whole dollars)
- [x] **Update `src/traffic.py`** — call `budget.estimate_delta()` in `plan()`; attach `BudgetDelta` to `Plan` dataclass
- [x] **Update `src/mcp_server.py`** — display budget delta in `plan_stack` output; if a cap is configured and exceeded, surface a blocking warning before `apply_stack` executes

### Budget cap (stack `.env`)

- [x] **`ACCOUNT_BUDGET_CAP`** — optional env var in stack `.env`; whole dollars; blocks apply when projected total exceeds cap
- [x] **`CURRENCY`** — optional env var; ISO 4217; display only; defaults to USD
- Note: `globals.json` / `globals.py` deferred to Phase 28 (global variables); budget cap is stack-specific and lives in `.env`

### Tests

- [x] **`tests/test_budget.py`** — test `estimate_delta` for creates, updates, deletes; test `check_cap` for under-cap and over-cap cases; test plan output includes delta; test apply blocked when cap exceeded; 33 tests passing

---

## Phase 25 — Campaign Review Packet / Stack Documentation (ADR-017 Tier 1, highest priority)

`document_stack` generates a human-readable Markdown review artifact for a non-technical marketing manager, media director, or agency operator. This is the immediate bridge from the OSS engine to the commercial mission: AdCode should not merely produce technical logs; it should produce a buyer-readable proof packet showing what will launch, what it will cost, and whether it passes agency rules.

This phase supersedes the previous ordering where PR-driven plan/apply came next. PR automation remains aligned, but the review artifact is the highest-leverage next step for demos, customer discovery, and early pilots.

### Product requirement

The output should be framed as a **Campaign Review Packet**. It must be readable without JSON knowledge, GitHub knowledge, or terminal context.

The report should answer these questions in plain English:

1. **What is being launched or changed?**
2. **Is it safe to approve?**
3. **What policy checks passed, warned, or failed?**
4. **What budget exposure does this create?**
5. **Which campaigns/ad sets/ads are affected?**
6. **What targeting and flight dates will be used?**
7. **What requires human review before apply?**

### Documentation

- [x] **Update ADR-017** — mark stack documentation / reporting as in progress and note that this phase is being pulled ahead of PR automation to support demos and buyer-visible validation
- [x] **Update README** — add `document_stack` to MCP tools table and describe it as a Campaign Review Packet generator
- [x] **Add demo note to README or examples** — document how to run `validate_stack`, `plan_stack`, and `document_stack` together to produce a review packet for a sample campaign; add `examples/contractor-mistakes/` demo stack

### Code

- [x] **Create `src/services/document.py`** — stack documentation generator
  - `generate(template: dict, state: StateFile, violations: list[PolicyViolation], delta: BudgetDelta | None, plan: Plan | None = None, cap_result: CapResult | None = None, currency: str = "USD") -> str` — produce Markdown formatted for review by a non-technical manager
  - Avoids JSON, raw field names, internal class names, and developer-centric phrasing
  - Uses plain-English labels and concise tables
- [x] **Required report sections**
  - **Executive summary** — account/stack name, number of campaigns/ad sets/ads, overall approval status
  - **Approval recommendation** — short plain-English conclusion based on policy errors, warnings, and budget cap status
  - **Budget impact** — declared added/removed/net budget, projected total if available, cap status, currency, and per-object budget breakdown
  - **Policy results** — pass/warning/error summary with rule IDs, severity, affected object/path, and plain-English fix guidance
  - **Campaign hierarchy** — campaign → ad sets → ads with status, objective, budget, and optimization goal
  - **Targeting summary** — per ad set: geo, interests, behaviors, custom audiences, and broad targeting warning
  - **Flight dates** — start/end dates and duration; flags missing end dates and flights >90 days
  - **Planned changes** — creates, updates, deletes summary from plan when available
  - **Human review checklist** — checklist of items to confirm before apply
  - **Next action** — fix blocking issues / approve with warnings / proceed to apply
- [x] **Update `src/mcp_server.py`** — add `document_stack` MCP tool; calls `document.generate()` with template, state, policy violations, budget delta, plan, and cap result; returns Markdown string; no Meta API call required
- [x] **Create or update demo stack** — `examples/contractor-mistakes/` with broad targeting, missing end date, missing spend cap, and budget cap pressure; includes `README.md` with demo flow and `.env.example`

### Tests

- [x] **`tests/test_document.py`** — 12 tests passing: required sections, policy errors/warnings, budget impact with delta and cap, broad targeting flag, missing end date, graceful empty state, no raw JSON, status BLOCKED/READY, planned changes section

---

## Phase 26 — Demo Package and Customer Discovery Support (commercial validation priority)

Create a small, repeatable demo path that shows AdCode catching real-looking contractor mistakes before spend happens. This phase is intentionally lightweight and should avoid overbuilding SaaS or CI infrastructure.

### Documentation / demo assets

- [ ] **Create a demo walkthrough** — document a 10-minute flow: bad contractor template → `validate_stack` → `plan_stack` → budget impact → `document_stack` Campaign Review Packet
- [ ] **Create a demo script** — include talk track for agency/media/analytics stakeholders, emphasizing risk reduction and review artifacts rather than internal implementation details
- [ ] **Create sample review packet output** — checked into examples if sanitized and suitable for OSS; otherwise keep sensitive versions in `private-docs/`
- [ ] **Create pilot-readiness checklist** — minimal steps needed to run a QA-only pilot without granting Meta write access

### Demo requirements

- [ ] Demo should work without a real Meta account for first conversation
- [ ] Demo should show at least three concrete issues: targeting risk, missing/unsafe flight date, and budget impact/cap risk
- [ ] Demo should produce a single review artifact that can be sent to a non-technical reviewer
- [ ] Demo should make clear that live apply is optional; AdCode can begin as a QA/review layer

---

## Phase 27 — PR-Driven Plan/Apply (ADR-017 Tier 1, defer full automation until pilot demand)

Automate `plan_stack` on pull request open and post the output as a PR comment. Merge can trigger apply later. Implements the Atlantis pattern without changes to the core engine. See ADR-017.

This remains strategically aligned, but full implementation is deferred behind the Campaign Review Packet and initial customer discovery. Agencies may not be ready to approve live Meta applies through GitHub on day one. For demos and early pilots, a manual or local review-packet workflow is sufficient.

### Documentation

- [ ] **Write `docs/ci-integration.md`** — how to wire up the GitHub Actions workflow; required secrets (`FB_APP_ID`, `FB_APP_SECRET`, `FB_ACCESS_TOKEN`, `ANTHROPIC_API_KEY`); expected PR comment format
- [ ] **Update ADR-017** — mark PR-driven plan/apply as deferred until review-packet demo and pilot feedback validate workflow demand
- [ ] **Update README** — add CI integration section linking to `docs/ci-integration.md`

### Code

- [ ] **Create `scripts/ci_plan.py` first** — CLI wrapper that accepts a stack template path, runs plan/document generation, formats output as Markdown, and prints to stdout for capture by a workflow
- [ ] **Create `.github/workflows/plan.yml` later** — trigger on `pull_request` when `**/*_template.json` changes; check out repo; install dependencies; run `ci_plan.py`; post review packet or plan output as PR comment via GitHub API
- [ ] **Defer `.github/workflows/apply.yml`** — do not prioritize merge-triggered live apply until at least one real pilot confirms this is desirable and safe
- [ ] **Create `scripts/ci_apply.py` later** — CLI wrapper that accepts a stack template path, runs apply, exits non-zero on failure
- [ ] **Update `src/traffic.py`** — ensure plan and apply exit codes are reliable for CI use (0 = success, 1 = failure, 2 = plan has blocking violations)

### Tests

- [ ] **`tests/test_ci_plan.py`** — test `ci_plan.py` output format; test exit codes for clean plan, violations, and engine error

---

## Phase 28 — Delivery Snapshot (ADR-017 Tier 2, high buyer value after review packet)

`delivery_stack` pulls spend, impressions, and delivery status for each managed campaign and compares against declared budget and flight dates. Scoped to managed stack objects only, consistent with ADR-015. See ADR-017.

This is the most buyer-visible Tier 2 feature because it answers: **is the approved campaign actually running?** Build after the review packet/demo unless a pilot specifically asks for it sooner.

### Documentation

- [ ] **Update ADR-017** — mark delivery snapshot as next candidate after Campaign Review Packet; note ADR-015 tension and resolution (stack-scoped reads only)
- [ ] **Update README** — add `delivery_stack` to MCP tools table

### Code

- [ ] **Extend `src/api/meta.py`** — add `get_campaign_insights(campaign_id: str, date_preset: str) -> dict`; fields: `spend`, `impressions`, `clicks`, `reach`, `cpm`; use `date_preset=lifetime` by default
- [ ] **Create `src/services/delivery.py`** — delivery snapshot
  - `snapshot(template: dict, state: StateFile, client: MetaClient) -> DeliveryReport` — for each campaign in state, fetch insights and effective status; compare spend against declared `daily_budget` / `lifetime_budget` and flight dates; classify each campaign as SPENDING, ZERO_SPEND, PAUSED, ERROR, or NOT_STARTED
  - `DeliveryReport` dataclass: list of `CampaignDelivery` (name, fb_id, status, spend, budget, classification, note)
- [ ] **Update `src/mcp_server.py`** — add `delivery_stack` MCP tool; call `delivery.snapshot()`; format as a table with clear status indicators
- [ ] **Consider adding delivery status to Campaign Review Packet** — once implemented, include live delivery status in reports for applied stacks

### Tests

- [ ] **`tests/test_delivery.py`** — test each classification case; test campaigns not yet in state are excluded; test `get_campaign_insights` mock returns correct field mapping

---

## Phase 29 — Schema Linting (ADR-017 Tier 2, build based on customer pain)

Provider-aware rules beyond JSON Schema: valid objective/optimization goal/billing event combinations, pixel requirements, placement constraints. Deterministic and reproducible. See ADR-017.

This aligns with the governance mission, but should be driven by real pilot feedback so the first lint rules match the mistakes agencies actually need to prevent.

### Documentation

- [ ] **Write `docs/schema-linting.md`** — document supported lint rules, how to suppress a rule, and how to contribute new rules
- [ ] **Update ADR-017** — mark schema linting as deferred until customer discovery identifies the highest-value deterministic checks

### Code

- [ ] **Create `src/services/lint.py`** — schema linter
  - `lint(template: dict) -> list[LintError]` — run all lint rules against the template; return structured errors
  - `LintError` dataclass: `rule_id`, `path` (JSON pointer), `message`, `severity`
  - Candidate initial rules:
    - Objective/optimization goal compatibility matrix (e.g. `OUTCOME_SALES` requires `OFFSITE_CONVERSIONS` or `CONVERSIONS`)
    - Objective/billing event compatibility matrix
    - Pixel required when objective is `OUTCOME_SALES` or `OUTCOME_LEADS`
    - `bid_amount` required when `bid_strategy` is `LOWEST_COST_WITH_BID_CAP`
    - Mutually exclusive budget fields (`daily_budget` and `lifetime_budget` cannot both be set on the same ad set)
- [ ] **Update `src/services/validate.py`** — call `lint()` before AI policy review; surface `LintError` results in `ValidationResult`; ERROR-severity lint errors set `is_pushable=False`
- [ ] **Update `src/mcp_server.py`** — include lint errors in `validate_stack` and `plan_stack` output
- [ ] **Feed lint results into Campaign Review Packet** — summarize deterministic configuration errors in plain English

### Tests

- [ ] **`tests/test_lint.py`** — one test per lint rule: valid config passes, invalid config fails with correct rule ID and path; test `is_pushable` blocked by ERROR lint errors

---

## Phase 30 — Global Variables and Budget Enforcement (ADR-017 Tier 2, scale feature)

Operator-level `globals.json` supplying shared values injected into stacks at plan time. Complements stack `.env` — globals handle policy-level shared configuration, `.env` handles credentials. See ADR-017.

This is useful for multi-client or agency-wide scale, but the Phase 24 stack `.env` budget cap is sufficient for initial demos and pilots.

### Documentation

- [ ] **Create `docs/globals.md`** — document `globals.json` format, resolution order (stack dir → parent dirs), supported variable types, and `${VAR}` interpolation syntax
- [ ] **Update ADR-017** — mark global variables as a scale feature after pilot validation
- [ ] **Update README** — document `globals.json` in repository layout

### Schema

- [ ] **Create `schemas/globals.schema.json`** — JSON Schema for `globals.json`: `account_budget_cap`, `currency`, `default_page_id`, `default_pixel_id`, and a free-form `vars` map for `${VAR}` interpolation

### Code

- [ ] **Extend `src/services/globals.py`** (started in Phase 24) — add `interpolate(template: dict, globals: Globals) -> dict`; replace `${VAR}` tokens in template string values before validation and plan
- [ ] **Update `src/traffic.py`** — call `globals.interpolate()` on the loaded template before `plan()` runs
- [ ] **Update `src/mcp_server.py`** — load globals at startup; log which globals file was found; surface interpolation errors clearly
- [ ] **Feed resolved global budget cap into Budget Impact Review** — make the final Campaign Review Packet show whether the cap came from stack `.env` or global config

### Tests

- [ ] **`tests/test_globals.py`** — test resolution walk-up finds nearest `globals.json`; test interpolation replaces tokens; test missing variable raises clear error; test budget cap loaded correctly

---

## Phase 31 — Scheduled Drift Monitoring (ADR-017 Tier 2, pilot/support feature)

Run `drift_stack` on a configurable schedule and notify the operator of out-of-band changes. See ADR-017.

This is highly aligned with the governance mission, but is best built after there is a real pilot or support customer who wants an applied stack monitored over time. It is also a natural future paid support/hosted capability.

### Documentation

- [ ] **Update ADR-017** — mark scheduled drift monitoring as a pilot/support feature
- [ ] **Update `integrations/email_mailroom/README.md`** — document drift monitor deployment alongside the mailroom

### Code

- [ ] **Create `src/services/drift_monitor.py`** — scheduled drift runner
  - `run_and_notify(config_path: Path, email_client, operator_email: str) -> None` — load stack, run `fetch_actuals()` + `diff_state()`, send email only if drift items exist; include formatted drift report in body
  - `format_drift_email(report: DriftReport) -> str` — Markdown drift summary suitable for email
- [ ] **Create `scripts/drift_monitor.py`** — CLI entry point: `python scripts/drift_monitor.py --config <stack>` — runs once; intended to be called by cron or a scheduler
- [ ] **Update `fly.toml`** — add a cron-style scheduled machine or document `fly machine run --schedule` invocation for drift monitor
- [ ] **Update `integrations/email_mailroom/README.md`** — document environment variables: `DRIFT_SCHEDULE`, `OPERATOR_EMAIL`
- [ ] **Eventually feed drift status into Campaign Review Packet** — for applied stacks, include whether live Facebook matches approved state

### Tests

- [ ] **`tests/test_drift_monitor.py`** — test notification sent when drift exists; test no email sent when stack is clean; test email format includes drift item details

---

## Phase 32 — Workspace Registry and Registered Stacks (ADR-018 / ADR-019, foundational governance feature)

Move AdCode from a single ambient active stack toward a workspace model where approved stacks are registered and selected by stable `stack_id` values. This is the highest-leverage next step for organizational MCP use because it supports operational safety, governance, explainability, and integration.

The current `--config <stack_template>` local operator mode should continue working. The workspace registry should be introduced as an optional mode first, then become the preferred path for multi-stack and organizational workflows.

### Product requirement

- [ ] **Preserve local operator mode** — current one-stack `--config` workflow must remain simple for demos, development, and single-operator use
- [ ] **Prevent arbitrary file/account combinations** — registered stacks should bind template path, state path, ad account ID, environment, and credential profile together
- [ ] **Make environment explicit** — stack metadata should identify client, environment, platform, account ID, and operational risk level
- [ ] **Support read-only discovery** — agents should be able to list and describe what AdCode is allowed to manage before planning or applying

### Documentation

- [ ] **Create `docs/workspace-registry.md`** — document workspace file format, registered stack metadata, local vs organizational mode, and migration path from `--config`
- [ ] **Update README** — add a short note that current `--config` mode is local operator mode and registered stacks are the preferred direction for multi-environment use
- [ ] **Update `docs/product-brief.md`** — reference registered stacks as the concrete mechanism behind operational safety and integration
- [ ] **Update `docs/roadmap.md`** — mark workspace registry as the next foundational governance feature once implementation starts

### Schema / config

- [ ] **Create `schemas/workspace.schema.json`** — validate workspace registry files
- [ ] **Define workspace file format** — include `version`, `workspace_id`, `default_mode`, and `stacks` map
- [ ] **Define registered stack fields** — `stack_id`, `client`, `environment`, `platform`, `template_path`, `state_path`, `ad_account_id`, `credential_profile`, `allowed_operations`, `requires_confirmation`, `allow_deletes`
- [ ] **Define path resolution rules** — relative paths resolve from workspace file directory; absolute paths allowed only for local/private use

### Code

- [ ] **Create `src/services/workspace.py`** — load, validate, and resolve workspace registry files
- [ ] **Add `Workspace` and `RegisteredStack` models** — provide typed access to stack metadata and resolved paths
- [ ] **Update `src/mcp_server.py` startup** — accept optional `--workspace <path>` in addition to current `--config <path>`
- [ ] **Implement `list_stacks` MCP tool** — read-only; returns stack IDs, client, environment, platform, account ID, and allowed operations
- [ ] **Implement `describe_stack(stack_id)` MCP tool** — read-only; returns resolved stack metadata without secrets
- [ ] **Allow `validate_stack(stack_id?)` and `plan_stack(stack_id?)`** — if workspace mode is active, operate on the registered stack; if omitted in legacy mode, use the active stack
- [ ] **Block unknown stack IDs** — fail closed with a clear error if an agent requests an unregistered stack
- [ ] **Avoid exposing secrets** — never return tokens, app secrets, or credential values through workspace tools

### Tests

- [ ] **`tests/test_workspace.py`** — validate workspace schema, path resolution, duplicate stack IDs, missing stack files, and unknown stack lookup errors
- [ ] **`tests/test_mcp_workspace_tools.py`** — test `list_stacks`, `describe_stack`, and stack-aware `validate_stack`/`plan_stack` with mocked providers
- [ ] **Migration test** — verify existing `--config` local operator mode still starts and existing stack tools still work

---

## Phase 33 — Durable Plan Records and `apply_plan` (ADR-018 / ADR-019, safety and audit foundation)

Make plans durable review artifacts instead of transient tool output. Applying changes in organizational mode should eventually require a previously generated `plan_id` that binds the operation to a registered stack, account ID, stack hash, state hash, generated timestamp, and changeset summary.

This phase strengthens operational safety, governance, explainability, and future PR/approval workflows.

### Product requirement

- [ ] **Make plan review explicit** — users and agents should have a stable `plan_id` to reference during approval
- [ ] **Bind apply to reviewed plan** — organizational mode should prefer `apply_plan(plan_id, ...)` over direct ambient `apply_stack`
- [ ] **Detect stale plans** — applying a plan should fail or warn if the stack/state inputs changed since the plan was generated
- [ ] **Preserve explainability** — plan records should include enough structured data for AI summaries, review packets, and audit logs

### Documentation

- [ ] **Create `docs/plan-records.md`** — document `plan_id`, plan storage, hash binding, expiration/staleness rules, and apply workflow
- [ ] **Update ADR-004 or add follow-up ADR** — clarify that unified changesets become durable plan records in organizational mode
- [ ] **Update README MCP tools table** — document `apply_plan` once implemented and explain relationship to `apply_stack`
- [ ] **Update `docs/product-brief.md`** — identify durable plan records as the mechanism for safe agent-mediated approval

### Schema / storage

- [ ] **Create `schemas/plan.schema.json`** — schema for durable plan records
- [ ] **Define plan storage location** — likely stack-local `.adcode/plans/<plan_id>.json` or workspace-level `.adcode/plans/`
- [ ] **Define plan ID format** — stable, unique, non-secret identifier suitable for audit logs and user confirmation
- [ ] **Record plan inputs** — stack ID, template path, state path, ad account ID, stack hash, state hash, generated timestamp, AdCode version if available
- [ ] **Record plan summary** — creates, updates, deletes, delete count, budget impact, risk summary, policy result summary

### Code

- [ ] **Create `src/services/plans.py`** — create, persist, load, validate, and expire plan records
- [ ] **Update `plan_stack`** — return a `plan_id` when plan persistence is enabled; preserve current human-readable plan output
- [ ] **Implement `show_plan(plan_id)` MCP tool** — read-only; returns plan metadata, changeset, risk summary, and staleness status
- [ ] **Implement `apply_plan(plan_id, confirmations...)` MCP tool** — load the plan, verify stack/account/hash bindings, enforce confirmations, then apply
- [ ] **Keep `apply_stack` for local mode** — retain direct apply for current local workflow, but document it as less suitable for organizational mode
- [ ] **Add staleness checks** — detect changed template/state files before applying a saved plan
- [ ] **Add delete confirmation binding** — if deletes are present, confirmation should reference the plan ID and stack/account identity

### Tests

- [ ] **`tests/test_plan_records.py`** — test plan creation, plan loading, hash binding, stale plan detection, and missing plan errors
- [ ] **`tests/test_apply_plan.py`** — test applying from a valid plan, blocking stale plans, blocking missing confirmations, and preserving local `apply_stack`
- [ ] **MCP tests** — test `show_plan` and `apply_plan` tool responses with mocked Meta client

---

## Phase 34 — Domain Audit Log and Governance Events (ADR-018 / ADR-019, organizational trust feature)

Add an AdCode-owned audit log for domain-specific events. External MCP gateways may audit tool calls, but AdCode still needs advertising-domain audit records that capture stack identity, account identity, plan IDs, confirmation values, and state-write results.

This phase supports governance, operational safety, explainability, and future organizational deployments.

### Product requirement

- [ ] **Record mutation history** — every apply/import/state-changing operation should produce an audit event
- [ ] **Record important live reads** — drift checks and import discovery should be auditable when they call Facebook
- [ ] **Avoid secret leakage** — audit logs must redact tokens, app secrets, access tokens, and sensitive credential values
- [ ] **Support local and organizational mode** — write local JSONL audit logs now; allow future gateway/user identity fields when available

### Documentation

- [ ] **Create `docs/audit-log.md`** — document event types, JSONL format, redaction rules, retention expectations, and local vs organizational use
- [ ] **Update README** — mention AdCode domain audit events alongside Git history once implemented
- [ ] **Update `docs/product-brief.md`** — describe audit logs as the governance mechanism for who changed what and what state was written

### Schema / format

- [ ] **Create `schemas/audit-event.schema.json`** — validate audit event records
- [ ] **Define event types** — `plan_created`, `apply_started`, `apply_completed`, `apply_failed`, `drift_checked`, `import_started`, `import_completed`, `import_failed`
- [ ] **Define common fields** — timestamp, event ID, caller identity if available, stack ID, client, environment, ad account ID, tool name, plan ID, result status
- [ ] **Define redaction rules** — ensure no secrets or raw credentials are written

### Code

- [ ] **Create `src/services/audit.py`** — append-only JSONL audit writer with redaction and best-effort failure handling
- [ ] **Add audit configuration** — support default local path such as `.adcode/audit.jsonl`; allow override by CLI/server arg or workspace config
- [ ] **Instrument `plan_stack`** — emit `plan_created` when durable plan records are enabled
- [ ] **Instrument `apply_stack` / `apply_plan`** — emit started/completed/failed events with changeset summary and state write result
- [ ] **Instrument `drift_stack`** — emit drift check event including item count and account identity, not full sensitive payloads
- [ ] **Instrument `import_resource`** — emit import events showing adopted resource type and IDs where safe
- [ ] **Surface audit path in `show_stack` / `describe_stack`** — help operators know where governance records are written

### Tests

- [ ] **`tests/test_audit.py`** — test event write, redaction, append behavior, and schema validation
- [ ] **Integration-style tests with mocked operations** — verify apply/drift/import emit expected audit events

---

## Phase 35 — Organizational MCP Readiness Hardening (ADR-018 / ADR-019, integration feature)

Prepare AdCode to run cleanly behind approved AI clients, MCP gateways, or enterprise connector platforms without making the gateway the source of domain truth.

This phase should come after the workspace registry, durable plan records, and audit log foundations are underway.

### Product requirement

- [ ] **Keep MCP as an interface layer** — core governance logic must remain usable from CLI/CI/future UI, not only MCP
- [ ] **Accept caller context when available** — allow gateways to pass identity/session metadata, but do not require it for local mode
- [ ] **Expose safe structured outputs** — tools should return machine-readable summaries that agents can explain without inventing facts
- [ ] **Fail closed on policy uncertainty** — missing stack registration, account mismatch, stale plan, or missing confirmation should block mutation

### Documentation

- [ ] **Create `docs/organizational-deployment.md`** — describe local operator mode vs centralized MCP/gateway mode, credential boundaries, and recommended controls
- [ ] **Document gateway compatibility expectations** — identity headers/context, tool-level RBAC, audit layering, and approved AI-client deployment patterns
- [ ] **Update private integration notes if promoted later** — keep mainstream client setup docs private until verified and aligned with organizational safety model

### Code

- [ ] **Add optional caller context model** — capture user/session/client identity from MCP request context if the client/gateway provides it
- [ ] **Thread caller context into audit events** — include user identity where available without breaking local mode
- [ ] **Return structured tool results consistently** — include `status`, `stack_id`, `account_id`, `warnings`, and `next_actions` where useful
- [ ] **Add account identity verification hook** — before mutating registered stacks, verify the live provider account matches the registered account when provider support exists
- [ ] **Add read-only default mode for workspace server** — allow server startup in read-only mode where mutating tools fail closed
- [ ] **Add capability reporting** — expose what operations are available in current local/workspace mode without exposing secrets

### Tests

- [ ] **MCP structured-output tests** — verify key tools return predictable fields for agent consumption
- [ ] **Read-only mode tests** — verify mutating tools are blocked while read/plan tools still work
- [ ] **Caller context tests** — verify optional user/session data flows into audit events when provided and is omitted safely when absent

## Phase 36 — Minimal MCP Tool Surface (ADR-022, urgent simplification)

Treat MCP endpoint simplicity as a product feature and safety boundary. Converge the Local Operator Mode tool list toward Terraform-like stack lifecycle verbs instead of exposing overlapping convenience endpoints.

This phase should be prioritized before adding new MCP tools. New authoring, documentation, import, or validation capabilities should first try to fit into the simplified surface described by ADR-022.

### Product requirement

- [x] **Keep the public MCP tool list small** — optimize for obvious agent behavior over convenience endpoint count
- [x] **Use `plan_stack` as the normal validation path** — users should edit JSON, run plan, fix issues, and plan again
- [x] **Keep JSON as the primary UI** — authoring helpers should draft visible JSON, not hide desired state behind tools
- [x] **Preserve stack-scoped IaC semantics** — no broad live Facebook account console behavior through MCP
- [x] **Prefer resources/docs over tools for static information** — schema, examples, and authoring guidance should not become multiple tool endpoints

### Documentation

- [x] **Update README MCP tool table** — reflect the simplified target surface and any deprecated/renamed tools
- [x] **Create `docs/stack-authoring.md`** — document JSON-first authoring, minimal valid stack shape, common enum values, recipes, and common mistakes
- [x] **Document MCP tool addition criteria** — include ADR-022's checklist in developer-facing docs so future features do not expand the surface by default
- [x] **Update examples and onboarding text** — make the default loop `edit JSON -> plan_stack -> apply_stack`

### Code

- [x] **Demote or remove `validate_stack` from the public MCP tool list** — keep validation internally, but make `plan_stack` the preferred feedback path
- [x] **Fold `search_import_candidates` into `import_resource`** — add an explicit preview/list action so import discovery and import execution share one public verb
- [x] **Replace `generate_stack_from_excel` with `draft_stack`** — preserve Excel support first, then allow future source types such as text briefs or recipes without adding new tools
- [x] **Keep `draft_stack` non-mutating by default** — return draft JSON, assumptions, ambiguities, and next actions without calling Facebook or applying changes
- [x] **Evaluate MCP resources for static authoring materials** — expose schema/docs/examples as resources if practical; otherwise keep them in docs without adding tools
- [x] **Audit `src/mcp_server.py` tool descriptions** — make each remaining public tool's purpose and safety boundary explicit

### Tests

- [x] **Tool list snapshot test** — verify the public MCP tool list matches the simplified expected set
- [x] **`plan_stack` validation-path tests** — verify schema/policy failures are surfaced clearly through `plan_stack`
- [x] **`import_resource` preview tests** — verify preview mode lists candidates without writing template/state or calling live write APIs
- [x] **`draft_stack` Excel compatibility tests** — verify existing Excel ingestion behavior is preserved under the new tool name
- [x] **Non-mutation tests for authoring helpers** — verify draft/resource/documentation paths do not call Facebook write APIs
