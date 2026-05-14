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
from mcp.types import TextContent, Tool

from src.api.meta import MetaClient
from src.reconcile import DriftType, diff_state, fetch_actuals, format_report
from src.services.ingest import extract_campaigns, format_ambiguity_report, read_excel
from src.services.state import StateFile
from src.services.validate import validate_all
from src.traffic import apply as apply_plan
from src.traffic import load_campaign_json, plan

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("adcode")

# Set once at startup by _load_stack_config via --config <stack>_template.json.
# All tool handlers read these globals instead of accepting json_path per call.
_STACK_JSON_PATH: Path | None = None
_STACK_STATE_DIR: Path | None = None
_ACCOUNT_ID: str = ""

SUPPORTED_IMPORT_RESOURCE_TYPES = {"adset"}


def _get_meta_client() -> MetaClient:
    return MetaClient(
        app_id=os.environ["FB_APP_ID"],
        app_secret=os.environ["FB_APP_SECRET"],
        access_token=os.environ["FB_ACCESS_TOKEN"],
        account_id=os.environ["FB_ACCOUNT_ID"],
    )


def _get_ai_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _require_stack_config() -> tuple[Path, Path, str]:
    if _STACK_JSON_PATH is None or _STACK_STATE_DIR is None or not _ACCOUNT_ID:
        raise ValueError(
            "MCP server not configured with a stack. "
            "Start with: python src/mcp_server.py --config <stack>_template.json"
        )
    return _STACK_JSON_PATH, _STACK_STATE_DIR, _ACCOUNT_ID


def _resolve_campaign_json() -> dict:
    json_path, _, _ = _require_stack_config()
    return load_campaign_json(str(json_path))


