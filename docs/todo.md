# AdCode — Build Checklist

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

- Email bot (`src/email_bot.py`) — watches inbox, wraps MCP tools with email transport
- `src/api/google_ads.py` — Google Ads API client
- `schemas/google_campaign.schema.json`
- Multi-account batch operations

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

---

## Deferred — SaaS Multi-Tenancy

Phase 12 (customer registry, API key auth, GitHub API file storage, onboarding scripts) was scoped for a hosted-SaaS deployment model. The current ADR-driven architecture is local MCP server + bring-your-own-model. The right collaboration and tenancy design depends on the first real client integration — defer until that context exists.

Reference: `docs/saas-architecture.md` for the original design.

---

## Backlog

- [x] Implement `get_campaign_export(account_id)` — fetch full campaign hierarchy from Facebook (campaigns + ad sets + ads) for a given account in a single MCP tool call; `get_campaign_status` returns campaign-level only
