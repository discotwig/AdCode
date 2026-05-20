# ADR-018: AdCode as a Digital Advertising Governance Layer

**Date:** 2026-05-20  
**Status:** Accepted  
**Clarifies:** ADR-002, ADR-015  
**Related:** ADR-004, ADR-012, ADR-014, ADR-017

---

## Context

AdCode began as an MCP-first tool for applying infrastructure-as-code patterns to Meta advertising operations. The initial build path prioritized a local MCP server because it provided a fast way to expose the core engine to AI agents without building a custom web application first.

That decision remains useful, but the product framing has matured.

The long-term product is not "an MCP server." The product is a digital advertising governance layer: a system that helps organizations define, review, apply, reconcile, and audit advertising changes safely.

MCP is the first interface because it gives operators and AI agents a natural way to inspect state, run deterministic tools, interpret results, and request actions. However, MCP should not be treated as the only product boundary. The same governance layer should be usable from multiple interfaces over time, including MCP, CLI, CI/PR workflows, email, and possibly a hosted UI or API.

This distinction matters because a local MCP server used by one engineer has different requirements from an MCP server embedded into an organization's approved AI clients. Organizational use requires stronger environment selection, identity, authorization, audit logging, and production safety.

---

## Decision

AdCode will be designed as a digital advertising governance layer with MCP as the first interface, not as an MCP-only product.

The core engine and state model should remain interface-independent. MCP tools should expose safe operations over registered Ad Stacks, but business-critical behavior must live below the MCP transport layer.

Future AdCode features should assume two supported deployment modes:

1. **Local operator mode**
   - A single technical user runs AdCode locally.
   - The MCP server points at a local workspace or active stack.
   - Credentials, state, and stack files are local.
   - This mode remains important for development, demos, and early adoption.

2. **Organizational mode**
   - A marketing company or internal marketing team exposes AdCode through approved AI clients.
   - Users interact through an MCP client, gateway, or internal agent platform.
   - Stack configuration, account mappings, permissions, and audit requirements are centrally governed.
   - Users operate on registered stacks rather than arbitrary files or ad accounts.

---

## Product Principle

AdCode's durable value is governance over advertising operations.

The system should help organizations answer:

- What advertising resources are declared?
- What live resources are managed by AdCode?
- What would change if this stack were applied?
- What has drifted from declared state?
- Who approved this change?
- What account and environment did it affect?
- Were deletes or risky operations involved?
- What did the live advertising API return?
- What state was written after apply?

MCP is a strong interface for these workflows because agents can reason over fetched information and deterministic tool results. But the governance guarantees must come from AdCode itself, not from the AI model.

---

## Required Architectural Direction

### 1. Registered stacks

AdCode should move toward a workspace registry model where tools operate on registered stack IDs rather than arbitrary file paths.

A registered stack should eventually bind:

- stack ID;
- client;
- environment;
- platform;
- stack file;
- state file;
- ad account ID;
- credential profile;
- allowed operations;
- production/deletion confirmation rules;
- audit configuration.

This avoids letting an AI agent or user freely combine arbitrary stack files, state files, credentials, and ad accounts.

### 2. Plan/apply safety

Mutating operations should flow through a plan/apply lifecycle.

The preferred long-term workflow is:

1. validate stack;
2. fetch live actuals when needed;
3. generate a plan;
4. explain the plan;
5. require human confirmation for risky operations;
6. apply the approved plan;
7. write state atomically;
8. record an audit event.

`apply` should increasingly be tied to a previously generated plan rather than executing directly from ambient server configuration.

### 3. Organizational auditability

AdCode should record domain-specific audit events for mutating operations and important live reads.

Audit records should eventually capture:

- user or caller identity when available;
- stack ID;
- client;
- environment;
- ad account ID;
- operation type;
- generated plan ID;
- stack/state hashes where practical;
- delete count and risk summary;
- confirmation values;
- Meta API result summary;
- state write result.

External MCP gateways or enterprise platforms may provide their own audit trails, but AdCode should still record advertising-domain audit details internally.

### 4. Interface independence

The core AdCode engine should not depend on MCP.

MCP is the first interface, but the same core operations should remain available to future interfaces such as:

- CLI;
- GitHub Actions or PR comments;
- email workflows;
- hosted API;
- web review UI;
- enterprise MCP gateways.

The MCP server should be a transport and orchestration layer over the governance engine, not the governance engine itself.

### 5. AI as analyst, not authority

AI agents may interpret results, summarize plans, identify risks, and guide users through workflows.

They should not be the source of truth for:

- whether a stack is registered;
- which ad account a stack maps to;
- whether a user is allowed to apply changes;
- whether deletes are permitted;
- whether a production confirmation is valid;
- whether state should be written.

Those decisions must be enforced by deterministic AdCode logic.

---

## Consequences

### Positive

- The project has a clearer long-term identity beyond "MCP server."
- MCP remains valuable without becoming a limiting product boundary.
- Local use and organizational embedding can share the same core engine.
- Future features can be evaluated against governance value, not only MCP convenience.
- Registered stacks provide a path toward safer multi-client and multi-environment use.
- Plan/apply, audit logs, and explicit environment metadata make AdCode more credible for marketing organizations.

### Negative

- The implementation becomes more complex than a single local MCP server.
- Organizational use introduces identity, authorization, audit, and deployment concerns that may not be needed for early local usage.
- Some workflows that are convenient locally, such as operating directly on an active stack from process configuration, may need to be constrained or reworked.
- MCP client capabilities vary, so AdCode cannot rely on every client to provide adequate environment selection, approval, or audit UX.

---

## Non-Goals

This decision does not require AdCode to become a hosted SaaS product.

This decision does not require building a generic MCP gateway.

This decision does not require supporting multi-tenant agency operations in the immediate MVP.

This decision does not remove local MCP usage.

This decision does not make AdCode a general-purpose Meta Ads console. ADR-015 still applies: AdCode's MCP surface should remain stack-scoped and IaC-oriented.

---

## Near-Term Implementation Implications

Future features should prefer:

- `stack_id` over arbitrary stack file paths in MCP tools;
- workspace-level stack registries;
- read-only discovery tools such as `list_stacks` and `describe_stack`;
- verified `plan_id` values for mutating operations;
- explicit production and delete confirmations;
- audit events for mutating operations;
- clear separation between core engine, registry layer, and MCP interface.

A practical migration path is:

1. keep supporting the current local active-stack mode;
2. add an optional workspace registry;
3. add registered-stack-aware read-only tools;
4. make planning work by `stack_id`;
5. make applying work from `plan_id`;
6. eventually make registered stacks required for organizational mode.
