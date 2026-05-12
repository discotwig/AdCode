import pytest
from unittest.mock import MagicMock

from src.reconcile import (
    fetch_actuals, diff_state, format_report,
    DriftReport, DriftItem, DriftType,
    _fix_mojibake, _values_equal,
)
from src.services.state import StateFile


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.list_campaigns.return_value = [
        {"id": "camp_001", "name": "Summer Sale", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}
    ]
    client.list_adsets.return_value = [
        {"id": "adset_001", "name": "US 25-54", "status": "PAUSED",
         "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS", "daily_budget": 5000}
    ]
    client.list_ads.return_value = [
        {"id": "ad_001", "name": "Creative v1", "status": "PAUSED"}
    ]
    return client


@pytest.fixture
def synced_state():
    s = StateFile("act_123")
    s.upsert_campaign("Summer Sale", "camp_001", {
        "name": "Summer Sale", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"
    })
    s.upsert_adset("Summer Sale", "US 25-54", "adset_001", {
        "name": "US 25-54", "status": "PAUSED",
        "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS", "daily_budget": 5000
    })
    s.upsert_ad("Summer Sale", "US 25-54", "Creative v1", "ad_001", "creative_001", {
        "name": "Creative v1", "status": "PAUSED"
    })
    return s


# ------------------------------------------------------------------
# fetch_actuals
# ------------------------------------------------------------------

