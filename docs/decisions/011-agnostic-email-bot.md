# ADR-011 — Agnostic Email Bot: Remove Sender Routing

**Status:** Accepted  
**Date:** 2026-05-13  
**Supersedes:** parts of ADR-009 (sender authentication block)

---

## Context

The original email bot matched the `From` address of every inbound email against an `email_addresses` allowlist stored in `customers/*/config.json`. Unrecognized senders were rejected. The bot also looked up `operator_email`, `bot_email`, and per-customer API keys from the same config dict.

This design was built before the Mailroom Architecture (ADR-010) established that the bot holds no engine context. With ADR-010 in place, the per-sender lookup serves no purpose:

- The bot no longer routes templates to different engine configs — the operator does that manually after receiving a forwarded email.
- The bot no longer calls the Facebook API, so there are no per-customer credentials to look up.
- The only security boundary that matters is the `WEBHOOK_SECRET` shared with the Cloudflare Email Worker, which already prevents arbitrary internet traffic from hitting the endpoint.

Maintaining a per-customer sender allowlist adds operational cost (updating config on every new contact) and creates a misleading mental model where the email bot appears to know about specific clients.

---

## Decision

The email bot is **sender-agnostic**. Any email that arrives at the webhook with a valid `WEBHOOK_SECRET` is processed, regardless of sender address.

All routing configuration moves from `customers/*/config.json` to global environment variables on the Fly.io app:

| Env var | Purpose |
| --- | --- |
| `OPERATOR_EMAIL` | Destination for forwarded valid templates (Path 1) |
| `BOT_EMAIL` | `From` address for all outbound replies |
| `RESEND_API_KEY` | Resend API credential |
| `ANTHROPIC_API_KEY` | Anthropic API credential |
| `WEBHOOK_SECRET` | Shared secret with Cloudflare Worker (security boundary — unchanged) |

The `email_addresses`, `operator_email`, and `bot_email` fields are removed from `customers/*/config.json` and `schemas/customer_config.schema.json`. Customer configs are now purely for the local MCP server (`customer_slug`, `account_id`, `campaigns_dir`, `state_dir`).

### Account ID in seeded templates (Path 3)

When the bot seeds a starter template from a dirty Excel or plain-text brief, the `account_id` field is populated with the literal placeholder `"act_REPLACE_WITH_YOUR_ACCOUNT_ID"`. The client must fill this in before resubmitting. This is consistent with the IaC principle that the human must review and own the declaration before it can be applied.

---

## Consequences

**Positive:**
- No per-customer configuration required on the email bot — adding a new client requires no code or config changes on Fly.io.
- Clients can send from any address (work email, assistant's email, etc.) without the bot rejecting them.
- The bot's behavior is fully determined by its own environment variables, not by distributed config files.
- Simpler tests — no need to mock `_load_all_configs` or `_find_customer`.

**Negative / Trade-offs:**
- The bot no longer rejects obviously wrong senders. Any email that reaches the Cloudflare Worker and passes `WEBHOOK_SECRET` check will be processed. Spam or misdirected email will generate AI ingestion cost (Path 3) before being discarded as a no-op.
- The operator must look at the `From` address in the forwarded email to know which client sent the template. Previously, the bot derived the client identity automatically. Now it is up to the operator to match the template to the right `customers/<slug>/` directory.

**Security posture unchanged:** The `WEBHOOK_SECRET` is the only entry gate. Cloudflare Email Worker POSTs to the webhook only after validating the secret. Random internet requests cannot trigger processing.

---

## Files Changed

| File | Change |
| --- | --- |
| `src/email_bot.py` | Removed `_load_all_configs`, `_find_customer`, `CUSTOMERS_DIR`; added `OPERATOR_EMAIL`/`BOT_EMAIL` module constants; removed unknown-sender rejection block |
| `customers/demo/config.json` | Removed `email_addresses`, `operator_email`, `bot_email` |
| `schemas/customer_config.schema.json` | Removed `email_addresses`, `operator_email`, `bot_email` |
| `tests/test_email_bot.py` | Removed `DEMO_CONFIG`, `TestUnknownSenderRejected`, `_find_customer` tests; mocks patch global env vars; added `TestAnySenderAccepted` |
