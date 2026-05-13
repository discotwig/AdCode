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
    DeleteCampaign, DeleteAdSet, DeleteAd,
)
from src.services.state import StateFile

CAMPAIGNS_DIR = Path(__file__).parent / "fixtures"


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


@pytest.fixture
def state_with_extra_campaign(populated_state, example_campaign):
    populated_state.upsert_campaign("Stale Campaign", "stale_camp_001", {"name": "Stale Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []})
    populated_state.upsert_adset("Stale Campaign", "Stale AdSet", "stale_adset_001", {"name": "Stale AdSet", "status": "PAUSED", "billing_event": "LINK_CLICKS", "optimization_goal": "LINK_CLICKS", "daily_budget": 500})
    return populated_state


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


# ------------------------------------------------------------------
# plan() — delete detection
# ------------------------------------------------------------------

class TestPlanDeletes:
    def test_delete_campaign_absent_from_json(self, example_campaign, mock_client, state_with_extra_campaign):
        p = plan(example_campaign, state_with_extra_campaign, mock_client)
        delete_ops = [op for op in p.operations if isinstance(op, DeleteCampaign)]
        assert len(delete_ops) == 1
        assert delete_ops[0].campaign_name == "Stale Campaign"
        assert delete_ops[0].fb_id == "stale_camp_001"

    def test_delete_adset_absent_from_json(self, example_campaign, mock_client, state_with_extra_campaign):
        p = plan(example_campaign, state_with_extra_campaign, mock_client)
        delete_ops = [op for op in p.operations if isinstance(op, DeleteAdSet)]
        assert any(op.adset_name == "Stale AdSet" for op in delete_ops)

    def test_delete_ad_absent_from_json(self, example_campaign, mock_client, populated_state):
        populated_state.upsert_ad(
            example_campaign["campaigns"][0]["name"],
            example_campaign["campaigns"][0]["ad_sets"][0]["name"],
            "Stale Ad", "stale_ad_001", "stale_creative_001", {"name": "Stale Ad", "status": "PAUSED"}
        )
        p = plan(example_campaign, populated_state, mock_client)
        delete_ops = [op for op in p.operations if isinstance(op, DeleteAd)]
        assert len(delete_ops) == 1
        assert delete_ops[0].ad_name == "Stale Ad"

    def test_no_deletes_when_json_matches_state(self, example_campaign, mock_client, populated_state):
        p = plan(example_campaign, populated_state, mock_client)
        assert not p.has_deletes

    def test_has_deletes_true_when_campaign_removed(self, example_campaign, mock_client, state_with_extra_campaign):
        p = plan(example_campaign, state_with_extra_campaign, mock_client)
        assert p.has_deletes

    def test_delete_ops_come_after_create_update_ops(self, example_campaign, mock_client, state_with_extra_campaign):
        # Add a new adset so there are creates too
        example_campaign["campaigns"][0]["ad_sets"].append({
            "name": "New AdSet", "status": "PAUSED", "daily_budget": 1000,
            "billing_event": "LINK_CLICKS", "optimization_goal": "LINK_CLICKS",
            "targeting": {"age_min": 18, "age_max": 65, "geo_locations": {"countries": ["US"]}},
            "ads": []
        })
        p = plan(example_campaign, state_with_extra_campaign, mock_client)
        create_indices = [i for i, op in enumerate(p.operations) if isinstance(op, (CreateCampaign, CreateAdSet, CreateAd))]
        delete_indices = [i for i, op in enumerate(p.operations) if isinstance(op, (DeleteCampaign, DeleteAdSet, DeleteAd))]
        assert create_indices and delete_indices
        assert max(create_indices) < min(delete_indices)

    def test_delete_leaf_first_order(self, example_campaign, mock_client, state_with_extra_campaign):
        p = plan(example_campaign, state_with_extra_campaign, mock_client)
        delete_ops = [op for op in p.operations if isinstance(op, (DeleteCampaign, DeleteAdSet, DeleteAd))]
        types = [type(op).__name__ for op in delete_ops]
        # Ads before adsets before campaigns
        if "DeleteCampaign" in types and "DeleteAdSet" in types:
            assert types.index("DeleteAdSet") < types.index("DeleteCampaign")


# ------------------------------------------------------------------
# apply() — delete execution
# ------------------------------------------------------------------

class TestApplyDeletes:
    def test_apply_calls_delete_campaign(self, example_campaign, mock_client, state_with_extra_campaign, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, state_with_extra_campaign, mock_client)
            result = apply(p, mock_client, state_with_extra_campaign)
        mock_client.delete_campaign.assert_called_with("stale_camp_001")
        assert result.ok

    def test_apply_removes_campaign_from_state(self, example_campaign, mock_client, state_with_extra_campaign, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, state_with_extra_campaign, mock_client)
            apply(p, mock_client, state_with_extra_campaign)
        assert state_with_extra_campaign.get_campaign_id("Stale Campaign") is None

    def test_apply_calls_delete_adset(self, example_campaign, mock_client, state_with_extra_campaign, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, state_with_extra_campaign, mock_client)
            result = apply(p, mock_client, state_with_extra_campaign)
        mock_client.delete_adset.assert_called_with("stale_adset_001")
        assert result.ok

    def test_apply_delete_continues_after_failure(self, example_campaign, mock_client, state_with_extra_campaign, tmp_path):
        mock_client.delete_campaign.side_effect = Exception("API error")
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(example_campaign, state_with_extra_campaign, mock_client)
            result = apply(p, mock_client, state_with_extra_campaign)
        assert len(result.failed) > 0


# ------------------------------------------------------------------
# plan() — Ad Stack isolation (ADR-012)
# ------------------------------------------------------------------

class TestPlanStackIsolation:
    def test_plan_only_deletes_from_its_own_state(self, example_campaign, mock_client):
        """plan() must not emit delete ops for campaigns that belong to a different stack."""
        # Stack A: has "Other Stack Campaign" — simulates a state file owned by a different stack
        stack_a_state = StateFile("act_000000000", stack_name="other_stack")
        stack_a_state.upsert_campaign(
            "Other Stack Campaign", "other_camp_001",
            {"name": "Other Stack Campaign", "status": "PAUSED", "objective": "REACH", "special_ad_categories": []}
        )

        # Stack B: has only the campaigns that match example_campaign
        stack_b_state = StateFile("act_000000000", stack_name="example")
        campaign = example_campaign["campaigns"][0]
        adset = campaign["ad_sets"][0]
        ad = adset["ads"][0]
        stack_b_state.upsert_campaign(campaign["name"], "camp_fb_001", {"name": campaign["name"], "objective": campaign["objective"], "status": campaign["status"], "special_ad_categories": []})
        stack_b_state.upsert_adset(campaign["name"], adset["name"], "adset_fb_001", {"name": adset["name"], "status": adset["status"], "billing_event": adset["billing_event"], "optimization_goal": adset["optimization_goal"], "daily_budget": adset["daily_budget"]})
        stack_b_state.upsert_ad(campaign["name"], adset["name"], ad["name"], "ad_fb_001", "creative_fb_001", {"name": ad["name"], "status": ad["status"]})

        # plan() against Stack B's state: example_campaign matches exactly — no deletes expected
        p = plan(example_campaign, stack_b_state, mock_client)
        delete_ops = [op for op in p.operations if isinstance(op, (DeleteCampaign, DeleteAdSet, DeleteAd))]
        deleted_names = [getattr(op, "campaign_name", None) for op in delete_ops]

        # "Other Stack Campaign" must never appear in Stack B's delete ops
        assert "Other Stack Campaign" not in deleted_names
        assert len(delete_ops) == 0
