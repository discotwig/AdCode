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
**Domain:** `ryanbishop.me` (already on Cloudflare)

### Inbound flow

```
Client email → traffic@ryanbishop.me
  → Cloudflare Email Routing (MX records)
  → Email Worker (adcode-inbound)
  → POST https://api.ryanbishop.me/inbound
  → FastAPI on Fly.io
```

The Email Worker is a single JS file (`src/workers/inbound.js`) with no build step. It reads the raw MIME message and POSTs it to the webhook with a shared secret. Rejection on webhook failure prevents silent drops.

### Outbound

Resend sends all outbound from `traffic@ryanbishop.me`. Domain is verified via SPF/DKIM records in Cloudflare DNS. Single `send_email()` call wraps the Resend SDK.

### Hosting

Fly.io runs `uvicorn src.email_bot:app` on port 8080. A persistent volume (`adcode_data`) is mounted at `/app/customers` so state files survive redeploys. An `entrypoint.sh` syncs `config.json` files from the Docker image into the volume on every boot, so config changes deployed via `flyctl deploy` take effect without manual volume editing.

Cloudflare DNS routes `api.ryanbishop.me` (A/AAAA records) directly to Fly.io with TLS handled by Fly's Let's Encrypt certificate. Cloudflare proxy is intentionally disabled on this record to avoid TLS conflicts.

### Operator review gate

Pending briefs are stored as `.pending_{id}.json` files in the customer's `state/` directory (gitignored). The operator receives a plan email with subject `[AdCode Review] {id} | {original_subject}`. Replying `GO` or `HOLD` triggers apply or discard. The `id` is extracted from the subject line — no thread tracking or IMAP needed.

## Consequences

- No Gmail account or OAuth flow needed — Cloudflare handles inbound
- All infrastructure is within the Cloudflare + Fly.io ecosystem — no Google or AWS dependency
- Pending files are local to the Fly.io volume — not committed to git; a machine restart before GO/HOLD discards the pending (acceptable for now; operator can re-request)
- MCP server still runs locally via stdio transport; cloud MCP via SSE is deferred
