# AdCode

Infrastructure-as-code for ad campaign trafficking. The JSON file is the desired state. AdCode makes Facebook match it — exactly.

Git history is the audit trail. Pull requests are the review mechanism. No one needs to log into Facebook Ads Manager for routine trafficking or QA.

## Service model

AdCode is a contractor trafficking service. The operator receives campaign templates from clients, runs the engine locally, and pushes changes to Facebook. Clients never interact with the MCP server or the Facebook API directly.

This maps onto how agencies already buy ad trafficking — as a contractor engagement, not a software subscription. The operator's value is speed, accuracy, and a Git-backed audit trail of every change ever made.

**Why use AdCode over a manual trafficker:**
- Changes are applied from a versioned template — every push is a Git commit; any change can be explained or reverted
- Machine-applied changes are faster and more accurate than hand-entry in Ads Manager
- The operator accepts templates, not ad hoc instructions — submissions are structured and reviewable

See ADR-008 for the contractor service model design.

## Email bot (template mailroom)

Clients submit campaign templates by email. The email bot on Fly.io validates the submission and routes it — it does not connect to Facebook or run the engine.

```
Client emails template (.json) or Excel brief
  → Cloudflare Email Worker → api.ryanbishop.me/inbound (Fly.io)

Path 1 — Valid AdCode template:
  → Reply to client: "Request received and submitted"
  → Forward template to operator

Path 2 — JSON with schema errors:
  → Reply to client with specific errors and how to fix them
  → (Client fixes template and resubmits)

Path 3 — Dirty Excel or plain text:
  → Seed a starter template using AI
  → Reply to client with template attached (account_id placeholder included)
  → (Client fills in account_id, reviews, resubmits)
```

The bot is **sender-agnostic** — any email that arrives with a valid webhook secret is processed, regardless of sender address. No per-client allowlist is maintained. The `WEBHOOK_SECRET` shared with the Cloudflare Worker is the only security boundary.

Bot settings are global environment variables on Fly.io (`OPERATOR_EMAIL`, `BOT_EMAIL`, `RESEND_API_KEY`, `ANTHROPIC_API_KEY`, `WEBHOOK_SECRET`). Stack `.env` files (`customers/*/stack_name/.env`) are for the local MCP server only and contain no email routing fields.

See ADR-010 for the mailroom design rationale. See ADR-011 for the sender-agnostic decision.

## Operator workflow

After receiving a forwarded template, the operator applies it locally:

```bash
# 1. Save the template into the customer's stack folder
#    (copy attachment from email to customers/<slug>/<stack-name>/<stack-name>_template.json)

# 2. Start the MCP server scoped to that stack
python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json

# 3. Use your AI client (Claude, Gemini, Cursor) to plan and apply:
#    "Plan and apply this stack"
```

`--config` loads `.env` from the stack directory and sets `account_id` from the template. State is written to `customers/<slug>/<stack-name>/state.json` after each apply and committed to Git alongside the template. The Git history is the audit trail.

## How it works

AdCode follows the same model as Terraform:

| Concept | AdCode equivalent |
| --- | --- |
| Stack directory | `<stack-name>/` — the folder *is* the unit of isolation, exactly like `cd my-stack/` in Terraform |
| Template | `<stack-name>/<stack-name>_template.json` — desired state; you edit this |
| Credentials | `<stack-name>/.env` — credentials for this stack's ad account (gitignored) |
| Stack state | `<stack-name>/state.json` — maps every managed object to its Facebook ID (like `terraform.tfstate`) |
| Changeset | `plan_campaigns` output — validates + shows creates, updates, and deletes |
| Apply | `apply_campaigns` — makes Facebook match the template, then writes `state.json` |

Each stack folder is fully self-contained: template, credentials, and state all live together. The server is started once per stack with `--config <stack>_template.json` — `account_id` and `.env` are read from that directory. Two stacks in the same Facebook account are completely independent. See ADR-012, ADR-013, and ADR-014 for the full design.

**The full lifecycle in four steps:**

1. **Define** — write or edit an Ad Stack file. Add a campaign to create it. Change a field to update it. Remove a campaign to delete it.
2. **Plan** — run `plan_campaigns` to validate the file and see the exact changeset before any API call is made. Deletions are called out explicitly and require confirmation to apply.
3. **Apply** — run `apply_campaigns`. Creates, updates, and deletes are applied in a single operation. The stack state file in Git is updated to reflect what's live.
4. **Audit** — run `get_drift_report` to detect if anyone made manual changes in Ads Manager that diverge from the stack state.