class TestFetchActuals:
    def test_returns_dict_keyed_by_campaign_name(self, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        assert "Summer Sale" in actuals

    def test_campaign_contains_adsets(self, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        assert "US 25-54" in actuals["Summer Sale"]["ad_sets"]

    def test_adset_contains_ads(self, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        assert "Creative v1" in actuals["Summer Sale"]["ad_sets"]["US 25-54"]["ads"]

    def test_fb_id_preserved_on_campaign(self, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        assert actuals["Summer Sale"]["fb_id"] == "camp_001"


# ------------------------------------------------------------------
# diff_state — IN_SYNC
# ------------------------------------------------------------------

class TestDiffStateInSync:
    def test_no_drift_when_state_matches_actuals(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        report = diff_state(synced_state, actuals)
        assert not report.has_drift()

    def test_empty_state_and_empty_actuals_produces_no_drift(self):
        state = StateFile("act_empty")
        report = diff_state(state, {})
        assert not report.has_drift()


# ------------------------------------------------------------------
# diff_state — MISSING_FROM_FACEBOOK
# ------------------------------------------------------------------

class TestMissingFromFacebook:
    def test_detects_campaign_missing_from_facebook(self, synced_state):
        report = diff_state(synced_state, {})
        missing = [i for i in report.items if i.drift_type == DriftType.MISSING_FROM_FACEBOOK]
        assert any(i.object_type == "campaign" and i.name == "Summer Sale" for i in missing)

    def test_detects_adset_missing_from_facebook(self, synced_state):
        actuals = {
            "Summer Sale": {"fb_id": "camp_001", "status": "PAUSED",
                            "objective": "OUTCOME_TRAFFIC", "ad_sets": {}}
        }
        report = diff_state(synced_state, actuals)
        missing = [i for i in report.items if i.drift_type == DriftType.MISSING_FROM_FACEBOOK]
        assert any(i.object_type == "adset" for i in missing)

    def test_detects_ad_missing_from_facebook(self, synced_state):
        actuals = {
            "Summer Sale": {
                "fb_id": "camp_001", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC",
                "ad_sets": {
                    "US 25-54": {"fb_id": "adset_001", "status": "PAUSED",
                                 "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS",
                                 "daily_budget": 5000, "ads": {}}
                }
            }
        }
        report = diff_state(synced_state, actuals)
        missing = [i for i in report.items if i.drift_type == DriftType.MISSING_FROM_FACEBOOK]
        assert any(i.object_type == "ad" for i in missing)


# ------------------------------------------------------------------
# diff_state — MISSING_FROM_STATE
# ------------------------------------------------------------------

class TestMissingFromState:
    def test_detects_campaign_missing_from_state(self, mock_client):
        empty_state = StateFile("act_123")
        actuals = fetch_actuals("act_123", mock_client)
        report = diff_state(empty_state, actuals)
        missing = [i for i in report.items if i.drift_type == DriftType.MISSING_FROM_STATE]
        assert any(i.object_type == "campaign" for i in missing)

    def test_detects_adset_missing_from_state(self, mock_client):
        state = StateFile("act_123")
        state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale", "status": "PAUSED"})
        actuals = fetch_actuals("act_123", mock_client)
        report = diff_state(state, actuals)
        missing = [i for i in report.items if i.drift_type == DriftType.MISSING_FROM_STATE]
        assert any(i.object_type == "adset" for i in missing)


# ------------------------------------------------------------------
# diff_state — FIELD_MISMATCH
# ------------------------------------------------------------------

class TestFieldMismatch:
    def test_detects_campaign_status_mismatch(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        actuals["Summer Sale"]["status"] = "ACTIVE"
        report = diff_state(synced_state, actuals)
        mismatches = [i for i in report.items if i.drift_type == DriftType.FIELD_MISMATCH]
        assert any(i.object_type == "campaign" for i in mismatches)

    def test_detects_adset_budget_mismatch(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        actuals["Summer Sale"]["ad_sets"]["US 25-54"]["daily_budget"] = 9999
        report = diff_state(synced_state, actuals)
        mismatches = [i for i in report.items if i.drift_type == DriftType.FIELD_MISMATCH]
        assert any(i.object_type == "adset" for i in mismatches)

    def test_detects_ad_status_mismatch(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        actuals["Summer Sale"]["ad_sets"]["US 25-54"]["ads"]["Creative v1"]["status"] = "ACTIVE"
        report = diff_state(synced_state, actuals)
        mismatches = [i for i in report.items if i.drift_type == DriftType.FIELD_MISMATCH]
        assert any(i.object_type == "ad" for i in mismatches)


# ------------------------------------------------------------------
# format_report
# ------------------------------------------------------------------

class TestFormatReport:
    def test_no_drift_message(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        report = diff_state(synced_state, actuals)
        text = format_report(report)
        assert "in sync" in text.lower()

    def test_non_empty_for_drift(self, synced_state):
        report = diff_state(synced_state, {})
        text = format_report(report)
        assert len(text) > 0
        assert "MISSING_FROM_FACEBOOK" in text

    def test_includes_object_name(self, synced_state):
        report = diff_state(synced_state, {})
        text = format_report(report)
        assert "Summer Sale" in text

    def test_includes_field_mismatch_details(self, synced_state, mock_client):
        actuals = fetch_actuals("act_123", mock_client)
        actuals["Summer Sale"]["status"] = "ACTIVE"
        report = diff_state(synced_state, actuals)
        text = format_report(report)
        assert "status" in text


# ------------------------------------------------------------------
# Bug fixes
# ------------------------------------------------------------------

class TestFixMojibake:
    def test_em_dash_mojibake_is_repaired(self):
        garbled = "AdCode Demo \xe2\x80\x94 Brand Awareness"
        assert _fix_mojibake(garbled) == "AdCode Demo — Brand Awareness"

    def test_clean_ascii_is_unchanged(self):
        assert _fix_mojibake("Summer Sale") == "Summer Sale"

    def test_already_valid_unicode_is_unchanged(self):
        assert _fix_mojibake("Café") == "Café"

    def test_fetch_actuals_repairs_mojibake_in_campaign_name(self):
        client = MagicMock()
        client.list_campaigns.return_value = [
            {"id": "c1", "name": "AdCode Demo \xe2\x80\x94 Brand Awareness", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}
        ]
        client.list_adsets.return_value = []
        actuals = fetch_actuals("act_123", client)
        assert "AdCode Demo — Brand Awareness" in actuals


class TestValuesEqual:
    def test_int_equals_string_of_same_number(self):
        assert _values_equal(1000, "1000")

    def test_string_equals_int_of_same_number(self):
        assert _values_equal("1000", 1000)

    def test_different_numbers_are_not_equal(self):
        assert not _values_equal(1000, 9999)

    def test_non_numeric_strings_use_exact_match(self):
        assert _values_equal("PAUSED", "PAUSED")
        assert not _values_equal("PAUSED", "ACTIVE")

    def test_budget_string_from_facebook_does_not_trigger_mismatch(self, synced_state=None):
        # Simulates Facebook returning daily_budget as a string
        state = StateFile("act_123")
        state.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"})
        state.upsert_adset("Summer Sale", "US 25-54", "adset_001", {
            "name": "US 25-54", "status": "PAUSED",
            "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS", "daily_budget": 5000
        })
        state.upsert_ad("Summer Sale", "US 25-54", "Creative v1", "ad_001", "creative_001", {"name": "Creative v1", "status": "PAUSED"})

        actuals = {
            "Summer Sale": {
                "fb_id": "camp_001", "name": "Summer Sale", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC",
                "ad_sets": {
                    "US 25-54": {
                        "fb_id": "adset_001", "name": "US 25-54", "status": "PAUSED",
                        "billing_event": "IMPRESSIONS", "optimization_goal": "LINK_CLICKS",
                        "daily_budget": "5000",  # Facebook returns as string
                        "ads": {"Creative v1": {"fb_id": "ad_001", "name": "Creative v1", "status": "PAUSED"}}
                    }
                }
            }
        }
        report = diff_state(state, actuals)
        assert not report.has_drift()
