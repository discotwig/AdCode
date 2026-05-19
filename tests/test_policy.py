import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.services.policy import (
    PolicyRule,
    PolicyViolation,
    evaluate,
    load_policies,
)
from src.services.validate import validate_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_template(
    objective="OUTCOME_TRAFFIC",
    billing_event="IMPRESSIONS",
    optimization_goal="LINK_CLICKS",
    targeting=None,
    spend_cap=None,
    end_time=None,
):
    campaign: dict = {
        "name": "Test Campaign",
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": [],
        "ad_sets": [
            {
                "name": "Test Ad Set",
                "status": "PAUSED",
                "billing_event": billing_event,
                "optimization_goal": optimization_goal,
                "targeting": targeting or {"geo_locations": {"countries": ["US"]}},
                "ads": [],
            }
        ],
    }
    if spend_cap is not None:
        campaign["spend_cap"] = spend_cap
    if end_time is not None:
        campaign["ad_sets"][0]["end_time"] = end_time

    return {"account_id": "act_000000000", "campaigns": [campaign]}


def _make_ai_client():
    client = MagicMock()
    content = MagicMock()
    content.text = "[]"
    client.messages.create.return_value.content = [content]
    return client


def _rules_by_id(rules: list[PolicyRule]) -> dict[str, PolicyRule]:
    return {r.id: r for r in rules}


# ---------------------------------------------------------------------------
# load_policies
# ---------------------------------------------------------------------------

class TestLoadPolicies:
    def test_returns_four_builtins(self):
        rules = load_policies(None)
        ids = {r.id for r in rules}
        assert "broadmatch-targeting" in ids
        assert "spend-cap-required" in ids
        assert "end-time-required" in ids
        assert "objective-billing-compatibility" in ids

    def test_returns_policy_rule_objects(self):
        rules = load_policies(None)
        assert all(isinstance(r, PolicyRule) for r in rules)

    def test_missing_stack_dir_returns_only_builtins(self, tmp_path):
        rules = load_policies(tmp_path)
        assert len(rules) >= 4

    def test_stack_local_rule_overrides_builtin(self, tmp_path):
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        override = {
            "id": "spend-cap-required",
            "description": "Overridden: spend cap is optional for this stack",
            "severity": "WARNING",
            "condition": {
                "scope": "campaign",
                "type": "field_required",
                "field": "name",
                "message": "noop override",
            },
        }
        (policy_dir / "spend-cap-required.json").write_text(json.dumps(override), encoding="utf-8")

        rules = load_policies(tmp_path)
        by_id = _rules_by_id(rules)
        assert by_id["spend-cap-required"].description == "Overridden: spend cap is optional for this stack"

    def test_stack_local_rule_added_alongside_builtins(self, tmp_path):
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        custom = {
            "id": "custom-rule",
            "description": "Custom stack rule",
            "severity": "WARNING",
            "condition": {
                "scope": "campaign",
                "type": "field_required",
                "field": "name",
                "message": "Campaign '{name}' is missing name",
            },
        }
        (policy_dir / "custom-rule.json").write_text(json.dumps(custom), encoding="utf-8")

        rules = load_policies(tmp_path)
        ids = {r.id for r in rules}
        assert "custom-rule" in ids
        assert "broadmatch-targeting" in ids


# ---------------------------------------------------------------------------
# evaluate — broadmatch rule
# ---------------------------------------------------------------------------

class TestBroadmatch:
    def test_fires_when_no_audience_constraints(self):
        template = _make_template(targeting={"geo_locations": {"countries": ["US"]}})
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert len(violations) == 1
        assert violations[0].rule_id == "broadmatch-targeting"
        assert violations[0].severity == "WARNING"

    def test_passes_with_interests(self):
        targeting = {
            "geo_locations": {"countries": ["US"]},
            "interests": [{"id": "1", "name": "Fitness"}],
        }
        template = _make_template(targeting=targeting)
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert violations == []

    def test_passes_with_custom_audiences(self):
        targeting = {
            "geo_locations": {"countries": ["US"]},
            "custom_audiences": [{"id": "lookalike_001"}],
        }
        template = _make_template(targeting=targeting)
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert violations == []

    def test_passes_with_behaviors(self):
        targeting = {
            "geo_locations": {"countries": ["US"]},
            "behaviors": [{"id": "2", "name": "Frequent travelers"}],
        }
        template = _make_template(targeting=targeting)
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert violations == []

    def test_empty_interests_list_still_fires(self):
        targeting = {
            "geo_locations": {"countries": ["US"]},
            "interests": [],
        }
        template = _make_template(targeting=targeting)
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# evaluate — spend-cap-required rule
# ---------------------------------------------------------------------------

class TestSpendCapRequired:
    def test_fires_when_spend_cap_missing(self):
        template = _make_template()
        rules = [r for r in load_policies(None) if r.id == "spend-cap-required"]
        violations = evaluate(template, rules)
        assert len(violations) == 1
        assert violations[0].rule_id == "spend-cap-required"
        assert violations[0].severity == "WARNING"

    def test_passes_when_spend_cap_present(self):
        template = _make_template(spend_cap=500000)
        rules = [r for r in load_policies(None) if r.id == "spend-cap-required"]
        violations = evaluate(template, rules)
        assert violations == []


# ---------------------------------------------------------------------------
# evaluate — end-time-required rule
# ---------------------------------------------------------------------------

