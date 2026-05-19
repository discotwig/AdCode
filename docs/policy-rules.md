# AdCode Policy Rules

Deterministic governance rules evaluated at `validate_stack` and `plan_stack` time. Rules are JSON files versioned alongside your stack — reviewable, composable, and reproducible.

## How it works

1. `validate_stack` and `plan_stack` load all active policy rules.
2. Each rule is evaluated against every campaign and ad set in the template.
3. Violations are returned alongside schema errors and AI policy warnings in the validation summary.
4. `ERROR`-severity violations block `apply_stack`. `WARNING`-severity violations are reported but do not block.

## Rule file format

Each rule is a `.json` file validated against `schemas/policy.schema.json`.

```json
{
  "id": "spend-cap-required",
  "description": "Campaigns must declare a spend cap to prevent runaway spend",
  "severity": "WARNING",
  "condition": {
    "scope": "campaign",
    "type": "field_required",
    "field": "spend_cap",
    "message": "Campaign '{name}' has no spend_cap — consider adding one to limit total spend"
  }
}
```

### Required fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier. Used in violation output and to override builtin rules. |
| `description` | string | Human-readable description shown in `docs/policy-rules.md` references. |
| `severity` | `"ERROR"` \| `"WARNING"` | `ERROR` blocks apply; `WARNING` is advisory. |
| `condition` | object | The check to perform. Shape depends on `type`. |

### Condition types

#### `field_required`

The named field must be present and not null on every object of the given scope.

```json
{
  "scope": "campaign",
  "type": "field_required",
  "field": "spend_cap",
  "message": "Campaign '{name}' has no spend_cap"
}
```

`scope` is `"campaign"` or `"ad_set"`. `{name}` in `message` is replaced with the object's `name` field.

#### `any_field_nonempty`

At least one of the listed dot-path fields must be present and a non-empty list on every object of the given scope.

```json
{
  "scope": "ad_set",
  "type": "any_field_nonempty",
  "fields": ["targeting.interests", "targeting.behaviors", "targeting.custom_audiences"],
  "message": "Ad set '{name}' has no audience constraints (broadmatch)"
}
```

Dot notation resolves nested fields: `"targeting.interests"` reads `obj["targeting"]["interests"]`.

#### `compatibility_matrix`

The combination of three field values must appear in the `allowed` list. `row_field` may use a `campaign.` prefix to read from the parent campaign when evaluating ad sets.

```json
{
  "scope": "ad_set",
  "type": "compatibility_matrix",
  "row_field": "campaign.objective",
  "col_field": "billing_event",
  "third_field": "optimization_goal",
  "allowed": [
    ["OUTCOME_TRAFFIC", "IMPRESSIONS", "LINK_CLICKS"],
    ["OUTCOME_TRAFFIC", "IMPRESSIONS", "LANDING_PAGE_VIEWS"]
  ],
  "message": "Ad set '{name}' has incompatible objective/billing_event/optimization_goal"
}
```

## Evaluation order

1. **Schema validation** (`validate_schema`) — JSON Schema checks. Failures here skip all policy evaluation.
2. **Deterministic policy rules** (`policy.evaluate`) — builtin + stack-local rules, evaluated in `id` sort order.
3. **AI policy review** (`validate_policy`) — Claude checks for prohibited content, copy patterns, and other issues that rules cannot catch.

## Rule resolution

Rules are loaded from two locations and merged by `id`:

1. **Builtin rules** — `policies/builtin/` in the AdCode repository root.
2. **Stack-local rules** — `policies/` inside the active stack directory (e.g., `customers/acme/q1_brand/policies/`).

If a stack-local rule has the same `id` as a builtin, the stack-local version wins. This lets operators tighten, relax, or replace builtin rules per stack.

## Builtin rules

| ID | Scope | Severity | Flags |
|---|---|---|---|
| `broadmatch-targeting` | ad set | WARNING | Ad sets with no interests, behaviors, or custom audiences |
| `spend-cap-required` | campaign | WARNING | Campaigns without a `spend_cap` |
| `end-time-required` | ad set | WARNING | Ad sets without an `end_time` |
| `objective-billing-compatibility` | ad set | ERROR | Invalid objective / billing_event / optimization_goal combinations |

## Adding a custom rule

1. Create `policies/` inside the stack directory.
2. Write a `.json` file following the rule format above.
3. Use a unique `id` (or an existing builtin `id` to override it).
4. Run `validate_stack` — your rule is evaluated immediately.

Custom rules are committed to the stack repository alongside the template, giving the same audit trail as the template itself.

## Suppressing a builtin rule

To disable a builtin rule for a specific stack, create a stack-local rule with the same `id` and set `severity` to `"WARNING"` with a condition that always passes (e.g., `field_required` on a field that is always present like `name`). A future version will support an explicit `disabled: true` flag.
