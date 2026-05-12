# AdCode — Agent Guide

Infrastructure-as-code for Facebook ad trafficking. A campaign JSON file is the desired state; AdCode makes Facebook match it. See README.md for setup and tool reference.

## Behavioral rules

### Campaign name characters — do not normalize

When displaying campaign names from Facebook API responses, state files, or drift reports, show the raw string exactly as returned. Do not assume `â€"` is corrupted, suggest encoding fixes, or reformat any Unicode characters in names.

**Why:** Facebook stores and returns certain characters in this form. The state file is expected to match Facebook verbatim. ADR-006 already addressed the actual Windows UTF-8 fix at the file I/O layer — any remaining character differences in names are intentional, not bugs.

### Drift reports — do not flag false positives

Only report drift when the local state and Facebook values genuinely differ from each other. A name that appears identically on both sides is not drift, even if the characters look unusual.

### "Compare to Facebook" means the live API

Never use the local state file to answer questions about what's currently live. Use `fetch_actuals()` (reconcile.py) or the relevant MCP tool.

## Architecture orientation

| File | Role |
| --- | --- |
| `src/mcp_server.py` | All MCP tool handlers — the primary user-facing surface |
| `src/traffic.py` | `plan()` + `apply()` engine; owns all create/update/delete logic |
| `src/reconcile.py` | `fetch_actuals()` (live API) + `diff_state()` (drift detection) |
| `src/api/meta.py` | Facebook Marketing API client (`MetaClient`) |
| `src/services/state.py` | State file read/write; `get_*_by_fb_id()` and name-based lookups |
| `schemas/campaign.schema.json` | Canonical schema for campaign definitions |

## Key patterns

**`fb_id` correlation.** `plan()` matches by `fb_id` first, falls back to name-match. Enables stable tracking through renames. `import_adsets` populates `fb_id` automatically.

**Unified changeset.** `plan()` emits delete ops for state entries absent from the JSON. `apply_campaigns` gates deletions behind `confirm_deletes=true` (ADR-004).

**`fetch_actuals()` is the live-data source.** Reused by `get_campaign_export` and `import_adsets` — add no new API logic unless `MetaClient` doesn't support it.

**Atomic state writes.** `state.py` writes to `.tmp` then renames — never write state directly.

## Key references

- ADRs: `docs/decisions/` (001 local MCP, 002 Git audit, 004 unified changeset, 005 import_adsets, 006 encoding fix)
- Build history: `docs/todo.md`
- Out of scope: Google Ads, hosted SaaS, email bot (all V2)
