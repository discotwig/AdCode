import pytest
from src.services.document import generate
from src.services.policy import PolicyViolation
from src.services.budget import BudgetDelta, CapResult
from src.services.state import StateFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_state() -> StateFile:
    return StateFile("act_000000000")


def _minimal_template(campaigns=None) -> dict:
    return {
        "account_id": "act_000000000",
        "campaigns": campaigns or [],
    }


def _campaign(name="Test Campaign", objective="OUTCOME_TRAFFIC", status="PAUSED",
              daily_budget=10000, spend_cap=None, ad_sets=None) -> dict:
    c = {
        "name": name,
        "objective": objective,
        "status": status,
        "special_ad_categories": [],
        "daily_budget": daily_budget,
        "ad_sets": ad_sets or [],
    }
    if spend_cap is not None:
        c["spend_cap"] = spend_cap
    return c


def _ad_set(name="Test Ad Set", status="PAUSED", daily_budget=5000,
            end_time=None, targeting=None, ads=None) -> dict:
    s = {
        "name": name,
        "status": status,
        "daily_budget": daily_budget,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LINK_CLICKS",
        "targeting": targeting or {"geo_locations": {"countries": ["US"]}},
        "ads": ads or [],
    }
    if end_time is not None:
        s["end_time"] = end_time
    return s


# ---------------------------------------------------------------------------
# 1. Required sections present
# ---------------------------------------------------------------------------

def test_required_sections_present():
    template = _minimal_template([_campaign(ad_sets=[_ad_set()])])
    result = generate(template, _empty_state(), [], None)

    for heading in [
        "Executive Summary",
        "Approval Recommendation",
        "Budget Impact",
        "Policy Results",
        "Campaign Hierarchy",
        "Targeting Summary",
        "Flight Dates",
        "Human Review Checklist",
        "Next Action",
    ]:
        assert heading in result, f"Missing section: {heading}"


# ---------------------------------------------------------------------------
# 2. Policy ERROR violations appear with rule ID and severity
# ---------------------------------------------------------------------------

def test_policy_errors_rendered():
    violation = PolicyViolation(
        rule_id="broadmatch",
        severity="ERROR",
        field="campaigns[0].ad_sets[0]",
        message="Ad set has no targeting constraints.",
    )
    template = _minimal_template([_campaign(ad_sets=[_ad_set()])])
    result = generate(template, _empty_state(), [violation], None)

    assert "broadmatch" in result
    assert "ERROR" in result


# ---------------------------------------------------------------------------
# 3. Policy WARNING violations rendered and distinguishable from ERROR
# ---------------------------------------------------------------------------

def test_policy_warnings_rendered_differently():
    error_v = PolicyViolation(rule_id="broadmatch", severity="ERROR",
                              field="campaigns[0].ad_sets[0]", message="Broad.")
    warn_v = PolicyViolation(rule_id="spend-cap-required", severity="WARNING",
                             field="campaigns[0]", message="No spend cap.")
    template = _minimal_template([_campaign(ad_sets=[_ad_set()])])
    result = generate(template, _empty_state(), [error_v, warn_v], None)

    assert "WARNING" in result
    assert "ERROR" in result
    # Both rule IDs should appear
    assert "spend-cap-required" in result


# ---------------------------------------------------------------------------
# 4. Budget impact shows added/removed/net
# ---------------------------------------------------------------------------

def test_budget_impact_shows_delta():
    delta = BudgetDelta(added=500, removed=0, net=500)
    template = _minimal_template([_campaign()])
    result = generate(template, _empty_state(), [], delta)

    # Should show currency-formatted values somewhere
    assert "500" in result
    assert "Budget Impact" in result


# ---------------------------------------------------------------------------
# 5. Budget cap exceeded shows warning
# ---------------------------------------------------------------------------

