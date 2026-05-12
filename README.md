# AdCode

Infrastructure-as-code for ad campaign trafficking. The JSON file is the desired state. AdCode makes Facebook match it — exactly.

Git history is the audit trail. Pull requests are the review mechanism. No one needs to log into Facebook Ads Manager for routine trafficking or QA.

## Service model

AdCode is designed to be operated as a **contractor service**, not a SaaS product. The operator provides an email address; clients send media plans; campaigns get pushed; confirmations come back. The client never interacts with the MCP server or Facebook API directly.

This maps onto how agencies already buy ad trafficking — as a contractor engagement, not a software subscription. No procurement friction, no seat licenses, no client onboarding beyond "send us your brief."

The operator is the human in the loop. Every push goes through a plan-review step before `apply_campaigns` runs. The operator approves the plan; the software executes it. See ADR-008 for the full design rationale.

## Email bot

Clients interact with AdCode entirely by email — no logins, no dashboards.

```
Client → traffic@ryanbishop.me → Cloudflare Email Worker
  → api.ryanbishop.me/inbound (Fly.io)
  → Claude extracts campaign JSON
  → Operator receives plan email
  → Operator replies GO → apply → client confirmation
                    HOLD → client notified, brief discarded
```

Attach an Excel brief or write the campaign description in plain text. The AI extracts campaign definitions, validates against Facebook policy, and generates a plan. If anything is ambiguous, the client gets a list of questions before the plan is generated.

The email bot runs as a FastAPI service on Fly.io. See ADR-009 for architecture decisions and `docs/email-worker-runbook.md` for operational procedures.

## How it works

AdCode follows the same model as AWS CloudFormation or Terraform:

| Concept | AdCode equivalent |
| --- | --- |
| Template | Campaign JSON file (`campaigns/<slug>/<account>/file.json`) |
| Stack state | `state/<account>.json` — maps every managed object to its Facebook ID |
| Changeset | `plan_campaigns` output — validates + shows creates, updates, and deletes |
| Apply | `apply_campaigns` — makes Facebook match the JSON, then updates the state file |

**The full lifecycle in four steps:**

1. **Define** — write or edit a campaign JSON file. Add a campaign to create it. Change a field to update it. Remove a campaign to delete it.
2. **Plan** — run `plan_campaigns` to validate the file and see the exact changeset before any API call is made. Deletions are called out explicitly and require confirmation to apply.
3. **Apply** — run `apply_campaigns`. Creates, updates, and deletes are applied in a single operation. The state file in Git is updated to reflect what's live.
4. **Audit** — run `get_drift_report` to detect if anyone made manual changes in Ads Manager that diverge from the state file.

