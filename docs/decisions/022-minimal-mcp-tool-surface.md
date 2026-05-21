# ADR-022: Minimal Terraform-Like MCP Tool Surface

**Date:** 2026-05-20  
**Status:** Accepted  
**Builds on:** ADR-002, ADR-015, ADR-018, ADR-019, ADR-021  
**Related:** ADR-004, ADR-012, ADR-013, ADR-014, ADR-020

---

## Context

AdCode is infrastructure-as-code for Meta Ads. Its MCP server is a primary operator interface, so the public tool list strongly shapes how users and AI agents understand the product.

A broad MCP tool surface can make AdCode look like a general Meta Ads console. That conflicts with the core model established by ADR-015: AdCode manages the active stack through declared JSON, plan/apply, state, drift detection, and explicit import workflows.

Endpoint sprawl is especially risky for AI agents. When many overlapping tools are exposed, agents have more opportunities to choose the wrong path, skip the intended workflow, confuse local state with desired state or live Facebook state, or bypass the product's governance model.

Terraform is the preferred analogy. Terraform is powerful partly because its primary workflow is small, predictable, and boring: edit configuration, plan, apply, inspect state, and import when needed. Terraform does not expose every provider operation as a top-level workflow. That restraint is a feature, not a lack of functionality.

AdCode should follow the same principle.

---

## Decision

AdCode will treat a minimal MCP tool surface as a product feature and governance control.

The MCP server should expose a small set of stack-scoped verbs that reinforce the infrastructure-as-code lifecycle. New public MCP tools should be added only when they introduce a distinct stack lifecycle operation that cannot be cleanly represented by an existing workflow, MCP resource, documentation page, internal helper, or parameter on an existing tool.

The target Local Operator Mode tool surface is:

| Tool | Purpose |
| --- | --- |
| `show_stack` | Show active stack context, paths, account ID, and local configuration status. |
| `draft_stack` | Produce starter JSON from supported sources such as Excel, text brief, or recipe. Does not call Facebook or apply changes. |
| `plan_stack` | Validate the active stack and show the changeset. This is the normal validation feedback path. |
| `apply_stack` | Apply reviewed changes to Facebook and update state. |
| `drift_stack` | Compare managed state to live Facebook data. |
| `show_state` | Inspect tracked local state for the active stack. |
| `import_resource` | Preview and import supported live resources into the template/state. |
| `document_stack` | Produce a non-technical campaign review packet. |

This target surface is directional. Existing tools may remain temporarily for compatibility while implementation catches up, but future work should converge toward this smaller set.

---

## Tool Consolidation Direction

### `validate_stack`

`validate_stack` overlaps with `plan_stack` because `plan_stack` validates the active stack before showing a changeset.

Future MCP surface cleanup should demote, hide, or remove `validate_stack` from the public tool list unless it has a clearly distinct user value. Validation should remain an internal service either way.

Preferred user loop:

```text
edit JSON -> plan_stack -> fix JSON -> plan_stack -> apply_stack
```

### `search_import_candidates`

`search_import_candidates` overlaps with `import_resource` because candidate discovery is part of the import workflow.

Future work should fold candidate discovery into `import_resource`, for example through an explicit preview/list action. The public surface should have one import verb.

### `generate_stack_from_excel`

`generate_stack_from_excel` is an authoring helper. It should be replaced or subsumed by a broader `draft_stack` tool rather than coexisting with additional generation tools.

`draft_stack` should initially support the current Excel behavior and can later support brief text, recipe-driven scaffolds, or template revisions without adding separate public MCP tools for each source type.

### Documentation, schema, examples, and allowed values

Static authoring information should not become many MCP tools.

If practical, expose static information as MCP resources rather than tools, such as:

- `adcode://docs/stack-authoring`
- `adcode://schema/campaign`
- `adcode://examples/minimal-stack`

If resources are not yet practical, keep this information in `docs/` and example files before adding tool endpoints.

---

## Criteria for Adding a Public MCP Tool

A proposed public MCP tool should satisfy most or all of these criteria:

1. It supports the stack IaC lifecycle.
2. It is scoped to the active stack or an approved registered stack.
3. It does not bypass `plan_stack` / `apply_stack` for live writes.
4. It is materially distinct from existing tools.
5. It makes the agent's next action clearer, not more ambiguous.
6. It cannot be better represented as an MCP resource, documentation page, internal helper, or parameter on an existing tool.
7. It preserves a clear distinction between desired state, local state, and live Facebook data.
8. It does not turn AdCode into a general Facebook Ads console.

If a proposed tool does not meet this bar, it should not be added to the public MCP surface.

---

## Relationship to Organizational Hosted Mode

This decision applies first to Local Operator Mode, where one server is scoped to one active stack via `--config`.

Organizational Hosted Mode may later require stack discovery or selection capabilities such as registered stack listing or description. Those tools should be governed by ADR-020's hosted-mode constraints and should not weaken the core stack lifecycle model.

Hosted-mode discovery tools should answer "which approved stack can I operate?" rather than expose broad provider-console functionality.

---

## Consequences

### Positive

- The product remains easier to understand and explain.
- AI agents have fewer wrong paths through the system.
- JSON remains the desired-state UI rather than being hidden behind many convenience tools.
- Live writes remain centered on the plan/apply workflow.
- The MCP surface better reflects Terraform-like infrastructure-as-code practice.
- Public tools become easier to document, test, govern, and secure.

### Negative

- Some convenience workflows may require more thoughtful input parameters instead of new tool names.
- Removing or hiding existing tools may require client documentation updates.
- A generalized tool such as `draft_stack` or `import_resource` may have a more complex input schema than several narrow tools.
- Operators may occasionally need to use Facebook Ads Manager, scripts, or future intentionally scoped diagnostics for workflows outside the stack lifecycle.

---

## Non-Goals

This decision does not remove core capabilities from AdCode.

This decision does not forbid internal helper functions or CLI utilities.

This decision does not require immediate breaking removal of existing MCP tools.

This decision does not make AdCode a complete Terraform clone.

This decision does not authorize broad live Facebook account browsing through MCP.

---

## Guiding Principle

The MCP tool list should be small enough that the correct workflow is obvious:

```text
show -> draft/edit JSON -> plan -> apply -> drift/state/import/document as needed
```

Simplicity is part of the safety model.
