# AdCode

Terraform for digital advertising.

AdCode is a digital advertising governance layer for Meta Ads. It manages campaigns from declarative JSON stacks and gives AI agents a safe, governed way to operate from approved campaign definitions.

AdCode provides plan/apply workflows, stack-local state, drift detection, and MCP tools so agents can inspect, explain, and request changes through a deterministic execution layer instead of making ad platform changes directly.

The JSON stack is the desired state; the operator engine applies its managed changes to Facebook. Private Git history and pull requests can support review, but durable plan records, approval-to-plan binding, and a production audit system are not implemented.

## Why

Digital advertising operations still depend on spreadsheets, manual entry, screenshots, and ad-hoc QA in browser UIs. That makes campaigns hard to reproduce, review, roll back, or reconcile after someone edits them directly in Ads Manager.

AdCode applies infrastructure-as-code practices to paid media:

- **Declarative stacks**: describe what should exist, not the sequence of clicks to create it.
- **Plan before apply**: review creates, updates, and deletes before any live Meta mutation. Planning can call Anthropic.
- **Stack-local state**: track Facebook IDs and last-pushed params like `terraform.tfstate`.
- **Drift detection**: compare managed state to live Facebook data.
- **Git-backed history**: optionally commit templates and state together in a private repository, never the public project.
- **Restricted MCP execution**: generated local projects allow inspection/planning, not live Meta operations. This is not an OS or agent sandbox.

## Product Pillars

AdCode is designed around five advertising-governance priorities:

| Pillar | What AdCode should provide |
| --- | --- |
| Operational safety | Prevent wrong-account, wrong-stack, unreviewed, or destructive changes through stack scoping, plan/apply, delete gates, and production confirmations. |
| Speed | Reduce repetitive trafficking and QA work with reusable stacks, idempotent applies, Excel-to-stack seeding, drift checks, and review packets. |
| Governance | Preserve who changed what, what was approved, which account was affected, and what state was written through Git history, state files, audit logs, and approval records. |
| Explainability | Make planned, live, and applied state understandable through structured plans, drift reports, import summaries, risk summaries, and AI-readable outputs. |
| Integration | Fit into existing AI, Git, agency, and enterprise workflows through MCP-first access and an interface-independent core engine. |

The product story is: give your company's AI agents a safe, governed way to operate Meta Ads from approved campaign definitions. MCP is the first interface, not the product boundary.

See [ADR-018](docs/decisions/018-adcode-as-governance-layer.md), [ADR-019](docs/decisions/019-product-pillars.md), and [ADR-020](docs/decisions/020-mcp-connection-modes.md) for the design rationale.

## Local macOS / Cursor POC

The local POC lets an owner describe campaigns in plain language to Cursor, inspect the edited JSON, and review plans without giving the project MCP live Meta access. No hosted connection or code repository checkout on the recipient's Mac is required.

1. Extract a trusted source ZIP and double-click `scripts/install_macos.command` as your normal user. The purpose-built bundle is `dist/AdCode-Local-POC.zip` with root `Install AdCode.command`. The unsigned download may require normal Finder/Privacy & Security approval; do not bypass Gatekeeper or quarantine.
2. Restart Cursor. Ask global **AdCode-Setup → `create_workspace`** using a friendly `customer_name` and optional `workspace_name` (default `Campaigns`), not slugs, account IDs, or secrets. Its four tools are `create_workspace`, `list_workspaces`, `check_workspace`, and `open_workspace`.
3. Use `open_workspace` with the returned known `workspace_id`, or open the returned folder yourself under **`~/AdCode Workspaces`** (not Documents). It contains an unfinished draft (`account_id: ""`, `campaigns: []`), a blank private `.env`, `.env.example`, guided metadata, project MCP configuration and rules/ignore files; no fake provider IDs or state are created.
4. **Edit `.env` yourself privately**: enter `FB_ACCOUNT_ID`, Meta app ID/secret/token, Anthropic key, a required budget cap in **whole currency units, not cents**, and an uppercase supported ISO currency code. Never let an agent read the file. `Configure AdCode.command` is an optional local helper supporting unbound guided drafts as well as bound workspaces, not the primary setup path; it saves settings without permitting account retargeting. Ask `check_workspace` to check local settings; after valid settings it binds the untouched empty draft's account without contacting providers. Generated `--access-mode planning --onboarding` projects refresh settings on subsequent stack-tool calls without a restart.
5. Tell Cursor what you are promoting, your budget, and your dates. Ask it to edit local JSON, keep new campaigns `PAUSED`, inspect it, then request a plan/review packet. Campaign data can be processed by Cursor's providers and Anthropic and may incur costs. Never put runtime credentials in chat, MCP JSON, installer inputs, or telemetry. Keep Cursor permissions and approval prompts enabled; setup never bypasses them or authorizes spending.

