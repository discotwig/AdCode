# ADR-010 — Mailroom Architecture: Email Bot Decoupled from Engine

**Status:** Accepted
**Date:** 2026-05-13

---

## Context

The email bot (Phase 14) was built to run the full trafficking pipeline on Fly.io: ingest → plan → operator review (GO/HOLD) → apply → confirm. This required Facebook credentials, state files, and a running MetaClient on the hosted server.

In practice this created several problems:

1. **Credentials on the server.** Facebook access tokens for every client account had to be stored as Fly.io secrets. The hosted service became a credential vault for all client ad accounts.

2. **State files on a transient server.** The `state/{account}.json` files that drive plan/apply had to live on a Fly.io volume. State was decoupled from the Git repository that is supposed to be the source of truth.

3. **Operational complexity.** Every new client required a new Fly.io instance (for credential isolation) or a shared instance with multi-tenant routing. Neither is simple to operate for a solo contractor.

4. **Wrong separation of concerns.** The email bot was doing the job of the operator: running the engine. The IaC mental model requires a human to review a plan before applying it. Automating the apply step on Fly.io removed that gate rather than supporting it.

---

## Decision

The email bot is reduced to a **mailroom**: it validates submissions and routes them. It does not call the Facebook API, run `plan()`, run `apply()`, or hold client credentials.

The engine (plan, apply, drift detection) runs exclusively on the operator's local machine, scoped to one client at a time via `--config`.

---

## Architecture

### Email Bot Responsibilities (Fly.io)

Receive inbound email and route based on attachment type:

**Path 1 — Valid AdCode template (JSON passes schema):**
- Reply to client: "Your request has been received and is being processed."
- Forward the email with the template attached to the operator.

**Path 2 — JSON attachment that fails schema validation:**
- Reply to client with specific schema errors and instructions for how to fix each one.
- Do not forward to operator. Client must fix and resubmit.

**Path 3 — Dirty Excel file or plain-text brief:**
- Run `ingest_excel` / `extract_from_text` to seed a starter template.
- Reply to client with the seeded `.json` template attached.
- Instructions: "Review this starter template, complete any missing fields, and resubmit."
- Do not forward to operator. This path is for onboarding and template creation, not campaign submission.

The bot holds no Facebook credentials, no state files, and no knowledge of what campaigns exist on Facebook.

### Operator Responsibilities (local machine)

1. Receive forwarded email containing a valid template.
2. Save the template to `customers/{slug}/campaigns/`.
3. Start the MCP server scoped to that client:
   ```
   python src/mcp_server.py --config customers/{slug}/config.json
   ```
4. Use the AI client (Claude, Gemini) or CLI directly to plan and apply:
   ```
   python src/traffic.py customers/{slug}/campaigns/{file}.json --dry-run
   python src/traffic.py customers/{slug}/campaigns/{file}.json
   ```
5. Git commits the updated state file — this is the audit trail.

### Template Ownership

The client owns and maintains their AdCode template. The operator does not write or update templates on behalf of clients. The operator is the engine that processes them.

This mirrors the DevOps model: the business team owns the Terraform files; the DevOps engineer runs the engine. The difference is each client maintains their own template rather than the operator maintaining it for them.

---

## Consequences

**Positive:**
- No Facebook credentials on Fly.io. The hosted service only needs Anthropic (for ingestion) and Resend (for email) API keys.
- State files stay on the operator's machine and in Git — the audit trail is preserved correctly.
- Fly.io can run as a single shared instance. No per-client instance required. Client isolation is provided by sender authentication and config lookup, not process isolation.
- The operator review gate is a natural part of the workflow rather than a bolted-on GO/HOLD email loop.
- Simpler Fly.io image — the `facebook-business` SDK is not needed on the server.

**Negative:**
- The operator must manually save the template and start the engine for each client submission. There is no automated apply path.
- Turnaround time depends on the operator being available to process the submission. This is acceptable for a contractor service model — the operator's attention is part of the value delivered.
- The clarification loop (multiple rounds of ambiguity questions) is removed from the email bot. The bot answers with a seeded template once; the client is responsible for completing it before resubmitting.

---

## What Is Removed

| Removed | Reason |
| --- | --- |
| `plan()` call in email bot | Engine runs locally, not on Fly.io |
| `apply()` call in email bot | Same |
| `validate_all()` call in email bot | Schema validation is sufficient for routing; AI policy validation happens locally at plan time |
| `MetaClient` in email bot | No Facebook API calls on Fly.io |
| `StateFile` in email bot | No state on Fly.io |
| Pending file system (`.pending_*.json`) | GO/HOLD loop is removed |
| Operator GO/HOLD reply parsing | Operator acts locally; no reply-to-apply flow |
| Multi-round clarification loop | One submission, one response |
| Per-client Fly.io instances | Single shared instance with sender-based routing |
