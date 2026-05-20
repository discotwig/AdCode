import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.mcp_server import (
    _apply_stack,
    _drift_stack,
    _generate_stack_from_excel,
    _import_resource,
    _load_stack_config,
    _plan_stack,
    _search_import_candidates,
    _show_stack,
    _show_state,
    _validate_stack,
    call_tool,
    list_tools,
    main,
)
from src.services.state import StateFile


CAMPAIGNS_DIR = Path(__file__).parent / "fixtures"
EXAMPLE_PATH = str(CAMPAIGNS_DIR / "example.json")

with open(EXAMPLE_PATH, encoding="utf-8") as _f:
    EXAMPLE_JSON = json.load(_f)

_EXAMPLE_PATH_OBJ = Path(EXAMPLE_PATH).resolve()


def _make_ai_client(policy_warnings=None):
    client = MagicMock()
    content = MagicMock()
    content.text = json.dumps(policy_warnings or [])
    client.messages.create.return_value.content = [content]
    return client


def _make_meta_client():
    client = MagicMock()
    client.create_campaign.return_value = "camp_fb_001"
    client.create_adset.return_value = "adset_fb_001"
    client.create_creative.return_value = "creative_fb_001"
    client.create_ad.return_value = "ad_fb_001"
    client.list_campaigns.return_value = []
    client.list_adsets.return_value = []
    client.list_ads.return_value = []
    return client


def _patch_active_stack(tmp_path, template_data=None):
    template = tmp_path / "test_stack_template.json"
    template.write_text(json.dumps(template_data or EXAMPLE_JSON), encoding="utf-8")
    return (
        patch("src.mcp_server._STACK_JSON_PATH", template.resolve()),
        patch("src.mcp_server._STACK_STATE_DIR", tmp_path),
        patch("src.mcp_server._ACCOUNT_ID", (template_data or EXAMPLE_JSON)["account_id"]),
        patch("src.services.state.STATE_DIR", tmp_path),
    )


def _state_matching_example():
    state = StateFile(EXAMPLE_JSON["account_id"], stack_name="state")
    campaign = EXAMPLE_JSON["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    state.upsert_campaign(
        campaign["name"],
        campaign.get("fb_id", "c1"),
        {k: campaign[k] for k in ["name", "objective", "status", "special_ad_categories"]},
    )
    state.upsert_adset(
        campaign["name"],
        adset["name"],
        adset.get("fb_id", "a1"),
        {k: adset[k] for k in ["name", "status", "billing_event", "optimization_goal", "daily_budget"]},
    )
    state.upsert_ad(
        campaign["name"],
        adset["name"],
        ad["name"],
        ad.get("fb_id", "ad1"),
        "cr1",
        {"name": ad["name"], "status": ad["status"]},
    )
    return state


@pytest.mark.asyncio
async def test_list_tools_is_strict_iac_surface():
    tools = await list_tools()
    names = {tool.name for tool in tools}

    assert names == {
        "show_stack",
        "validate_stack",
        "plan_stack",
        "apply_stack",
        "drift_stack",
        "show_state",
        "search_import_candidates",
        "import_resource",
        "generate_stack_from_excel",
        "document_stack",
    }


@pytest.mark.asyncio
async def test_list_tools_excludes_broad_live_console_surface():
    tools = await list_tools()
    names = {tool.name for tool in tools}

    retired = {
        "pause_campaigns",
        "list_campaigns",
        "get_campaign_status",
        "get_campaign_export",
        "find_duplicates",
        "plan_campaigns",
        "apply_campaigns",
        "get_local_state",
        "get_drift_report",
        "import_adsets",
        "ingest_excel",
    }
    assert names.isdisjoint(retired)


@pytest.mark.asyncio
async def test_stack_tools_do_not_accept_json_path_or_account_id():
    tools = await list_tools()
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        assert "json_path" not in props
        assert "account_id" not in props
        assert "json_str" not in props


