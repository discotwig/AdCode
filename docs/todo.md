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
- [x] **Create `customers/` directory with `demo/` scaffold** — move `campaigns/demo/` and `state/act_366643171197739.json` under `customers/demo/`; add `customers/demo/config.json` and `customers/demo/.env.example`
- [x] **Update `.gitignore`** — add `customers/*/.env` so per-customer credential files are never committed
- [x] **Write `scripts/new_customer.py`** — onboarding script: accepts `customer_slug` and `account_id`, creates `customers/{slug}/` directory scaffold, copies `.env.example`, prints next steps
- [x] **Update README** — replace current setup instructions with customer-centric workflow; document `--config` flag and `new_customer.py`
- [x] **Update tests** — pass explicit `state_dir` to `StateFile` in test fixtures; add test for `--config` startup path in `test_mcp_server.py`

---

## Phase 14 — Email Bot (`src/email_bot.py`)

The client-facing interface for the contractor service model. Clients send media plans by email; the operator receives a plan for review; approved plans are applied to Facebook; clients receive confirmation. See ADR-008 for flow design.

**Architecture:** Cloudflare Email Routing receives inbound mail at `traffic@ryanbishop.me`, an Email Worker POSTs the raw message to `https://api.ryanbishop.me/inbound`, and a FastAPI app on Fly.io handles the pipeline. Resend sends all outbound email.

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

- [x] **Cloudflare Email Routing** — enabled on `ryanbishop.me`; route `traffic@ryanbishop.me` → `adcode-inbound` worker
- [x] **Deploy Email Worker** — deployed via Cloudflare dashboard; `WEBHOOK_URL` and `WEBHOOK_SECRET` secrets set
- [x] **Resend domain verification** — `ryanbishop.me` verified; SPF/DKIM/DMARC records in Cloudflare DNS
- [x] **Fly.io app** — app `adcode` deployed; volume `adcode_data` mounted at `/app/customers`; all secrets set
- [x] **Cloudflare DNS** — A/AAAA records for `api.ryanbishop.me` pointing to Fly.io; TLS cert issued by Let's Encrypt via `flyctl certs add`

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
OPERATOR_EMAIL=bishopryant@gmail.com
BOT_EMAIL=traffic@ryanbishop.me
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

- [x] **Move** `customers/demo/campaigns/act_366643171197739/demo_v1.json` → `customers/demo/campaigns/demo_v1.json`
- [x] **Delete** `customers/demo/campaigns/act_366643171197739/` directory
- [x] **Rename** `customers/demo/state/act_366643171197739.json` → `customers/demo/state/demo_v1.json`

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
