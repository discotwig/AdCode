# ADR-021: JSON-First Stack Template Authoring

**Date:** 2026-05-20  
**Status:** Accepted  
**Builds on:** ADR-003, ADR-012, ADR-013, ADR-015, ADR-018, ADR-019  
**Related:** ADR-017

---

## Context

AdCode uses JSON stack templates as the desired-state interface for Meta Ads campaign management. These templates are not merely an internal serialization format; they are one of the primary user interfaces of the product.

Marketing experts, operators, and AI agents should be able to inspect, review, and edit stack templates directly. This keeps campaign intent explicit, versionable, diffable, and reviewable through normal Git and plan/apply workflows.

At the same time, asking users to construct full stack templates from scratch is unnecessarily difficult. A valid stack template requires nested campaign, ad set, ad, creative, targeting, budget, status, objective, optimization, billing, and CTA fields. Many fields have constrained enum values or provider-specific identifiers. Even users who are comfortable editing JSON should not have to memorize the entire schema or start from a blank file.

The product therefore needs an authoring model that helps users produce valid starter templates while preserving JSON as the durable source of truth and review surface.

There is also a product-design concern around MCP endpoint sprawl. The MCP server already exposes a meaningful number of tools. Adding many overlapping documentation, schema, generation, validation, and revision tools would make the public surface harder to understand and weaken the strict IaC tool boundary established by ADR-015.

In particular, overlapping tools should be avoided where one workflow already subsumes another. For example, if `plan_stack` validates the active template as part of producing a changeset, then a separate public `validate_stack` tool may be less important over time unless it provides clearly distinct value.

---

## Decision

AdCode will use a **JSON-first template authoring model**.

The stack template JSON remains a primary user interface and the durable source of desired state. Users are expected to read, review, and make edits to JSON templates directly.

However, users should not be expected to construct stack templates from scratch. AdCode should provide scaffolding and authoring assistance that creates valid starter JSON, explains assumptions, and points users toward the edits they need to make.

The authoring principle is:

> AdCode should never require users to write stack JSON from scratch, but it should always make generated JSON visible, editable, validated, planned, and reviewable before anything reaches Facebook.

---

## Authoring Model

The preferred workflow is:

1. A user starts from a scaffold, recipe, brief, Excel artifact, or generated draft.
2. AdCode or an AI assistant produces a valid or near-valid JSON stack template.
3. The user reads and edits the JSON directly.
4. The user runs `plan_stack`.
5. `plan_stack` validates the active stack and shows the planned changes.
6. The user iterates on the JSON until the plan is acceptable.
7. The user generates a review packet with `document_stack`, if needed.
8. The user applies with `apply_stack` only after review.

AI may help draft or revise a template, but AI does not replace the JSON artifact and does not bypass plan/apply.

---

## MCP Surface Direction

AdCode should avoid adding many narrowly scoped or overlapping MCP endpoints for template authoring.

Instead of separate tools such as:

- `describe_stack_schema`;
- `list_stack_values`;
- `get_stack_examples`;
- `generate_stack_template`;
- `validate_stack_draft`;
- `suggest_stack_fixes`;
- `list_stack_recipes`;

AdCode should prefer one of two compact approaches.

### Preferred if MCP resources are practical

Expose static authoring information as MCP resources rather than tools.

Examples:

- `adcode://docs/stack-authoring`
- `adcode://schema/campaign`
- `adcode://examples/minimal-stack`

Resources are appropriate for information the model or user reads but does not execute.

A single authoring tool may still exist for generating starter JSON from a brief or structured source.

### Acceptable simpler implementation

Use one broad authoring tool rather than multiple overlapping tools.

A future generalized tool could replace or subsume `generate_stack_from_excel` and support multiple input sources, such as:

- text brief;
- Excel brief;
- recipe name plus inputs;
- existing template plus requested revision.

Possible names include:

- `draft_stack`;
- `scaffold_stack`;
- `author_stack`;
- `seed_stack_template`.

