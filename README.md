# AdCode

Terraform for digital advertising.

AdCode manages Meta ad campaigns from declarative JSON stacks. It provides plan/apply workflows, stack-local state, drift detection, and MCP tools so AI agents can operate through a deterministic execution layer instead of making ad platform changes directly.

Git is the audit trail. Pull requests are the review mechanism. The JSON stack is the desired state, and AdCode makes Facebook match it exactly.

## Why

Digital advertising operations still depend on spreadsheets, manual entry, screenshots, and ad-hoc QA in browser UIs. That makes campaigns hard to reproduce, review, roll back, or reconcile after someone edits them directly in Ads Manager.

AdCode applies infrastructure-as-code practices to paid media:

- **Declarative stacks**: describe what should exist, not the sequence of clicks to create it.
- **Plan before apply**: review creates, updates, and deletes before any API call.
- **Stack-local state**: track Facebook IDs and last-pushed params like `terraform.tfstate`.
- **Drift detection**: compare managed state to live Facebook data.
- **Git-backed audit**: commit templates and state together for a durable history.
- **AI-safe execution**: expose the engine through MCP while keeping changes deterministic and reviewable.

## Current Model

AdCode is built for a contractor/operator workflow today. Clients submit campaign templates by email. The hosted email bot validates and routes submissions, but it does not hold Facebook credentials or run the apply engine. The operator runs the MCP server locally against one stack at a time.

That split is intentional:

- client-facing email stays simple;
- Meta credentials stay off the hosted server;
- state stays with the Git repository;
- a human reviews the plan before campaigns are pushed.

See [ADR-008](docs/decisions/008-contractor-service-model.md), [ADR-010](docs/decisions/010-mailroom-engine-split.md), and [ADR-014](docs/decisions/014-stack-level-env.md) for the design rationale.

## Core Concepts

| Concept | AdCode equivalent |
| --- | --- |
| Stack | `customers/<slug>/<stack-name>/` |
| Desired state | `<stack-name>_template.json` |
| Credentials | `.env` in the stack directory |
| State | `state.json` in the stack directory |
| Plan | `plan_stack` output |
| Apply | `apply_stack` |
| Drift report | `drift_stack` |
| Provider | `src/api/meta.py` today; more providers are a roadmap item |

Each stack folder is self-contained:

```text
customers/
  acme/
    q1_brand/
      q1_brand_template.json
      .env
      .env.example
      state.json
```

Starting the server with `--config customers/acme/q1_brand/q1_brand_template.json` loads credentials from `customers/acme/q1_brand/.env`, reads `account_id` from the template, and scopes every stack tool to that folder.

## Quickstart

For a step-by-step walkthrough, see [docs/getting-started.md](docs/getting-started.md).

### 1. Install

```bash
git clone <repo>
cd AdCode
pip install -r requirements.txt
```

### 2. Create a stack

```bash
python scripts/new_customer.py acme-marketing act_123456789
```

This creates:

```text
customers/acme-marketing/acme-marketing_v1/
  .env.example
  acme-marketing_v1_template.json
```

Copy the environment template and fill in the stack credentials:

```bash
cp customers/acme-marketing/acme-marketing_v1/.env.example customers/acme-marketing/acme-marketing_v1/.env
```

Required values:

- `FB_APP_ID`
- `FB_APP_SECRET`
- `FB_ACCESS_TOKEN`
- `ANTHROPIC_API_KEY`

The Facebook account ID lives in the stack template as `account_id`; it does not need to be duplicated in `.env`.

### 3. Start the MCP server

```bash
python src/mcp_server.py --config customers/acme-marketing/acme-marketing_v1/acme-marketing_v1_template.json
```

Startup only loads and validates local stack configuration. Provider credentials are used when a provider-backed tool such as `apply_stack`, `drift_stack`, `search_import_candidates`, or `import_resource` runs.

The legacy `--skip-connection-check` flag is accepted for existing local scripts, but startup no longer performs a live Facebook connection check.

### 4. Plan and apply

From an MCP-compatible client, ask for the active stack to be planned:

```text
Plan this stack.
```

Then apply after reviewing the changes:

```text
Apply this stack.
```

If the plan includes deletes, `apply_stack` requires `confirm_deletes=true`.

## Minimal Stack

See [examples/minimal-stack/minimal_stack_template.json](examples/minimal-stack/minimal_stack_template.json) for a complete valid stack.

The shape mirrors the Facebook hierarchy:

```text
account
  campaign
    ad set
      ad
        creative
```

After apply, AdCode records Facebook-assigned IDs in `state.json` and writes new `fb_id` values back into the template so future plans can track renames and avoid accidental duplicate creation.

