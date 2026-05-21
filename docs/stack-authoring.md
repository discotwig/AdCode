# Stack Authoring Guide

AdCode manages Meta Ads campaigns from declarative JSON stacks. This guide covers how to author, seed, and iterate on stack templates using the MCP tool surface.

## The Default Loop

```text
edit JSON → plan_stack → fix JSON → plan_stack → apply_stack
```

`plan_stack` is the normal validation path. It runs schema validation, policy rules, AI policy review, and template linting, then shows the full changeset. Run it after every edit before applying.

## Lint Feedback

`plan_stack` also reports deterministic lint warnings — findings that are structurally valid but suspicious, incomplete, or likely to cause problems at launch. Lint warnings are non-blocking; they appear in the plan output for review but do not prevent apply.

Common lint checks:
- **Placeholder cleanup** — leftover scaffold values like `act_000000000`, `REPLACE_WITH_PAGE_ID`, `IMAGE_HASH`, `example.com`, `TODO`, `TBD`
- **Budget sanity** — both `daily_budget` and `lifetime_budget` on the same ad set; `lifetime_budget` without `start_time`/`end_time`
- **Launch-status safety** — new resources (no `fb_id`) set to `ACTIVE` before review
- **`fb_id` hygiene** — duplicate `fb_id` values that would confuse state correlation
- **Naming** — duplicate campaign or ad set names within the same stack
- **Creative completeness** — link creative missing a `call_to_action`

Lint findings also appear in the Campaign Review Packet (`document_stack`) as a "Launch Readiness Notes" section in plain English.

## Seeding a Template

If you have an Excel brief, use `draft_stack` to extract a starter JSON template:

```text
draft_stack(excel_path="path/to/brief.xlsx")
```

The tool returns a draft JSON with extracted campaign definitions and a list of ambiguities for you to review. It does not call Facebook or write any files — you receive the JSON and decide what to do with it.

After reviewing, save the JSON to your stack directory as `<stack-name>_template.json`, fill in any placeholder values, and run `plan_stack` to validate before applying.

## Minimal Valid Stack Shape

A stack template must include these top-level fields:

```json
{
  "account_id": "act_000000000",
  "campaigns": [...]
}
```

Each campaign:

```json
{
  "name": "Campaign Name",
  "objective": "OUTCOME_TRAFFIC",
  "status": "PAUSED",
  "special_ad_categories": [],
  "spend_cap": 10000,
  "ad_sets": [...]
}
```

Each ad set:

```json
{
  "name": "Ad Set Name",
  "status": "PAUSED",
  "billing_event": "LINK_CLICKS",
  "optimization_goal": "LINK_CLICKS",
  "daily_budget": 2000,
  "end_time": "2026-12-31T23:59:59Z",
  "targeting": {
    "geo_locations": {"countries": ["US"]},
    "age_min": 18,
    "age_max": 65
  },
  "ads": [...]
}
```

See [examples/minimal-stack/](../examples/minimal-stack/) for a complete working example and [schemas/campaign.schema.json](../schemas/campaign.schema.json) for the full field reference.

## Common Enum Values

**Campaign objectives:**

| Value | Description |
| --- | --- |
| `OUTCOME_TRAFFIC` | Drive traffic to a website or app |
| `OUTCOME_LEADS` | Collect leads via forms or landing pages |
| `OUTCOME_SALES` | Drive purchases or conversions |
| `OUTCOME_AWARENESS` | Build brand awareness and reach |
| `OUTCOME_ENGAGEMENT` | Drive engagement with content |
| `OUTCOME_APP_PROMOTION` | Drive app installs or events |

**Billing events:** `LINK_CLICKS`, `IMPRESSIONS`, `APP_INSTALLS`, `THRUPLAY`

**Optimization goals:** `LINK_CLICKS`, `IMPRESSIONS`, `REACH`, `LANDING_PAGE_VIEWS`, `OFFSITE_CONVERSIONS`, `LEAD_GENERATION`, `THRUPLAY`, `APP_INSTALLS`

**Status values:** `ACTIVE`, `PAUSED`

## Importing Live Resources

If campaigns already exist on Facebook and you want to bring them under AdCode management:

1. Add the campaign to your template with its `fb_id`:

```json
{
  "name": "Existing Campaign",
  "fb_id": "act_123456789",
  "objective": "OUTCOME_TRAFFIC",
  "status": "ACTIVE",
  "special_ad_categories": [],
  "ad_sets": []
}
```

2. Preview what ad sets are importable:

```text
import_resource(resource_type="adset", preview=true)
```

3. Import specific ad sets by name:

```text
import_resource(resource_type="adset", names=["Ad Set A", "Ad Set B"])
```

4. Run `plan_stack` to verify no spurious changes before committing.

## Policy Rules

Policy rules live in `policies/builtin/` (built-in) and optionally in a `policies/` directory inside your stack folder (stack-local overrides). They are evaluated automatically by `plan_stack`.

Built-in rules catch:

- Broad targeting (no interests, behaviors, or custom audiences)
- Missing `spend_cap` on campaigns
- Missing `end_time` on ad sets
- Invalid objective/billing event/optimization goal combinations

ERROR-severity violations block `apply_stack`. WARNING-severity violations appear in the plan and review packet but do not block apply.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| No `spend_cap` on campaign | Add `"spend_cap": <whole dollars>` to each campaign |
| Missing `end_time` on ad set | Add `"end_time": "YYYY-MM-DDThh:mm:ssZ"` to each ad set |
| Broad targeting (no interests or audiences) | Add `interests`, `behaviors`, or `custom_audiences` to `targeting` |
| `daily_budget` and `lifetime_budget` both set | Use one or the other per ad set, not both |
| Flight longer than 90 days without review | Shorten the flight or note in the review packet why the long duration is intentional |

## Adding a New Tool vs. Using Existing Ones

The MCP surface is intentionally small. Before proposing a new MCP tool, check whether the need can be met by:

- A parameter on an existing tool (e.g., `preview=true` on `import_resource`)
- Static documentation in `docs/`
- A schema example in `examples/`
- An internal helper function called by an existing tool

New public MCP tools should satisfy most of the criteria in [ADR-022](decisions/022-minimal-mcp-tool-surface.md).
