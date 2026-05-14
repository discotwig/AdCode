# ADR-016: Public Repository Sanitization

**Date:** 2026-05-14
**Status:** Accepted

---

## Context

AdCode is being prepared for public GitHub visibility. The current repository tree includes public product code and docs, plus local operator artifacts that should not be published as operational details.

The repository history is not being rewritten. This decision covers the current tree only.

---

## Decision

Sanitize the current repository tree for public visibility without removing the public email mailroom integration.

Public examples and docs use placeholder values:

- `traffic@example.com` for inbound mail examples.
- `https://api.example.com/inbound` for webhook examples.
- `adcode-mailroom-example` or `your-fly-app` for Fly.io app examples.
- `act_000000000` and `000000000000000` for demo account and page IDs.

Local operator workspaces are intentionally ignored. The `customers/` tree is where private stack templates, state, `.env` files, and customer-specific credentials live. Those files belong in private operator storage, not the public project repository.

The tracked local AI assistant config `.claude/settings.local.json` is removed from the current tree, and `.claude/` is ignored.

---

## Consequences

- The public repo keeps runnable examples, schemas, docs, tests, and the mailroom integration.
- Real deployment endpoints, personal domains, personal mailboxes, and real-looking ad account/page IDs are removed from current tracked files.
- Existing historical commits may still contain old values because history is not rewritten.
- Public-readiness tests scan the current tracked tree so future changes do not reintroduce private deployment details.
