# ADR-013: Terraform Stack Layout

**Date:** 2026-05-13  
**Status:** Accepted  
**Supersedes:** ADR-012 (Ad Stack Model) — directory structure only; the isolation guarantee is unchanged

---

## Context

ADR-012 established the Ad Stack model: each template file has its own isolated state file, keyed by the template's filename stem (`campaigns/demo_v1.json` ↔ `state/demo_v1.json`). This was the right isolation contract but the wrong directory layout.

The separate `campaigns/` and `state/` subdirectories introduced two problems:

1. **Config dependency for state resolution.** The MCP server needed `--config` to know where the `state/` directory lived. If an AI client called `plan_campaigns` without the server having loaded a config, `_require_state_dir()` threw an error. State location was a server-side global, not derivable from the template path alone.

2. **Divergence from established IaC conventions.** Terraform, the closest analogue, does not separate templates from state. The folder *is* the stack: `main.tf` and `terraform.tfstate` live side by side. Users already familiar with Terraform expect this layout.

---

## Decision

Adopt the Terraform convention: **each stack is a directory** containing both the template and `state.json` co-located.

```
customers/<slug>/
  config.json          # account_id + slug only — no longer specifies dirs
  .env                 # credentials (gitignored)
  <stack-name>/        # one directory per Ad Stack (like a Terraform workspace)
    <stack-name>.json  # template (desired state)
    state.json         # stack state (like terraform.tfstate)
```

The template filename matches the folder name. The state file is always `state.json`.

### State resolution rule

```python
state_dir  = Path(json_path).parent        # the stack folder
state_file = state_dir / "state.json"      # always this name
```

No server globals. No config lookup. The path to the template fully determines the path to the state.

### Comparison with Terraform

| Terraform | AdCode (ADR-013) |
|---|---|
| `my-stack/main.tf` | `demo_v1/demo_v1.json` |
| `my-stack/terraform.tfstate` | `demo_v1/state.json` |
| `cd my-stack && terraform apply` | `apply_campaigns(json_path="…/demo_v1/demo_v1.json")` |
| Multiple stacks = multiple folders | Multiple stacks = multiple folders under `customers/<slug>/` |

---

## Consequences

### Positive

- **State location is self-contained.** Any tool that receives `json_path` can find the state without knowing anything about the server's config. `_require_state_dir()` and the `_state_dir` global are removed entirely.
- **Familiar layout.** Operators who know Terraform recognise the structure immediately.
- **Cleaner separation.** Adding a new stack = `mkdir <name> && touch <name>/<name>.json`. No config edits required.
- **`config.json` simplifies.** Only `customer_slug` and `account_id` remain. `campaigns_dir` and `state_dir` are removed.

### Negative

- **Breaking change for existing customer directories.** Any directory using the old `campaigns/` + `state/` layout must be migrated. The demo directory (`customers/demo/`) is migrated as part of this ADR.
- **Stack name is the folder name, not the file stem.** Tools receive the full path to the template; state is always at `../state.json` relative to it. The `stack_name` parameter passed to `StateFile.load` is now always the string `"state"`.

### Migration

For each existing customer:
1. Create `<stack-name>/` alongside `config.json`
2. Move `campaigns/<stack-name>.json` → `<stack-name>/<stack-name>.json`
3. Move `state/<stack-name>.json` → `<stack-name>/state.json`
4. Delete the empty `campaigns/` and `state/` directories
5. Remove `campaigns_dir` and `state_dir` from `config.json`

---

## Alternatives considered

**Keep separate `campaigns/` + `state/` but fix the config dependency** — derive `state_dir` from the config file path stored alongside the template. Rejected: adds indirection and doesn't fix the conceptual mismatch with Terraform.

**Generic template filename (`template.json`)** — every stack folder contains `template.json` + `state.json`. Rejected: the stack name would only appear in the folder name, making file-level operations (search, copy, email attachments) ambiguous.