The core scripts are exposed as MCP tools. Connect your model (Gemini, Claude, etc.) to the MCP server and interact via natural language.

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd AdCode
pip install -r requirements.txt
```

### 2. Create a customer directory

Each client gets their own isolated stack directory. Use the onboarding script to scaffold it:

```bash
python scripts/new_customer.py <slug> <account_id>
# e.g. python scripts/new_customer.py acme-marketing act_123456789
```

This creates `customers/<slug>/<slug>_v1/` containing a `.env.example` and a blank `<slug>_v1_template.json`.

### 3. Configure credentials

```bash
cp customers/<slug>/<stack-name>/.env.example customers/<slug>/<stack-name>/.env
# Fill in FB_APP_ID, FB_APP_SECRET, FB_ACCESS_TOKEN, ANTHROPIC_API_KEY
```

Facebook credentials: create a System User in Meta Business Manager, grant it access to the ad account, and generate a token with `ads_management` permission. `account_id` is set in the template JSON — no `FB_ACCOUNT_ID` entry needed in `.env`.

Each stack has its own `.env`. This is intentional — it makes it structurally impossible to apply the wrong account's credentials to the wrong stack.

### 4. Start the MCP server

```bash
python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json
```

`--config` points directly at the stack template. The server loads `.env` from the same directory, reads `account_id` from the template JSON, and is now scoped to that one stack for the lifetime of the process.

Point your MCP-compatible model at the server. The tool surface is described below.

## MCP Tools

| Tool | Description |
| --- | --- |
| `plan_campaigns` | Validate the active stack template and show the full changeset (creates, updates, deletes) — no changes made to Facebook. Always run before `apply_campaigns` |
| `apply_campaigns(confirm_deletes?)` | Apply the active stack to Facebook — creates, updates, and deletes scoped to this stack only. If the plan includes deletions, returns the plan first and requires `confirm_deletes=true` |
| `list_campaigns(account_id?)` | Fetch all campaigns directly from Facebook — always live, never from the local state file |
| `pause_campaigns(filter?)` | Pause campaigns on Facebook matching a name or ID filter — queries Facebook directly |
| `get_campaign_status(campaign_id)` | Fetch live fields for a single campaign from Facebook by ID |
| `get_campaign_export(account_id)` | Fetch the full campaign hierarchy (campaigns + ad sets + ads) for an account in one call — always live |
| `get_drift_report` | Compare this Ad Stack's state to live Facebook data; only reports on campaigns declared in this stack |
| `import_adsets(adset_names?)` | Adopt ad sets that exist on Facebook but are not tracked in this stack (MISSING_FROM_STATE items) — the equivalent of `terraform import` for ad sets |
| `find_duplicates(account_id?)` | Find campaigns with duplicate names in the account; returns each name with multiple fb_ids along with created_time and status |
| `get_local_state(campaign_name?)` | Read this Ad Stack's state file — shows what AdCode last recorded after a push, scoped to this stack only |
| `ingest_excel(excel_path)` | Extract campaign JSON from an Excel brief using AI; flags ambiguities for human review |

## Repository layout

```text
customers/
  <slug>/
    <stack-name>/                      One folder per Ad Stack — the folder IS the stack
      <stack-name>_template.json       Template (desired state) — edit this
      .env                             Credentials for this stack's ad account (gitignored)
      .env.example                     Credential template (committed)
      state.json                       Stack state written after apply (like terraform.tfstate)
src/
  api/meta.py           Facebook Marketing API client
  services/
    state.py            State file read/write (stack-scoped)
    validate.py         Schema and AI policy validation
    ingest.py           Excel → JSON ingestion
  traffic.py            Apply engine
  reconcile.py          Drift detection
  mcp_server.py         MCP server entry point
