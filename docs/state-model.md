# State Model

AdCode state is the bridge between declarative templates and Facebook's assigned object IDs.

## Why State Exists

The template describes desired objects by human-readable names. Facebook identifies live objects by IDs. AdCode needs state to answer:

- Is this campaign new or already managed?
- Which Facebook ID should be updated?
- Did a template removal mean a delete should be planned?
- Did a rename happen without changing the underlying object?

Without state, the engine cannot reliably distinguish update, create, rename, and delete behavior.

## Location

Each stack has one state file:

```text
customers/<slug>/<stack-name>/state.json
```

The state file sits beside the template:

```text
customers/<slug>/<stack-name>/<stack-name>_template.json
```

This makes the stack folder the isolation boundary.

## Shape

State records:

- `account_id`;
- `last_pushed_at`;
- campaigns keyed by name;
- ad sets keyed by name under each campaign;
- ads keyed by name under each ad set;
- Facebook IDs;
- last-pushed params.

The schema is [schemas/state.schema.json](../schemas/state.schema.json).

## Matching Rules

The plan engine matches objects by `fb_id` first, then falls back to name.

This enables safe renames:

1. A campaign has `fb_id` in the template.
2. The name changes.
3. `plan()` finds the existing state entry by `fb_id`.
4. `apply()` updates Facebook and migrates the state key to the new name.

## Delete Detection

Deletes are planned when an object exists in `state.json` but no longer appears in the template.

Deletes are scoped to the active stack only. Another stack's state file is not loaded, so another stack's campaigns cannot be deleted by this stack's plan.

`apply_campaigns` requires explicit delete confirmation.

## Editing State

Do not edit `state.json` by hand during normal use.

Valid reasons to change state manually are rare:

- one-time migration;
- recovering from a failed or interrupted operation;
- intentionally untracking an object without deleting it from Facebook.

Prefer tool-supported operations like `import_adsets` when adopting live objects into a stack.

## Git

State files are committed intentionally. Commit template and state changes together after each apply. That pair is the audit trail:

- template: what AdCode was asked to make true;
- state: what Facebook IDs AdCode recorded after execution.
