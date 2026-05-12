import copy
import json
import pytest
from pathlib import Path
import jsonschema

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
CAMPAIGNS_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def campaign_schema():
    with open(SCHEMAS_DIR / "campaign.schema.json") as f:
        return json.load(f)


@pytest.fixture
def state_schema():
    with open(SCHEMAS_DIR / "state.schema.json") as f:
        return json.load(f)


@pytest.fixture
def example_campaign():
    with open(CAMPAIGNS_DIR / "example.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def valid_state():
    return {
        "account_id": "act_123456789",
        "last_pushed_at": "2026-05-11T10:00:00Z",
        "campaigns": {
            "Example — Summer Sale Traffic": {
                "fb_id": "120200000000001",
                "params": {"name": "Example — Summer Sale Traffic", "objective": "OUTCOME_TRAFFIC"},
                "ad_sets": {
                    "US 25-54 All Genders — Broad": {
                        "fb_id": "120200000000002",
                        "params": {"name": "US 25-54 All Genders — Broad"},
                        "ads": {
                            "Summer Sale — Static Image v1": {
                                "fb_id": "120200000000003",
                                "creative_id": "120200000000004",
                                "params": {"name": "Summer Sale — Static Image v1"}
                            }
                        }
                    }
                }
            }
        }
    }


class TestCampaignSchema:
    def test_example_passes_schema(self, campaign_schema, example_campaign):
        jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_account_id_fails(self, campaign_schema, example_campaign):
        del example_campaign["account_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_account_id_format_fails(self, campaign_schema, example_campaign):
        example_campaign["account_id"] = "123456789"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_campaigns_key_fails(self, campaign_schema):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"account_id": "act_123"}, campaign_schema)

    def test_empty_campaigns_array_fails(self, campaign_schema):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"account_id": "act_123", "campaigns": []}, campaign_schema)

    def test_legacy_objective_is_valid(self, campaign_schema, example_campaign):
        # Schema accepts legacy Facebook objectives for campaigns imported from Ads Manager
        example_campaign["campaigns"][0]["objective"] = "LINK_CLICKS"
        jsonschema.validate(example_campaign, campaign_schema)  # must not raise

    def test_invalid_status_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["status"] = "RUNNING"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_deleted_status_not_allowed(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["status"] = "DELETED"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_special_ad_categories_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["special_ad_categories"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_special_ad_category_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["special_ad_categories"] = ["DRUGS"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_ad_sets_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_empty_ad_sets_is_valid(self, campaign_schema, example_campaign):
        # Campaigns imported from Facebook may have no ad sets tracked yet
        example_campaign["campaigns"][0]["ad_sets"] = []
        jsonschema.validate(example_campaign, campaign_schema)  # must not raise

    def test_invalid_billing_event_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["billing_event"] = "CLICKS"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_optimization_goal_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["optimization_goal"] = "SALES"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_targeting_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["targeting"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_geo_locations_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["targeting"]["geo_locations"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_empty_ads_array_is_valid(self, campaign_schema, example_campaign):
        # Ad sets imported from Facebook may have no ads yet
        example_campaign["campaigns"][0]["ad_sets"][0]["ads"] = []
        jsonschema.validate(example_campaign, campaign_schema)  # must not raise

    def test_missing_ads_key_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["ads"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_creative_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_missing_object_story_spec_fails(self, campaign_schema, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_link_not_uri_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"][
            "object_story_spec"]["link_data"]["link"] = "not-a-url"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_cta_type_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"][
            "object_story_spec"]["link_data"]["call_to_action"]["type"] = "INVALID_CTA"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_spend_cap_optional(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["spend_cap"] = 100000
        jsonschema.validate(example_campaign, campaign_schema)

    def test_multiple_campaigns_valid(self, campaign_schema, example_campaign):
        second = copy.deepcopy(example_campaign["campaigns"][0])
        second["name"] = "Second Campaign"
        example_campaign["campaigns"].append(second)
        jsonschema.validate(example_campaign, campaign_schema)

    def test_gender_targeting_valid(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["targeting"]["genders"] = [1]
        jsonschema.validate(example_campaign, campaign_schema)

    def test_invalid_gender_value_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["targeting"]["genders"] = [3]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)

    def test_age_min_below_18_fails(self, campaign_schema, example_campaign):
        example_campaign["campaigns"][0]["ad_sets"][0]["targeting"]["age_min"] = 17
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example_campaign, campaign_schema)


class TestStateSchema:
    def test_valid_state_passes(self, state_schema, valid_state):
        jsonschema.validate(valid_state, state_schema)

    def test_empty_campaigns_passes(self, state_schema):
        jsonschema.validate({
            "account_id": "act_123456789",
            "last_pushed_at": "2026-05-11T10:00:00Z",
            "campaigns": {}
        }, state_schema)

    def test_missing_account_id_fails(self, state_schema, valid_state):
        del valid_state["account_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(valid_state, state_schema)

    def test_missing_last_pushed_at_fails(self, state_schema, valid_state):
        del valid_state["last_pushed_at"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(valid_state, state_schema)

    def test_missing_fb_id_in_campaign_fails(self, state_schema, valid_state):
        del valid_state["campaigns"]["Example — Summer Sale Traffic"]["fb_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(valid_state, state_schema)

    def test_missing_fb_id_in_adset_fails(self, state_schema, valid_state):
        adset = valid_state["campaigns"]["Example — Summer Sale Traffic"]["ad_sets"]["US 25-54 All Genders — Broad"]
        del adset["fb_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(valid_state, state_schema)

    def test_missing_creative_id_in_ad_fails(self, state_schema, valid_state):
        ad = (valid_state["campaigns"]["Example — Summer Sale Traffic"]
              ["ad_sets"]["US 25-54 All Genders — Broad"]
              ["ads"]["Summer Sale — Static Image v1"])
        del ad["creative_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(valid_state, state_schema)