## MCP Tools

| Tool | Description |
| --- | --- |
| `show_stack` | Show the active stack template, state path, account ID, and local configuration status. |
| `validate_stack` | Validate the active stack template without calling Facebook. |
| `plan_stack` | Validate the active stack and show creates, updates, and deletes without changing Facebook. |
| `apply_stack(confirm_deletes?)` | Apply the active stack to Facebook and update local state. Deletes require explicit confirmation. |
| `drift_stack` | Compare managed stack state to live Facebook data. Unmanaged account objects are intentionally excluded. |
| `show_state(campaign_name?)` | Read this stack's `state.json`; does not call Facebook. |
| `search_import_candidates(resource_type)` | Find unmanaged live resources that belong under campaigns declared in the active stack. Currently supports `resource_type="adset"`. |
| `import_resource(resource_type, names?)` | Adopt supported live resources into the stack template and state. Currently supports ad sets only. |
| `generate_stack_from_excel(excel_path)` | Extract campaign JSON from an Excel brief using AI and flag ambiguities. |

## Architecture

```text
Client template or Excel brief
        |
        v
Email mailroom on Fly.io
  - validates JSON
  - seeds starter templates
  - forwards valid templates to operator
        |
        v
Operator local machine
  - stack folder with template, .env, state.json
  - MCP server scoped to one stack
        |
        v
Plan/apply engine
  - schema validation
  - AI policy review
  - state diff
  - delete guard
        |
        v
Meta provider -> Facebook Marketing API
        |
        v
state.json + template fb_id updates -> Git commit
```

For more detail, see [docs/architecture.md](docs/architecture.md).

Related design docs:

- [State model](docs/state-model.md)
- [Provider interface](docs/provider-interface.md)
- [Roadmap](docs/roadmap.md)
- [Security policy](SECURITY.md)
- [Architecture decisions](docs/decisions/README.md)

## Repository Layout

```text
customers/
  <slug>/
    <stack-name>/
      <stack-name>_template.json
      .env.example
      .env
      state.json
examples/
  minimal-stack/
schemas/
  campaign.schema.json
  state.schema.json
src/
  api/meta.py
  services/state.py
  services/validate.py
  services/ingest.py
  traffic.py
  reconcile.py
  mcp_server.py
integrations/
  email_mailroom/
tests/
docs/
```

## Optional: Email Intake

The email mailroom is an optional integration for service operators who receive templates or briefs by email. It lives in [integrations/email_mailroom](integrations/email_mailroom/README.md).

```text
Client email
  -> Cloudflare Email Worker
  -> /inbound on Fly.io
```

Routing behavior:

- Valid JSON template: acknowledge the client and forward the template to the operator.
- Invalid JSON template: reply with schema errors and do not forward.
- Excel or plain text: use AI to seed a starter template and send it back to the client for review.

The mailroom is sender-agnostic. Any email that arrives with the shared webhook secret is processed. The bot uses global environment variables:

- `OPERATOR_EMAIL`
- `BOT_EMAIL`
- `RESEND_API_KEY`
- `ANTHROPIC_API_KEY`
- `WEBHOOK_SECRET`

The mailroom does not hold Facebook credentials, run plan/apply, or store stack state.

## Running Tests

Unit tests use mocks and do not require Facebook credentials:

```bash
pytest
```

Integration tests require a Meta developer app, a test ad account, and valid credentials:

```bash
pytest tests/test_integration.py -v
```

Integration tests are skipped automatically when credentials are absent.

## Manual CLI Smoke Tests

Plan without calling Facebook:

```bash
python src/traffic.py customers/<slug>/<stack-name>/<stack-name>_template.json --dry-run
```

Apply:

```bash
python src/traffic.py customers/<slug>/<stack-name>/<stack-name>_template.json
```

Run drift detection:

```bash
python src/reconcile.py act_123456789
```

Seed a template from Excel:

```bash
python -m src.services.ingest brief.xlsx --output customers/<slug>/<stack-name>/<stack-name>_template.json
```

## Open Source And Commercial Model

The open-source project is the local infrastructure engine: schemas, state, plan/apply, drift detection, MCP tools, and provider integrations.

Commercial opportunities are services and managed governance around the engine: implementation, support, hosted state, approvals, RBAC, scheduled drift monitoring, cloud runners, observability, and enterprise integrations.

See [docs/commercial-model.md](docs/commercial-model.md) for the current strategy.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most valuable contributions today are provider maturity, state/reconciliation correctness, examples, documentation, and tests around operational safety.