def test_load_stack_config_sets_globals_and_account_env(tmp_path):
    stack_dir = tmp_path / "my_stack"
    stack_dir.mkdir()
    template = stack_dir / "my_stack_template.json"
    template.write_text(json.dumps({"account_id": "act_999", "campaigns": []}), encoding="utf-8")

    import src.mcp_server as mod
    with patch.dict("os.environ", {}, clear=False):
        _load_stack_config(str(template))
        assert mod.os.environ["FB_ACCOUNT_ID"] == "act_999"

    assert mod._STACK_JSON_PATH == template.resolve()
    assert mod._STACK_STATE_DIR == stack_dir.resolve()
    assert mod._ACCOUNT_ID == "act_999"


def test_load_stack_config_loads_stack_env(tmp_path):
    stack_dir = tmp_path / "my_stack"
    stack_dir.mkdir()
    template = stack_dir / "my_stack_template.json"
    template.write_text(json.dumps({"account_id": "act_888", "campaigns": []}), encoding="utf-8")
    (stack_dir / ".env").write_text("FB_APP_ID=test_app_id_from_env\n", encoding="utf-8")

    with patch.dict("os.environ", {}, clear=False):
        _load_stack_config(str(template))
        import os
        assert os.environ.get("FB_APP_ID") == "test_app_id_from_env"


@pytest.mark.asyncio
async def test_show_stack_reports_active_local_paths(tmp_path):
    stack_patches = _patch_active_stack(tmp_path)
    with stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3]:
        result = await _show_stack({})

    data = json.loads(result[0].text)
    assert data["account_id"] == EXAMPLE_JSON["account_id"]
    assert data["template_path"].endswith("test_stack_template.json")
    assert data["state_path"].endswith("state.json")
    assert "credentials" not in data


@pytest.mark.asyncio
async def test_validate_stack_does_not_call_meta(tmp_path):
    meta = _make_meta_client()
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server._get_meta_client", return_value=meta),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _validate_stack({})

    assert "Pushable" in result[0].text
    meta.list_campaigns.assert_not_called()


@pytest.mark.asyncio
async def test_plan_stack_does_not_call_provider_writes(tmp_path):
    meta = _make_meta_client()
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server._get_meta_client", return_value=meta),
        patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"], stack_name="state")),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _plan_stack({})

    assert "CreateCampaign" in result[0].text or "No changes" in result[0].text
    meta.create_campaign.assert_not_called()
    meta.update_campaign.assert_not_called()
    meta.delete_campaign.assert_not_called()


@pytest.mark.asyncio
async def test_plan_stack_passes_stack_state_name(tmp_path):
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"], stack_name="state")) as mock_load,
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        await _plan_stack({})

    assert mock_load.call_args.kwargs["stack_name"] == "state"


@pytest.mark.asyncio
async def test_apply_stack_blocks_policy_errors(tmp_path):
    warnings = [{"severity": "ERROR", "field": "x", "message": "Prohibited", "suggestion": "Fix"}]
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client(warnings)),
        patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
        patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _apply_stack({})

    assert "blocked" in result[0].text.lower()