schemas/                JSON Schema definitions for Ad Stacks and state files
tests/                  Test suite
docs/                   Architecture decisions, API research, build checklist
```

## Ad Stack format

See `schemas/campaign.schema.json` for the full schema. A minimal example is in `tests/fixtures/example.json`.

The structure mirrors Facebook's object hierarchy: campaign → ad set → ad → creative. The top-level `account_id` tells the engine which Facebook account to call against.

Each campaign, ad set, and ad supports an optional `fb_id` field. When present, `plan_campaigns` matches by `fb_id` instead of name, enabling stable tracking through renames. The `import_adsets` tool populates `fb_id` automatically for imported objects.

`state.json` is always written in the same folder as the template and must be committed to Git alongside it. It is the only file you should never edit by hand — use `import_adsets` for surgical state updates.

## Excel ingestion

If you have an Excel brief, use the `ingest_excel` tool with an Excel path and the AI will extract campaign definitions against the schema, flag ambiguities, and return JSON ready for review. Commit the JSON after reviewing ambiguities — do not re-ingest from Excel after the JSON is committed.

## Multi-tenant deployment

Each client gets their own server process, working directory, and credentials. MCP has no built-in auth — isolation is achieved through process boundaries, not middleware.

```text
customers/
  acme/
    q1_brand/                      ← Ad Stack folder
      q1_brand_template.json       ← template
      .env                         ← credentials for Acme's ad account (gitignored)
      state.json                   ← stack state (written after apply)
    q2_retail/                     ← independent Ad Stack folder
      q2_retail_template.json
      .env
      state.json
  globex/
    summer_launch/
      summer_launch_template.json
      .env
      state.json
```

A server started with `--config customers/acme/q1_brand/q1_brand_template.json` loads only Acme's credentials and can only act on that stack. Each stack's `.env` pins it to a specific ad account — it is physically impossible to apply the wrong credentials to the wrong stack.

Run `python scripts/new_customer.py <slug> <account_id>` to scaffold a new customer directory. See ADR-008 for the service model, ADR-012 for Ad Stack isolation, ADR-013 for the Terraform-style layout, and ADR-014 for the stack-level credential model.

## Connecting Gemini (or any MCP-compatible model)

The MCP server speaks the [Model Context Protocol](https://modelcontextprotocol.io/) over stdio. Any MCP-compatible model can connect to it.

### Gemini (Google AI Studio / Vertex AI)

1. Start the server in a terminal:

   ```bash
   python src/mcp_server.py
   ```

2. In your Gemini configuration, add an MCP server entry pointing to that process. The exact config format depends on your Gemini client, but the pattern is:

   ```json
   {
     "mcpServers": {
       "adcode": {
         "command": "python",
         "args": ["src/mcp_server.py"],
         "cwd": "/path/to/AdCode"
       }
     }
   }
   ```

3. Gemini will discover the tools automatically. You can now issue natural language instructions like:
   - *"Validate campaigns/my_account.json and tell me if there are any policy issues."*
   - *"Push campaigns/q3_launch.json to Facebook."*
   - *"Show me the drift report for act_123456789."*

### Claude Code (via MCP settings)

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "adcode": {
      "command": "python",
      "args": ["src/mcp_server.py"],
      "cwd": "/path/to/AdCode"
    }
  }
}
```

## Logging

The server logs structured JSON to stdout. Each log line includes `ts`, `level`, `logger`, `message`, and context fields like `fb_id`, `account_id`, and `name` where applicable.

To enable JSON logging in scripts, call `configure_logging()` at startup:

```python
from src.logger import configure_logging
configure_logging()
```

## Running tests

### Unit tests (no credentials needed)

```bash
pytest tests/
```

220+ tests, all local with mocks. Should pass out of the box.

### Integration tests (Facebook sandbox)

You need a Meta developer account with a test ad account:

1. Go to [developers.facebook.com](https://developers.facebook.com), create an app with Marketing API access
2. Create a System User in Business Manager, generate a token with `ads_management` permission
3. Fill in `.env` with your credentials
4. Run:

```bash
pytest tests/test_integration.py -v
```

Integration tests are skipped automatically when credentials are absent.

### Manual smoke tests (CLI)

Plan (dry-run) a campaign file — shows what would change without calling the API:

```bash
python src/traffic.py customers/<slug>/campaigns/<file>.json --dry-run
```

Apply a campaign file to Facebook:

```bash
python src/traffic.py customers/<slug>/campaigns/<file>.json
```

Run a drift report for an account:

```bash
python src/reconcile.py <account_id>
```

Seed a campaign template from an Excel brief:

```bash
python -m src.services.ingest my_brief.xlsx --output customers/<slug>/campaigns/output.json
```