def test_budget_cap_exceeded_shown():
    delta = BudgetDelta(added=450, removed=0, net=450)
    cap_result = CapResult(exceeded=True, cap=400, projected=450, overage=50)
    template = _minimal_template([_campaign()])
    result = generate(template, _empty_state(), [], delta, cap_result=cap_result)

    assert "EXCEEDED" in result or "exceeded" in result.lower()
    assert "400" in result or "cap" in result.lower()


# ---------------------------------------------------------------------------
# 6. Broad targeting flag when no interests/behaviors/audiences
# ---------------------------------------------------------------------------

def test_broad_targeting_flag():
    ad_set = _ad_set(targeting={"geo_locations": {"countries": ["US"]}})
    template = _minimal_template([_campaign(ad_sets=[ad_set])])
    result = generate(template, _empty_state(), [], None)

    # Should warn about broad targeting in targeting summary
    assert "broad" in result.lower() or "Broad" in result


# ---------------------------------------------------------------------------
# 7. Missing end date flag
# ---------------------------------------------------------------------------

def test_missing_end_date_flag():
    ad_set = _ad_set(end_time=None)
    template = _minimal_template([_campaign(ad_sets=[ad_set])])
    result = generate(template, _empty_state(), [], None)

    # Flight dates section should flag missing end date
    assert "end date" in result.lower() or "no end" in result.lower()


# ---------------------------------------------------------------------------
# 8. Empty state / no plan / no delta — graceful output
# ---------------------------------------------------------------------------

def test_graceful_with_empty_state_no_plan_no_delta():
    template = _minimal_template([_campaign(ad_sets=[_ad_set()])])
    result = generate(template, _empty_state(), [], None)

    assert isinstance(result, str)
    assert len(result) > 100
    assert "Campaign Review Packet" in result


# ---------------------------------------------------------------------------
# 9. No raw JSON dumps in output
# ---------------------------------------------------------------------------

def test_no_raw_json_in_output():
    ad_set = _ad_set(targeting={
        "geo_locations": {"countries": ["US"]},
        "interests": [{"id": "6003139266461", "name": "Online shopping"}],
    })
    template = _minimal_template([_campaign(ad_sets=[ad_set])])
    result = generate(template, _empty_state(), [], None)

    # Raw JSON-style strings should not appear
    assert '": {' not in result
    assert '"id":' not in result


# ---------------------------------------------------------------------------
# 10. Status is BLOCKED when ERROR violations present
# ---------------------------------------------------------------------------

def test_status_blocked_on_error_violations():
    violation = PolicyViolation(rule_id="broadmatch", severity="ERROR",
                                field="campaigns[0].ad_sets[0]", message="Broad.")
    template = _minimal_template([_campaign(ad_sets=[_ad_set()])])
    result = generate(template, _empty_state(), [violation], None)

    assert "BLOCKED" in result


# ---------------------------------------------------------------------------
# 11. Status is READY FOR REVIEW when no violations
# ---------------------------------------------------------------------------

def test_status_ready_when_clean():
    ad_set = _ad_set(
        end_time="2027-01-01T00:00:00Z",
        targeting={
            "geo_locations": {"countries": ["US"]},
            "interests": [{"id": "6003139266461", "name": "Online shopping"}],
        },
    )
    template = _minimal_template([_campaign(spend_cap=100000, ad_sets=[ad_set])])
    result = generate(template, _empty_state(), [], None)

    assert "READY" in result or "Ready" in result


# ---------------------------------------------------------------------------
# 12. Planned changes section included when plan provided
# ---------------------------------------------------------------------------

def test_planned_changes_section_with_plan():
    from src.traffic import Plan, CreateCampaign
    from src.services.budget import BudgetDelta

    op = CreateCampaign(campaign=_campaign())
    p = Plan(operations=[op], budget_delta=BudgetDelta(added=100, removed=0, net=100))
    template = _minimal_template([_campaign()])
    result = generate(template, _empty_state(), [], p.budget_delta, plan=p)

    assert "Planned Changes" in result
    assert "Create" in result or "create" in result.lower()
