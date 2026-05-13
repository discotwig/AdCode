# ADR-014: Stack-Level `.env` and `--config` Target

**Date:** 2026-05-13
**Status:** Accepted
**Supersedes:** ADR-013 (Terraform Stack Layout) — directory structure and server startup only; the stack isolation guarantee is unchanged

---

## Context

ADR-013 established the Terraform-aligned stack layout: each stack is a directory containing `<stack-name>_template.json` and `state.json` co-located. However, two things remained at the customer level:

1. **`config.json`** — stored `customer_slug` and `account_id`; was the target of `--config` at server startup
2. **`.env`** — stored all API credentials; shared across every stack under a customer

This created a safety problem for agency use. An agency manages multiple clients, each with a distinct Facebook ad account. With credentials at the customer level, starting the server for `client_a/stack_q2/` still loaded `client_a/.env`, which is fine — but the server had no guarantee that those credentials matched the `account_id` in any given stack template. A mis-typed `--config` path could point the server at the wrong stack while loading the wrong credentials silently.

Additionally, `config.json` had become a thin redundant wrapper — its only non-redundant field (`account_id`) is already in every stack template. The `customer_slug` field was never used by any tool handler.

---

## Decision

1. **`--config` now points to the stack template file directly**, not to a customer-level `config.json`.

   ```bash
   # Before
   python src/mcp_server.py --config customers/acme/config.json

   # After
   python src/mcp_server.py --config customers/acme/stack_test1/stack_test1_template.json
   ```

2. **`.env` lives in the stack directory**, co-located with the template.

   ```
   customers/<slug>/
     <stack-name>/
       <stack-name>_template.json   ← --config points here; contains account_id
       .env                         ← credentials for this stack's ad account
       state.json                   ← stack state (unchanged)
   ```

3. **`config.json` is eliminated.** `account_id` is read directly from the template JSON at startup. `customer_slug` is dropped — it was unused.

4. **The server sets three module-level globals at startup** from the template path, replacing the previous pattern of passing `json_path` as a per-call tool argument:

   ```python
   _STACK_JSON_PATH: Path   # absolute path to the template file
   _STACK_STATE_DIR: Path   # parent directory (the stack folder)
   _ACCOUNT_ID: str         # from template["account_id"]
   ```

   Tool handlers read these globals. No tool schema exposes `json_path` or `account_id` as a parameter for stack-scoped operations.

---

## Consequences

### Positive

- **Credential isolation is structural.** The `.env` for `client_a/stack_q2/` can only be loaded when the server is started with a path inside that stack directory. It is physically impossible to accidentally apply `client_b`'s credentials to `client_a`'s stack.
- **`account_id` is single-sourced.** It lives only in the template JSON. No synchronisation with `config.json` is needed.
- **Simpler tool schemas.** `json_path` and `account_id` are removed from six tool schemas (`plan_campaigns`, `apply_campaigns`, `get_drift_report`, `get_local_state`, `import_adsets`, `pause_campaigns`). Tool calls are shorter and less error-prone.
- **`config.json` is gone.** One fewer file type to explain, scaffold, or maintain.

### Negative

- **Breaking change for existing customer directories.** Any directory using the old layout (customer-level `config.json` and `.env`) must be migrated. The `acme` demo customer is migrated as part of this ADR.
- **Server must be restarted to switch stacks.** Previously a client could call any stack by passing `json_path`. Now the active stack is fixed at startup. This is intentional — it enforces the one-server-per-stack safety model.
- **No multi-stack server.** An operator managing two stacks simultaneously must run two server processes. Accepted trade-off given the credential safety benefit.

### Migration

For each existing customer:
1. Move `customers/<slug>/.env` into each stack directory: `customers/<slug>/<stack-name>/.env`
2. Delete `customers/<slug>/config.json`
3. Delete `customers/<slug>/.env`
4. Update any `--config` invocations to point at `<stack-name>/<stack-name>_template.json`

---

## Alternatives considered

**Keep `.env` at customer level, fix config dependency only** — `--config` points at the stack template, but credentials stay shared across a customer's stacks. Rejected: partial fix that leaves the credential-isolation gap open. An operator could still start the server against the wrong account's template while the correct `.env` was absent.

**Walk up the directory tree for `.env`** — load the first `.env` found by ascending from the stack directory. Rejected: re-introduces ambiguity. The correct `.env` should always be exactly one place, not "somewhere above."

**Per-account credentials in environment variables only** — no `.env` file at all; operators set credentials in their shell before starting the server. Accepted as a valid complementary pattern (the server falls back to env vars if `.env` is absent), but not sufficient as the primary model since it provides no per-stack isolation in practice.
