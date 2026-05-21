from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.budget import (
    BudgetDelta,
    CapResult,
    check_cap,
    estimate_delta,
    format_budget_section,
)
from src.services.state import StateFile
from src.traffic import (
    CreateAdSet,
    CreateCampaign,
    DeleteAdSet,
    DeleteCampaign,
    Plan,
    UpdateAdSet,
    UpdateCampaign,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_state() -> StateFile:
    return StateFile("act_000000000")


def _state_with_adset(campaign_name: str, adset_name: str, params: dict) -> StateFile:
    state = StateFile("act_000000000")
    state.upsert_campaign(campaign_name, "camp_001", {"name": campaign_name})
    state.upsert_adset(campaign_name, adset_name, "adset_001", params)
    return state


def _state_with_campaign(campaign_name: str, params: dict) -> StateFile:
    state = StateFile("act_000000000")
    state.upsert_campaign(campaign_name, "camp_001", params)
    return state


def _template(campaigns=None):
    return {
        "account_id": "act_000000000",
        "campaigns": campaigns or [],
    }


def _campaign(name="Camp A", daily_budget=None, spend_cap=None, ad_sets=None):
    c = {
        "name": name,
        "objective": "OUTCOME_TRAFFIC",
        "status": "PAUSED",
        "special_ad_categories": [],
        "ad_sets": ad_sets or [],
    }
    if daily_budget is not None:
        c["daily_budget"] = daily_budget
    if spend_cap is not None:
        c["spend_cap"] = spend_cap
    return c


def _adset(name="Ad Set A", daily_budget=None, lifetime_budget=None):
    a = {
        "name": name,
        "status": "PAUSED",
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LINK_CLICKS",
        "targeting": {"geo_locations": {"countries": ["US"]}},
        "ads": [],
    }
    if daily_budget is not None:
        a["daily_budget"] = daily_budget
    if lifetime_budget is not None:
        a["lifetime_budget"] = lifetime_budget
    return a


# ---------------------------------------------------------------------------
# estimate_delta — creates
# ---------------------------------------------------------------------------


class TestEstimateDeltaCreates:
    def test_create_campaign_adds_daily_budget(self):
        camp = _campaign(daily_budget=5000)
        p = Plan(operations=[CreateCampaign(campaign=camp)])
        state = _empty_state()
        template = _template([camp])
        delta = estimate_delta(p, state, template)
        assert delta.added == 50  # 5000 cents = $50

    def test_create_adset_adds_daily_budget(self):
        adset = _adset(daily_budget=5000)
        p = Plan(operations=[CreateAdSet(campaign_name="Camp A", adset=adset)])
        state = _empty_state()
        template = _template([_campaign(ad_sets=[adset])])
        delta = estimate_delta(p, state, template)
        assert delta.added == 50

    def test_create_adset_adds_lifetime_budget(self):
        adset = _adset(lifetime_budget=100000)
        p = Plan(operations=[CreateAdSet(campaign_name="Camp A", adset=adset)])
        state = _empty_state()
        template = _template([_campaign(ad_sets=[adset])])
        delta = estimate_delta(p, state, template)
        assert delta.added == 1000  # 100000 cents = $1000

    def test_create_campaign_with_no_budget_adds_zero(self):
        camp = _campaign()
        p = Plan(operations=[CreateCampaign(campaign=camp)])
        state = _empty_state()
        template = _template([camp])
        delta = estimate_delta(p, state, template)
        assert delta.added == 0

    def test_create_adset_with_no_budget_adds_zero(self):
        adset = _adset()
        p = Plan(operations=[CreateAdSet(campaign_name="Camp A", adset=adset)])
        state = _empty_state()
        template = _template([_campaign(ad_sets=[adset])])
        delta = estimate_delta(p, state, template)
        assert delta.added == 0

    def test_spend_cap_not_counted_as_budget(self):
        camp = _campaign(spend_cap=1000000)
        p = Plan(operations=[CreateCampaign(campaign=camp)])
        state = _empty_state()
        template = _template([camp])
        delta = estimate_delta(p, state, template)
        assert delta.added == 0


# ---------------------------------------------------------------------------
# estimate_delta — deletes
# ---------------------------------------------------------------------------


class TestEstimateDeltaDeletes:
    def test_delete_adset_removes_daily_budget_from_state(self):
        state = _state_with_adset("Camp A", "Ad Set A", {"daily_budget": 5000})
        p = Plan(
            operations=[
                DeleteAdSet(
                    campaign_name="Camp A", adset_name="Ad Set A", fb_id="adset_001"
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.removed == 50

    def test_delete_adset_removes_lifetime_budget_from_state(self):
        state = _state_with_adset("Camp A", "Ad Set A", {"lifetime_budget": 200000})
        p = Plan(
            operations=[
                DeleteAdSet(
                    campaign_name="Camp A", adset_name="Ad Set A", fb_id="adset_001"
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.removed == 2000

    def test_delete_campaign_removes_daily_budget_from_state(self):
        state = _state_with_campaign("Camp A", {"daily_budget": 10000})
        p = Plan(operations=[DeleteCampaign(campaign_name="Camp A", fb_id="camp_001")])
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.removed == 100

    def test_delete_adset_with_no_state_params_removes_zero(self):
        state = _empty_state()
        p = Plan(
            operations=[
                DeleteAdSet(
                    campaign_name="Camp A", adset_name="Ad Set A", fb_id="adset_001"
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.removed == 0


# ---------------------------------------------------------------------------
# estimate_delta — updates
# ---------------------------------------------------------------------------


class TestEstimateDeltaUpdates:
    def test_update_adset_budget_increase(self):
        state = _state_with_adset("Camp A", "Ad Set A", {"daily_budget": 5000})
        p = Plan(
            operations=[
                UpdateAdSet(
                    campaign_name="Camp A",
                    adset_name="Ad Set A",
                    fb_id="adset_001",
                    changed_fields={"daily_budget": 10000},
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.added == 50  # 10000 - 5000 = 5000 cents = $50 increase
        assert delta.removed == 0

    def test_update_adset_budget_decrease(self):
        state = _state_with_adset("Camp A", "Ad Set A", {"daily_budget": 10000})
        p = Plan(
            operations=[
                UpdateAdSet(
                    campaign_name="Camp A",
                    adset_name="Ad Set A",
                    fb_id="adset_001",
                    changed_fields={"daily_budget": 5000},
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.added == 0
        assert delta.removed == 50  # 10000 - 5000 = 5000 cents = $50 decrease

    def test_update_campaign_budget_increase(self):
        state = _state_with_campaign("Camp A", {"daily_budget": 5000})
        p = Plan(
            operations=[
                UpdateCampaign(
                    campaign_name="Camp A",
                    fb_id="camp_001",
                    changed_fields={"daily_budget": 15000},
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.added == 100  # (15000 - 5000) cents = $100

    def test_update_budget_handles_facebook_string_values(self):
        state = _state_with_adset("Camp A", "Ad Set A", {"daily_budget": "10000"})
        p = Plan(
            operations=[
                UpdateAdSet(
                    campaign_name="Camp A",
                    adset_name="Ad Set A",
                    fb_id="adset_001",
                    changed_fields={"daily_budget": 5000},
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.added == 0
        assert delta.removed == 50

    def test_delete_budget_handles_facebook_string_values(self):
        state = _state_with_adset(
            "Camp A", "Ad Set A", {"daily_budget": "5000", "lifetime_budget": "10000"}
        )
        p = Plan(
            operations=[
                DeleteAdSet(
                    campaign_name="Camp A", adset_name="Ad Set A", fb_id="adset_001"
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.removed == 150

    def test_update_with_no_budget_fields_is_zero(self):
        state = _state_with_adset(
            "Camp A", "Ad Set A", {"daily_budget": 5000, "status": "ACTIVE"}
        )
        p = Plan(
            operations=[
                UpdateAdSet(
                    campaign_name="Camp A",
                    adset_name="Ad Set A",
                    fb_id="adset_001",
                    changed_fields={"status": "PAUSED"},
                )
            ]
        )
        template = _template()
        delta = estimate_delta(p, state, template)
        assert delta.added == 0
        assert delta.removed == 0


# ---------------------------------------------------------------------------
# estimate_delta — composite and edge cases
# ---------------------------------------------------------------------------


class TestEstimateDeltaComposite:
    def test_empty_plan_returns_zero_delta(self):
        delta = estimate_delta(Plan(), _empty_state(), _template())
        assert delta.added == 0
        assert delta.removed == 0
        assert delta.net == 0

    def test_net_equals_added_minus_removed(self):
        state = _state_with_adset("Camp A", "Ad Set Old", {"daily_budget": 3000})
        adset_new = _adset("Ad Set New", daily_budget=8000)
        p = Plan(
            operations=[
                CreateAdSet(campaign_name="Camp A", adset=adset_new),
                DeleteAdSet(
                    campaign_name="Camp A", adset_name="Ad Set Old", fb_id="adset_001"
                ),
            ]
        )
        template = _template([_campaign(ad_sets=[adset_new])])
        delta = estimate_delta(p, state, template)
        assert delta.added == 80  # 8000 cents = $80
        assert delta.removed == 30  # 3000 cents = $30
        assert delta.net == 50  # 80 - 30


# ---------------------------------------------------------------------------
# check_cap
# ---------------------------------------------------------------------------


class TestCheckCap:
    def test_no_cap_never_exceeded(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        template = _template([_campaign(ad_sets=[_adset(daily_budget=5000)])])
        result = check_cap(delta, template, cap=None)
        assert not result.exceeded
        assert result.cap is None

    def test_under_cap_not_exceeded(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        template = _template([_campaign(ad_sets=[_adset(daily_budget=5000)])])
        result = check_cap(delta, template, cap=100)
        assert not result.exceeded
        assert result.overage == 0

    def test_over_cap_exceeded(self):
        delta = BudgetDelta(added=150, removed=0, net=150)
        template = _template([_campaign(ad_sets=[_adset(daily_budget=15000)])])
        result = check_cap(delta, template, cap=100)
        assert result.exceeded
        assert result.overage == 50

    def test_projected_equals_template_total_in_dollars(self):
        # Two ad sets: 5000 + 10000 cents = $50 + $100 = $150 total
        template = _template(
            [
                _campaign(
                    ad_sets=[
                        _adset("AS1", daily_budget=5000),
                        _adset("AS2", daily_budget=10000),
                    ]
                )
            ]
        )
        delta = BudgetDelta(added=0, removed=0, net=0)
        result = check_cap(delta, template, cap=200)
        assert result.projected == 150

    def test_campaign_daily_budget_included_in_projected(self):
        template = _template([_campaign(daily_budget=20000, ad_sets=[])])
        delta = BudgetDelta(added=0, removed=0, net=0)
        result = check_cap(delta, template, cap=500)
        assert result.projected == 200  # 20000 cents = $200

    def test_spend_cap_excluded_from_projected(self):
        template = _template(
            [
                _campaign(
                    spend_cap=1000000,
                    ad_sets=[
                        _adset("AS1", daily_budget=5000),
                    ],
                )
            ]
        )
        delta = BudgetDelta(added=0, removed=0, net=0)
        result = check_cap(delta, template, cap=500)
        assert result.projected == 50  # only daily_budget counts

    def test_lifetime_budget_included_in_projected(self):
        template = _template([_campaign(ad_sets=[_adset(lifetime_budget=50000)])])
        delta = BudgetDelta(added=0, removed=0, net=0)
        result = check_cap(delta, template, cap=1000)
        assert result.projected == 500  # 50000 cents = $500

    def test_overage_zero_when_not_exceeded(self):
        delta = BudgetDelta(added=0, removed=0, net=0)
        template = _template([_campaign(ad_sets=[_adset(daily_budget=5000)])])
        result = check_cap(delta, template, cap=100)
        assert result.overage == 0


# ---------------------------------------------------------------------------
# format_budget_section
# ---------------------------------------------------------------------------


class TestFormatBudgetSection:
    def _cap_none(self, projected=50):
        return CapResult(exceeded=False, cap=None, projected=projected, overage=0)

    def _cap_ok(self, projected=50, cap=100):
        return CapResult(exceeded=False, cap=cap, projected=projected, overage=0)

    def _cap_exceeded(self, projected=150, cap=100, overage=50):
        return CapResult(exceeded=True, cap=cap, projected=projected, overage=overage)

    def test_shows_delta_values(self):
        delta = BudgetDelta(added=80, removed=30, net=50)
        text = format_budget_section(delta, self._cap_none(projected=50), "USD")
        assert "80" in text
        assert "30" in text
        assert "50" in text

    def test_usd_uses_dollar_sign(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        text = format_budget_section(delta, self._cap_none(), "USD")
        assert "$" in text

    def test_non_usd_uses_currency_code(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        text = format_budget_section(delta, self._cap_none(), "EUR")
        assert "EUR" in text

    def test_cap_exceeded_shows_warning(self):
        delta = BudgetDelta(added=150, removed=0, net=150)
        text = format_budget_section(delta, self._cap_exceeded(), "USD")
        assert "EXCEEDED" in text

    def test_no_cap_says_none_configured(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        text = format_budget_section(delta, self._cap_none(), "USD")
        assert "none" in text.lower()

    def test_cap_ok_shows_cap_value(self):
        delta = BudgetDelta(added=50, removed=0, net=50)
        text = format_budget_section(delta, self._cap_ok(projected=50, cap=100), "USD")
        assert "100" in text


# ---------------------------------------------------------------------------
# Integration: plan() attaches budget_delta
# ---------------------------------------------------------------------------


class TestPlanAttachesBudgetDelta:
    def test_plan_has_budget_delta(self):
        from src.traffic import plan

        template = {
            "account_id": "act_000000000",
            "campaigns": [_campaign(ad_sets=[_adset(daily_budget=5000)])],
        }
        state = _empty_state()
        p = plan(template, state, None)
        assert p.budget_delta is not None
        assert isinstance(p.budget_delta, BudgetDelta)

    def test_plan_delta_reflects_creates(self):
        from src.traffic import plan

        template = {
            "account_id": "act_000000000",
            "campaigns": [_campaign(ad_sets=[_adset(daily_budget=5000)])],
        }
        state = _empty_state()
        p = plan(template, state, None)
        assert p.budget_delta.added == 50


# ---------------------------------------------------------------------------
# Integration: _apply_stack blocked by cap
# ---------------------------------------------------------------------------


class TestApplyBlockedByCap:
    @pytest.mark.asyncio
    async def test_apply_blocked_when_cap_exceeded(self, tmp_path):
        import json
        from unittest.mock import patch

        from src.mcp_server import _apply_stack

        template = {
            "account_id": "act_000000000",
            "campaigns": [_campaign(ad_sets=[_adset(daily_budget=15000)])],
        }
        template_file = tmp_path / "test_template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")

        ai_client = MagicMock()
        ai_content = MagicMock()
        ai_content.text = "[]"
        ai_client.messages.create.return_value.content = [ai_content]

        meta_client = MagicMock()
        meta_client.create_campaign.return_value = "camp_001"
        meta_client.create_adset.return_value = "adset_001"
        meta_client.create_creative.return_value = "creative_001"
        meta_client.create_ad.return_value = "ad_001"
        meta_client.list_campaigns.return_value = []
        meta_client.list_adsets.return_value = []

        patches = (
            patch("src.mcp_server._STACK_JSON_PATH", template_file.resolve()),
            patch("src.mcp_server._STACK_STATE_DIR", tmp_path),
            patch("src.mcp_server._ACCOUNT_ID", "act_000000000"),
            patch("src.services.state.STATE_DIR", tmp_path),
            patch("src.mcp_server._get_ai_client", return_value=ai_client),
            patch("src.mcp_server._get_meta_client", return_value=meta_client),
            patch.dict("os.environ", {"ACCOUNT_BUDGET_CAP": "100", "CURRENCY": "USD"}),
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
        ):
            result = await _apply_stack({})

        text = result[0].text
        assert "Blocked by budget cap" in text or "EXCEEDED" in text
