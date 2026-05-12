import json
import logging
import os
import sys
from pathlib import Path

# Running `python src/mcp_server.py` puts `src/` on sys.path, not the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import anthropic
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.api.meta import MetaClient
from src.services.state import StateFile
from src.services.validate import validate_all
from src.services.ingest import read_excel, extract_campaigns, format_ambiguity_report
from src.traffic import load_campaign_json, plan, apply as apply_plan, DeleteCampaign, DeleteAdSet, DeleteAd
from src.reconcile import fetch_actuals, diff_state, format_report

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("adcode")


def _get_meta_client() -> MetaClient:
    return MetaClient(
        app_id=os.environ["FB_APP_ID"],
        app_secret=os.environ["FB_APP_SECRET"],
        access_token=os.environ["FB_ACCESS_TOKEN"],
        account_id=os.environ["FB_ACCOUNT_ID"],
    )


def _get_ai_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _resolve_campaign_json(json_path: str | None, json_str: str | None) -> dict:
    if json_path:
        return load_campaign_json(json_path)
    if json_str:
        import jsonschema
        data = json.loads(json_str)
        from src.traffic import _CAMPAIGN_SCHEMA
        jsonschema.validate(data, _CAMPAIGN_SCHEMA)
        return data
    raise ValueError("Provide either json_path or json_str.")


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="push_campaigns",
            description=(
                "Validate, diff, and apply a campaign JSON file to Facebook. "
                "Creates, updates, AND deletes objects so Facebook matches the file exactly. "
                "If the plan includes deletions, returns the plan and requires confirm_deletes=true to proceed. "
                "Aborts if validation produces blocking errors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "json_path": {"type": "string", "description": "Path to campaign JSON file in the repo."},
                    "json_str": {"type": "string", "description": "Inline campaign JSON string."},
                    "confirm_deletes": {"type": "boolean", "description": "Set true to apply a plan that includes deletions."},
                },
            },
        ),
        Tool(
            name="pause_campaigns",
            description="Pause campaigns matching a name or account filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "account_id": {"type": "string"},
                    "campaign_id": {"type": "string"},
                },
            },
        ),
        Tool(
            name="get_campaign_json",
            description="Return raw state file JSON for one or more campaigns. Read-only; never calls the Facebook API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "Filter by campaign name (substring match)."},
                    "account_id": {"type": "string", "description": "Limit to a specific ad account."},
                },
            },
        ),
        Tool(
            name="get_campaign_status",
            description="Fetch live status from Facebook for a single campaign.",
            inputSchema={
                "type": "object",
                "required": ["campaign_id"],
                "properties": {
                    "campaign_id": {"type": "string"},
                },
            },
        ),
        Tool(
            name="get_drift_report",
            description="Diff the state file against Facebook actuals and report any divergence.",
            inputSchema={
                "type": "object",
                "required": ["account_id"],
                "properties": {
                    "account_id": {"type": "string"},
                },
            },
        ),
        Tool(
            name="validate_campaigns",
            description="Run schema and AI policy validation without pushing. Returns a structured report.",
            inputSchema={
                "type": "object",
                "properties": {
                    "json_path": {"type": "string"},
                    "json_str": {"type": "string"},
                },
            },
        ),
        Tool(
            name="preview_diff",
            description="Show the full changeset (creates, updates, and deletes) without making any changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "json_path": {"type": "string"},
                    "json_str": {"type": "string"},
                },
            },
        ),
        Tool(
            name="ingest_excel",
            description="Extract campaign JSON from an Excel file using AI. Returns extracted campaigns and a list of ambiguities for human review.",
            inputSchema={
                "type": "object",
                "required": ["excel_path"],
                "properties": {
                    "excel_path": {"type": "string"},
                },
            },
        ),
    ]


