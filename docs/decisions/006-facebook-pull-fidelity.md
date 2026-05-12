# ADR-006 — Facebook Pull Fidelity: Budget Coercion, Schedule Fields, and Empty Ads

**Status:** Accepted  
**Date:** 2026-05-12

---

## Context

ADR-005 introduced `import_adsets` to adopt untracked ad sets from Facebook into the campaign JSON and state file. When that tool was exercised against a real account (`act_366643171197739`), three gaps in the implementation surfaced:

1. **Budget fields returned as strings.** The Facebook Marketing API returns `daily_budget` and `lifetime_budget` as string values (e.g. `"1000"`, `"3000"`). The AdCode schema declares these as `integer`. The mismatch caused `jsonschema.validate` to reject the imported JSON, making the tool useless against real accounts.

2. **Schedule and bid fields silently dropped.** Ad sets using `lifetime_budget` require `start_time` and `end_time` (Facebook rejects lifetime-budget ad sets without them). `bid_amount` is required when `bid_strategy` is `LOWEST_COST_WITH_BID_CAP`. The original `_import_adsets` handler only copied a fixed list of fields and omitted all three. Plans generated after import therefore proposed spurious updates to add the missing fields back.

3. **`ads: []` rejected by the schema.** `import_adsets` intentionally stubs imported ad sets with an empty `ads` array (ad-level import is out of scope per ADR-005). The schema enforced `minItems: 1` on `ads`, so every imported ad set failed validation and could not be planned or applied.

A fourth systemic issue also surfaced: **Windows default encoding.** On Windows, `open()` without an explicit `encoding` parameter uses the system code page (typically CP1252). Campaign names containing em dashes (U+2014 — a common character in this codebase) were decoded differently by `load_campaign_json` vs `StateFile.load`, causing the name-based lookup in `plan()` to treat every campaign as a new create paired with a delete of the old entry. This was masked on macOS/Linux where the default encoding is UTF-8.

---

## Decisions

### 1. Coerce API budget and bid strings to integers on import

When copying fields from Facebook into the campaign JSON during `_import_adsets`, cast `daily_budget`, `lifetime_budget`, and `bid_amount` to `int`. Skip any budget field whose integer value is `0` (Facebook returns `"0"` for the unused budget type when only one of daily/lifetime is set).

**Rationale:** The schema is correct — budgets are integers (cents). The API is the source of the incorrect type. Fixing the type at the ingestion boundary is the right place: it keeps downstream code (schema validation, plan diffing) honest and avoids spreading `int(x)` casts into `traffic.py` or `reconcile.py`.

### 2. Copy `start_time`, `end_time`, and `bid_amount` during import

Extend the field list in `_import_adsets` to include `start_time`, `end_time`, and `bid_amount` whenever Facebook returns them.

**Rationale:** These fields are structurally necessary for the imported definition to be round-trippable. A definition that omits `start_time`/`end_time` on a lifetime-budget ad set cannot be applied to Facebook without error. Including them at import time means the local definition accurately reflects what Facebook holds, and `plan_campaigns` produces a clean no-op rather than false updates.

### 3. Allow `ads: []` in the campaign JSON schema

Lower `minItems` on the `ads` array from `1` to `0`. Add a description noting that empty is valid for imported or stub ad sets.

**Rationale:** The `minItems: 1` constraint expressed an aspirational completeness requirement ("a valid campaign definition should have at least one ad") that conflicts with two real workflows: `import_adsets` (which stubs ads by design) and stub campaigns created for planning purposes before creatives are ready. The constraint was preventing these workflows entirely. Removing it does not weaken safety materially — a campaign with an empty ad set will be a no-op for ad creation, which is the correct behaviour. The `plan_campaigns` output makes it visible that no ads exist.

### 4. Explicit `encoding="utf-8"` on all JSON file I/O

Pass `encoding="utf-8"` to every `open()` call that reads or writes a campaign JSON or state file. Write JSON with `ensure_ascii=False` so Unicode characters (em dashes, accented letters) are stored as literal UTF-8, not as `\uXXXX` escapes.

**Rationale:** Windows cannot be assumed to have UTF-8 as its default encoding. Campaign and ad set names in this codebase contain Unicode characters that are decoded differently under CP1252. A name mismatch between `load_campaign_json` and `StateFile.load` caused `plan()` to generate spurious full-replace changesets. Pinning encoding at the I/O boundary is the standard fix; it has no downside and makes the codebase portable across operating systems.

---

## Schema changes

| Field | Before | After | Reason |
|---|---|---|---|
| `ad_set.optimization_goal` | no `PAGE_LIKES` | adds `PAGE_LIKES` | Facebook returns this value for legacy ad sets imported from Ads Manager |
| `ad_set.ads` | `minItems: 1` | `minItems: 0` | Allow stub and imported ad sets with no ads |

---

## Consequences

**Positive:**
- `import_adsets` produces valid, round-trippable JSON against real accounts.
- `plan_campaigns` after an import returns a clean no-op (no spurious updates).
- The tool is portable: Unicode names in campaigns are stable on Windows and macOS.

**Negative:**
- `ads: []` is now a valid campaign definition. A user who accidentally empties the ads array will not get a schema error. The mistake surfaces later as a no-op push rather than a validation failure — acceptable given the `plan_campaigns`-before-apply workflow.

---

## Files changed

| File | Change |
|---|---|
| `src/mcp_server.py` | `_import_adsets`: coerce budget/bid to int, skip zero budgets, copy `bid_amount` / `start_time` / `end_time`; write JSON with `encoding="utf-8"` and `ensure_ascii=False` |
| `src/traffic.py` | `load_campaign_json`: explicit `encoding="utf-8"` |
| `src/services/state.py` | `StateFile.load` / `save`: explicit `encoding="utf-8"` |
| `schemas/campaign.schema.json` | `ad_set.optimization_goal`: add `PAGE_LIKES`; `ad_set.ads`: `minItems` 1 → 0 |
| `tests/test_mcp_server.py` | Load `EXAMPLE_JSON` with `encoding="utf-8"` |
| `tests/test_schema.py` | Load `example_campaign` fixture with `encoding="utf-8"`; invert `test_empty_ads_array_fails` to assert empty ads is valid |
| `campaigns/demo/act_366643171197739/demo_v1.json` | Populated with live ad sets from Facebook (three imported ad sets with full field fidelity) |
| `state/act_366643171197739.json` | Synced to match campaign JSON names and imported ad set params |