@pytest.mark.asyncio
async def test_apply_stack_requires_delete_confirmation(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    state.upsert_campaign(
        "Stale Campaign",
        "stale_001",
        {"name": "Stale Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []},
    )
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
        patch("src.mcp_server.StateFile.load", return_value=state),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _apply_stack({})

    assert "confirm_deletes" in result[0].text
    assert "DELETE" in result[0].text


@pytest.mark.asyncio
async def test_apply_stack_executes_confirmed_delete(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    state.upsert_campaign(
        "Stale Campaign",
        "stale_001",
        {"name": "Stale Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []},
    )
    meta = _make_meta_client()
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server._get_meta_client", return_value=meta),
        patch("src.mcp_server.StateFile.load", return_value=state),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _apply_stack({"confirm_deletes": True})

    assert "Applied" in result[0].text
    meta.delete_campaign.assert_called_with("stale_001")


@pytest.mark.asyncio
async def test_show_state_reads_local_state_without_meta(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"], stack_name="state")
    state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale"})
    meta = _make_meta_client()
    stack_patches = _patch_active_stack(tmp_path)
    with (
        patch("src.mcp_server.StateFile.load", return_value=state),
        patch("src.mcp_server._get_meta_client", return_value=meta),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _show_state({"campaign_name": "summer"})

    assert "Summer Sale" in result[0].text
    meta.list_campaigns.assert_not_called()


def _actuals_for_import():
    return {
        "Parent Campaign": {
            "fb_id": "camp_001",
            "id": "camp_001",
            "name": "Parent Campaign",
            "status": "PAUSED",
            "ad_sets": {
                "Ad Set A": {
                    "fb_id": "adset_A",
                    "id": "adset_A",
                    "name": "Ad Set A",
                    "status": "PAUSED",
                    "billing_event": "LINK_CLICKS",
                    "optimization_goal": "LINK_CLICKS",
                    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                    "daily_budget": "300",
                    "targeting": {},
                    "ads": {},
                },
                "Ad Set B": {
                    "fb_id": "adset_B",
                    "id": "adset_B",
                    "name": "Ad Set B",
                    "status": "PAUSED",
                    "billing_event": "LINK_CLICKS",
                    "optimization_goal": "LINK_CLICKS",
                    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                    "daily_budget": "400",
                    "targeting": {},
                    "ads": {},
                },
            },
        },
        "Other Campaign": {
            "fb_id": "camp_999",
            "id": "camp_999",
            "name": "Other Campaign",
            "status": "PAUSED",
            "ad_sets": {
                "Outside Ad Set": {
                    "fb_id": "adset_outside",
                    "id": "adset_outside",
                    "name": "Outside Ad Set",
                    "status": "PAUSED",
                    "ads": {},
                },
            },
        },
    }


def _import_template():
    return {
        "account_id": "act_123",
        "campaigns": [
            {
                "name": "Parent Campaign",
                "fb_id": "camp_001",
                "objective": "REACH",
                "status": "PAUSED",
                "special_ad_categories": [],
                "ad_sets": [],
            }
        ],
    }


def _list_adsets_under_import_parent():
    return [
        {
            "id": "adset_A",
            "name": "Ad Set A",
            "status": "PAUSED",
            "billing_event": "LINK_CLICKS",
            "optimization_goal": "LINK_CLICKS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "daily_budget": "300",
            "targeting": {},
        },
        {
            "id": "adset_B",
            "name": "Ad Set B",
            "status": "PAUSED",
            "billing_event": "LINK_CLICKS",
            "optimization_goal": "LINK_CLICKS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "daily_budget": "400",
            "targeting": {},
        },
    ]


@pytest.mark.asyncio
async def test_drift_stack_filters_unmanaged_live_objects(tmp_path):
    state = StateFile("act_123", stack_name="state")
    state.upsert_campaign(
        "Parent Campaign",
        "camp_001",
        {"name": "Parent Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []},
    )
    stack_patches = _patch_active_stack(tmp_path, _import_template())
    with (
        patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
        patch("src.mcp_server.StateFile.load", return_value=state),
        patch("src.mcp_server.fetch_actuals", return_value=_actuals_for_import()),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _drift_stack({})

    assert "MISSING_FROM_STATE" not in result[0].text
    assert "Outside Ad Set" not in result[0].text


@pytest.mark.asyncio
async def test_search_import_candidates_only_returns_adsets_under_declared_campaigns(tmp_path):
    state = StateFile("act_123", stack_name="state")
    state.upsert_campaign("Parent Campaign", "camp_001", {"name": "Parent Campaign", "status": "PAUSED"})
    meta = _make_meta_client()
    meta.list_adsets.return_value = _list_adsets_under_import_parent()
    stack_patches = _patch_active_stack(tmp_path, _import_template())
    with (
        patch("src.mcp_server._get_meta_client", return_value=meta),
        patch("src.mcp_server.StateFile.load", return_value=state),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _search_import_candidates({"resource_type": "adset"})

    data = json.loads(result[0].text)
    assert data["count"] == 2
    assert {item["name"] for item in data["candidates"]} == {"Ad Set A", "Ad Set B"}
    assert "Outside Ad Set" not in result[0].text
    meta.list_adsets.assert_called_once_with("camp_001")


@pytest.mark.asyncio
async def test_search_import_candidates_rejects_unsupported_type(tmp_path):
    result = await _search_import_candidates({"resource_type": "campaign"})
    assert "Only resource_type='adset'" in result[0].text


@pytest.mark.asyncio
async def test_import_resource_imports_named_adset(tmp_path):
    state = StateFile("act_123", stack_name="state")
    state.upsert_campaign("Parent Campaign", "camp_001", {"name": "Parent Campaign", "status": "PAUSED"})
    meta = _make_meta_client()
    meta.list_adsets.return_value = _list_adsets_under_import_parent()
    stack_patches = _patch_active_stack(tmp_path, _import_template())
    with (
        patch("src.mcp_server._get_meta_client", return_value=meta),
        patch("src.mcp_server.StateFile.load", return_value=state),
        stack_patches[0], stack_patches[1], stack_patches[2], stack_patches[3],
    ):
        result = await _import_resource({"resource_type": "adset", "names": ["Ad Set A"]})

    assert "Imported 1" in result[0].text
    updated = json.loads((tmp_path / "test_stack_template.json").read_text(encoding="utf-8"))
    adset_names = [adset["name"] for adset in updated["campaigns"][0]["ad_sets"]]
    assert adset_names == ["Ad Set A"]
    assert updated["campaigns"][0]["ad_sets"][0].get("fb_id") == "adset_A"
    assert state.get_adset_id("Parent Campaign", "Ad Set A") == "adset_A"


@pytest.mark.asyncio
async def test_import_resource_rejects_unsupported_type():
    result = await _import_resource({"resource_type": "campaign"})
    assert "Only resource_type='adset'" in result[0].text


@pytest.mark.asyncio
async def test_generate_stack_from_excel_returns_template_json(tmp_path):
    result_obj = MagicMock()
    result_obj.campaigns = [{"name": "Generated Campaign", "objective": "REACH", "status": "PAUSED", "ad_sets": []}]
    with (
        patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
        patch("src.mcp_server.read_excel", return_value={"Sheet1": []}),
        patch("src.mcp_server.extract_campaigns", return_value=result_obj),
        patch("src.mcp_server.format_ambiguity_report", return_value="No ambiguities."),
    ):
        result = await _generate_stack_from_excel({"excel_path": str(tmp_path / "brief.xlsx")})

    assert "Generated Campaign" in result[0].text
    assert "Extracted campaign JSON" in result[0].text


@pytest.mark.asyncio
async def test_old_tool_names_return_unknown():
    result = await call_tool("pause_campaigns", {})
    assert "Unknown tool" in result[0].text


def test_main_does_not_perform_startup_facebook_check(tmp_path):
    stack_dir = tmp_path / "my_stack"
    stack_dir.mkdir()
    template = stack_dir / "my_stack_template.json"
    template.write_text(json.dumps({"account_id": "act_123", "campaigns": []}), encoding="utf-8")

    with (
        patch("sys.argv", ["mcp_server", "--config", str(template)]),
        patch("src.mcp_server._get_meta_client") as mock_meta,
        patch("src.mcp_server._main", MagicMock(return_value=None)),
        patch("asyncio.run"),
    ):
        main()

    mock_meta.assert_not_called()