Prepared files, recognized connection configuration, and a requested Cursor launch are **not** proof of an active MCP or authenticated provider connection. Local `ready`/entered-settings statuses do not verify provider access.

The user-local installation lives in `~/Library/Application Support/AdCode`, using uv 0.13.7 (downloaded archives SHA-256 verified), managed Python 3.13, and the universal hash-locked `requirements-local.lock`. The runtime is allowlisted, not a repository/private-data copy. Updates preserve releases and roll back the active pointer on Cursor registration failure; existing projects stay pinned to their original release and virtualenv. There is no automatic migration or old-release cleanup. Older workspaces without guided metadata return `upgrade_required` from the local check and remain unchanged.

Generated projects explicitly use `--access-mode planning`; enabling legacy operator tools requires a deliberate configuration change, never automatic installer escalation. The POC has no durable approval binding, production audit guarantee, or platform sandbox. A Meta account may not be a sandbox. This is not a signed/notarized DMG and includes no payment/licensing, update service, or Meta OAuth flow.

**Validation:** full Windows `python -m pytest -q`: **563 passed, 25 skipped**. Clean Linux Python **3.13.18**, fresh hash-locked bundle runtime, nine selected local/MCP files including guided access and real guided stdio: **249 passed, no skips**, with no provider calls. Rebuild and verify archive integrity, public-file allowlist, permissions, and checksum after documentation changes. Actual macOS hardware is unavailable; installation, Cursor UI and approval behavior remain unverified. Earlier results are historical and recorded separately. See the [validation record](docs/local-poc-validation.md). See the [local operator runbook](docs/local-operator.md), [security boundaries](SECURITY.md), and [ADR-024](docs/decisions/024-local-macos-cursor-poc.md).

## Deployment Options

Local operation is implemented; organizational hosting is a design direction, not a production-ready feature of this POC:

| Mode | Use case | Connection model |
| --- | --- | --- |
| **Local Operator Mode** | Personal development, informal demos, and single-operator client service work. | A local MCP client such as Cursor launches `src/mcp_server.py` over `stdio` with `--config <stack_template>`. No hosting or tunnel is required. |
| **Organizational Hosted Mode** | Formal cloud-agent demos, multi-user organizational use, paid hosted services, and client-hosted implementations. | AdCode runs as a hosted MCP service or behind an authenticated gateway/enterprise connector. Cloud clients connect over HTTPS to approved registered stacks. |

Temporary tunnels such as `ngrok` are useful only for engineering tests. They are not the recommended model for formal demos, customer use, or production operations.

See [ADR-020](docs/decisions/020-mcp-connection-modes.md) for the connection-mode decision.

## Current Model

AdCode is built for a contractor/operator workflow today. Clients submit campaign templates by email. The hosted email bot validates and routes submissions, but it does not hold Facebook credentials or run the apply engine. The operator runs the MCP server locally against one stack at a time using Local Operator Mode.

That split is intentional:

- client-facing email stays simple;
- Meta credentials stay off the hosted server;
- state stays with the Git repository;
- a human reviews the plan before campaigns are pushed.

See [ADR-008](docs/decisions/008-contractor-service-model.md), [ADR-010](docs/decisions/010-mailroom-engine-split.md), and [ADR-014](docs/decisions/014-stack-level-env.md) for the current service model rationale.

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

## Developer / Legacy Operator Quickstart

For the restricted macOS/Cursor POC, use the [local operator runbook](docs/local-operator.md) instead. The commands below are the deliberate developer/operator path: **without `--access-mode`, the server retains all nine legacy tools, including live writes**. They do not describe the generated planning-only workspace.

For the older operator walkthrough, see [docs/getting-started.md](docs/getting-started.md).

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

Optional values:

- `ACCOUNT_BUDGET_CAP` — total declared spend cap in whole currency units, not cents. When set, `plan_stack` shows whether the stack exceeds the cap and `apply_stack` is blocked if it does. This is not a Meta billing limit.
- `CURRENCY` — ISO 4217 currency code for display (default: `USD`).

These are optional only in the legacy workflow; guided local POC settings checks require both.

In this legacy workflow, the Facebook account ID lives in the stack template as `account_id` and does not need to be duplicated in `.env`. Guided onboarding instead requires private `FB_ACCOUNT_ID` entry in `.env` so the local check can bind the empty draft.

### 3. Start the MCP server

```bash
python src/mcp_server.py --config customers/acme-marketing/acme-marketing_v1/acme-marketing_v1_template.json
```

Startup only loads and validates local stack configuration. Provider credentials are used when a provider-backed tool such as `apply_stack`, `drift_stack`, or `import_resource` runs.

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