def _load_state(account_id: str) -> StateFile:
    _, state_dir, _ = _require_stack_config()
    return StateFile.load(account_id, stack_name="state", state_dir=state_dir)


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="show_stack",
            description=(
                "Show the active AdCode stack configuration: template path, state path, account ID, "
                "and local .env presence. Does not call Facebook or expose credential values."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="validate_stack",
            description=(
                "Validate the active stack template with JSON Schema and AI policy checks. "
                "Does not call Facebook and does not change local files."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="plan_stack",
            description=(
                "Validate the active stack and show the changeset needed to make Facebook match the template. "
                "No changes are made to Facebook or local state. Always run this before apply_stack."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="apply_stack",
            description=(
                "Apply the active stack to Facebook and update local state. Deletes require a second call "
                "with confirm_deletes=true after reviewing plan_stack output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm_deletes": {
                        "type": "boolean",
                        "description": "Set true to proceed when the plan includes deletions.",
                    },
                },
            },
        ),
        Tool(
            name="drift_stack",
            description=(
                "Compare this stack's managed state to live Facebook data. Reports missing managed objects "
                "and field mismatches only; unmanaged account objects are intentionally excluded."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="show_state",
            description=(
                "Read campaigns from this stack's state.json. Does not call Facebook. "
                "Use this to inspect tracked configuration and Facebook IDs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_name": {
                        "type": "string",
                        "description": "Optional campaign name substring filter.",
                    },
                },
            },
        ),
        Tool(
            name="search_import_candidates",
            description=(
                "Search for supported live resources that can be adopted into the active stack. "
                "Currently supports resource_type='adset' and only returns ad sets under campaigns "
                "declared in the stack template."
            ),
            inputSchema={
                "type": "object",
                "required": ["resource_type"],
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type to search. Currently only 'adset' is supported.",
                    },
                },
            },
        ),
        Tool(
            name="import_resource",
            description=(
                "Adopt a supported live resource into the active stack template and state file. "
                "Currently supports resource_type='adset'. This writes local files only and never "
                "pushes changes to Facebook."
            ),
            inputSchema={
                "type": "object",
                "required": ["resource_type"],
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type to import. Currently only 'adset' is supported.",
                    },
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional subset of resource names to import.",
                    },
                },
            },
        ),
        Tool(
            name="generate_stack_from_excel",
            description=(
                "Extract campaign JSON from an Excel brief using AI and flag ambiguities for review. "
                "Returns a starter stack template; it does not call Facebook."
            ),
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
    arguments = arguments or {}
    try:
        if name == "show_stack":
            return await _show_stack(arguments)
        if name == "validate_stack":
            return await _validate_stack(arguments)
        if name == "plan_stack":
            return await _plan_stack(arguments)
        if name == "apply_stack":
            return await _apply_stack(arguments)
        if name == "drift_stack":
            return await _drift_stack(arguments)
        if name == "show_state":
            return await _show_state(arguments)
        if name == "search_import_candidates":
            return await _search_import_candidates(arguments)
        if name == "import_resource":
            return await _import_resource(arguments)
        if name == "generate_stack_from_excel":
            return await _generate_stack_from_excel(arguments)
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return [TextContent(type="text", text=f"Error: {exc}")]


def _format_plan(p) -> str:
    lines = [f"Plan: {p.summary()}", ""]
    for op in p.operations:
        op_type = type(op).__name__
        cname = (
            getattr(op, "campaign_name", None)
            or getattr(op, "campaign", {}).get("name", "")
            or ""
        )
        aname = getattr(op, "adset_name", "")
        ad_name = getattr(op, "ad_name", "")
        fb_id = getattr(op, "fb_id", "")

        if op_type.startswith("Delete"):
            label = f"  DELETE {op_type.replace('Delete', '').lower()}"
            detail = " / ".join(filter(None, [cname, aname, ad_name]))
            lines.append(f'{label}: "{detail}"  (fb_id: {fb_id})')
        elif hasattr(op, "changed_fields"):
            lines.append(f"  {op_type}: {cname} - fields: {list(op.changed_fields.keys())}")
        else:
            lines.append(f"  {op_type}: {cname}")
    return "\n".join(lines)


async def _show_stack(args: dict) -> list[TextContent]:
    json_path, state_dir, account_id = _require_stack_config()
    data = {
        "template_path": str(json_path),
        "stack_dir": str(state_dir),
        "state_path": str(state_dir / "state.json"),
        "env_path": str(state_dir / ".env"),
        "env_exists": (state_dir / ".env").exists(),
        "account_id": account_id,
        "configured": True,
    }
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def _validate_stack(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json()
    validation = validate_all(campaign_json, _get_ai_client())
    return [TextContent(type="text", text=validation.summary())]


async def _plan_stack(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json()
    validation = validate_all(campaign_json, _get_ai_client())

    state = _load_state(campaign_json["account_id"])
    p = plan(campaign_json, state, None)

    diff_section = _format_plan(p) if len(p) > 0 else "No changes - Facebook already matches this configuration."
    return [TextContent(type="text", text="\n".join([validation.summary(), "", diff_section]))]


async def _apply_stack(args: dict) -> list[TextContent]:
    campaign_json = _resolve_campaign_json()
    validation = validate_all(campaign_json, _get_ai_client())

    if not validation.is_pushable:
        return [TextContent(type="text", text=f"Blocked by validation.\n\n{validation.summary()}")]

    meta = _get_meta_client()
    state = _load_state(campaign_json["account_id"])
    p = plan(campaign_json, state, meta)

    if len(p) == 0:
        return [TextContent(type="text", text=f"No changes detected.\n\n{validation.summary()}")]

    if p.has_deletes and not args.get("confirm_deletes"):
        message = (
            f"{validation.summary()}\n\n"
            "Plan includes deletions. Call again with confirm_deletes=true to proceed.\n\n"
            + _format_plan(p)
        )
        return [TextContent(type="text", text=message)]

    json_path, _, _ = _require_stack_config()
    result = apply_plan(
        p,
        meta,
        state,
        campaign_json=campaign_json,
        campaign_json_path=str(json_path),
    )
    return [TextContent(type="text", text="\n".join([validation.summary(), "", f"Applied: {result.summary()}"]))]


async def _show_state(args: dict) -> list[TextContent]:
    _, _, account_id = _require_stack_config()
    campaign_name_filter = args.get("campaign_name", "").lower()
    state = _load_state(account_id)

    campaigns = state.campaigns()
    if campaign_name_filter:
        campaigns = {k: v for k, v in campaigns.items() if campaign_name_filter in k.lower()}

    if not campaigns:
        return [TextContent(type="text", text="No matching campaigns found in state file.")]

    return [TextContent(type="text", text=json.dumps(campaigns, indent=2))]


async def _drift_stack(args: dict) -> list[TextContent]:
    _, _, account_id = _require_stack_config()
    meta = _get_meta_client()
    state = _load_state(account_id)
    actuals = fetch_actuals(account_id, meta)
    report = diff_state(state, actuals)
    report.items = [item for item in report.items if item.drift_type != DriftType.MISSING_FROM_STATE]
    return [TextContent(type="text", text=format_report(report))]


async def _generate_stack_from_excel(args: dict) -> list[TextContent]:
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


def _unsupported_resource_message() -> list[TextContent]:
    return [TextContent(type="text", text="Only resource_type='adset' is currently supported.")]


def _to_plain(obj):
    """Recursively convert Facebook SDK Mapping/sequence objects to plain Python types."""
    import collections.abc

    if isinstance(obj, collections.abc.Mapping):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def _find_parent_campaign(actuals: dict, adset_name: str) -> str | None:
    return next(
        (cname for cname, cdata in actuals.items() if adset_name in cdata.get("ad_sets", {})),
        None,
    )


def _candidate_adsets(state: StateFile, actuals: dict, campaign_json: dict) -> list[dict]:
    report = diff_state(state, actuals)
    declared_campaigns = {campaign["name"] for campaign in campaign_json.get("campaigns", [])}
    candidates: list[dict] = []

    for item in report.items:
        if item.drift_type != DriftType.MISSING_FROM_STATE or item.object_type != "adset":
            continue

        parent = _find_parent_campaign(actuals, item.name)
        if parent is None or parent not in declared_campaigns:
            continue

        live = actuals[parent]["ad_sets"][item.name]
        candidates.append(
            {
                "resource_type": "adset",
                "name": item.name,
                "parent_campaign": parent,
                "fb_id": item.fb_id,
                "status": live.get("status"),
            }
        )

    return candidates


async def _search_import_candidates(args: dict) -> list[TextContent]:
    if args.get("resource_type") not in SUPPORTED_IMPORT_RESOURCE_TYPES:
        return _unsupported_resource_message()

    campaign_json = _resolve_campaign_json()
    meta = _get_meta_client()
    state = _load_state(campaign_json["account_id"])
    actuals = fetch_actuals(campaign_json["account_id"], meta)
    candidates = _candidate_adsets(state, actuals, campaign_json)

    result = {
        "resource_type": "adset",
        "count": len(candidates),
        "candidates": candidates,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _import_resource(args: dict) -> list[TextContent]:
    if args.get("resource_type") not in SUPPORTED_IMPORT_RESOURCE_TYPES:
        return _unsupported_resource_message()

    json_path, _, account_id = _require_stack_config()
    name_filter = set(args["names"]) if args.get("names") else None

    meta = _get_meta_client()
    state = _load_state(account_id)
    actuals = fetch_actuals(account_id, meta)
    campaign_json = load_campaign_json(str(json_path))
    candidates = _candidate_adsets(state, actuals, campaign_json)
    if name_filter:
        candidates = [candidate for candidate in candidates if candidate["name"] in name_filter]

    if not candidates:
        return [TextContent(type="text", text="No supported untracked resources found - nothing to import.")]

    campaigns_by_name = {campaign["name"]: i for i, campaign in enumerate(campaign_json["campaigns"])}
    imported = []

    for candidate in candidates:
        parent = candidate["parent_campaign"]
        live = actuals[parent]["ad_sets"][candidate["name"]]
        adset_entry: dict = {"name": candidate["name"], "status": live.get("status", "PAUSED"), "ads": []}

        for field in (
            "daily_budget",
            "lifetime_budget",
            "billing_event",
            "optimization_goal",
            "bid_strategy",
            "bid_amount",
            "start_time",
            "end_time",
            "targeting",
        ):
            if live.get(field) is None:
                continue

            value = _to_plain(live[field])
            if field in ("daily_budget", "lifetime_budget", "bid_amount") and value != "":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    pass
            if field in ("daily_budget", "lifetime_budget") and value == 0:
                continue
            adset_entry[field] = value

        campaign_idx = campaigns_by_name[parent]
        campaign_json["campaigns"][campaign_idx].setdefault("ad_sets", [])
        campaign_json["campaigns"][campaign_idx]["ad_sets"].append(adset_entry)

        params = {key: value for key, value in adset_entry.items() if key != "ads"}
        state.upsert_adset(parent, candidate["name"], candidate["fb_id"], params)
        imported.append(f'{parent} / {candidate["name"]}  (fb_id: {candidate["fb_id"]})')

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(campaign_json, fh, indent=2, ensure_ascii=False)
    state.save()

    lines = [f"Imported {len(imported)} resource(s) into {json_path.name} and state:"]
    lines.extend(f"  + {entry}" for entry in imported)
    lines.extend(["", "Run plan_stack to verify no spurious changes before committing."])
    return [TextContent(type="text", text="\n".join(lines))]


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def _load_stack_config(template_path: str) -> None:
    """Configure the server from a stack template file.

    Loads .env from the stack directory, reads account_id from the template JSON,
    and sets module-level globals used by all tool handlers.
    """
    global _STACK_JSON_PATH, _STACK_STATE_DIR, _ACCOUNT_ID
    path = Path(template_path).resolve()
    stack_dir = path.parent

    env_path = stack_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger.info("Loaded stack .env: %s", env_path)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    _STACK_JSON_PATH = path
    _STACK_STATE_DIR = stack_dir
    _ACCOUNT_ID = data["account_id"]
    os.environ["FB_ACCOUNT_ID"] = _ACCOUNT_ID
    logger.info("Loaded stack config: template=%s account=%s", path.name, _ACCOUNT_ID)


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    import asyncio

    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            _load_stack_config(sys.argv[idx + 1])
    else:
        logger.warning(
            "No --config provided. Credentials must be set in environment variables. "
            "Run with --config customers/<slug>/<stack>/<stack>_template.json"
        )

    asyncio.run(_main())


if __name__ == "__main__":
    main()
