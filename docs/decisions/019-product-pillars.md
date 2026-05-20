# ADR-019: Product Pillars for Advertising Governance

**Date:** 2026-05-20  
**Status:** Accepted  
**Builds on:** ADR-018  
**Related:** ADR-004, ADR-015, ADR-017

---

## Context

ADR-018 reframed AdCode as a digital advertising governance layer with MCP as the first interface, not the product boundary.

That framing needs a durable product filter for future feature design. Marketing companies and advertising organizations will usually care less about the implementation details of MCP, JSON, or infrastructure-as-code than the operational outcomes those mechanics provide.

The important buyer and operator questions are:

- Can this prevent mistakes in live ad accounts?
- Can this reduce manual trafficking and QA work?
- Can this show who changed what and who approved it?
- Can this explain what will change, what drifted, and what was imported?
- Can this fit into the AI, Git, and approval workflows the organization already uses?

These questions should shape the public story, the roadmap, and the design of future MCP tools.

---

## Decision

AdCode features will be evaluated against five product pillars:

1. **Operational Safety**
2. **Speed**
3. **Governance**
4. **Explainability**
5. **Integration**

These pillars are the product-level expression of the governance layer. They should be referenced when prioritizing new features, designing tool surfaces, writing documentation, and explaining AdCode to marketing organizations.

The short product story is:

> Give your company's AI agents a safe, governed way to operate Meta Ads from approved campaign definitions.

AdCode should not be positioned merely as:

> An MCP server for Meta Ads.

---

## Pillars

### 1. Operational Safety

AdCode should reduce the risk of wrong-account, wrong-stack, unreviewed, or destructive changes.

Feature directions that support this pillar include:

- registered stacks that bind stack IDs to account IDs, state files, and credential profiles;
- plan-before-apply workflows;
- explicit delete gates;
- production confirmations;
- live account identity checks;
- drift detection before mutation;
- stack-scoped tools instead of broad live-account console tools.

AdCode should make it structurally difficult for an AI agent or user to combine arbitrary files, credentials, and ad accounts.

### 2. Speed

AdCode should reduce repetitive manual trafficking and QA work.

Feature directions that support this pillar include:

- declarative stack templates;
- idempotent apply operations;
- Excel-to-stack starter generation;
- faster QA through state inspection and drift reports;
- reusable stack layouts;
- review packets and plan summaries for non-technical stakeholders.

The speed story is not that AI directly and freely changes ads. The speed story is that teams stop repeating manual setup and QA steps and instead review precise, deterministic plans.

### 3. Governance

AdCode should make advertising operations accountable, reviewable, and auditable.

Feature directions that support this pillar include:

- Git-backed stack and state history;
- durable plan records;
- audit logs for mutating operations and important live reads;
- approval records;
- account and environment metadata;
- role and permission hooks for organizational deployments;
- clear separation between read-only, planning, and mutating operations.

Governance should exist in AdCode's domain model even when an external MCP gateway or enterprise platform also provides tool-level audit trails.

### 4. Explainability

AdCode should make planned, live, and applied state understandable to humans.

Feature directions that support this pillar include:

- structured plan output showing creates, updates, and deletes;
- drift reports that show local state vs. live Facebook values;
- import summaries that explain which live resources were adopted;
- post-apply summaries;
- risk summaries;
- Campaign Review Packets;
- AI-readable deterministic outputs that agents can summarize without becoming the source of truth.

AI agents may explain AdCode results, but deterministic AdCode logic must produce the underlying facts and enforce safety rules.

### 5. Integration

AdCode should fit into the workflows marketing organizations already use.

Feature directions that support this pillar include:

- MCP-first access for approved AI clients;
- interface-independent core engine usable by CLI, CI/PR workflows, email, hosted API, or web UI;
- Git-friendly stack and state files;
- central-deployment readiness;
- credential profiles and future gateway compatibility;
- outputs that can be used in pull requests, approval workflows, and review packets.

MCP is valuable because it lets AdCode operate inside existing agent workflows, but AdCode should remain usable beyond any single MCP client.

---

## Feature Design Test

When evaluating a new feature, ask:

1. **Safety:** Does this reduce the chance of wrong-account, wrong-stack, or unreviewed production changes?
2. **Speed:** Does this reduce manual trafficking, QA, or repetitive setup?
3. **Governance:** Does this improve auditability, permissions, approvals, or accountability?
4. **Explainability:** Does this make planned, live, or applied state easier to understand?
5. **Integration:** Does this help AdCode fit into existing AI, Git, agency, or enterprise workflows?

Strong near-term features should usually support at least three pillars. Features that support none of the pillars are likely distractions.

---

## Roadmap Implications

The pillars favor governance features over broad live-account console features.

Near-term priority should lean toward:

- workspace and registered-stack discovery;
- `list_stacks` and `describe_stack`;
- plan records and `plan_id`;
- `apply_plan` instead of ambient direct apply for organizational mode;
- audit logs;
- plan and risk summaries;
- stronger drift and import explanations;
- PR/CI-friendly review outputs.

The pillars deprioritize, unless intentionally scoped later:

- broad Meta account browsing;
- unrestricted natural-language mutation;
- direct live writes outside plan/apply;
- generic performance analytics;
- arbitrary account/file overrides;
- generic MCP gateway functionality;
- additional ad platforms before the governance model is strong.

---

## Consequences

### Positive

- Future feature design has a clear product filter.
- The public story becomes more buyer-relevant and less implementation-centric.
- MCP remains valuable without dominating the product identity.
- Roadmap decisions can be tied to safety, speed, governance, explainability, and integration.
- The project has a stronger basis for organizational adoption.

### Negative

- Some technically useful tools may be deferred if they do not support the pillars.
- The product may evolve more slowly than a simple local automation script because governance requirements add design constraints.
- Documentation and demos must explain both the technical workflow and the operational value.

---

## Non-Goals

This decision does not require building every governance feature immediately.

This decision does not make AdCode a hosted SaaS product.

This decision does not require a generic MCP gateway.

This decision does not remove the local operator workflow.

This decision does not turn AdCode into a general-purpose Meta Ads console or performance reporting platform.
