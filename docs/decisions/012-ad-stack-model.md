# ADR-012 — Ad Stack Model: Per-Template State Isolation

**Status:** Accepted  
**Date:** 2026-05-13

---

## Context

The original design keyed state files by `account_id` — a single `state/act_123.json` for every campaign AdCode has ever applied to that account. Every template applied to that account writes into the same shared state file.

The `plan()` delete logic (lines 305–320 of `src/traffic.py`) emits deletes for every campaign in state that is absent from the template being applied — regardless of which template originally created it.

This creates several serious problems:

**Cross-contamination deletes.** If two template files manage different campaigns in the same account, applying either one will emit delete ops against the other's campaigns. The `confirm_deletes=true` gate prevents accidental execution, but the plan output is alarming and the risk is real for any operator who confirms without careful review.

**No scope boundary.** The engine has no technical limit on which campaigns it can see or touch in an account. If AdCode has ever applied any campaign to `act_123`, all of those campaigns are visible in the state file and potentially subject to delete when any template for that account is applied.

**No ownership contract.** There is no explicit record of which template "owns" which campaigns. The relationship between a template file and the campaigns it manages is implied by naming conventions and human discipline, not enforced by the system.

**Drift detection is account-wide.** `get_drift_report` compares the entire state file against live Facebook data. There is no way to ask "show me drift only for the campaigns in this specific template."

For a contractor service where multiple clients have campaigns in the same Facebook ad account, this model is operationally unsafe. A contractor may have access to an entire ad account but a contractual obligation to only touch specific campaigns. The account-scoped state model provides no enforcement of that boundary.

---

## Decision

The unit of management in AdCode is an **Ad Stack**, not an ad account.

Each Ad Stack is a matched pair of files:

- **Template file** — `customers/<slug>/campaigns/<stack_name>.json` — the desired state declaration. The operator and client co-own this file. It defines exactly which campaigns AdCode manages.
- **State file** — `customers/<slug>/state/<stack_name>.json` — what AdCode last applied for this stack. Written by the engine after each successful apply. Never shared with another stack.

State files are **keyed by stack name (the template filename stem), not by `account_id`**. The `account_id` field remains inside the template so the engine knows which Facebook account to call against, but it no longer determines the state file path.

`plan()` and `apply()` load the state file whose name matches the template filename. They are physically incapable of reading another stack's state, and the delete logic can only emit ops against campaigns that appear in that stack's state file.

---

## Directory layout

```
customers/acme/
  campaigns/
    q2_brand.json             ← Ad Stack definition (desired state)
    q3_retargeting.json       ← Independent Ad Stack
  state/
    q2_brand.json             ← State for q2_brand stack only
    q3_retargeting.json       ← State for q3_retargeting stack — never touched by q2_brand
```

Two stacks for the same account (`account_id` may be the same in both template files) are completely independent. Applying `q2_brand.json` cannot read, modify, or delete anything tracked by `q3_retargeting.json`.

---

## Stack lifecycle

| Action | How |
| --- | --- |
| Create a stack | Add a new template file to `campaigns/` |
| Apply a stack | `plan_campaigns` → `apply_campaigns` on that file; state written to matching filename in `state/` |
| Add a campaign | Declare it in the template; apply → CREATE op |
| Remove a campaign | Delete it from the template; apply → scoped DELETE op (only this stack is affected) |
| Untrack without deleting from Facebook | Remove from template + manually delete that entry from the stack's state file (`terraform state rm` equivalent) |
| Destroy a stack entirely | Empty all campaigns from the template; apply (executes DELETEs); delete both files |
| Check stack drift | `get_drift_report` scoped to the stack name or template path |
| List stacks | `list_stacks` — reads `customers/<slug>/campaigns/*.json` and pairs with state |

---

## Scope contract

The stack definition file is the operator's explicit scope contract with the client:

> "I will manage exactly the campaigns declared in this file. I cannot see, modify, or delete any campaign outside it — regardless of what access my Facebook credentials permit."

This is the equivalent of IAM policy enforcement within a Facebook ad account. Facebook itself does not offer campaign-level access control. The Ad Stack model provides that guarantee at the engine level.

---

## Consequences

**Positive:**
- Hard isolation between stacks — one stack cannot produce delete ops or drift reports against another stack's campaigns, even in the same Facebook account
- The stack definition is a formal, auditable scope contract between operator and client
- Git history becomes per-stack — `state/q2_brand.json` only changes when that stack is applied; unrelated stacks are untouched
- Eliminates the cross-contamination delete risk that existed with account-scoped state
- Drift detection is meaningful — scoped to only the campaigns the operator agreed to manage
- Enables multiple independent contractors to manage different stacks in the same account without interfering with each other

**Negative / Trade-offs:**
- Breaking change: existing `state/act_123.json` files must be migrated to per-stack state files before the refactored engine is used
- `get_drift_report` must accept a template path or stack name rather than just `account_id`
- `import_adsets` must resolve and write into the correct stack's state file
- Operators must be deliberate about which stack file they pass to each tool — there is no longer a single account-wide state to fall back on

---

## What is not changed

- The `account_id` field in the template — still required, still tells the engine which Facebook account to call
- The `customers/<slug>/config.json` format — still used by the MCP server for credentials and directory paths
- The template JSON schema (`campaign.schema.json`) — campaigns, ad sets, and ads are declared identically
- The plan → apply workflow — identical from the operator's perspective; the only change is which state file is loaded

---

## Migration path

Existing `state/act_123.json` files contain all campaigns ever pushed for that account. Each entry should be moved into a new per-stack state file whose name matches the template that manages it. The engine will not migrate automatically — this is a one-time manual step before the refactored engine is used in production.

---

## Implementation

This ADR documents the decision. The refactoring of `src/services/state.py`, `src/traffic.py`, `src/reconcile.py`, and `src/mcp_server.py` is tracked as a separate phase in `docs/todo.md`.
