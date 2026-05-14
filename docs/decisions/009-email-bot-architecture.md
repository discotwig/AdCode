# ADR-009 — Email Bot Architecture: Cloudflare + Resend + Fly.io

**Status:** Accepted  
**Date:** 2026-05-12

## Context

Phase 14 adds a client-facing email interface for the contractor service model (ADR-008). Clients email a campaign brief; the operator reviews a plan; approved plans are applied to Facebook. The system needs:

- Inbound email reception at a custom domain address
- Outbound email sending from the same domain
- A Python process to run the pipeline (Claude, Facebook API, state files)
- Always-on hosting — not serverless, since state files must persist and SSE MCP connections are long-lived

## Options considered

### Gmail API polling
Rejected. Requires OAuth2 consent flow per account, a dedicated Gmail address (phone verification blocked), and polling introduces latency. Adds Google dependency for a non-Google workload.

### Resend inbound + outbound
Rejected. Resend has no inbound email routing product — outbound only.

### n8n / Zapier
Rejected. Workflow orchestration tools add a third-party dependency in the critical path and obscure the business logic in a GUI.

## Decision

**Inbound:** Cloudflare Email Routing + Email Workers  
**Outbound:** Resend API  
**Hosting:** Fly.io (always-on, 256 MB shared VM)  
**Domain:** `example.com` (placeholder public example)

### Inbound flow

```
Client email → traffic@example.com
  → Cloudflare Email Routing (MX records)
  → Email Worker (adcode-inbound-example)
  → POST https://api.example.com/inbound
  → FastAPI on Fly.io
```

The Email Worker is a single JS file (`src/workers/inbound.js`) with no build step. It reads the raw MIME message and POSTs it to the webhook with a shared secret. Rejection on webhook failure prevents silent drops.

### Outbound

Resend sends all outbound from `traffic@example.com`. Domain is verified via SPF/DKIM records in Cloudflare DNS. Single `send_email()` call wraps the Resend SDK.

### Hosting

Fly.io runs `uvicorn src.email_bot:app` on port 8080. A persistent volume (`adcode_data`) is mounted at `/app/customers` so state files survive redeploys. An `entrypoint.sh` syncs `config.json` files from the Docker image into the volume on every boot, so config changes deployed via `flyctl deploy` take effect without manual volume editing.

Cloudflare DNS routes `api.example.com` (A/AAAA records) directly to Fly.io with TLS handled by Fly's Let's Encrypt certificate. Cloudflare proxy is intentionally disabled on this record to avoid TLS conflicts.

### Operator review gate

Pending briefs are stored as `.pending_{id}.json` files in the customer's `state/` directory (gitignored). The operator receives a plan email with subject `[AdCode Review] {id} | {original_subject}`. Replying `GO` or `HOLD` triggers apply or discard. The `id` is extracted from the subject line — no thread tracking or IMAP needed.

## Consequences

- No Gmail account or OAuth flow needed — Cloudflare handles inbound
- All infrastructure is within the Cloudflare + Fly.io ecosystem — no Google or AWS dependency
- Pending files are local to the Fly.io volume — not committed to git; a machine restart before GO/HOLD discards the pending (acceptable; Phase 15 startup sweep notifies operator of expired briefs)
- MCP server still runs locally via stdio transport; cloud MCP via SSE is deferred

## Operational notes (learned during deployment)

- **Cloudflare SSL must be set to "Full"** (not Flexible). Flexible causes 520 errors; Strict causes 525 TLS handshake failures on Fly.io.
- **DNS: Cloudflare proxy must be OFF** for `api.example.com`. Use A/AAAA records pointing to Fly.io IPs (not CNAME). Cloudflare proxy conflicts with Fly.io's Let's Encrypt TLS cert.
- **Fly.io volume shadows Docker image** — volume at `/app/customers` overwrites the image's `customers/` directory. `entrypoint.sh` copies `config.json` from `customers_defaults/` (baked into image) to the volume on every boot.
- **Cloudflare "Dropped" status is normal** — when an Email Worker handles an email, Email Routing shows "Dropped". This means the Worker consumed it, not that it was lost. Real signal is Worker logs showing `outcome: ok`.
- **Worker rejection = Fly.io 500** — if the FastAPI handler throws (e.g. Anthropic 529), Fly.io returns 500 → Worker calls `message.setReject()` → email bounces to sender. Mitigated with `max_retries=6` and explicit 529 catch returning 200.
- **All AI calls use `claude-sonnet-4-6`** — Opus has much lower rate limits and caused persistent 529 errors during testing.

## Clarification flow design

When extraction produces ambiguities, the bot saves a `.clarifying_{id}.json` state file and sends a multiple-choice question email with `[Clarify-{id}]` embedded in the subject. Client replies route to `_handle_clarification()` which applies answers to the saved draft via `_APPLY_CLARIFICATIONS` prompt.

This keeps `ingest.py`, `brief.py`, and `prompts.py` clean and shared with the MCP server. All email conversation state management is isolated to `email_bot.py`.

**Known issue (as of 2026-05-12):** Subject-based `[Clarify-{id}]` matching may not survive Gmail's reply subject rewriting. Fallback to `In-Reply-To` header matching is the likely fix — see Phase 16 in `docs/todo.md`.