# ------------------------------------------------------------------
# Tool handlers
# ------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "push_campaigns":
            return await _push_campaigns(arguments)
        elif name == "pause_campaigns":
            return await _pause_campaigns(arguments)
        elif name == "get_campaign_json":
            return await _get_campaign_json(arguments)
        elif name == "get_campaign_status":
            return await _get_campaign_status(arguments)
        elif name == "get_drift_report":
            return await _get_drift_report(arguments)
        elif name == "validate_campaigns":
            return await _validate_campaigns(arguments)
        elif name == "preview_diff":
            return await _preview_diff(arguments)
        elif name == "ingest_excel":
            return await _ingest_excel(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return [TextContent(type="text", text=f"Error: {e}")]


def _format_plan(p) -> str:
    lines = [f"Plan: {p.summary()}", ""]
    for op in p.operations:
        op_type = type(op).__name__
        cname = (getattr(op, "campaign_name", None)
                 or getattr(op, "campaign", {}).get("name", "") or "")
        aname = getattr(op, "adset_name", "")
        ad_name = getattr(op, "ad_name", "")
        fb_id = getattr(op, "fb_id", "")

        if op_type.startswith("Delete"):
            label = f"  DELETE {op_type.replace('Delete', '').lower()}"
            detail = " / ".join(filter(None, [cname, aname, ad_name]))
            lines.append(f"{label}: \"{detail}\"  (fb_id: {fb_id})")
        elif hasattr(op, "changed_fields"):
            lines.append(f"  {op_type}: {cname} — fields: {list(op.changed_fields.keys())}")
        else:
            lines.append(f"  {op_type}: {cname}")
    return "\n".join(lines)


async def _push_campaigns(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json(args.get("json_path"), args.get("json_str"))
    ai_client = _get_ai_client()
    validation = validate_all(campaign_json, ai_client)

    if not validation.is_pushable:
        return [TextContent(type="text", text=f"Push blocked by validation.\n\n{validation.summary()}")]

    meta = _get_meta_client()
    account_id = campaign_json["account_id"]
    state = StateFile.load(account_id)
    p = plan(campaign_json, state, meta)

    if len(p) == 0:
        return [TextContent(type="text", text=f"No changes detected.\n\n{validation.summary()}")]

    if p.has_deletes and not args.get("confirm_deletes"):
        msg = (
            f"{validation.summary()}\n\n"
            "Plan includes deletions. Call again with confirm_deletes=true to proceed.\n\n"
            + _format_plan(p)
        )
        return [TextContent(type="text", text=msg)]

    result = apply_plan(p, meta, state)
    lines = [validation.summary(), "", f"Push complete: {result.summary()}"]
    return [TextContent(type="text", text="\n".join(lines))]


async def _pause_campaigns(args: dict) -> list[TextContent]:
    meta = _get_meta_client()
    account_id = args.get("account_id", os.environ.get("FB_ACCOUNT_ID", ""))
    state = StateFile.load(account_id)

    paused = []
    campaign_name = args.get("campaign_name")
    campaign_id_filter = args.get("campaign_id")

    for cname, cdata in state.campaigns().items():
        if campaign_name and campaign_name.lower() not in cname.lower():
            continue
        fb_id = cdata.get("fb_id")
        if campaign_id_filter and fb_id != campaign_id_filter:
            continue
        if fb_id:
            meta.pause_campaign(fb_id)
            state.upsert_campaign(cname, fb_id, {**cdata.get("params", {}), "status": "PAUSED"})
            paused.append(f"{cname} ({fb_id})")

    if paused:
        state.save()
        return [TextContent(type="text", text="Paused:\n" + "\n".join(f"  - {p}" for p in paused))]
    return [TextContent(type="text", text="No matching campaigns found.")]


async def _get_campaign_json(args: dict) -> list[TextContent]:
    account_id = args.get("account_id", os.environ.get("FB_ACCOUNT_ID", ""))
    campaign_name_filter = args.get("campaign_name", "").lower()
    state = StateFile.load(account_id)

    campaigns = state.campaigns()
    if campaign_name_filter:
        campaigns = {k: v for k, v in campaigns.items() if campaign_name_filter in k.lower()}

    if not campaigns:
        return [TextContent(type="text", text="No matching campaigns found in state file.")]

    return [TextContent(type="text", text=json.dumps(campaigns, indent=2))]


async def _get_campaign_status(args: dict) -> list[TextContent]:
    meta = _get_meta_client()
    campaign_id = args["campaign_id"]
    data = meta.get_campaign(campaign_id)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def _get_drift_report(args: dict) -> list[TextContent]:
    account_id = args["account_id"]
    meta = _get_meta_client()
    state = StateFile.load(account_id)
    actuals = fetch_actuals(account_id, meta)
    report = diff_state(state, actuals)
    return [TextContent(type="text", text=format_report(report))]


async def _validate_campaigns(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json(args.get("json_path"), args.get("json_str"))
    ai_client = _get_ai_client()
    result = validate_all(campaign_json, ai_client)
    return [TextContent(type="text", text=result.summary())]


async def _preview_diff(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json(args.get("json_path"), args.get("json_str"))
    meta = _get_meta_client()
    account_id = campaign_json["account_id"]
    state = StateFile.load(account_id)
    p = plan(campaign_json, state, meta)

    if len(p) == 0:
        return [TextContent(type="text", text="No changes. State matches desired configuration.")]

    return [TextContent(type="text", text=_format_plan(p))]


async def _ingest_excel(args: dict) -> list[TextContent]:
    excel_path = args["excel_path"]
    ai_client = _get_ai_client()
    excel_data = read_excel(excel_path)
    result = extract_campaigns(excel_data, ai_client)
    report = format_ambiguity_report(result)

    output = {
        "account_id": "act_000000000",
        "campaigns": result.campaigns,
    }
    lines = [report, "", "Extracted campaign JSON:", json.dumps(output, indent=2)]
    return [TextContent(type="text", text="\n".join(lines))]


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
