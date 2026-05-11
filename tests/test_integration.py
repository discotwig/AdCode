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

from src.api.meta import MetaClient
from src.services.state import StateFile
from src.traffic import load_campaign_json, plan, apply as apply_plan
from src.reconcile import fetch_actuals, diff_state, DriftType

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

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
    def test_create_campaign_writes_state_and_matches_actuals(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = load_campaign_json(str(CAMPAIGNS_DIR / "example.json"))
        campaign_json["account_id"] = account_id

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            result = apply_plan(p, client, state)

        assert result.ok, f"Apply failed: {result.summary()}"
        campaign_name = campaign_json["campaigns"][0]["name"]
        assert state.get_campaign_id(campaign_name) is not None

        actuals = fetch_actuals(account_id, client)
        report = diff_state(state, actuals)
        drift_items = report.drift_items()
        assert not drift_items, f"Drift detected after push: {drift_items}"

    def test_idempotent_repush_produces_updates_not_creates(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = load_campaign_json(str(CAMPAIGNS_DIR / "example.json"))
        campaign_json["account_id"] = account_id

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p1 = plan(campaign_json, state, client)
            apply_plan(p1, client, state)

            # Second push — state is populated, no changes expected
            p2 = plan(campaign_json, state, client)
            assert len(p2) == 0, f"Expected no-op plan, got: {p2.summary()}"

    def test_drift_detected_after_manual_change(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = load_campaign_json(str(CAMPAIGNS_DIR / "example.json"))
        campaign_json["account_id"] = account_id

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            apply_plan(p, client, state)

            campaign_name = campaign_json["campaigns"][0]["name"]
            fb_id = state.get_campaign_id(campaign_name)

            # Simulate manual change outside AdCode
            client.update_campaign(fb_id, {"status": "ACTIVE"})

        actuals = fetch_actuals(account_id, client)
        report = diff_state(state, actuals)
        mismatch_items = [i for i in report.items if i.drift_type == DriftType.FIELD_MISMATCH]
        assert len(mismatch_items) > 0, "Expected field mismatch drift after manual change"

    def test_pause_campaign_reflected_in_actuals(self, tmp_path):
        client = _make_client()
        account_id = os.environ["FB_ACCOUNT_ID"]
        campaign_json = load_campaign_json(str(CAMPAIGNS_DIR / "example.json"))
        campaign_json["account_id"] = account_id
        campaign_json["campaigns"][0]["status"] = "ACTIVE"

        state = StateFile(account_id)
        with patch("src.services.state.STATE_DIR", tmp_path):
            p = plan(campaign_json, state, client)
            apply_plan(p, client, state)

            campaign_name = campaign_json["campaigns"][0]["name"]
            fb_id = state.get_campaign_id(campaign_name)
            client.pause_campaign(fb_id)

        actual = client.get_campaign(fb_id)
        assert actual.get("status") in ("PAUSED", "paused")