Public examples use placeholder account and page IDs only. Replace values such as `act_000000000` and `000000000000000` with your own Meta IDs in private stack files.

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

The MCP surface is intentionally small — a Terraform-like set of stack lifecycle verbs.

| Project access mode | Available tools |
| --- | --- |
| `--access-mode inspect` | `show_stack`, `show_state` only |
| `--access-mode planning` (generated local POC default) | Inspect tools plus `plan_stack`, `document_stack`; no MCP file writes, live Meta access, or Excel tool |
| `--access-mode operator` or no flag (legacy compatibility) | All nine tools in the table below |

Restrictions apply at both discovery and dispatch, including guessed hidden-tool calls. Restricted modes clear inherited provider/settings environment values; planning loads the fixed stack's `.env` without interpolation. Account binding mismatches fail closed. These controls do not restrict Cursor's independent terminal/file tools.

The following loop and full tool table describe **operator mode**, not the generated planning-only POC. See [ADR-022](docs/decisions/022-minimal-mcp-tool-surface.md) and [docs/stack-authoring.md](docs/stack-authoring.md) for the design rationale.

The normal operator loop is:

```text
draft_stack (seed from Excel) → edit JSON → plan_stack → apply_stack
drift_stack → remediate_drift when live Facebook has manual changes to overwrite
show_state / import_resource / document_stack as needed
```

| Tool | Description |
| --- | --- |
| `show_stack` | Show the active stack template path, state path, account ID, and local `.env` status. Read-only; no Facebook call. |
| `draft_stack(excel_path)` | Produce a starter JSON template from an Excel brief using AI. Returns draft JSON with flagged ambiguities. Does not call Facebook or write state. |
| `plan_stack` | Validate the active stack (schema, policy rules, AI review) and show the full changeset. The normal validation feedback path — run this before every apply. Includes budget delta and cap check when `ACCOUNT_BUDGET_CAP` is set. |
| `apply_stack(confirm_deletes?)` | Apply the active stack to Facebook and update local state. Deletes require a second call with `confirm_deletes=true` after reviewing the plan. |
| `drift_stack` | Compare managed stack state to live Facebook data. Reports only stack-managed objects; unmanaged account objects are intentionally excluded. |
| `remediate_drift(confirm_deletes?)` | Terraform-like drift remediation: compare the approved template to live Facebook, overwrite managed live drift with template values, and update local state. Run after reviewing `drift_stack`; deletes require `confirm_deletes=true`. |
| `show_state(campaign_name?)` | Read this stack's `state.json`. Does not call Facebook. |
| `import_resource(resource_type, names?, preview?)` | Adopt live resources into the stack template and state. Use `preview=true` to list importable candidates before committing. Currently supports `resource_type="adset"` only. |
| `document_stack` | Generate a Campaign Review Packet — a Markdown report for non-technical review showing planned changes, budget impact, policy results, targeting summary, flight dates, and an approval recommendation. Does not call Facebook. |

## Architecture

Current local/operator architecture:

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
  - local MCP client over stdio
  - stack folder with template, .env, state.json
  - MCP server scoped to one stack by --config
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

Future organizational hosted deployments use the same engine behind a hosted MCP endpoint, registered stacks, and additional governance controls.

For more detail, see [docs/architecture.md](docs/architecture.md).

Related design docs:

- [State model](docs/state-model.md)
- [Provider interface](docs/provider-interface.md)
- [Roadmap](docs/roadmap.md)
- [Security policy](SECURITY.md)
- [Architecture decisions](docs/decisions/README.md)
- [AdCode as a governance layer](docs/decisions/018-adcode-as-governance-layer.md)
- [Product pillars](docs/decisions/019-product-pillars.md)
- [Supported MCP connection modes](docs/decisions/020-mcp-connection-modes.md)

## Repository Layout

```text
customers/
  <slug>/
    <stack-name>/
      <stack-name>_template.json
      .env.example
      .env
      state.json
      policies/             ← optional stack-local policy rules
examples/
  minimal-stack/
policies/
  builtin/                  ← built-in policy rules (versioned with AdCode)
schemas/
  campaign.schema.json
  state.schema.json
  policy.schema.json
src/
  api/meta.py
  services/state.py
  services/validate.py
  services/policy.py
  services/ingest.py
  traffic.py
  reconcile.py
  mcp_server.py
integrations/
  email_mailroom/
tests/
docs/
```

`customers/` is intentionally ignored by Git. Use it for private stack templates, `state.json`, `.env` credentials, and customer-specific operating files. Do not commit customer workspaces to the public repository.

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

These developer/operator CLI commands are outside the generated project's MCP access-mode boundary; apply can affect a real account. Do not run them as a workaround for planning-mode restrictions.

Plan without calling Facebook (AI review may still call Anthropic):

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
