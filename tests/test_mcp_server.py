import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.mcp_server import (
    _apply_campaigns, _plan_campaigns, _pause_campaigns,
    _get_local_state, _get_campaign_status, _get_drift_report,
    _list_campaigns, _ingest_excel, _import_adsets, _find_duplicates,
    _get_campaign_export, list_tools,
)
from src.services.state import StateFile

CAMPAIGNS_DIR = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

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
    client.get_campaign.return_value = {"id": "camp_001", "name": "Test", "status": "PAUSED"}
    client.list_campaigns.return_value = []
    client.list_adsets.return_value = []
    client.list_ads.return_value = []
    return client


EXAMPLE_PATH = str(CAMPAIGNS_DIR / "example.json")

with open(EXAMPLE_PATH, encoding="utf-8") as _f:
    EXAMPLE_JSON = json.load(_f)


# ------------------------------------------------------------------
# list_tools
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_all_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "apply_campaigns" in names
    assert "plan_campaigns" in names
    assert "list_campaigns" in names
    assert "pause_campaigns" in names
    assert "get_local_state" in names
    assert "get_campaign_status" in names
    assert "get_drift_report" in names
    assert "ingest_excel" in names


@pytest.mark.asyncio
async def test_list_tools_no_retired_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "push_campaigns" not in names
    assert "get_campaign_json" not in names
    assert "validate_campaigns" not in names
    assert "preview_diff" not in names
    assert "preview_teardown" not in names
    assert "teardown_campaigns" not in names


# ------------------------------------------------------------------
# apply_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_campaigns_applies_when_valid(tmp_path):
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _apply_campaigns({"json_path": EXAMPLE_PATH})
    text = result[0].text
    assert "Applied" in text or "No changes" in text


@pytest.mark.asyncio
async def test_apply_campaigns_blocked_when_policy_error(tmp_path):
    policy_warnings = [{"severity": "ERROR", "field": "x", "message": "Prohibited", "suggestion": "Fix"}]
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client(policy_warnings)),
          patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _apply_campaigns({"json_path": EXAMPLE_PATH})
    assert "blocked" in result[0].text.lower()


