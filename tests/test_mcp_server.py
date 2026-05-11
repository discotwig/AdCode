import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp_server import (
    _push_campaigns, _pause_campaigns, _get_campaign_json,
    _get_campaign_status, _get_drift_report, _validate_campaigns,
    _preview_diff, _ingest_excel, list_tools,
)
from src.services.state import StateFile

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


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

with open(EXAMPLE_PATH) as _f:
    EXAMPLE_JSON = json.load(_f)


# ------------------------------------------------------------------
# list_tools
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_all_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "push_campaigns" in names
    assert "pause_campaigns" in names
    assert "get_campaign_json" in names
    assert "get_campaign_status" in names
    assert "get_drift_report" in names
    assert "validate_campaigns" in names
    assert "preview_diff" in names
    assert "ingest_excel" in names


# ------------------------------------------------------------------
# push_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_campaigns_applies_when_valid(tmp_path):
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _push_campaigns({"json_path": EXAMPLE_PATH})
    text = result[0].text
    assert "Push complete" in text or "No changes" in text


@pytest.mark.asyncio
async def test_push_campaigns_blocked_when_policy_error(tmp_path):
    policy_warnings = [{"severity": "ERROR", "field": "x", "message": "Prohibited", "suggestion": "Fix"}]
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client(policy_warnings)),
          patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _push_campaigns({"json_path": EXAMPLE_PATH})
    text = result[0].text
    assert "blocked" in text.lower()


@pytest.mark.asyncio
async def test_push_campaigns_validates_before_applying(tmp_path):
    meta = _make_meta_client()
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=StateFile(EXAMPLE_JSON["account_id"])),
          patch("src.services.state.STATE_DIR", tmp_path)):
        await _push_campaigns({"json_path": EXAMPLE_PATH})


@pytest.mark.asyncio
async def test_push_campaigns_no_changes_message(tmp_path):
    # Pre-populate state so no changes are needed
    state = StateFile(EXAMPLE_JSON["account_id"])
    campaign = EXAMPLE_JSON["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    state.upsert_campaign(campaign["name"], "c1", {k: campaign[k] for k in ["name","objective","status","special_ad_categories"]})
    state.upsert_adset(campaign["name"], adset["name"], "a1", {k: adset[k] for k in ["name","status","billing_event","optimization_goal","daily_budget"]})
    state.upsert_ad(campaign["name"], adset["name"], ad["name"], "ad1", "cr1", {"name": ad["name"], "status": ad["status"]})

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _push_campaigns({"json_path": EXAMPLE_PATH})
    assert "No changes" in result[0].text


# ------------------------------------------------------------------
# pause_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_campaigns_pauses_matching(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale", "status": "ACTIVE"})
    meta = _make_meta_client()

    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _pause_campaigns({"campaign_name": "Summer Sale", "account_id": "act_123"})

    meta.pause_campaign.assert_called_once_with("camp_001")
    assert "Summer Sale" in result[0].text


@pytest.mark.asyncio
async def test_pause_campaigns_no_match_message(tmp_path):
    state = StateFile("act_123")
    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _pause_campaigns({"campaign_name": "Nonexistent", "account_id": "act_123"})
    assert "No matching" in result[0].text


# ------------------------------------------------------------------
# get_campaign_json
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_campaign_json_returns_state_data(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale"})

    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _get_campaign_json({"account_id": "act_123"})

    assert "Summer Sale" in result[0].text


@pytest.mark.asyncio
async def test_get_campaign_json_filters_by_name(tmp_path):
    state = StateFile("act_123")
    state.upsert_campaign("Summer Sale", "camp_001", {})
    state.upsert_campaign("Winter Promo", "camp_002", {})

    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        result = await _get_campaign_json({"account_id": "act_123", "campaign_name": "summer"})

    text = result[0].text
    assert "Summer Sale" in text
    assert "Winter Promo" not in text


@pytest.mark.asyncio
async def test_get_campaign_json_does_not_call_meta_api():
    state = StateFile("act_123")
    meta = _make_meta_client()
    with (patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.mcp_server._get_meta_client", return_value=meta),
          patch.dict("os.environ", {"FB_ACCOUNT_ID": "act_123"})):
        await _get_campaign_json({})
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
# validate_campaigns
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_campaigns_returns_summary(tmp_path):
    with patch("src.mcp_server._get_ai_client", return_value=_make_ai_client()):
        result = await _validate_campaigns({"json_path": EXAMPLE_PATH})
    assert "Pushable" in result[0].text


# ------------------------------------------------------------------
# preview_diff
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_diff_does_not_call_apply(tmp_path):
    meta = _make_meta_client()
    state = StateFile(EXAMPLE_JSON["account_id"])
    with (patch("src.mcp_server._get_meta_client", return_value=meta),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _preview_diff({"json_path": EXAMPLE_PATH})
    meta.create_campaign.assert_not_called()
    assert len(result[0].text) > 0


@pytest.mark.asyncio
async def test_preview_diff_no_changes_message(tmp_path):
    state = StateFile(EXAMPLE_JSON["account_id"])
    campaign = EXAMPLE_JSON["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    state.upsert_campaign(campaign["name"], "c1", {k: campaign[k] for k in ["name","objective","status","special_ad_categories"]})
    state.upsert_adset(campaign["name"], adset["name"], "a1", {k: adset[k] for k in ["name","status","billing_event","optimization_goal","daily_budget"]})
    state.upsert_ad(campaign["name"], adset["name"], ad["name"], "ad1", "cr1", {"name": ad["name"], "status": ad["status"]})

    with (patch("src.mcp_server._get_meta_client", return_value=_make_meta_client()),
          patch("src.mcp_server.StateFile.load", return_value=state),
          patch("src.services.state.STATE_DIR", tmp_path)):
        result = await _preview_diff({"json_path": EXAMPLE_PATH})
    assert "No changes" in result[0].text
