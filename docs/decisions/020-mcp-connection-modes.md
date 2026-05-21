# ADR-020: Supported MCP Connection Modes

**Date:** 2026-05-20  
**Status:** Accepted  
**Builds on:** ADR-002, ADR-015, ADR-018, ADR-019  
**Related:** ADR-004, ADR-012, ADR-013, ADR-014

---

## Context

AdCode exposes its primary operator interface through MCP. During early integration planning, three different MCP deployment patterns were being considered at the same time:

1. a local AI client launching the AdCode MCP server directly over `stdio`;
2. a local AdCode MCP server exposed to a cloud AI client through an HTTP/SSE bridge and temporary tunnel;
3. a hosted AdCode MCP service exposed over a stable network endpoint for enterprise or cloud-agent use.

Treating all three as equally supported patterns created confusion in the product architecture and documentation. Local clients such as Cursor can start a local MCP server directly and communicate with it over `stdio`. Cloud-hosted clients such as Microsoft 365 Copilot cannot reach a developer laptop's `localhost`; they generally require a stable HTTPS endpoint, usually behind an enterprise connector, MCP gateway, or hosted service.

Temporary tunnel tools such as `ngrok` can bridge this gap for engineering tests, but they are not representative of a production connection model. They do not provide a durable domain, organizational authentication, stable access controls, audit boundaries, or a realistic customer operating model.

AdCode needs a clearer distinction between simple local operator usage and governed organizational deployment.

---

## Decision

AdCode will explicitly support two primary MCP connection modes:

1. **Local Operator Mode**
2. **Organizational Hosted Mode**

A third pattern, **Temporary Tunnel Test Mode**, may be used for engineering validation, but it is not a primary supported user or customer deployment model.

---

## Supported Mode 1: Local Operator Mode

Local Operator Mode is the default mode for personal development, local manual work, informal demos, and single-operator client service work.

In this mode, a local MCP client launches or connects to the AdCode MCP server directly over `stdio`.

Typical clients include:

- Cursor;
- other local IDE agents or desktop MCP clients, if later documented and verified.

Local Operator Mode uses the existing single-stack startup pattern:

- `src/mcp_server.py` is run locally;
- `--config <stack_template>` selects the active stack;
- stack-local configuration and credentials remain local;
- switching clients, stacks, or environments is done by changing the local MCP configuration or command arguments.

Local Operator Mode should stay simple. It should not require:

- a hosted endpoint;
- `ngrok` or another tunnel;
- a workspace registry;
- multi-user identity;
- enterprise network infrastructure;
- organizational MCP gateways.

This mode is appropriate when the operator is intentionally choosing the stack file and execution context. The safety model is based on local operator control, stack-scoped tools, plan-before-apply behavior, validation, explicit delete confirmation, and the existing `--config` boundary.

---

## Supported Mode 2: Organizational Hosted Mode

Organizational Hosted Mode is the target mode for formal cloud-agent demos, multi-user organizational use, paid hosted service offerings, and paid client-hosted implementation work.

In this mode, AdCode runs as a hosted MCP service or behind an authenticated MCP gateway / enterprise connector. Cloud AI clients connect to it over a stable HTTPS endpoint.

Representative clients include:

- Microsoft 365 Copilot / Copilot Studio;
- future enterprise cloud agents or approved AI-client platforms.

Organizational Hosted Mode should be built around governed access rather than arbitrary file selection. It should use registered stacks and stable stack identities instead of letting agents choose arbitrary local paths or account combinations.

This mode is the reason for the workspace registry and registered-stack roadmap. Organizational Hosted Mode should eventually support:

- `--workspace <workspace_registry>` startup;
- stable `stack_id` selection;
- `list_stacks` and `describe_stack` discovery;
- explicit client, environment, platform, account, and risk metadata;
- binding between template path, state path, ad account ID, credential profile, and allowed operations;
- read-only and mutation-capability controls;
- durable plan records;
- `apply_plan` workflows;
- domain audit logs;
- optional caller identity from gateways;
- account verification before mutation where provider support exists;
- fail-closed behavior for unknown stacks, stale plans, account mismatches, and missing confirmations.

Organizational Hosted Mode is the correct model for formal Microsoft 365 Copilot demos. Those demos should use a hosted AdCode endpoint with safe demo workspaces and appropriate access controls, not a public tunnel into a developer laptop.

---

## Non-Primary Pattern: Temporary Tunnel Test Mode

Temporary Tunnel Test Mode is the pattern where a local AdCode MCP server is exposed to a cloud client through tools such as:

