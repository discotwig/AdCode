# AdCode

Infrastructure-as-code for ad campaign trafficking. Campaign definitions live as JSON in this repository. A script reads the JSON, calls the Facebook Marketing API, and writes a state file with returned IDs back to the repo.

Git history is the audit trail. Pull requests are the review mechanism. No one needs to log into Facebook Ads Manager for routine trafficking or QA.

## How it works

1. Define campaigns in `campaigns/<account>.json` using the schema in `schemas/campaign.schema.json`
2. Run `preview_diff` to see what will change before any API call is made
3. Run `push_campaigns` to apply — the engine creates or updates campaigns and writes `state/<account>.json`
4. Run `get_drift_report` to verify actuals match state after any manual changes

The core scripts are exposed as MCP tools. Connect your model (Gemini, Claude, etc.) to the MCP server and interact via natural language.

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd AdCode
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in FB_APP_ID, FB_APP_SECRET, FB_ACCESS_TOKEN, FB_ACCOUNT_ID, ANTHROPIC_API_KEY
```

Facebook credentials: create a System User in your Meta Business Manager, grant it access to the ad account, and generate a token with `ads_management` permission.

### 3. Start the MCP server

```bash
python src/mcp_server.py
```

Point your MCP-compatible model at the server. The tool surface is described below.

## MCP Tools

| Tool | Description |
| --- | --- |
| `push_campaigns(json_path)` | Validate, diff, and apply a campaign JSON file to Facebook |
| `pause_campaigns(filter)` | Pause campaigns matching a name or account filter |
| `get_campaign_json(filter?)` | Return raw state file JSON for inspection — read-only, no API calls |
| `get_campaign_status(campaign_id)` | Fetch live status from Facebook for a single campaign |
| `get_drift_report(account_id)` | Diff state file against Facebook actuals; report any divergence |
| `validate_campaigns(json_path)` | Run schema + AI policy validation without pushing |
| `preview_diff(json_path)` | Show what `push_campaigns` would do without making any changes |

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

## Excel ingestion

If you have an Excel brief, use the `validate_campaigns` tool with an Excel path and the AI will extract campaign definitions against the schema, flag ambiguities, and return JSON ready for review. Commit the JSON after reviewing ambiguities — do not re-ingest from Excel after the JSON is committed.

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

```bash
pytest tests/
```

Integration tests require a live Facebook sandbox account and are skipped when credentials are absent:

```bash
FB_APP_ID=... FB_APP_SECRET=... FB_ACCESS_TOKEN=... FB_ACCOUNT_ID=... pytest tests/test_integration.py -v
```