@pytest.mark.asyncio
async def test_apply_campaigns_no_changes_message(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    campaign = EXAMPLE_JSON["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    state.upsert_campaign(campaign["name"], campaign.get("fb_id", "c1"), {k: campaign[k] for k in ["name", "objective", "status", "special_ad_categories"]})
    state.upsert_adset(campaign["name"], adset["name"], adset.get("fb_id", "a1"), {k: adset[k] for k in ["name", "status", "billing_event", "optimization_goal", "daily_budget"]})
    state.upsert_ad(campaign["name"], adset["name"], ad["name"], ad.get("fb_id", "ad1"), "cr1", {"name": ad["name"], "status": ad["status"]})

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _apply_campaigns({"json_path": EXAMPLE_PATH})
    assert "No changes" in result[0].text


@pytest.mark.asyncio
async def test_apply_campaigns_returns_plan_when_deletes_without_confirm(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    state.upsert_campaign("Stale Campaign", "stale_001", {"name": "Stale Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []})
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _apply_campaigns({"json_path": EXAMPLE_PATH})
    text = result[0].text
    assert "confirm_deletes" in text
    assert "DELETE" in text.upper()


@pytest.mark.asyncio
async def test_apply_campaigns_executes_deletes_with_confirm(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    state.upsert_campaign("Stale Campaign", "stale_001", {"name": "Stale Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []})
    meta = _make_meta_client()
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _apply_campaigns({"json_path": EXAMPLE_PATH, "confirm_deletes": True})
    assert "Applied" in result[0].text
    meta.delete_campaign.assert_called_with("stale_001")


# ------------------------------------------------------------------
# plan_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_campaigns_does_not_call_apply(tmp_path):
    meta = _make_meta_client()
    state = StateFile(EXAMPLE_JSON["account_id"])
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _plan_campaigns({"json_path": EXAMPLE_PATH})
    meta.create_campaign.assert_not_called()
    meta.update_campaign.assert_not_called()
    meta.delete_campaign.assert_not_called()
    assert len(result[0].text) > 0


@pytest.mark.asyncio
async def test_plan_campaigns_includes_validation_and_diff(tmp_path):
    meta = _make_meta_client()
    state = StateFile(EXAMPLE_JSON["account_id"])
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _plan_campaigns({"json_path": EXAMPLE_PATH})
    text = result[0].text
    # Should contain both validation summary and diff
    assert "Pushable" in text or "blocked" in text.lower()
    assert "CreateCampaign" in text or "No changes" in text


@pytest.mark.asyncio
async def test_plan_campaigns_no_changes_message(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    campaign = EXAMPLE_JSON["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    state.upsert_campaign(campaign["name"], campaign.get("fb_id", "c1"), {k: campaign[k] for k in ["name", "objective", "status", "special_ad_categories"]})
    state.upsert_adset(campaign["name"], adset["name"], adset.get("fb_id", "a1"), {k: adset[k] for k in ["name", "status", "billing_event", "optimization_goal", "daily_budget"]})
    state.upsert_ad(campaign["name"], adset["name"], ad["name"], ad.get("fb_id", "ad1"), "cr1", {"name": ad["name"], "status": ad["status"]})

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _plan_campaigns({"json_path": EXAMPLE_PATH})
    assert "No changes" in result[0].text


# ------------------------------------------------------------------
# list_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_campaigns_calls_facebook_api():
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "123", "name": "Test Campaign", "status": "PAUSED", "objective": "REACH"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _list_campaigns({})
    meta.list_campaigns.assert_called_once()
    assert "Test Campaign" in result[0].text


@pytest.mark.asyncio
async def test_list_campaigns_never_reads_state():
    meta = _make_meta_client()
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load") as mock_state_load,
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        await _list_campaigns({})
    mock_state_load.assert_not_called()


# ------------------------------------------------------------------
# pause_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_campaigns_pauses_matching(tmp_path):
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "ACTIVE"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=StateFile("act_123")),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _pause_campaigns({"campaign_name": "Summer Sale", "account_id": "act_123"})

    meta.pause_campaign.assert_called_once_with("camp_001")
    assert "Summer Sale" in result[0].text


@pytest.mark.asyncio
async def test_pause_campaigns_skips_already_paused(tmp_path):
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "PAUSED"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=StateFile("act_123")),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _pause_campaigns({"campaign_name": "Summer Sale", "account_id": "act_123"})

    meta.pause_campaign.assert_not_called()
    assert "already paused" in result[0].text


@pytest.mark.asyncio
async def test_pause_campaigns_no_match_message(tmp_path):
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "ACTIVE"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=StateFile("act_123")),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _pause_campaigns({"campaign_name": "Nonexistent", "account_id": "act_123"})
    assert "No matching" in result[0].text


@pytest.mark.asyncio
async def test_pause_campaigns_queries_facebook_not_state(tmp_path):
    meta = _make_meta_client()
    meta.list_campaigns.return_value = []
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=StateFile("act_123")),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        await _pause_campaigns({"account_id": "act_123"})
    meta.list_campaigns.assert_called_once()


# ------------------------------------------------------------------
# get_local_state
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_local_state_returns_state_data():
    state = StateFile("act_123")
    state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale"})

    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _get_local_state({"account_id": "act_123"})

    assert "Summer Sale" in result[0].text


@pytest.mark.asyncio
async def test_get_local_state_filters_by_name():
    state = StateFile("act_123")
    state.upsert_campaign("Summer Sale", "camp_001", {})
    state.upsert_campaign("Winter Promo", "camp_002", {})

    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _get_local_state({"account_id": "act_123", "campaign_name": "summer"})

    text = result[0].text
    assert "Summer Sale" in text
    assert "Winter Promo" not in text


@pytest.mark.asyncio
async def test_get_local_state_does_not_call_meta_api():
    state = StateFile("act_123")
    meta = _make_meta_client()
    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.mcp_server._get_meta_client", return_value=meta),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        await _get_local_state({})
    meta.list_campaigns.assert_not_called()
    meta.get_campaign.assert_not_called()


# ------------------------------------------------------------------
# get_campaign_status
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_campaign_status_calls_meta_api():
    meta = _make_meta_client()
    with patch("src.mcp_server._get_meta_client", return_value=meta):
        result = await _get_campaign_status({"campaign_id": "camp_001"})
    meta.get_campaign.assert_called_once_with("camp_001")
    assert "status" in result[0].text


# ------------------------------------------------------------------
# get_drift_report
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_returns_report():
    meta = _make_meta_client()
    state = StateFile("act_123")
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=state)):
        result = await _get_drift_report({"account_id": "act_123"})
    assert len(result[0].text) > 0


# ------------------------------------------------------------------
# import_adsets
# ------------------------------------------------------------------

def _make_actuals(with_adset=True):
    adsets = {}
    if with_adset:
        adsets["Untracked Ad Set"] = {
            "fb_id": "adset_999",
            "id": "adset_999",
            "name": "Untracked Ad Set",
            "status": "PAUSED",
            "billing_event": "LINK_CLICKS",
            "optimization_goal": "LINK_CLICKS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "daily_budget": 500,
            "targeting": {"age_min": 25, "age_max": 44, "geo_locations": {"countries": ["US"]}},
            "ads": {},
        }
    return {
        "Parent Campaign": {
            "fb_id": "camp_001",
            "id": "camp_001",
            "name": "Parent Campaign",
            "status": "PAUSED",
            "ad_sets": adsets,
        }
    }


def _make_campaign_json(tmp_path, with_adset=False):
    data = {
        "account_id": "act_123",
        "campaigns": [
            {
                "name": "Parent Campaign",
                "objective": "REACH",
                "status": "PAUSED",
                "special_ad_categories": [],
                "ad_sets": [{"name": "Untracked Ad Set", "status": "PAUSED", "ads": []}] if with_adset else [],
            }
        ],
    }
    path = tmp_path / "test.json"
    path.write_text(json.dumps(data))
    return str(path)


@pytest.mark.asyncio
async def test_import_adsets_imports_missing_adset(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Parent Campaign", "camp_001", {"name": "Parent Campaign", "status": "PAUSED"})
    json_path = _make_campaign_json(tmp_path)
    actuals = _make_actuals(with_adset=True)

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.mcp_server.fetch_actuals", return_value=actuals),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _import_adsets({"account_id": "act_123", "json_path": json_path})

    text = result[0].text
    assert "Imported 1" in text
    assert "Untracked Ad Set" in text

    updated = json.loads(Path(json_path).read_text())
    adset_names = [a["name"] for a in updated["campaigns"][0]["ad_sets"]]
    assert "Untracked Ad Set" in adset_names
    assert updated["campaigns"][0]["ad_sets"][0]["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert state.get_adset_id("Parent Campaign", "Untracked Ad Set") == "adset_999"


@pytest.mark.asyncio
async def test_import_adsets_filters_by_name(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Parent Campaign", "camp_001", {"name": "Parent Campaign", "status": "PAUSED"})
    json_path = _make_campaign_json(tmp_path)

    actuals = _make_actuals(with_adset=False)
    actuals["Parent Campaign"]["ad_sets"]["Ad Set A"] = {
        "fb_id": "adset_A", "id": "adset_A", "name": "Ad Set A",
        "status": "PAUSED", "billing_event": "LINK_CLICKS", "optimization_goal": "LINK_CLICKS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "daily_budget": 300, "targeting": {}, "ads": {},
    }
    actuals["Parent Campaign"]["ad_sets"]["Ad Set B"] = {
        "fb_id": "adset_B", "id": "adset_B", "name": "Ad Set B",
        "status": "PAUSED", "billing_event": "LINK_CLICKS", "optimization_goal": "LINK_CLICKS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "daily_budget": 400, "targeting": {}, "ads": {},
    }

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.mcp_server.fetch_actuals", return_value=actuals),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _import_adsets({
            "account_id": "act_123",
            "json_path": json_path,
            "adset_names": ["Ad Set A"],
        })

    text = result[0].text
    assert "Imported 1" in text
    updated = json.loads(Path(json_path).read_text())
    adset_names = [a["name"] for a in updated["campaigns"][0]["ad_sets"]]
    assert "Ad Set A" in adset_names
    assert "Ad Set B" not in adset_names


@pytest.mark.asyncio
async def test_import_adsets_skips_already_tracked(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Parent Campaign", "camp_001", {"name": "Parent Campaign", "status": "PAUSED"})
    state.upsert_adset("Parent Campaign", "Untracked Ad Set", "adset_999",
                       {"name": "Untracked Ad Set", "status": "PAUSED"})
    json_path = _make_campaign_json(tmp_path, with_adset=True)
    actuals = _make_actuals(with_adset=True)

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.mcp_server.fetch_actuals", return_value=actuals),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _import_adsets({"account_id": "act_123", "json_path": json_path})

    assert "nothing to import" in result[0].text.lower()


@pytest.mark.asyncio
async def test_list_tools_includes_import_adsets():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "import_adsets" in names


# ------------------------------------------------------------------
# find_duplicates
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# get_campaign_export
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_campaign_export_returns_full_hierarchy():
    meta = _make_meta_client()
    actuals = {
        "Summer Sale": {
            "fb_id": "camp_001",
            "id": "camp_001",
            "name": "Summer Sale",
            "status": "ACTIVE",
            "ad_sets": {
                "Broad Audience": {
                    "fb_id": "adset_001",
                    "name": "Broad Audience",
                    "status": "ACTIVE",
                    "ads": {
                        "Ad A": {"fb_id": "ad_001", "name": "Ad A", "status": "ACTIVE"},
                    },
                },
            },
        }
    }
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.fetch_actuals", return_value=actuals)):
        result = await _get_campaign_export({"account_id": "act_123"})
    data = json.loads(result[0].text)
    assert "Summer Sale" in data
    assert "Broad Audience" in data["Summer Sale"]["ad_sets"]
    assert "Ad A" in data["Summer Sale"]["ad_sets"]["Broad Audience"]["ads"]


@pytest.mark.asyncio
async def test_get_campaign_export_calls_fetch_actuals():
    meta = _make_meta_client()
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.fetch_actuals", return_value={}) as mock_fetch):
        await _get_campaign_export({"account_id": "act_123"})
    mock_fetch.assert_called_once_with("act_123", meta)


@pytest.mark.asyncio
async def test_find_duplicates_returns_duplicates():
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "ACTIVE", "created_time": "2026-01-01"},
        {"id": "camp_002", "name": "Summer Sale", "status": "PAUSED", "created_time": "2026-01-02"},
        {"id": "camp_003", "name": "Winter Promo", "status": "ACTIVE", "created_time": "2026-02-01"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _find_duplicates({})
    data = json.loads(result[0].text)
    assert data["duplicate_count"] == 1
    assert "Summer Sale" in data["duplicates"]
    fb_ids = [e["fb_id"] for e in data["duplicates"]["Summer Sale"]]
    assert "camp_001" in fb_ids
    assert "camp_002" in fb_ids
    assert "Winter Promo" not in data["duplicates"]


@pytest.mark.asyncio
async def test_find_duplicates_no_duplicates():
    meta = _make_meta_client()
    meta.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "ACTIVE", "created_time": "2026-01-01"},
        {"id": "camp_002", "name": "Winter Promo", "status": "PAUSED", "created_time": "2026-02-01"},
    ]
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _find_duplicates({})
    data = json.loads(result[0].text)
    assert data["duplicate_count"] == 0
    assert data["duplicates"] == {}
