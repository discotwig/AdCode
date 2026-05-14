# Architecture

AdCode is infrastructure-as-code for paid media. A stack template declares the desired Facebook campaign hierarchy, and the engine plans and applies the API operations needed to make live Facebook state match that template.

## System Diagram

```text
                         hosted mailroom

Client email
  .json / .xlsx / text
        |
        v
Cloudflare Email Worker
        |
        v
FastAPI email bot on Fly.io
  - validates JSON attachments
  - replies with schema errors
  - seeds starter templates from Excel or text
  - forwards valid templates to the operator


                         local execution

Operator saves template into a stack folder
        |
        v
customers/<slug>/<stack-name>/
  <stack-name>_template.json
  .env
  state.json
        |
        v
MCP server scoped with --config <stack-name>_template.json
        |
        v
plan_stack
  - JSON Schema validation
  - AI policy review
  - desired-vs-state diff
  - delete detection
        |
        v
operator review
        |
        v
apply_stack
  - Meta API create/update/delete
  - state.json update
  - template fb_id persistence
        |
        v
Git commit of template + state
```

## Layer Responsibilities

| Layer | Files | Responsibility |
| --- | --- | --- |
| Stack data | `customers/<slug>/<stack>/` | Template, credentials, and state for one isolated Ad Stack. |
| MCP interface | `src/mcp_server.py` | Tool surface used by AI clients and operators. |
| Plan/apply engine | `src/traffic.py` | Computes changesets and executes create/update/delete operations. |
| State service | `src/services/state.py` | Reads and writes stack-local `state.json` atomically. |
| Provider client | `src/api/meta.py` | Wraps the Facebook Business SDK. |
| Drift detection | `src/reconcile.py` | Compares stack state to live Facebook actuals. |
| Validation | `src/services/validate.py` | Combines schema validation with AI policy review. |
| Ingestion | `src/services/ingest.py` | Converts Excel briefs into campaign JSON. Plain-text email extraction lives in the email mailroom integration. |
| Email mailroom | `integrations/email_mailroom/` | Optional client-facing intake and routing; no Facebook credentials. |

## Stack Isolation

The stack folder is the unit of isolation.

```text
customers/acme/q1_brand/
  q1_brand_template.json
  .env
  state.json

customers/acme/q2_retail/
  q2_retail_template.json
  .env
  state.json
```

The MCP server is started with one stack template:

```bash
python src/mcp_server.py --config customers/acme/q1_brand/q1_brand_template.json
```

Startup does three things:

1. Loads `.env` from the stack directory.
2. Reads `account_id` from the template.
3. Sets the active state directory to the stack folder.

As a result, stack-scoped tools cannot accidentally read or write another stack's state file. Two stacks may target the same Facebook account, but their delete plans and drift reports remain independent because each stack has its own `state.json`.

## Desired State Flow

`plan_stack` loads the active template and local state, then produces a changeset:

```text
template campaigns
  compared with
state.json campaigns
  produces
Create*, Update*, Delete* operations
```

The planner matches by `fb_id` first and by name second. This allows campaign, ad set, and ad renames without duplicate creation.

Deletes are produced when an object exists in `state.json` but no longer appears in the template. `apply_stack` blocks plans containing deletes unless `confirm_deletes=true` is provided.

## Apply Flow

`apply_stack` executes operations against `MetaClient`:

1. Create or update campaigns.
2. Create or update ad sets.
3. Create creatives and ads.
4. Delete removed ads, ad sets, and campaigns leaf-first.
5. Save `state.json` after each successful operation.
6. Persist newly created `fb_id` values back into the template.

State writes are atomic: the state service writes a temporary file and renames it into place.

## Drift Detection

`drift_stack` fetches the live Facebook hierarchy and compares it to the managed stack state. It reports:

- `MISSING_FROM_FACEBOOK`: tracked locally but absent from Facebook.
- `FIELD_MISMATCH`: present in both, but tracked fields differ.
- `IN_SYNC`: no tracked difference.

Drift detection intentionally compares state to live Facebook data. It does not treat the template as proof of what is live, and it does not report unmanaged account objects as drift. Use `search_import_candidates(resource_type="adset")` when you want to discover supported live objects that can be adopted into the stack.

## Hosted Boundary

The hosted email bot is a mailroom, not the execution engine. It does not hold Meta credentials, state files, or pending apply plans.

This keeps the hosted surface small:

- `RESEND_API_KEY` for outbound email.
- `ANTHROPIC_API_KEY` for template seeding.
- `WEBHOOK_SECRET` for Cloudflare Worker authentication.

The execution engine remains local to the operator until there is enough production usage to justify a hosted control plane.

## Provider Roadmap

Meta is the only implemented provider today. The next architectural milestone is a provider interface that makes campaign hierarchy operations explicit:

- list campaigns, ad sets, ads;
- create/update/delete campaigns;
- create/update/delete ad sets;
- create/update/delete ads and creatives;
- normalize provider-specific fields for state and drift.

A second partial provider would be valuable even before it is complete because it would force the core engine to separate provider-neutral planning from provider-specific API behavior.
