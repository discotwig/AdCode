import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from src import bootstrap_server


@pytest.mark.asyncio
async def test_bootstrap_schemas_and_real_dispatch(tmp_path):
    root = tmp_path.resolve() / "Documents ü with spaces" / "AdCode"
    app = bootstrap_server.create_server(root)
    async with create_connected_server_and_client_session(app) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {"create_workspace", "list_workspaces", "check_workspace", "open_workspace"}
        schemas = {tool.name: tool.inputSchema for tool in tools}
        create_schema = schemas["create_workspace"]
        assert create_schema["additionalProperties"] is False
        assert set(create_schema["properties"]) == {"customer_name", "workspace_name"}
        assert create_schema["required"] == ["customer_name"]
        for name in ("check_workspace", "open_workspace"):
            assert set(schemas[name]["properties"]) == {"workspace_id"}
            assert schemas[name]["additionalProperties"] is False
        assert schemas["list_workspaces"]["properties"] == {}
        assert schemas["list_workspaces"]["additionalProperties"] is False
        listing = await client.call_tool("list_workspaces", {})
        assert json.loads(listing.content[0].text) == {"workspaces": []}
        assert not root.exists()
        response = await client.call_tool("create_workspace", {
            "customer": "acme", "stack_name": "spring", "account_id": "act_123",
        })
        assert not response.isError
        created = json.loads(response.content[0].text)
        assert Path(created["workspace"]) == root / "acme" / "spring"
        assert Path(created["template"]).is_file()
        assert "Cursor" in created["next_steps"][0]
        assert "Configure AdCode.command" in created["next_steps"][1]
        listing = await client.call_tool("list_workspaces", {})
        assert json.loads(listing.content[0].text)["workspaces"] == [
            {k: v for k, v in created.items() if k != "next_steps"}
        ]
        duplicate = await client.call_tool("create_workspace", {
            "customer": "acme", "stack_name": "spring", "account_id": "act_123",
        })
        assert "error" in json.loads(duplicate.content[0].text)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("create_workspace", {"customer": "../escape", "stack_name": "stack", "account_id": "act_1"}),
    ("create_workspace", {"customer": "acme", "stack_name": "stack", "account_id": "act_1",
                          "root": "/tmp/arbitrary"}),
    ("create_workspace", {"customer": "acme", "stack_name": "stack", "account_id": "act_1",
                          "access_token": "do-not-echo-this-secret"}),
    ("create_workspace", {"customer": "acme"}),
    ("list_workspaces", {"root": "/tmp/arbitrary"}),
    ("list_workspaces", {"secret": "do-not-echo-this-secret"}),
    ("apply_stack", {}),
])
async def test_reject_invalid_inputs(tmp_path, name, args):
    root = tmp_path.resolve() / "root"
    async with create_connected_server_and_client_session(bootstrap_server.create_server(root)) as client:
        response = await client.call_tool(name, args)
        text = response.content[0].text
        assert "error" in text.lower() or response.isError
        # Dispatch validates keys itself and never interpolates supplied values.
        assert "do-not-echo-this-secret" not in text
    assert not root.exists()


def test_import_is_provider_and_credential_free():
    source = Path(__file__).resolve().parents[1]
    # Fresh process so prior test collection cannot hide an accidental import.
    code = """
import builtins
import sys
import dotenv
import dotenv.main
# MCP transitively imports pydantic-settings/dotenv; importing the library is
# harmless, but actually discovering or loading any .env is forbidden.
def no_credentials(*args, **kwargs):
    raise AssertionError('Attempted credential loading')
for module in (dotenv, dotenv.main):
    for name in ('load_dotenv', 'dotenv_values', 'find_dotenv'):
        setattr(module, name, no_credentials)
blocked = ('anthropic', 'facebook_business', 'src.api', 'src.mcp_server', 'src.local_setup')
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + '.') for prefix in blocked):
        raise AssertionError('Provider or credential module imported: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import src.bootstrap_server
assert not any(name in sys.modules for name in blocked)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=source,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_main_root_override_and_default(tmp_path):
    captured = []

    async def serve(app):
        captured.append(app)

    root = tmp_path.resolve() / "override"
    with patch.object(bootstrap_server, "_serve", serve), patch.object(bootstrap_server, "create_server") as factory:
        bootstrap_server.main(["--root", str(root)])
        factory.assert_called_once_with(root)
        assert captured == [factory.return_value]
    with patch.object(bootstrap_server, "_serve", serve), patch.object(bootstrap_server, "create_server") as factory:
        bootstrap_server.main([])
        factory.assert_called_once_with(Path.home() / "AdCode Workspaces")
    assert not root.exists()


@pytest.mark.asyncio
async def test_dispatch_rejects_extras_without_sdk_schema_validation(tmp_path):
    # The Server wrapper allows disabling schema validation, proving the handler
    # itself rejects injected arbitrary paths and credential arguments.
    from mcp.types import CallToolRequest, CallToolRequestParams

    app = bootstrap_server.create_server(tmp_path.resolve() / "root")
    handler = app.request_handlers[CallToolRequest]
    request = CallToolRequest(method="tools/call", params=CallToolRequestParams(
        name="list_workspaces", arguments={"root": "do-not-echo-this-secret"}))
    response = await handler(request)
    text = response.root.content[0].text
    assert "error" in json.loads(text)
    assert "do-not-echo-this-secret" not in text


@pytest.mark.asyncio
async def test_guided_mcp_flow_and_private_rejections(tmp_path):
    root = tmp_path.resolve() / 'Workspace with spaces'
    app = bootstrap_server.create_server(root)
    async with create_connected_server_and_client_session(app) as client:
        response = await client.call_tool('create_workspace', {'customer_name': 'Friendly Company'})
        created = json.loads(response.content[0].text)
        assert created['workspace_id'] == 'friendly-company/campaigns'
        assert created['workspace_name'] == 'Campaigns'
        assert created['schema_version'] == 2
        assert not created['provider_connection_verified']
        listing = await client.call_tool('list_workspaces', {})
        assert json.loads(listing.content[0].text)['workspaces'] == [created]
        args = {'workspace_id': created['workspace_id']}
        checked = await client.call_tool('check_workspace', args)
        data = json.loads(checked.content[0].text)
        assert data['status'] == 'needs_settings'
        assert data['campaign_status'] == 'brief_incomplete'
        assert not data['credentials_entered']
        with patch('src.services.workspace.subprocess.run') as launch, patch('src.services.workspace.sys.platform', 'darwin'):
            opened = await client.call_tool('open_workspace', args)
            assert json.loads(opened.content[0].text)['launch_requested']
            launch.assert_called_once()
        rejected = await client.call_tool('create_workspace', {
            'customer_name': 'Another Company', 'FB_ACCESS_TOKEN': 'never-echo-this-value'})
        assert 'error' in json.loads(rejected.content[0].text)
        assert 'never-echo-this-value' not in rejected.content[0].text
        rejected = await client.call_tool('check_workspace', {'workspace_id': '../never-echo-this-value'})
        assert 'error' in json.loads(rejected.content[0].text)
        assert 'never-echo-this-value' not in rejected.content[0].text
