"""End-to-end local bootstrap/project MCP handshake with no provider calls."""
import json
from pathlib import Path
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_bootstrap_creates_a_working_restricted_project_mcp(tmp_path):
    root = tmp_path / "Private Workspaces"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "src/bootstrap_server.py"), "--root", str(root)],
        cwd=str(tmp_path),
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {"create_workspace", "list_workspaces", "check_workspace", "open_workspace"}
            result = await session.call_tool("create_workspace", {
                "customer": "example", "stack_name": "trial", "account_id": "act_000000000",
            })
            assert not result.isError
            workspace = Path(json.loads(result.content[0].text)["workspace"])
            listed = await session.call_tool("list_workspaces", {})
            assert len(json.loads(listed.content[0].text)["workspaces"]) == 1
    assert not (workspace / ".env").exists()
    assert not (workspace / "state.json").exists()
    config = json.loads((workspace / ".cursor/mcp.json").read_text())["mcpServers"]["adcode"]
    assert "env" not in config
    parameters = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(tmp_path))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {"show_stack", "show_state", "plan_stack", "document_stack"}
            result = await session.call_tool("show_stack", {})
            info = json.loads(result.content[0].text)
            assert info["access_mode"] == "planning"
            assert not info["env_exists"]
            assert Path(info["template_path"]) == workspace / "trial_template.json"
            result = await session.call_tool("show_state", {})
            assert "No matching campaigns" in result.content[0].text
            result = await session.call_tool("apply_stack", {"confirm_deletes": True})
            assert result.isError
            assert "Blocked" in result.content[0].text
            result = await session.call_tool("import_resource", {"resource_type": "adset"})
            assert result.isError
    # A guessed write must not have created provider state or altered the starter.
    assert not (workspace / "state.json").exists()
    template = json.loads((workspace / "trial_template.json").read_text())
    assert template["campaigns"][0]["status"] == "PAUSED"
    assert template["campaigns"][0]["ad_sets"] == []


@pytest.mark.asyncio
async def test_guided_handoff_binds_private_settings_without_restarting_project(tmp_path):
    root = tmp_path / "Guided Workspaces"
    parameters = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "src/bootstrap_server.py"), "--root", str(root)], cwd=str(tmp_path))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as setup:
            await setup.initialize()
            created = await setup.call_tool("create_workspace", {"customer_name": "Acme & Partners"})
            info = json.loads(created.content[0].text)
            workspace_id = info["workspace_id"]
            workspace = root / workspace_id
            assert info["provider_connection_verified"] is False
            assert (workspace / ".env").is_file()
            template_path = workspace / "campaigns_template.json"
            assert json.loads(template_path.read_text()) == {"account_id": "", "campaigns": []}
            config = json.loads((workspace / ".cursor/mcp.json").read_text())["mcpServers"]["adcode"]
            project = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(tmp_path))
            async with stdio_client(project) as (project_read, project_write):
                async with ClientSession(project_read, project_write) as stack:
                    await stack.initialize()
                    result = await stack.call_tool("show_stack", {})
                    assert not json.loads(result.content[0].text)["configured"]
                    # Simulates the user editing the private file, never sending keys to MCP.
                    env = ("FB_ACCOUNT_ID=777\nFB_APP_ID=123456789\n"
                           "FB_APP_SECRET=unit-secret-sentinel\nFB_ACCESS_TOKEN=unit-token-sentinel\n"
                           "ANTHROPIC_API_KEY=unit-anthropic-sentinel\nACCOUNT_BUDGET_CAP=250\nCURRENCY=USD\n")
                    (workspace / ".env").write_text(env, encoding="utf-8")
                    checked = await setup.call_tool("check_workspace", {"workspace_id": workspace_id})
                    status = json.loads(checked.content[0].text)
                    assert status["status"] == "ready"
                    assert status["campaign_status"] == "brief_incomplete"
                    assert status["provider_connection_verified"] is False
                    assert "sentinel" not in checked.content[0].text
                    result = await stack.call_tool("show_stack", {})
                    loaded = json.loads(result.content[0].text)
                    assert loaded["configured"] and loaded["credentials_entered"]
                    assert loaded["account_id"] == "act_777"
                    assert loaded["provider_connection_verified"] is False
                    assert "sentinel" not in result.content[0].text
                    result = await stack.call_tool("plan_stack", {})
                    assert result.isError and "brief" in result.content[0].text
                    (workspace / ".env").write_text(env.replace("FB_ACCOUNT_ID=777", "FB_ACCOUNT_ID=888"))
                    result = await stack.call_tool("plan_stack", {})
                    assert result.isError and "do not match" in result.content[0].text
                    result = await stack.call_tool("apply_stack", {"confirm_deletes": True})
                    assert result.isError
            assert not (workspace / "state.json").exists()
            assert json.loads(template_path.read_text())["campaigns"] == []
