"""Guided local workspace setup; never accepts or returns credential values."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

# Cursor need not launch from the installed source directory.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.services.workspace import (
    create_workspace, start_workspace, list_workspaces, check_workspace, open_workspace,
)


def create_server(root: Path) -> Server:
    """Bind host-owned root configuration, never a per-tool arbitrary path."""
    app = Server("adcode-bootstrap", instructions=(
        "Help people prepare campaigns in ordinary, nontechnical language. Ask for their customer "
        "name and optionally a workspace name (default Campaigns), never account IDs or secrets. "
        "Create the workspace, offer to open it in Cursor, and point them to edit .env privately. "
        "Never use filesystem or terminal tools to read .env or ask for its contents in chat. Use check_workspace for safe statuses and, "
        "when settings are entered, ask what they are promoting, their budget and dates. "
        "Do not discuss roots, slugs or MCP setup unless asked. Prepared or launched is not "
        "connected: local checks never verify provider connections. Preserve Cursor permissions "
        "and approval prompts; never change access mode or infer approval for spending."
    ))

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        display = {"type": "string", "minLength": 1, "maxLength": 160}
        return [
            Tool(
                name="create_workspace",
                description=("Prepare a private campaign draft using friendly names. "
                             "Enter keys privately in the returned .env file, never in chat."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "customer_name": dict(display),
                        "workspace_name": {**display, "default": "Campaigns"},
                    },
                    "required": ["customer_name"],
                    "additionalProperties": False,
                },
            ),
            Tool(
                name="list_workspaces",
                description="List non-secret local workspace paths. Does not read credentials or contact providers.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            *[Tool(name=name, description=description, inputSchema={
                "type": "object", "properties": {"workspace_id": {"type": "string"}},
                "required": ["workspace_id"], "additionalProperties": False,
            }) for name, description in (
                ("check_workspace", "Check private local settings and finish a new draft's account binding. Never contacts providers or returns key values."),
                ("open_workspace", "Ask Cursor to open a known workspace. Does not verify any connection."),
            )],
        ]

    # SDK schema errors can echo supplied values. Validate here with safe messages.
    @app.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        # Validate dispatch independently of clients' schema validation. In particular,
        # never echo rejected inputs, which might accidentally contain a secret.
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object.")
            if name == "create_workspace":
                if set(arguments) == {"customer", "stack_name", "account_id"}:
                    result = create_workspace(root, **arguments)  # Unadvertised legacy compatibility.
                elif ("customer_name" in arguments
                      and set(arguments) <= {"customer_name", "workspace_name"}):
                    result = start_workspace(root, **arguments)
                else:
                    raise ValueError("Use a customer name and optional workspace name only.")
            elif name == "list_workspaces":
                if arguments:
                    raise ValueError("list_workspaces accepts no arguments.")
                result = {"workspaces": list_workspaces(root)}
            elif name in {"check_workspace", "open_workspace"}:
                if set(arguments) != {"workspace_id"}:
                    raise ValueError("Choose a workspace from the workspace list.")
                operation = check_workspace if name == "check_workspace" else open_workspace
                result = operation(root, arguments["workspace_id"])
            else:
                raise ValueError("Unknown bootstrap tool.")
        except Exception:
            result = {"error": "Local workspace operation failed. Check directory permissions and installation paths."}
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return app


async def _serve(app: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "AdCode Workspaces",
                        help="Local workspace root (host configuration, never a tool argument).")
    args = parser.parse_args(argv)
    asyncio.run(_serve(create_server(args.root)))


if __name__ == "__main__":
    main()
