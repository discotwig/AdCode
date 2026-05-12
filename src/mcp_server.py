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
from src.reconcile import fetch_actuals, diff_state, format_report, DriftType

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
            name="apply_campaigns",
            description=(
                "Apply a campaign JSON file to Facebook — creates, updates, and deletes objects "
                "so Facebook matches the file exactly. "
                "Run plan_campaigns first to review what will change. "
                "Blocked if validation finds errors. "
                "If the plan includes deletions, returns the plan and waits for confirm_deletes=true "
                "before proceeding — call again with that flag set to confirm."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "json_path": {"type": "string", "description": "Path to campaign JSON file in the repo."},
                    "json_str": {"type": "string", "description": "Inline campaign JSON string."},
                    "confirm_deletes": {"type": "boolean", "description": "Set true to proceed when the plan includes deletions."},
                },
            },
        ),
        Tool(
            name="pause_campaigns",
            description=(
                "Pause campaigns on Facebook matching a name or ID filter. "
                "Queries Facebook directly for the current campaign list — "
                "works even for campaigns not tracked in the local state file. "
                "Already-paused campaigns are reported but not re-paused."
            ),
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
            name="get_local_state",
            description=(
                "Read campaigns from the local state file (cache). "
                "Never calls the Facebook API — returns what AdCode last recorded after a push. "
                "Use this to inspect tracked configuration or fb_ids. "
                "Do NOT use this to answer questions about what currently exists on Facebook; "
                "use list_campaigns for that."
            ),
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
            description=(
                "Fetch live fields for a single campaign directly from Facebook by ID. "
                "Returns status, effective_status, objective, and budget fields. "
                "Use list_campaigns first if you don't already have the campaign ID."
            ),
            inputSchema={
                "type": "object",
                "required": ["campaign_id"],
                "properties": {
                    "campaign_id": {"type": "string", "description": "Facebook campaign ID (e.g. 120244515578050719)."},
                },
            },
        ),
        Tool(
            name="get_drift_report",
            description=(
                "Compare the local state file to live Facebook data and report any divergence. "
                "Detects: objects in state that no longer exist on Facebook (deleted externally), "
                "objects on Facebook not tracked in state (created outside AdCode), "
                "and field mismatches (edited manually in Ads Manager). "
                "Does not make any changes — read-only."
            ),
            inputSchema={
                "type": "object",
                "required": ["account_id"],
                "properties": {
                    "account_id": {"type": "string", "description": "Ad account ID (e.g. act_366643171197739)."},
                },
            },
        ),
        Tool(
            name="plan_campaigns",
            description=(
                "Validate a campaign JSON file and show the full changeset that apply_campaigns would execute — "
                "no changes are made to Facebook. "
                "Returns schema and AI policy validation results plus a diff of creates, updates, and deletes. "
                "Always run this before apply_campaigns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "json_path": {"type": "string", "description": "Path to campaign JSON file in the repo."},
                    "json_str": {"type": "string", "description": "Inline campaign JSON string."},
                },
            },
        ),
        Tool(
            name="list_campaigns",
            description=(
                "Fetch all campaigns directly from Facebook for a given ad account. "
                "Always calls the live Facebook API — never reads from the local state file. "
                "Use this to see what actually exists on Facebook, including campaigns that "
                "were created outside of AdCode or are not tracked in state. "
                "Returns id, name, objective, status, and effective_status for each campaign."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "Ad account ID (e.g. act_123). Defaults to FB_ACCOUNT_ID env var."},
                },
            },
        ),
        Tool(
            name="ingest_excel",
            description=(
                "Extract campaign JSON from an Excel brief using AI. "
                "Reads all sheets, maps rows to the campaign JSON schema, and flags anything ambiguous for human review. "
                "Returns extracted campaign JSON plus an ambiguity report. "
                "Commit the resulting JSON after reviewing — do not re-ingest from Excel once the JSON is committed."
            ),
            inputSchema={
                "type": "object",
                "required": ["excel_path"],
                "properties": {
                    "excel_path": {"type": "string"},
                },
            },
        ),
        Tool(
            name="import_adsets",
            description=(
                "Adopt ad sets that exist on Facebook but are not tracked in the AdCode state file "
                "(MISSING_FROM_STATE items from get_drift_report). "
                "Fetches each ad set's live configuration from Facebook, merges it into the campaign JSON file, "
                "and registers it in the state file so plan_campaigns treats it as already managed. "
                "Does not push any changes to Facebook — read-then-write to local files only. "
                "Run plan_campaigns after importing to confirm no spurious changes before committing."
            ),
            inputSchema={
                "type": "object",
                "required": ["account_id", "json_path"],
                "properties": {
                    "account_id": {"type": "string", "description": "Ad account ID (e.g. act_366643171197739)."},
                    "json_path": {"type": "string", "description": "Path to the campaign JSON file to update."},
                    "adset_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Subset of ad set names to import. Imports all MISSING_FROM_STATE ad sets if omitted.",
                    },
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
        if name == "apply_campaigns":
            return await _apply_campaigns(arguments)
        elif name == "plan_campaigns":
            return await _plan_campaigns(arguments)
        elif name == "pause_campaigns":
            return await _pause_campaigns(arguments)
        elif name == "get_local_state":
            return await _get_local_state(arguments)
        elif name == "get_campaign_status":
            return await _get_campaign_status(arguments)
        elif name == "get_drift_report":
            return await _get_drift_report(arguments)
        elif name == "list_campaigns":
            return await _list_campaigns(arguments)
        elif name == "ingest_excel":
            return await _ingest_excel(arguments)
        elif name == "import_adsets":
            return await _import_adsets(arguments)
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


async def _plan_campaigns(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json(args.get("json_path"), args.get("json_str"))
    ai_client = _get_ai_client()
    validation = validate_all(campaign_json, ai_client)

    meta = _get_meta_client()
    account_id = campaign_json["account_id"]
    state = StateFile.load(account_id)
    p = plan(campaign_json, state, meta)

    diff_section = _format_plan(p) if len(p) > 0 else "No changes — Facebook already matches this configuration."
    lines = [validation.summary(), "", diff_section]
    return [TextContent(type="text", text="\n".join(lines))]


async def _apply_campaigns(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json(args.get("json_path"), args.get("json_str"))
    ai_client = _get_ai_client()
    validation = validate_all(campaign_json, ai_client)

    if not validation.is_pushable:
        return [TextContent(type="text", text=f"Blocked by validation.\n\n{validation.summary()}")]

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
    lines = [validation.summary(), "", f"Applied: {result.summary()}"]
    return [TextContent(type="text", text="\n".join(lines))]


async def _pause_campaigns(args: dict) -> list[TextContent]:
    meta = _get_meta_client()
    account_id = args.get("account_id", os.environ.get("FB_ACCOUNT_ID", ""))
    campaign_name = args.get("campaign_name")
    campaign_id_filter = args.get("campaign_id")

    live_campaigns = meta.list_campaigns(account_id)

    paused = []
    state = StateFile.load(account_id)

    for c in live_campaigns:
        fb_id = c["id"]
        cname = c["name"]
        if campaign_name and campaign_name.lower() not in cname.lower():
            continue
        if campaign_id_filter and fb_id != campaign_id_filter:
            continue
        if c.get("status") == "PAUSED":
            paused.append(f"{cname} ({fb_id}) — already paused")
            continue
        meta.pause_campaign(fb_id)
        state.upsert_campaign(cname, fb_id, {**c, "status": "PAUSED"})
        paused.append(f"{cname} ({fb_id})")

    if paused:
        state.save()
        return [TextContent(type="text", text="Paused:\n" + "\n".join(f"  - {p}" for p in paused))]
    return [TextContent(type="text", text="No matching campaigns found.")]


async def _get_local_state(args: dict) -> list[TextContent]:
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




async def _list_campaigns(args: dict) -> list[TextContent]:
    meta = _get_meta_client()
    account_id = args.get("account_id") or os.environ.get("FB_ACCOUNT_ID", "")
    campaigns = meta.list_campaigns(account_id)
    return [TextContent(type="text", text=json.dumps(campaigns, indent=2))]


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


def _to_plain(obj):
    """Recursively convert Facebook SDK Mapping/sequence objects to plain Python types."""
    import collections.abc
    if isinstance(obj, collections.abc.Mapping):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


async def _import_adsets(args: dict) -> list[TextContent]:
    account_id = args["account_id"]
    json_path = args["json_path"]
    name_filter = set(args["adset_names"]) if args.get("adset_names") else None

    meta = _get_meta_client()
    state = StateFile.load(account_id)
    actuals = fetch_actuals(account_id, meta)
    report = diff_state(state, actuals)

    candidates = [
        item for item in report.items
        if item.drift_type == DriftType.MISSING_FROM_STATE and item.object_type == "adset"
    ]
    if name_filter:
        candidates = [a for a in candidates if a.name in name_filter]

    if not candidates:
        return [TextContent(type="text", text="No untracked ad sets found — nothing to import.")]

    campaign_json = load_campaign_json(json_path)
    campaigns_by_name = {c["name"]: i for i, c in enumerate(campaign_json["campaigns"])}

    imported, skipped = [], []
    for item in candidates:
        parent = next(
            (cname for cname, cdata in actuals.items() if item.name in cdata.get("ad_sets", {})),
            None,
        )
        if parent is None or parent not in campaigns_by_name:
            skipped.append(item.name)
            continue

        live = actuals[parent]["ad_sets"][item.name]
        adset_entry: dict = {"name": item.name, "status": live.get("status", "PAUSED"), "ads": []}
        for field in ("daily_budget", "lifetime_budget", "billing_event", "optimization_goal",
                      "bid_strategy", "bid_amount", "start_time", "end_time", "targeting"):
            if live.get(field) is None:
                continue
            val = _to_plain(live[field])
            if field in ("daily_budget", "lifetime_budget", "bid_amount") and val != "":
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    pass
            if field in ("daily_budget", "lifetime_budget") and val == 0:
                continue
            adset_entry[field] = val

        idx = campaigns_by_name[parent]
        campaign_json["campaigns"][idx].setdefault("ad_sets", [])
        campaign_json["campaigns"][idx]["ad_sets"].append(adset_entry)

        params = {k: v for k, v in adset_entry.items() if k != "ads"}
        state.upsert_adset(parent, item.name, item.fb_id, params)
        imported.append(f"{parent} / {item.name}  (fb_id: {item.fb_id})")

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(campaign_json, fh, indent=2, ensure_ascii=False)
    state.save()

    lines = [f"Imported {len(imported)} ad set(s) into {Path(json_path).name} and state:"]
    for entry in imported:
        lines.append(f"  + {entry}")
    if skipped:
        lines.extend(["", "Skipped (parent campaign not in JSON):"])
        for s in skipped:
            lines.append(f"  - {s}")
    lines.extend(["", "Run plan_campaigns to verify no spurious changes before committing."])
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