The core scripts are exposed as MCP tools. Connect your model (Gemini, Claude, etc.) to the MCP server and interact via natural language.

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd AdCode
pip install -r requirements.txt
```

### 2. Create a customer directory

Each client gets their own isolated directory with credentials, campaigns, and state. Use the onboarding script to scaffold it:

```bash
python scripts/new_customer.py <slug> <account_id>
# e.g. python scripts/new_customer.py acme-marketing act_123456789
```

This creates `customers/<slug>/` with a `config.json`, `.env.example`, and empty `campaigns/` and `state/` directories.

### 3. Configure credentials

```bash
cp customers/<slug>/.env.example customers/<slug>/.env
# Fill in FB_APP_ID, FB_APP_SECRET, FB_ACCESS_TOKEN, ANTHROPIC_API_KEY
```

Facebook credentials: create a System User in Meta Business Manager, grant it access to the ad account, and generate a token with `ads_management` permission. The `account_id` is already set in `config.json` — no `FB_ACCOUNT_ID` needed in `.env`.

### 4. Start the MCP server

```bash
python src/mcp_server.py --config customers/<slug>/config.json
```

The `--config` flag scopes the server to that customer's campaigns and state directory. Without it, the server falls back to repo-root `campaigns/` and `state/` (useful for development).

Point your MCP-compatible model at the server. The tool surface is described below.

## MCP Tools

| Tool | Description |
| --- | --- |
| `plan_campaigns(json_path)` | Validate a campaign JSON file and show the full changeset (creates, updates, deletes) — no changes made to Facebook. Always run before `apply_campaigns` |
| `apply_campaigns(json_path, confirm_deletes?)` | Apply a campaign JSON file to Facebook — creates, updates, and deletes. If the plan includes deletions, returns the plan first and requires `confirm_deletes=true` |
| `list_campaigns(account_id?)` | Fetch all campaigns directly from Facebook — always live, never from the local state file |
| `pause_campaigns(filter)` | Pause campaigns on Facebook matching a name or ID filter — queries Facebook directly, works for campaigns not tracked in state |
| `get_campaign_status(campaign_id)` | Fetch live fields for a single campaign from Facebook by ID |
| `get_campaign_export(account_id)` | Fetch the full campaign hierarchy (campaigns + ad sets + ads) for an account in one call — always live |
| `get_drift_report(account_id)` | Compare local state to live Facebook data; report objects missing, untracked, or field-mismatched |
| `import_adsets(json_path, account_id, name_filter?)` | Adopt ad sets that exist on Facebook but are not tracked in state (MISSING_FROM_STATE items) — the equivalent of `terraform import` for ad sets |
| `find_duplicates(account_id)` | Find campaigns with duplicate names in the account; returns each name with multiple fb_ids along with created_time and status |
| `get_local_state(filter?)` | Read the local state file (cache) — shows what AdCode last recorded after a push, not live Facebook state |
| `ingest_excel(excel_path)` | Extract campaign JSON from an Excel brief using AI; flags ambiguities for human review |

## Repository layout

```text
campaigns/          JSON campaign definitions (source of truth)
state/              State files written after push (campaign → Facebook ID mapping)
src/
  api/meta.py       Facebook Marketing API client
  services/
    state.py        State file read/write
    validate.py     Schema and AI policy validation
    ingest.py       Excel → JSON ingestion
  traffic.py        Apply engine
  reconcile.py      Drift detection
  mcp_server.py     MCP server entry point
schemas/            JSON Schema definitions for campaigns and state files
tests/              Test suite
docs/               Architecture decisions, API research, build checklist
```

## Campaign JSON format

See `schemas/campaign.schema.json` for the full schema. A minimal example is in `campaigns/example.json`.

The structure mirrors Facebook's object hierarchy: campaign → ad set → ad → creative.

Each campaign, ad set, and ad supports an optional `fb_id` field. When present, `plan_campaigns` matches by `fb_id` instead of name, enabling stable tracking through renames. The `import_adsets` tool populates `fb_id` automatically for imported objects.

## Excel ingestion

If you have an Excel brief, use the `ingest_excel` tool with an Excel path and the AI will extract campaign definitions against the schema, flag ambiguities, and return JSON ready for review. Commit the JSON after reviewing ambiguities — do not re-ingest from Excel after the JSON is committed.

## Multi-tenant deployment

Each client gets their own server process, working directory, and credentials. MCP has no built-in auth — isolation is achieved through process boundaries, not middleware.

```text
customers/
  acme/
    config.json        ← account_id, data paths (committed)
    .env               ← FB + Anthropic credentials (gitignored)
    campaigns/
      act_123456/
        q1_brand.json
    state/
      act_123456.json
  globex/
    config.json
    .env
    campaigns/
    state/
```

A server instance started with `--config customers/acme/config.json` can only reach Acme's account and data — it has no path or credentials for any other client.

Run `python scripts/new_customer.py <slug> <account_id>` to scaffold a new customer directory. See ADR-008 for the full design.

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

214 tests, all local with mocks. Should pass out of the box.

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

Validate a campaign file against schema and AI policy checks:

```bash
python -c "
import json, anthropic, os
from dotenv import load_dotenv
from src.services.validate import validate_all
load_dotenv()
data = json.load(open('campaigns/example.json'))
result = validate_all(data, anthropic.Anthropic())
print(result.summary())
"
```

Dry-run the apply engine to see what would change without calling the API:

```bash
python src/traffic.py campaigns/example.json --dry-run
```

Ingest an Excel brief into campaign JSON:

```bash
python -m src.services.ingest my_brief.xlsx --output campaigns/output.json
```
