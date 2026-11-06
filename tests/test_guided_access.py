"""Guided readiness, fixed account isolation and secret-safe errors; no APIs."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src import mcp_server as server
from src.services.workspace import start_workspace, check_workspace


@pytest.fixture
def guided(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ACCESS_MODE", "planning")
    monkeypatch.setattr(server, "_ONBOARDING_MODE", True)
    monkeypatch.setattr(server, "_STACK_JSON_PATH", None)
    monkeypatch.setattr(server, "_STACK_STATE_DIR", None)
    monkeypatch.setattr(server, "_ACCOUNT_ID", "")
    info = start_workspace(tmp_path, "Acme")
    workspace = tmp_path / info["workspace_id"]
    with patch.dict(os.environ, {}, clear=True):
        server._load_stack_config(str(workspace / "campaigns_template.json"))
        yield tmp_path, workspace, info["workspace_id"]


def settings(key="unit-anthropic-value"):
    return ("FB_ACCOUNT_ID=123\nFB_APP_ID=12345\nFB_APP_SECRET=unit-secret-value\n"
            "FB_ACCESS_TOKEN=unit-token-value\nANTHROPIC_API_KEY=" + key +
            "\nACCOUNT_BUDGET_CAP=200\nCURRENCY=USD\n")


@pytest.mark.asyncio
async def test_pending_connection_is_available_without_inherited_credentials(guided):
    _, workspace, _ = guided
    os.environ["ANTHROPIC_API_KEY"] = "another-workspace-key"
    result = await server.call_tool("show_stack", {})
    info = json.loads(result[0].text)
    assert not info["configured"] and not info["credentials_entered"]
    assert info["provider_connection_verified"] is False
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert workspace.joinpath(".env").is_file()
    result = await server.call_tool("plan_stack", {})
    assert result.isError and "privately" in result.content[0].text


def test_selected_keys_refresh_without_process_restart(guided):
    root, workspace, identity = guided
    env = workspace / ".env"
    env.write_text(settings(), encoding="utf-8")
    assert check_workspace(root, identity)["status"] == "ready"
    server._require_stack_config()
    with patch.object(server.anthropic, "Anthropic") as client:
        server._get_ai_client()
        client.assert_called_once_with(api_key="unit-anthropic-value")
    env.write_text(settings("unit-key-rotated"), encoding="utf-8")
    server._require_stack_config()
    assert os.environ["ANTHROPIC_API_KEY"] == "unit-key-rotated"
    env.write_text(settings().replace("ANTHROPIC_API_KEY=unit-anthropic-value", "ANTHROPIC_API_KEY="))
    server._require_stack_config()
    with pytest.raises(server.OnboardingError, match="privately"):
        server._get_ai_client()
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_bound_session_never_retargets_even_if_both_files_change(guided):
    root, workspace, identity = guided
    (workspace / ".env").write_text(settings())
    check_workspace(root, identity)
    server._require_stack_config()
    template = workspace / "campaigns_template.json"
    data = json.loads(template.read_text())
    data["account_id"] = "act_999"
    template.write_text(json.dumps(data))
    (workspace / ".env").write_text(settings().replace("FB_ACCOUNT_ID=123", "FB_ACCOUNT_ID=999"))
    with pytest.raises(server.OnboardingError, match="account changed"):
        server._require_stack_config()
    assert "ANTHROPIC_API_KEY" not in os.environ


@pytest.mark.asyncio
async def test_external_exception_values_never_reach_user_or_logs(guided, monkeypatch, caplog):
    value = "unit-private-header-sentinel"
    monkeypatch.setattr(server, "_plan_stack", AsyncMock(side_effect=ValueError(value)))
    result = await server.call_tool("plan_stack", {})
    assert result.isError
    assert value not in result.content[0].text
    assert value not in caplog.text
    assert "No ad changes" in result.content[0].text


@pytest.mark.asyncio
async def test_empty_brief_never_constructs_an_ai_client(guided):
    root, workspace, identity = guided
    (workspace / ".env").write_text(settings())
    check_workspace(root, identity)
    with patch.object(server.anthropic, "Anthropic") as client:
        for tool in ["plan_stack", "document_stack"]:
            result = await server.call_tool(tool, {})
            assert result.isError and "brief" in result.content[0].text
        client.assert_not_called()
    assert not (workspace / "state.json").exists()


def test_optional_local_setup_can_fill_a_guided_draft(guided):
    from src.local_setup import configure_workspace, workspace_status
    root, workspace, identity = guided
    updates = dict(line.split("=", 1) for line in settings().splitlines())
    configure_workspace(workspace, updates)
    assert workspace_status(workspace)["missing"] == []
    assert json.loads((workspace / "campaigns_template.json").read_text())["account_id"] == ""
    assert check_workspace(root, identity)["status"] == "ready"
    assert json.loads((workspace / "campaigns_template.json").read_text())["account_id"] == "act_123"


def test_optional_terminal_prompts_include_account_without_echoing_keys(monkeypatch):
    from src import local_setup
    monkeypatch.setattr(local_setup.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(local_setup.sys.stderr, "isatty", lambda: True)
    hidden = iter(["unit-app-value", "unit-secret-value", "unit-token-value", "unit-key-value"])
    visible = iter(["777", "200", "USD"])
    monkeypatch.setattr(local_setup.getpass, "getpass", lambda _: next(hidden))
    monkeypatch.setattr("builtins.input", lambda _: next(visible))
    result = local_setup._prompt_settings({}, terminal=True, account_required=True)
    assert result["FB_ACCOUNT_ID"] == "777"
    assert result["ACCOUNT_BUDGET_CAP"] == "200"
    assert result["CURRENCY"] == "USD"


def test_onboarding_needs_a_managed_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ONBOARDING_MODE", True)
    path = tmp_path / "draft_template.json"
    path.write_text(json.dumps({"account_id": "", "campaigns": []}))
    with pytest.raises(server.OnboardingError, match="setup check"):
        server._load_stack_config(str(path))


def test_onboarding_cannot_be_enabled_in_operator_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["mcp", "--access-mode", "operator", "--onboarding"])
    with patch("asyncio.run") as run, pytest.raises(SystemExit):
        server.main()
    run.assert_not_called()