`draft_stack` is preferred because it communicates that the output is a draft to be reviewed and edited, not an authoritative final campaign.

---

## Relationship to Existing Tools

### `generate_stack_from_excel`

`generate_stack_from_excel` is already an authoring helper, not an execution tool. It may remain as-is in the short term.

Longer term, it should either:

1. stay only if Excel remains important enough to justify a dedicated public tool; or
2. be folded into a more general drafting tool that accepts multiple source types.

The goal is to avoid parallel generation tools with overlapping behavior.

### `validate_stack`

`validate_stack` currently provides explicit schema and policy validation for the active stack. Since `plan_stack` also validates before producing a changeset, the two tools overlap.

This ADR does not require immediate removal of `validate_stack`, but future MCP surface cleanup should consider whether `validate_stack` still provides distinct value as a public tool.

Possible outcomes:

- keep it if users benefit from a lightweight validation-only action;
- hide or remove it if `plan_stack` is the normal validation feedback path;
- retain validation as an internal service either way.

### `plan_stack`

`plan_stack` remains the main feedback mechanism for edited templates. It should continue to validate the active stack before showing changes.

Template authoring should converge on this loop:

> edit JSON -> plan -> fix JSON -> plan again.

### `apply_stack`

Generated or AI-assisted templates must still go through normal `apply_stack` behavior. No authoring helper should write to Facebook directly.

---

## Documentation Direction

AdCode should include a human-readable Stack Template Authoring Guide under `docs/`.

The guide should explain:

- the minimal valid stack shape;
- the campaign/ad set/ad/creative hierarchy;
- required vs optional fields;
- common enum values;
- common campaign recipes;
- common mistakes;
- which values are account-specific Facebook IDs;
- which fields should usually be omitted for new resources, such as `fb_id`;
- the edit/plan/apply workflow.

The canonical machine-readable contract remains `schemas/campaign.schema.json`.

Documentation and authoring helpers should rely on the schema where possible so allowed values do not drift from implementation.

---

## Static Docs vs Account-Specific Discovery

Static documentation and account-specific discovery should remain separate concepts.

Static information includes:

- stack structure;
- schema;
- allowed enum values;
- example templates;
- authoring guidance;
- recipes.

This information should not require Facebook credentials or live API calls.

Account-specific information includes:

- Page IDs;
- custom audience IDs;
- image hashes;
- video IDs;
- pixel IDs;
- interest IDs;
- geo location keys.

These values may require live Facebook lookups. If AdCode adds discovery support for them in the future, those tools should be intentionally scoped and should not turn the MCP server into a general Facebook account console.

This preserves the ADR-015 rule that AdCode is a stack-scoped IaC surface, not a broad live account browser.

---

## Consequences

### Positive

- JSON remains the primary desired-state UI.
- Users can start from useful scaffolds instead of blank files.
- Marketers and operators can still read, review, and directly edit templates.
- AI can assist with drafting without bypassing deterministic validation, planning, review, and apply.
- MCP endpoint growth is constrained.
- Static docs, examples, and schema can support both humans and AI agents.
- The product remains aligned with infrastructure-as-code workflows.

### Negative

- Users still need to understand and edit JSON.
- Authoring assistance must be carefully designed so it does not feel magical or obscure the actual desired state.
- A single broad authoring tool may have a more complex input schema than several smaller tools.
- If MCP resources are used, client support and developer ergonomics may vary.

---

## Non-Goals

This decision does not remove JSON as a primary interface.

This decision does not require immediate removal of `validate_stack`.

This decision does not require immediate replacement of `generate_stack_from_excel`.

This decision does not introduce direct AI-to-Facebook mutation.

This decision does not approve a broad live Facebook account browsing surface.

This decision does not require marketers to author perfect templates without assistance.

---

## Guiding Principle

The stack template is the artifact.

Authoring helpers may draft it, explain it, or suggest changes to it, but the normal operational path remains:

```text
template JSON -> plan_stack -> review -> apply_stack -> state
```