class TestEndTimeRequired:
    def test_fires_when_end_time_missing(self):
        template = _make_template()
        rules = [r for r in load_policies(None) if r.id == "end-time-required"]
        violations = evaluate(template, rules)
        assert len(violations) == 1
        assert violations[0].rule_id == "end-time-required"
        assert violations[0].severity == "WARNING"

    def test_passes_when_end_time_present(self):
        template = _make_template(end_time="2026-12-31T23:59:59+0000")
        rules = [r for r in load_policies(None) if r.id == "end-time-required"]
        violations = evaluate(template, rules)
        assert violations == []


# ---------------------------------------------------------------------------
# evaluate — objective-billing-compatibility rule
# ---------------------------------------------------------------------------

class TestObjectiveBillingCompatibility:
    def test_valid_combo_passes(self):
        template = _make_template(
            objective="OUTCOME_TRAFFIC",
            billing_event="IMPRESSIONS",
            optimization_goal="LINK_CLICKS",
        )
        rules = [r for r in load_policies(None) if r.id == "objective-billing-compatibility"]
        violations = evaluate(template, rules)
        assert violations == []

    def test_invalid_combo_fires(self):
        template = _make_template(
            objective="OUTCOME_AWARENESS",
            billing_event="IMPRESSIONS",
            optimization_goal="OFFSITE_CONVERSIONS",
        )
        rules = [r for r in load_policies(None) if r.id == "objective-billing-compatibility"]
        violations = evaluate(template, rules)
        assert len(violations) == 1
        assert violations[0].rule_id == "objective-billing-compatibility"
        assert violations[0].severity == "ERROR"

    def test_outcome_sales_with_offsite_conversions_passes(self):
        template = _make_template(
            objective="OUTCOME_SALES",
            billing_event="IMPRESSIONS",
            optimization_goal="OFFSITE_CONVERSIONS",
        )
        rules = [r for r in load_policies(None) if r.id == "objective-billing-compatibility"]
        violations = evaluate(template, rules)
        assert violations == []

    def test_outcome_leads_with_lead_generation_passes(self):
        template = _make_template(
            objective="OUTCOME_LEADS",
            billing_event="IMPRESSIONS",
            optimization_goal="LEAD_GENERATION",
        )
        rules = [r for r in load_policies(None) if r.id == "objective-billing-compatibility"]
        violations = evaluate(template, rules)
        assert violations == []


# ---------------------------------------------------------------------------
# Multiple campaigns / ad sets
# ---------------------------------------------------------------------------

class TestMultipleObjects:
    def test_violation_per_adset(self):
        template = {
            "account_id": "act_000000000",
            "campaigns": [
                {
                    "name": "Camp A",
                    "objective": "OUTCOME_TRAFFIC",
                    "status": "PAUSED",
                    "special_ad_categories": [],
                    "ad_sets": [
                        {"name": "AS 1", "status": "PAUSED", "billing_event": "IMPRESSIONS",
                         "optimization_goal": "LINK_CLICKS",
                         "targeting": {"geo_locations": {"countries": ["US"]}}, "ads": []},
                        {"name": "AS 2", "status": "PAUSED", "billing_event": "IMPRESSIONS",
                         "optimization_goal": "LINK_CLICKS",
                         "targeting": {"geo_locations": {"countries": ["US"]}}, "ads": []},
                    ],
                }
            ],
        }
        rules = [r for r in load_policies(None) if r.id == "broadmatch-targeting"]
        violations = evaluate(template, rules)
        assert len(violations) == 2

    def test_violation_per_campaign(self):
        template = {
            "account_id": "act_000000000",
            "campaigns": [
                {"name": "Camp A", "objective": "OUTCOME_TRAFFIC", "status": "PAUSED",
                 "special_ad_categories": [], "ad_sets": []},
                {"name": "Camp B", "objective": "OUTCOME_TRAFFIC", "status": "PAUSED",
                 "special_ad_categories": [], "ad_sets": []},
            ],
        }
        rules = [r for r in load_policies(None) if r.id == "spend-cap-required"]
        violations = evaluate(template, rules)
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# Severity integration with validate_all
# ---------------------------------------------------------------------------

class TestSeverityIntegration:
    def test_error_violation_blocks_apply(self):
        template = _make_template(
            objective="OUTCOME_AWARENESS",
            billing_event="IMPRESSIONS",
            optimization_goal="OFFSITE_CONVERSIONS",
        )
        result = validate_all(template, _make_ai_client())
        assert not result.is_pushable
        assert any(v.severity == "ERROR" for v in result.policy_violations)

    def test_warning_only_does_not_block(self):
        template = _make_template(spend_cap=None)
        result = validate_all(template, _make_ai_client())
        # The template has no spend_cap and no end_time and no audience → 3 WARNINGs + 1 ERROR
        # objective/billing combo is valid (OUTCOME_TRAFFIC / IMPRESSIONS / LINK_CLICKS)
        assert result.is_pushable

    def test_validate_all_merges_violations_into_result(self):
        template = _make_template()
        result = validate_all(template, _make_ai_client())
        assert isinstance(result.policy_violations, list)
        assert len(result.policy_violations) > 0

    def test_validate_all_summary_includes_rule_id(self):
        template = _make_template()
        result = validate_all(template, _make_ai_client())
        summary = result.summary()
        assert "broadmatch-targeting" in summary

    def test_validate_all_with_stack_dir_loads_policies(self, tmp_path):
        template = _make_template()
        result = validate_all(template, _make_ai_client(), stack_dir=tmp_path)
        assert isinstance(result.policy_violations, list)
