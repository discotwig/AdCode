# ADR-005 — Import Untracked Ad Sets from Facebook

**Status:** Accepted  
**Date:** 2026-05-11

---

## Problem

`get_drift_report` can identify ad sets that exist on Facebook but are not tracked in the AdCode state file (`MISSING_FROM_STATE`). Once found, there is no way to bring them under management — the plan/apply flow ignores anything not already in state, so AdCode would create duplicates if you added them to the JSON manually and ran `apply_campaigns`.

The user must currently do this by hand:
1. Look up each ad set in Ads Manager.
2. Transcribe fields into the campaign JSON.
3. Manually add an entry to the state file with the correct fb_id.

This is error-prone and blocks the drift-remediation workflow entirely.

---

## Analogy: Terraform Import

`terraform import` is the right mental model. When a resource exists in the cloud but not in state, `terraform import <resource> <id>` fetches its current configuration and registers it in state so future plan/apply operations manage it correctly. The import does not push any changes — it just adopts the resource.

---

## Solution: `import_adsets` MCP Tool

Add an `import_adsets` tool that:

1. Runs drift detection for the account to find all `MISSING_FROM_STATE` ad sets.
2. Fetches each ad set's live configuration from Facebook.
3. Merges the ad sets into the campaign JSON file (desired state).
4. Registers each ad set in the state file with its `fb_id` (so plan/apply doesn't try to create it again).
5. Returns a summary of what was imported and a reminder to review and commit the updated JSON.

The tool is **read-then-write**: no Facebook mutations, only local file changes.

---

## Inputs

| Parameter | Required | Description |
|---|---|---|
| `account_id` | yes | Ad account (e.g. `act_366643171197739`) |
| `json_path` | yes | Path to the campaign JSON file to update |
| `adset_names` | no | Subset of ad set names to import; imports all `MISSING_FROM_STATE` if omitted |

---

## Field Mapping: Facebook → Campaign JSON Schema

| Facebook field | JSON schema field | Notes |
|---|---|---|
| `name` | `name` | direct |
| `status` | `status` | direct |
| `daily_budget` | `daily_budget` | direct; omit if `lifetime_budget` is set instead |
| `lifetime_budget` | `lifetime_budget` | direct; omit if `daily_budget` is set |
| `billing_event` | `billing_event` | direct |
| `optimization_goal` | `optimization_goal` | direct |
| `bid_strategy` | `bid_strategy` | **requires adding `bid_strategy` to `ADSET_FIELDS`** (currently missing) |
| `targeting` | `targeting` | direct |
| _(none)_ | `ads` | stub as `[]` — ad-level import is out of scope for this ADR |

### Known gap: `bid_strategy` missing from `ADSET_FIELDS`

`src/api/meta.py` declares:

```python
ADSET_FIELDS = ["id", "name", "campaign_id", "status", "effective_status", "targeting",
                "billing_event", "optimization_goal", "bid_amount", "daily_budget",
                "lifetime_budget", "start_time", "end_time"]
```

`bid_strategy` is absent. It must be added before `get_adset()` / `list_adsets()` returns it. This is a prerequisite for the import tool.

---

## Parent Campaign Resolution

`reconcile.fetch_actuals()` already returns ad sets nested under their parent campaigns. The import tool reuses this structure to determine which campaign each ad set belongs to — no additional API calls needed.

---

## State File Update

After importing, each ad set is written to state via `StateFile.upsert_adset()`:

```python
state.upsert_adset(campaign_name, adset_name, fb_id, params)
state.save()
```

This ensures the next `plan_campaigns` run sees the ad set as already tracked and produces no spurious creates.

---

## Out of Scope

- **Ad-level import.** Ads within the adopted ad sets are stubbed as `[]`. A follow-on `import_ads` tool can address this if needed.
- **Campaign-level import.** Only ad sets are targeted for now; campaigns that are `MISSING_FROM_STATE` are an edge case handled separately.
- **Bidding validation.** The tool copies fields verbatim from Facebook. It does not validate that the resulting JSON would pass `plan_campaigns` — the user should run `plan_campaigns` after importing to confirm.

---

## Files to Change

| File | Change |
|---|---|
| `src/api/meta.py` | Add `"bid_strategy"` to `ADSET_FIELDS` |
| `src/mcp_server.py` | Add `import_adsets` tool definition, handler `_import_adsets`, and route in `call_tool` |
| `tests/test_mcp_server.py` | Add tests for `import_adsets` (happy path, name filter, already-tracked ad set is skipped) |
| `docs/demo.md` | Add drift-remediation step showing `import_adsets` after `get_drift_report` |
