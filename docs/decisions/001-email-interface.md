# ADR 001 — Email as Primary Human Interface

**Status:** Accepted

---

## Context

AdCode needs a human-facing interface for non-technical agency staff (associates and QA specialists) to submit campaign work and receive results. The system's core logic lives in an MCP server, so the interface layer is a separate concern that can be deferred or swapped without touching the core.

The target users do not work in terminals, GitHub, or web dashboards as part of their daily workflow. They work in Excel and email. Any interface that introduces a new tool or login adds friction and reduces adoption.

Three candidate interfaces were evaluated:

**Web application.** A dedicated UI with forms, status dashboards, and file upload. Familiar to end users but requires building and hosting a web app, managing authentication, and maintaining a frontend. High build cost for an early-stage system. Adds a new tool to the user's workflow.

**GitHub UI.** Users commit JSON to a repository via the GitHub web interface or GitHub Desktop. Pull requests serve as review and approval. Technically elegant — Git is already the source of truth — but requires users to learn Git concepts (branches, commits, PRs) and navigate the GitHub UI. Not realistic for the target user.

**Email bot.** A bot watches an inbox. Users send Excel attachments with natural language instructions in the email body. The bot replies with validation results and approval prompts. Users reply APPROVE or REJECT. The bot dispatches a push report on completion. The interface is entirely email — no new tool, no new login.

---

## Decision

Email is the primary human interface for non-technical agency staff.

The email bot watches a designated inbox, accepts Excel attachments with instructions in the email body, runs the Excel → JSON ingestion and pre-push validation pipeline, replies with a structured validation report and an approval request, and on approval dispatches the push and replies with the reconciliation report.

The MCP + Gemini interface remains available for technical staff who prefer it. Both interfaces sit on top of the same MCP tools.

---

## Rationale

Email meets users where they already operate. The cognitive overhead is zero: attach a file, write instructions, reply to approve. The bot is invisible — from the user's perspective, they are emailing a colleague.

The email bot is architecturally simple: it is a model call with the MCP server attached and email transport wrapped around it. No frontend, no auth layer, no new infrastructure beyond a watched inbox.

The alternative interfaces impose learning costs on users who have no incentive to bear them. A web app adds a new login and workflow. GitHub UI requires Git literacy. Both are mismatches with the target user's existing habits.

Offshore contractors and non-technical account managers — the highest-volume users for routine trafficking — are best served by the most familiar interface possible.

---

## Consequences

**Positive:**
- Zero learning curve for target users.
- No frontend to build or maintain in v1.
- Email threads serve as a lightweight human-readable audit trail alongside Git history.
- The bot interface is composable — the same MCP tools serve both the email bot and direct Gemini users.

**Negative:**
- Email is asynchronous; the system cannot surface urgent issues in real time without additional alerting.
- Parsing natural language email instructions introduces ambiguity that structured web forms would not. The AI ingestion layer must handle this gracefully.
- Email deliverability and inbox management (spam, threading, attachment handling) are operational concerns that do not exist with a web app.
- Long-term, email is a weak foundation for complex workflows (e.g., multi-campaign bulk operations, status dashboards). A web interface may be required in a later version.

**Deferred to v2.** The email bot is out of scope for v1. V1 delivers the MCP server and core scripts. The email interface is built after working examples validate the underlying tool surface.