- `mcp-proxy`;
- `ngrok` or another HTTPS tunnel;
- an HTTP/SSE bridge to a local `stdio` MCP server.

This pattern may be useful for engineering validation, protocol experiments, or short-lived debugging of a cloud-client connection path.

It is not a recommended user, customer, formal demo, or production model.

Temporary Tunnel Test Mode should be documented, if at all, as private engineering test material with clear warnings. It should not be presented as the normal Microsoft 365 Copilot integration architecture.

Reasons this pattern is not primary:

- the endpoint is temporary and often changes between sessions;
- the access path is not representative of enterprise deployment;
- authentication and authorization are usually incomplete or ad hoc;
- audit and identity boundaries are unclear;
- mutation tools can be exposed accidentally;
- customer organizations are unlikely to accept this as an operating model;
- it distracts from the real distinction between local `stdio` usage and hosted organizational deployment.

---

## Documentation Direction

AdCode documentation should be reorganized around the two supported modes.

### Local Operator Guide

A local guide should explain how to use AdCode with local MCP clients, starting with Cursor.

It should cover:

- supported local clients;
- `stdio`-based MCP startup;
- use of the `--config` flag;
- how to switch stacks and environments locally;
- how to run the MCP server manually;
- which tools are appropriate for local demos and manual work;
- why no network tunnel or hosting is required.

This guide should make clear that workspace registry features are not required for basic local development or single-stack operation.

### Organizational Hosted MCP Guide

An organizational guide should explain how AdCode should be deployed for cloud agents and multi-user environments.

It should cover:

- hosted MCP endpoint expectations;
- authentication and authorization requirements;
- enterprise connector or MCP gateway placement;
- registered stacks and workspace registry concepts;
- supported cloud clients, beginning with Microsoft 365 Copilot when verified;
- read-only vs mutating tools;
- durable plan and approval expectations;
- audit logging;
- credential and account boundaries;
- recommended controls for formal demos and production use.

Cloud-client integration notes should assume a hosted endpoint by default. Temporary local tunnel instructions should be separated into private engineering test notes or omitted unless actively needed.

---

## Roadmap Implications

The existing `--config <stack_template>` workflow remains the supported Local Operator Mode and should be preserved.

Phase 32, Workspace Registry and Registered Stacks, should be understood primarily as a foundational feature for Organizational Hosted Mode, not as a requirement for local development.

The workspace registry's purpose is governance, not local convenience. It should answer questions such as:

- which stacks is this hosted service allowed to manage;
- which account belongs to each stack;
- which environment is this;
- which operations are allowed;
- whether a stack is read-only;
- whether deletes or mutations are allowed;
- how an agent discovers allowed stacks;
- how AdCode fails closed when a request targets an unknown or unauthorized stack.

Phase 33 durable plan records, Phase 34 audit logs, and Phase 35 organizational MCP readiness are also primarily Organizational Hosted Mode features, while still preserving local compatibility where useful.

---

## Consequences

### Positive

- AdCode has a clearer product and deployment story.
- Local development remains simple and does not inherit unnecessary organizational infrastructure requirements.
- Hosted cloud-agent deployment has a proper governance foundation.
- Formal demos can be designed around the same architecture expected for production use.
- Documentation can avoid presenting tunnel-based demos as the main integration path.
- Phase 32 through Phase 35 have a clearer purpose and boundary.

### Negative

- Some cloud-client testing may require real hosted infrastructure earlier than a tunnel-based demo would.
- Maintaining two documented modes requires careful terminology and examples.
- Organizational Hosted Mode will take longer to implement than a simple local bridge because it requires authentication, authorization, registered stacks, auditability, and safer mutation workflows.

---

## Non-Goals

This decision does not remove or deprecate Local Operator Mode.

This decision does not require every local MCP client to be documented immediately.

This decision does not require building a hosted SaaS immediately.

This decision does not require AdCode to implement a generic MCP gateway.

This decision does not forbid temporary tunnel testing for engineering purposes.

This decision does not make workspace registry mandatory for simple local `--config` workflows.

---

## Summary

AdCode will distinguish between simple local operation and governed hosted operation.

Local work uses Local Operator Mode: a local MCP client, local `stdio`, and explicit `--config` stack selection.

Cloud-agent and organizational work uses Organizational Hosted Mode: a hosted, authenticated MCP endpoint with registered stacks, durable plans, audit logs, and governance controls.

Temporary tunnels are engineering test tools, not the product integration model.
