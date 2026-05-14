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
| `src/services/validate.py` | Schema validation for stack templates |
| `src/services/ingest.py` | Excel brief → starter template seeding (`generate_stack_from_excel`) |
| `schemas/campaign.schema.json` | Canonical schema for campaign definitions |
| `integrations/email_mailroom/` | Optional email intake; validates and routes client templates |

## Key patterns

**`fb_id` correlation.** `plan()` matches by `fb_id` first, falls back to name-match. Enables stable tracking through renames. `import_resource` populates `fb_id` automatically.

**Unified changeset.** `plan()` emits delete ops for state entries absent from the JSON. `apply_stack` gates deletions behind `confirm_deletes=true` (ADR-004).

**`fetch_actuals()` is the live-data source.** Used by `drift_stack` — add no new API logic unless `MetaClient` doesn't support it.

**Atomic state writes.** `state.py` writes to `.tmp` then renames — never write state directly.

## Key references

- ADRs: `docs/decisions/` — key ones: 002 MCP-first, 004 unified changeset, 005 import untracked adsets, 006 Facebook pull fidelity, 008 contractor service model, 010 mailroom/engine split, 012 ad-stack model, 013 Terraform stack layout, 014 stack-level env, 015 strict IaC MCP surface, 016 public repo sanitization
- Build history: `docs/todo.md`
- Out of scope: Google Ads, hosted SaaS (all V2)
