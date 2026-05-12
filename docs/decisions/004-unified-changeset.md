# ADR-004 — Unified Changeset (CloudFormation-style Plan + Apply)

**Status:** Accepted  
**Date:** 2026-05-11

---

## Problem

The current push/teardown architecture has three separate tools that operate on different data sources:

| Tool | Source of truth for "what to change" |
|---|---|
| `push_campaigns` | JSON file vs state file (creates + updates only) |
| `preview_diff` | JSON file vs state file (read-only) |
| `teardown_campaigns` | JSON file vs **Facebook live** (deletes only, name-matched) |

This creates two classes of bugs:

1. **Invisible duplicates.** `teardown_campaigns` fetches Facebook and groups by campaign name. If two campaigns share a name, the second silently overwrites the first in the results dict — duplicates are never flagged or deleted.

2. **Fragmented UX.** Creates, updates, and deletes require separate tool calls with separate approval steps. There is no single view of "here is everything that will change."

---

## Analogy: AWS CloudFormation / SAM

CloudFormation provides the right mental model:

- The **template** (JSON/YAML) is the desired state.
- The **stack** is CloudFormation's internal record of every resource it created, keyed by logical ID → physical ID (ARN).
- `cf deploy` produces a **changeset**: creates, updates, and deletes shown together.
- Deletes are identified by looking at the stack (not by name-scanning live resources) — so duplicate-named resources are never an issue.
- You review the changeset and approve before anything is applied.

---

## Redesign

### Roles of each artifact

| Artifact | CF equivalent | Role |
|---|---|---|
| Campaign JSON file | Template | Desired state — what should exist |
| `state/{account_id}.json` | Stack state | Record of every fb_id AdCode created |
| `plan()` output | Changeset | Diff of template vs stack state |

### How `plan()` works (updated)

Compare the JSON file to the **state file** — not to Facebook live.

```
for each campaign in JSON:
    if not in state  →  CreateCampaign
    elif fields changed  →  UpdateCampaign
    else  →  noop

for each campaign in state:
    if not in JSON  →  DeleteCampaign (using state's fb_id)

same logic for ad sets and ads within each campaign
```

Deletes reference the fb_id stored in the state file. No name-matching against Facebook.

### Apply order

```
Creates:    campaigns → ad sets → ads   (parent must exist before child)
Updates:    any order
Deletes:    ads → ad sets → campaigns   (leaf-first, avoids referential errors)
```

### Unified MCP flow

Replace the four current tools with two:

| New tool | Replaces | Behavior |
|---|---|---|
| `preview_diff` | `preview_diff` + `preview_teardown` | Shows creates, updates, AND deletes. Read-only. |
| `push_campaigns` | `push_campaigns` + `teardown_campaigns` | Applies the full changeset. Requires explicit confirmation if any deletes are present. |

`teardown_campaigns` and `preview_teardown` are removed.

### Approval rule

- **Creates and updates only** → apply without extra confirmation (same as today).
- **Any deletes present** → `push_campaigns` returns the plan and requires `confirm_deletes=true` to proceed. This prevents accidental deletion when the intent was only to push changes.

### What `get_drift_report` does (unchanged)

Drift detection (state file vs Facebook live) is a separate, orthogonal concern. It answers: *"Has Facebook diverged from what AdCode last applied?"* It is not part of the plan/apply flow and remains as-is.

---

## Handling unmanaged resources (duplicates)

Resources that exist on Facebook but are **not** in the state file are invisible to the plan/apply flow — by design, matching CF behavior. AdCode only manages what it created.

Duplicate campaigns created outside AdCode (or before state tracking was established) require a separate tool (`find_duplicates`, tracked in SWE-5) that:
1. Fetches all campaigns for an account, keyed by fb_id (not name).
2. Groups by name and flags any name appearing more than once.
3. Returns each instance with its fb_id and created date so the user can decide which to keep.

---

## Files changed

| File | Change |
|---|---|
| `src/traffic.py` | Add `DeleteCampaign`, `DeleteAdSet`, `DeleteAd` ops; extend `plan()` to produce them; extend `apply()` to execute them and purge entries from state |
| `src/mcp_server.py` | Update `preview_diff` to show deletes; update `push_campaigns` to apply deletes with `confirm_deletes` guard; remove `preview_teardown` and `teardown_campaigns` |
| `src/services/teardown.py` | Delete file (logic absorbed into `traffic.py`) |
| `tests/test_traffic.py` | Add tests for delete operations in `plan()` and `apply()` |
| `tests/test_mcp_server.py` | Update tests for unified tools |
