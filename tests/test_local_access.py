"""Local distribution permissions; tests never use real keys or provider APIs."""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import mcp_server as server


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ACCESS_MODE", "planning")
    monkeypatch.setattr(server, "_STACK_JSON_PATH", None)
    monkeypatch.setattr(server, "_STACK_STATE_DIR", None)
    monkeypatch.setattr(server, "_ACCOUNT_ID", "")
    template = tmp_path / "test_template.json"
    template.write_text(json.dumps({"account_id": "act_123", "campaigns": []}))
    with patch.dict(os.environ, {}, clear=True):
        yield template


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,names", [
    ("inspect", {"show_stack", "show_state"}),
    ("planning", {"show_stack", "show_state", "plan_stack", "document_stack"}),
    ("unknown", set()),
])
async def test_restricted_discovery_is_an_explicit_allowlist(monkeypatch, mode, names):
    monkeypatch.setattr(server, "_ACCESS_MODE", mode)
    assert {t.name for t in await server.list_tools()} == names


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [
    "apply_stack", "remediate_drift", "import_resource", "drift_stack", "draft_stack",
    "an_unknown_tool",
])
async def test_guessed_tools_are_blocked_before_provider_or_file_access(monkeypatch, tool):
    monkeypatch.setattr(server, "_ACCESS_MODE", "planning")
    with patch.object(server, "_get_meta_client") as meta, patch.object(server, "_get_ai_client") as ai:
        result = await server.call_tool(tool, {"confirm_deletes": True, "excel_path": "/not/allowed"})
    assert result.isError
    assert "Blocked" in result.content[0].text
    meta.assert_not_called()
    ai.assert_not_called()


@pytest.mark.asyncio
async def test_planning_dispatch_preserves_allowed_handler(monkeypatch):
    monkeypatch.setattr(server, "_ACCESS_MODE", "planning")
    handler = AsyncMock(return_value=[])
    monkeypatch.setattr(server, "_plan_stack", handler)
    assert await server.call_tool("plan_stack", {}) == []
    handler.assert_awaited_once_with({})


def test_missing_ai_key_gives_local_setup_instructions_without_network(stack):
    with patch.object(server.anthropic, "Anthropic") as client:
        with pytest.raises(ValueError, match="Configure AdCode.command"):
            server._get_ai_client()
        client.assert_not_called()


def test_missing_meta_keys_give_local_setup_instructions_without_network(stack):
    with patch.object(server, "MetaClient") as client:
        with pytest.raises(ValueError, match="Never paste credentials"):
            server._get_meta_client()
        client.assert_not_called()


def test_planning_uses_only_its_stack_environment(stack):
    os.environ.update(FB_APP_ID="another-stack", FB_ACCESS_TOKEN="other-token", CURRENCY="EUR")
    (stack.parent / ".env").write_text("FB_APP_ID=local-app\nANTHROPIC_API_KEY='literal-${KEEP_THIS}-value'\n")
    server._load_stack_config(str(stack))
    assert os.environ["FB_APP_ID"] == "local-app"
    assert os.environ["ANTHROPIC_API_KEY"] == "literal-${KEEP_THIS}-value"
    assert "FB_ACCESS_TOKEN" not in os.environ
    assert "CURRENCY" not in os.environ
    assert os.environ["FB_ACCOUNT_ID"] == "act_123"


def test_inspect_never_loads_provider_secrets(stack, monkeypatch):
    monkeypatch.setattr(server, "_ACCESS_MODE", "inspect")
    os.environ["FB_ACCESS_TOKEN"] = "inherited-token"
    (stack.parent / ".env").write_text("FB_ACCESS_TOKEN=local-token\n")
    server._load_stack_config(str(stack))
    assert "FB_ACCESS_TOKEN" not in os.environ


def test_planning_rejects_mismatched_credential_account(stack):
    (stack.parent / ".env").write_text("FB_ACCOUNT_ID=act_999\n")
    with pytest.raises(ValueError, match="credential account"):
        server._load_stack_config(str(stack))


@pytest.mark.asyncio
async def test_editing_template_account_requires_a_new_connection(stack):
    server._load_stack_config(str(stack))
    stack.write_text(json.dumps({"account_id": "act_999", "campaigns": []}))
    result = await server.call_tool("show_stack", {})
    assert "Template account changed" in result[0].text


@pytest.mark.asyncio
async def test_saved_state_must_belong_to_fixed_account(stack):
    server._load_stack_config(str(stack))
    (stack.parent / "state.json").write_text(json.dumps({"account_id": "act_999", "campaigns": {}}))
    result = await server.call_tool("show_state", {})
    assert "State account does not match" in result[0].text


@pytest.mark.asyncio
async def test_show_stack_explains_safe_mode_without_secrets(stack):
    (stack.parent / ".env").write_text("FB_APP_SECRET=not-a-real-secret\n")
    server._load_stack_config(str(stack))
    result = await server.call_tool("show_stack", {})
    info = json.loads(result[0].text)
    assert info["access_mode"] == "planning"
    assert info["env_exists"]
    assert "not-a-real-secret" not in result[0].text


@pytest.mark.parametrize("arguments", [
    ["mcp", "--access-mode", "planning"],
    ["mcp", "--access-mode", "inspect"],
    ["mcp", "--access-mode", "invalid"],
])
def test_cli_restricted_modes_fail_closed_without_valid_configuration(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setattr(server, "_ACCESS_MODE", "operator")
    with patch("asyncio.run") as run, pytest.raises(SystemExit):
        server.main()
    run.assert_not_called()


def test_cli_explicit_planning_and_legacy_skip_flag(stack, monkeypatch):
    monkeypatch.setattr("sys.argv", ["mcp", "--config", str(stack), "--access-mode", "planning", "--skip-connection-check"])
    with patch.object(server, "_main", new=MagicMock(return_value=None)), patch("asyncio.run") as run:
        server.main()
    assert server._ACCESS_MODE == "planning"
    run.assert_called_once_with(None)
