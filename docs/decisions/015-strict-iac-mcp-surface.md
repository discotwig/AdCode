# ADR-015: Strict IaC MCP Tool Surface

**Date:** 2026-05-14  
**Status:** Accepted  
**Supersedes:** broad live-account MCP tools from earlier MCP phases

---

## Context

AdCode is positioned as infrastructure-as-code for ad operations. The MCP server is the primary operator interface, so its tool surface defines what the product is.

The previous MCP server mixed two models:

1. **Stack IaC tools** such as plan, apply, state inspection, drift detection, and import.
2. **Live Facebook console tools** such as listing all campaigns, fetching arbitrary campaign status, exporting the full account, finding duplicate account-wide names, and pausing live campaigns directly.

The second group is useful for general account troubleshooting, but it weakens the core promise:

> AdCode manages exactly the declared stack through plan/apply/state.

For contractor work, this distinction matters. The operator may have account-wide Facebook credentials, but the scope of responsibility should be the active Ad Stack, not the entire ad account.

Terraform provides a useful model: managed resources are checked through plan/drift workflows, and unmanaged resources enter through explicit import workflows. Terraform is not a general-purpose cloud account console.

---

## Decision

The MCP server exposes a strict Ad Stack IaC surface.

### Kept / added tools

| Tool | Purpose |
| --- | --- |
| `show_stack` | Show active stack metadata: template path, stack directory, state path, account ID, and whether stack `.env` exists. |
| `validate_stack` | Run schema validation and AI policy validation for the active stack template. |
| `plan_stack` | Show the changeset that `apply_stack` would execute. |
| `apply_stack` | Apply the active stack. Delete operations still require `confirm_deletes=true`. |
| `drift_stack` | Compare stack-managed state to live Facebook data. Reports only managed objects. |
| `show_state` | Read this stack's `state.json`; never calls Facebook. |
| `search_import_candidates` | Search live Facebook only for ad sets under campaigns declared in the active stack that could be imported. |
| `import_resource` | Import a supported live resource into the active stack template and `state.json`. Supports `resource_type="adset"` initially. |
| `generate_stack_from_excel` | Generate campaign JSON from an Excel brief. This is a template authoring helper, not an execution tool. |

### Removed tools

These are removed from the public MCP surface:

- `pause_campaigns`
- `list_campaigns`
- `get_campaign_status`
- `get_campaign_export`
- `find_duplicates`
- `plan_campaigns`
- `apply_campaigns`
- `get_local_state`
- `get_drift_report`
- `import_adsets`
- `ingest_excel`

No backwards-compatible MCP aliases are retained. The public surface should become clear immediately.

### Live Facebook reads

Live reads are allowed only when they support a stack-scoped workflow:

- drift detection for managed state;
- import discovery for campaigns declared in the active template;
- import execution into local template/state.

The MCP server is not a broad Facebook account browser.

### Live Facebook writes

All live writes must flow through:

```text
template -> plan_stack -> apply_stack -> state
```

Direct live writes such as `pause_campaigns` are removed.

---

## Consequences

### Positive

- The MCP server now matches the IaC mental model.
- The operator can clearly say: "This server manages only the active stack."
- AI cannot use AdCode as a general-purpose Facebook Ads console.
- There is only one live write path: plan/apply from declared desired state.
- Import remains possible, but it is explicit and scope-expanding.

### Negative

- Operators lose convenient broad live account inspection through MCP.
- Troubleshooting unmanaged account objects requires Facebook Ads Manager, separate scripts, or future intentionally scoped tools.
- Existing MCP clients must update tool names immediately.

---

## Deferred

- Generalized campaign and ad import.
- Name collision warnings inside `plan_stack`.
- A separate provider diagnostics tool or MCP server.
