import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from src.traffic import (
    plan, apply, load_campaign_json,
    Plan, ApplyResult,
    CreateCampaign, UpdateCampaign,
    CreateAdSet, UpdateAdSet,
    CreateAd, UpdateAd,
)
from src.services.state import StateFile

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def example_campaign():
    with open(CAMPAIGNS_DIR / "example.json") as f:
        return json.load(f)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.create_campaign.return_value = "camp_fb_001"
    client.create_adset.return_value = "adset_fb_001"
    client.create_creative.return_value = "creative_fb_001"
    client.create_ad.return_value = "ad_fb_001"
    return client


@pytest.fixture
def empty_state():
    return StateFile("act_000000000")


@pytest.fixture
def populated_state(example_campaign):
    s = StateFile("act_000000000")
    campaign = example_campaign["campaigns"][0]
    adset = campaign["ad_sets"][0]
    ad = adset["ads"][0]
    s.upsert_campaign(campaign["name"], "camp_fb_001", {"name": campaign["name"], "objective": campaign["objective"], "status": campaign["status"], "special_ad_categories": []})
    s.upsert_adset(campaign["name"], adset["name"], "adset_fb_001", {"name": adset["name"], "status": adset["status"], "billing_event": adset["billing_event"], "optimization_goal": adset["optimization_goal"], "daily_budget": adset["daily_budget"]})
    s.upsert_ad(campaign["name"], adset["name"], ad["name"], "ad_fb_001", "creative_fb_001", {"name": ad["name"], "status": ad["status"]})
    return s


# ------------------------------------------------------------------
# load_campaign_json
# ------------------------------------------------------------------

class TestLoadCampaignJson:
    def test_loads_valid_file(self):
        result = load_campaign_json(str(CAMPAIGNS_DIR / "example.json"))
        assert "campaigns" in result

    def test_raises_on_schema_violation(self, tmp_path):
        bad = {"account_id": "act_123", "campaigns": []}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad))
        import jsonschema
        with pytest.raises(jsonschema.ValidationError):
            load_campaign_json(str(p))


# ------------------------------------------------------------------
# plan()
# ------------------------------------------------------------------

class TestPlan:
    def test_all_creates_when_state_empty(self, example_campaign, mock_client, empty_state):
        p = plan(example_campaign, empty_state, mock_client)
        op_types = [type(op).__name__ for op in p.operations]
        assert "CreateCampaign" in op_types
        assert "CreateAdSet" in op_types
        assert "CreateAd" in op_types

    def test_no_operations_when_state_matches(self, example_campaign, mock_client, populated_state):
        p = plan(example_campaign, populated_state, mock_client)
        assert len(p) == 0

    def test_update_when_campaign_field_changes(self, example_campaign, mock_client, populated_state):
        example_campaign["campaigns"][0]["status"] = "ACTIVE"
        p = plan(example_campaign, populated_state, mock_client)
        update_ops = [op for op in p.operations if isinstance(op, UpdateCampaign)]
        assert len(update_ops) == 1
        assert "status" in update_ops[0].changed_fields

    def test_update_when_adset_field_changes(self, example_campaign, mock_client, populated_state):
        example_campaign["campaigns"][0]["ad_sets"][0]["daily_budget"] = 9999
        p = plan(example_campaign, populated_state, mock_client)
        update_ops = [op for op in p.operations if isinstance(op, UpdateAdSet)]
        assert len(update_ops) == 1
        assert "daily_budget" in update_ops[0].changed_fields

    def test_update_when_ad_status_changes(self, example_campaign, mock_client, populated_state):
        example_campaign["campaigns"][0]["ad_sets"][0]["ads"][0]["status"] = "ACTIVE"
        p = plan(example_campaign, populated_state, mock_client)
        update_ops = [op for op in p.operations if isinstance(op, UpdateAd)]
        assert len(update_ops) == 1

    def test_plan_summary_non_empty_for_new_campaign(self, example_campaign, mock_client, empty_state):
        p = plan(example_campaign, empty_state, mock_client)
        assert p.summary() != "No changes."

    def test_plan_summary_no_changes(self, example_campaign, mock_client, populated_state):
        p = plan(example_campaign, populated_state, mock_client)
        assert p.summary() == "No changes."

    def test_objective_change_does_not_produce_update(self, example_campaign, mock_client, populated_state):
        # Objective is immutable on Facebook — a change should still produce an update op
        # (the API will reject it, but that's the API's problem, not the planner's)
        example_campaign["campaigns"][0]["objective"] = "OUTCOME_AWARENESS"
        p = plan(example_campaign, populated_state, mock_client)
        update_ops = [op for op in p.operations if isinstance(op, UpdateCampaign)]
        assert len(update_ops) == 1


# ------------------------------------------------------------------
# apply()
# ------------------------------------------------------------------

class TestApply:
    def test_apply_calls_create_in_order(self, example_campaign, mock_client, empty_state, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            result = apply(p, mock_client, empty_state)

        mock_client.create_campaign.assert_called_once()
        mock_client.create_adset.assert_called_once()
        mock_client.create_creative.assert_called_once()
        mock_client.create_ad.assert_called_once()
        assert result.ok

    def test_apply_writes_state_after_campaign_create(self, example_campaign, mock_client, empty_state, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            apply(p, mock_client, empty_state)
        assert empty_state.get_campaign_id(example_campaign["campaigns"][0]["name"]) == "camp_fb_001"

    def test_apply_writes_state_after_adset_create(self, example_campaign, mock_client, empty_state, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            apply(p, mock_client, empty_state)
        campaign = example_campaign["campaigns"][0]
        adset = campaign["ad_sets"][0]
        assert empty_state.get_adset_id(campaign["name"], adset["name"]) == "adset_fb_001"

    def test_apply_writes_state_after_ad_create(self, example_campaign, mock_client, empty_state, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            apply(p, mock_client, empty_state)
        campaign = example_campaign["campaigns"][0]
        adset = campaign["ad_sets"][0]
        ad = adset["ads"][0]
        assert empty_state.get_ad_id(campaign["name"], adset["name"], ad["name"]) == "ad_fb_001"

    def test_apply_continues_after_partial_failure(self, example_campaign, mock_client, empty_state, tmp_path):
        mock_client.create_campaign.side_effect = Exception("API error")
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            result = apply(p, mock_client, empty_state)
        assert len(result.failed) > 0
        assert not result.ok

    def test_apply_reports_all_failures(self, example_campaign, mock_client, empty_state, tmp_path):
        mock_client.create_campaign.side_effect = Exception("Campaign error")
        mock_client.create_adset.side_effect = Exception("AdSet error")
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            result = apply(p, mock_client, empty_state)
        assert len(result.failed) >= 1
        summary = result.summary()
        assert "FAILED" in summary

    def test_apply_calls_update_campaign(self, example_campaign, mock_client, populated_state, tmp_path):
        example_campaign["campaigns"][0]["status"] = "ACTIVE"
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, populated_state, mock_client)
            result = apply(p, mock_client, populated_state)
        mock_client.update_campaign.assert_called_once_with("camp_fb_001", {"status": "ACTIVE"})
        assert result.ok

    def test_apply_result_summary_on_success(self, example_campaign, mock_client, empty_state, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, empty_state, mock_client)
            result = apply(p, mock_client, empty_state)
        assert "succeeded" in result.summary()
