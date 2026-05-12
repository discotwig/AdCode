# ADR-008 — Contractor Service Model and Multi-Tenant Architecture

**Status:** Accepted  
**Date:** 2026-05-12

---

## Context

AdCode is infrastructure-as-code for ad trafficking. The initial question was how to deploy it for multiple clients and how to position it commercially.

Two deployment targets were considered:

1. **SaaS product** — customers pay a subscription, log in, manage their own data.
2. **Contractor service** — the operator (Ryan) is hired as a trafficking contractor; clients send data and receive results; the software is invisible to them.

The SaaS model requires procurement approval, IT security review, seat licensing, and client onboarding. Ad agencies already have a budget line for trafficking contractors. The contractor model maps directly onto a familiar purchase decision.

The wife's agency framing clarified this: an agency would rather hire somebody to traffic ads than pay a software subscription they have to manage. The value delivered is the same — campaigns pushed accurately and on time — but the commercial relationship is contractor-client, not vendor-customer.

---

## Decisions

### 1. Position as a contractor service, not a SaaS product

The operator provides an email address. Clients send media plans (Excel, brief, or plain text). Campaigns are pushed. Confirmations come back. The client never interacts with the MCP server, Facebook API, or any AdCode interface directly.

This is the correct V1 positioning because:
- No procurement friction — agencies already budget for trafficking contractors.
- No onboarding — the client protocol is "send an email."
- The operator stays accountable — there is a person to call if something goes wrong, which agencies require.
- The operator's capacity scales (multiple clients, parallel accounts) while the billing relationship stays familiar.

### 2. Human review gate between plan and apply

The email bot flow is:

```
inbound email → ingest → plan_campaigns → email operator the plan → operator approves → apply_campaigns → confirm to client
```

`apply_campaigns` is never triggered automatically from an inbound email. The operator reviews the plan before any Facebook API call is made. This is the core of the service: the operator is the human in the loop who is responsible for what gets pushed.

This gate also defines the product's liability boundary. A bad plan that the operator approved is a contractor error. A plan that ran without review is a software failure. The gate keeps those distinct.

### 3. One MCP server instance per customer (process-level isolation)

MCP has no built-in authentication or tenant isolation. Isolation is achieved through process boundaries: each customer gets their own server process, its own working directory, and its own credentials. A server instance configured for client A cannot touch client B's data because it has no path or credentials to reach it.

The configuration pattern:

```
customers/
  acme/
    config.json        ← data paths, account_id (committed)
    .env               ← FB + Anthropic credentials (gitignored)
    campaigns/
      act_123456/
        q1_brand.json
    state/
      act_123456.json
```

`config.json` specifies `account_id`, `campaigns_dir`, and `state_dir`. The server reads it at startup and is permanently scoped to that customer. No routing logic, no tenant lookup, no cross-customer API calls possible.

### 4. State files are committed per customer, not ephemeral

State files (`state/{account_id}.json`) are the equivalent of CloudFormation stack state. They serve two functions that cannot be replaced by always calling Facebook:

- **ID correlation** — `plan()` needs `fb_id` to distinguish an update from a create, and to track objects through renames.
- **Delete detection** — the unified changeset finds deletions by diffing state against the JSON. No state means no reliable delete detection.

State is committed to the customer's repo alongside their campaign JSON files. Git history is the audit trail for both.

### 5. Credentials are never committed

`.env` is gitignored in every customer directory. Credentials are injected at runtime via environment variables. The customer repo (campaigns + state) is safe to share with the client for audit purposes without exposing credentials.

---

## Email bot interface (V2)

The email bot is the client-facing surface for this model. Design constraints that follow from this ADR:

- **Inbound routing by sender** — sender email → customer config lookup.
- **Reply contains the plan, not the result** — operator receives plan for review; apply is a separate step.
- **Outbound confirmation** — after apply, client receives a summary of what was pushed.
- **No self-service apply** — clients cannot trigger `apply_campaigns` directly. The operator is always in the loop before a push.

---

## Consequences

**Positive:**
- Commercial model matches how agencies already buy trafficking services.
- No procurement or IT friction for the first client engagement.
- Process-level isolation is simple, auditable, and requires no auth middleware.
- Git history per customer is a sellable audit trail.

**Negative:**
- The operator is a single point of failure for monitoring and review. This is intentional at V1 — the contractor model requires a human. Automation of the review step (e.g. policy-only auto-approve) is a V2 concern.
- Running one server process per customer adds operational overhead as the client list grows. Acceptable at small scale; warrants a managed runtime at larger scale.
