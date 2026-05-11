"""
Integration tests — require a live Facebook Marketing API sandbox account.

Skipped automatically when FB credentials are not set in the environment.
Run manually with:
  FB_APP_ID=... FB_APP_SECRET=... FB_ACCESS_TOKEN=... FB_ACCOUNT_ID=... pytest tests/test_integration.py -v

A sandbox account creates real objects in PAUSED state. Clean up your account
after running these tests or use a dedicated test ad account.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from dotenv import load_dotenv

load_dotenv()

from src.api.meta import MetaClient
from src.services.state import StateFile
from src.traffic import load_campaign_json, plan, apply as apply_plan
from src.reconcile import fetch_actuals, diff_state, DriftType  # noqa: F401 (kept for future use)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


def _campaign_no_ads(account_id: str) -> dict:
    """Minimal campaign fixture with no ads — avoids the Page ID requirement."""
    return {
        "account_id": account_id,
        "campaigns": [
            {
                "name": "AdCode Integration Test Campaign",
                "objective": "OUTCOME_TRAFFIC",
                "status": "PAUSED",
                "special_ad_categories": [],
                "ad_sets": [
                    {
                        "name": "AdCode Integration Test AdSet",
                        "status": "PAUSED",
                        "daily_budget": 500,
                        "billing_event": "LINK_CLICKS",
                        "optimization_goal": "LINK_CLICKS",
                        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                        "targeting": {
                            "age_min": 25,
                            "age_max": 54,
                            "geo_locations": {"countries": ["US"]},
                            "targeting_automation": {"advantage_audience": 0},
                        },
                        "ads": [],
                    }
                ],
            }
        ],
    }


_CREDS_PRESENT = all(
    os.environ.get(k) for k in ("FB_APP_ID", "FB_APP_SECRET", "FB_ACCESS_TOKEN", "FB_ACCOUNT_ID")
)
skip_without_creds = pytest.mark.skipif(
    not _CREDS_PRESENT,
    reason="Facebook API credentials not set — skipping integration tests.",
)


def _make_client() -> MetaClient:
    return MetaClient(
        app_id=os.environ["FB_APP_ID"],
        app_secret=os.environ["FB_APP_SECRET"],
        access_token=os.environ["FB_ACCESS_TOKEN"],
        account_id=os.environ["FB_ACCOUNT_ID"],
    )


@skip_without_creds
class TestPushAndVerify:
    def setup_method(self):
        import time
        self._created_campaign_ids = []
        time.sleep(10)

    def teardown_method(self):
        client = _make_client()
        for fb_id in getattr(self, "_created_campaign_ids", []):
            try:
                client.delete_campaign(fb_id)
            except Exception:
                pass

    def _track(self, state, campaign_name: str) -> str | None:
        fb_id = state.get_campaign_id(campaign_name)
        if fb_id:
            self._created_campaign_ids.append(fb_id)
        return fb_id

    def test_create_campaign_writes_state_and_matches_actuals(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = _campaign_no_ads(account_id)

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            result = apply_plan(p, client, state)

        assert result.ok, f"Apply failed: {result.summary()}"
        campaign_name = campaign_json["campaigns"][0]["name"]
        fb_id = self._track(state, campaign_name)
        assert fb_id is not None

        # Verify the campaign exists on Facebook and is PAUSED
        actual = client.get_campaign(fb_id)
        assert actual.get("status") in ("PAUSED", "paused"), f"Unexpected status: {actual}"

    def test_idempotent_repush_produces_updates_not_creates(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = _campaign_no_ads(account_id)

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p1 = plan(campaign_json, state, client)
            apply_plan(p1, client, state)
            self._track(state, campaign_json["campaigns"][0]["name"])

            # Second push — state is populated, no changes expected
            p2 = plan(campaign_json, state, client)
            assert len(p2) == 0, f"Expected no-op plan, got: {p2.summary()}"

    def test_drift_detected_after_manual_change(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = _campaign_no_ads(account_id)

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            apply_plan(p, client, state)

            campaign_name = campaign_json["campaigns"][0]["name"]
            fb_id = self._track(state, campaign_name)

            # Simulate manual change outside AdCode
            client.update_campaign(fb_id, {"status": "ACTIVE"})

        # Verify drift directly: state says PAUSED, Facebook says ACTIVE
        actual = client.get_campaign(fb_id)
        state_status = state.get_campaign_params(campaign_name).get("status")
        actual_status = actual.get("status", "").upper()
        assert state_status != actual_status, (
            f"Expected drift: state={state_status}, actual={actual_status}"
        )

    def test_pause_campaign_reflected_in_actuals(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = _campaign_no_ads(account_id)
        campaign_json["campaigns"][0]["status"] = "ACTIVE"

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            apply_plan(p, client, state)

            campaign_name = campaign_json["campaigns"][0]["name"]
            fb_id = self._track(state, campaign_name)
            client.pause_campaign(fb_id)

        actual = client.get_campaign(fb_id)
        assert actual.get("status") in ("PAUSED", "paused")
