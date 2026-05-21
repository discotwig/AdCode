"""Tests for src/services/lint.py — deterministic template linting."""
import copy
import pytest

from src.services.lint import LintFinding, LintReport, LintSeverity, lint_stack


# ---------------------------------------------------------------------------
# Clean baseline template — passes all lint rules
# ---------------------------------------------------------------------------

def _make_template(**overrides) -> dict:
    """Return a minimal clean template that passes all lint rules."""
    t = {
        "account_id": "act_123456789",
        "campaigns": [
            {
                "name": "Summer Sale",
                "fb_id": "camp_001",
                "objective": "OUTCOME_TRAFFIC",
                "status": "ACTIVE",
                "special_ad_categories": [],
                "ad_sets": [
                    {
                        "name": "US 25-54",
                        "fb_id": "adset_001",
                        "status": "ACTIVE",
                        "billing_event": "LINK_CLICKS",
                        "optimization_goal": "LINK_CLICKS",
                        "daily_budget": 5000,
                        "end_time": "2026-12-31T23:59:59Z",
                        "targeting": {"geo_locations": {"countries": ["US"]}},
                        "ads": [
                            {
                                "name": "Ad v1",
                                "fb_id": "ad_001",
                                "status": "ACTIVE",
                                "creative": {
                                    "name": "Creative v1",
                                    "object_story_spec": {
                                        "page_id": "123456789012345",
                                        "link_data": {
                                            "message": "Great deals this summer",
                                            "link": "https://mystore.com/sale",
                                            "call_to_action": {"type": "SHOP_NOW"},
                                        },
                                    },
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    t.update(overrides)
    return t


def _rules_by_id(report: LintReport) -> dict[str, LintFinding]:
    return {f.rule_id: f for f in report.findings}


# ---------------------------------------------------------------------------
# TestLintReportModel
# ---------------------------------------------------------------------------

class TestLintReportModel:
    def test_empty_report_is_empty(self):
        r = LintReport()
        assert r.is_empty()
        assert r.errors == []
        assert r.warnings == []
        assert r.infos == []

    def test_severity_counts(self):
        r = LintReport(findings=[
            LintFinding("lint-a", LintSeverity.ERROR, "x", "msg", "fix"),
            LintFinding("lint-b", LintSeverity.WARNING, "y", "msg", "fix"),
            LintFinding("lint-c", LintSeverity.INFO, "z", "msg", "fix"),
            LintFinding("lint-d", LintSeverity.WARNING, "w", "msg", "fix"),
        ])
        assert not r.is_empty()
        assert len(r.errors) == 1
        assert len(r.warnings) == 2
        assert len(r.infos) == 1

    def test_summary_includes_counts(self):
        r = LintReport(findings=[
            LintFinding("lint-a", LintSeverity.WARNING, "account_id", "Placeholder", "Fix it"),
        ])
        summary = r.summary()
        assert "lint" in summary.lower() or "warning" in summary.lower() or "finding" in summary.lower()
        assert "lint-a" in summary or "Placeholder" in summary

    def test_summary_empty_when_no_findings(self):
        r = LintReport()
        assert r.summary() == ""

    def test_clean_template_produces_no_findings(self):
        report = lint_stack(_make_template())
        assert report.is_empty(), f"Expected no findings, got: {report.findings}"


# ---------------------------------------------------------------------------
# TestPlaceholderAccountId
# ---------------------------------------------------------------------------

class TestPlaceholderAccountId:
    def test_passes_with_real_account_id(self):
        report = lint_stack(_make_template())
        assert "lint-placeholder-account-id" not in _rules_by_id(report)

    def test_warns_on_placeholder_account_id(self):
        t = _make_template(account_id="act_000000000")
        report = lint_stack(t)
        rules = _rules_by_id(report)
        assert "lint-placeholder-account-id" in rules
        finding = rules["lint-placeholder-account-id"]
        assert finding.severity == LintSeverity.WARNING
        assert "account_id" in finding.path

    def test_placeholder_account_id_has_suggestion(self):
        t = _make_template(account_id="act_000000000")
        report = lint_stack(t)
        finding = _rules_by_id(report)["lint-placeholder-account-id"]
        assert len(finding.suggestion) > 0


# ---------------------------------------------------------------------------
# TestPlaceholderPageId
# ---------------------------------------------------------------------------

class TestPlaceholderPageId:
    def test_passes_with_real_page_id(self):
        report = lint_stack(_make_template())
        assert "lint-placeholder-page-id" not in _rules_by_id(report)

    def test_warns_on_replace_with_page_id(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["page_id"] = "REPLACE_WITH_PAGE_ID"
        report = lint_stack(t)
        assert "lint-placeholder-page-id" in _rules_by_id(report)

    def test_warns_on_all_zeros_page_id(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["page_id"] = "000000000000000"
        report = lint_stack(t)
        assert "lint-placeholder-page-id" in _rules_by_id(report)

    def test_page_id_finding_has_warning_severity(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["page_id"] = "PAGE_ID"
        report = lint_stack(t)
        assert _rules_by_id(report)["lint-placeholder-page-id"].severity == LintSeverity.WARNING


# ---------------------------------------------------------------------------
# TestPlaceholderImageHash
# ---------------------------------------------------------------------------

class TestPlaceholderImageHash:
    def test_passes_with_no_image_hash(self):
        report = lint_stack(_make_template())
        assert "lint-placeholder-image-hash" not in _rules_by_id(report)

    def test_warns_on_placeholder_image_hash(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]["image_hash"] = "IMAGE_HASH"
        report = lint_stack(t)
        assert "lint-placeholder-image-hash" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-placeholder-image-hash"].severity == LintSeverity.WARNING

    def test_passes_with_real_image_hash(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]["image_hash"] = "a1b2c3d4e5f67890"
        report = lint_stack(t)
        assert "lint-placeholder-image-hash" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestPlaceholderUrl
# ---------------------------------------------------------------------------

class TestPlaceholderUrl:
    def test_passes_with_real_url(self):
        report = lint_stack(_make_template())
        assert "lint-placeholder-url" not in _rules_by_id(report)

    def test_warns_on_example_com_link(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]["link"] = "https://example.com/landing"
        report = lint_stack(t)
        assert "lint-placeholder-url" in _rules_by_id(report)

    def test_warns_on_bare_example_com(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]["link"] = "https://example.com"
        report = lint_stack(t)
        assert "lint-placeholder-url" in _rules_by_id(report)

    def test_url_finding_has_warning_severity(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]["link"] = "https://example.com"
        report = lint_stack(t)
        assert _rules_by_id(report)["lint-placeholder-url"].severity == LintSeverity.WARNING


# ---------------------------------------------------------------------------
# TestPlaceholderText
# ---------------------------------------------------------------------------

class TestPlaceholderText:
    def test_passes_with_normal_names(self):
        report = lint_stack(_make_template())
        assert "lint-placeholder-text" not in _rules_by_id(report)

    def test_warns_on_todo_campaign_name(self):
        t = _make_template()
        t["campaigns"][0]["name"] = "TODO"
        report = lint_stack(t)
        assert "lint-placeholder-text" in _rules_by_id(report)

    def test_warns_on_tbd_adset_name(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["name"] = "TBD"
        report = lint_stack(t)
        assert "lint-placeholder-text" in _rules_by_id(report)

    def test_does_not_flag_unusual_unicode(self):
        """Campaign names with unusual Unicode or dashes must NOT be flagged — ADR-023."""
        t = _make_template()
        t["campaigns"][0]["name"] = "Q3 Brand — Phase 2 (â€”)"
        report = lint_stack(t)
        assert "lint-placeholder-text" not in _rules_by_id(report)

    def test_does_not_flag_partial_match(self):
        """'TODO' substring inside a longer name should not fire the rule."""
        t = _make_template()
        t["campaigns"][0]["name"] = "Q3 TODO Finalize"
        report = lint_stack(t)
        assert "lint-placeholder-text" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestDualBudget
# ---------------------------------------------------------------------------

class TestDualBudget:
    def test_passes_with_only_daily_budget(self):
        report = lint_stack(_make_template())
        assert "lint-dual-budget" not in _rules_by_id(report)

    def test_warns_when_both_budgets_set(self):
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["lifetime_budget"] = 100000
        report = lint_stack(t)
        assert "lint-dual-budget" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-dual-budget"].severity == LintSeverity.WARNING

    def test_passes_with_only_lifetime_budget(self):
        t = _make_template()
        adset = t["campaigns"][0]["ad_sets"][0]
        del adset["daily_budget"]
        adset["lifetime_budget"] = 100000
        adset["start_time"] = "2026-01-01T00:00:00Z"
        report = lint_stack(t)
        assert "lint-dual-budget" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestLifetimeBudgetNoDates
# ---------------------------------------------------------------------------

class TestLifetimeBudgetNoDates:
    def test_passes_with_lifetime_budget_and_dates(self):
        t = _make_template()
        adset = t["campaigns"][0]["ad_sets"][0]
        del adset["daily_budget"]
        adset["lifetime_budget"] = 100000
        adset["start_time"] = "2026-01-01T00:00:00Z"
        # end_time already present in clean template
        report = lint_stack(t)
        assert "lint-lifetime-budget-no-dates" not in _rules_by_id(report)

    def test_warns_when_lifetime_budget_lacks_end_time(self):
        t = _make_template()
        adset = t["campaigns"][0]["ad_sets"][0]
        del adset["daily_budget"]
        adset["lifetime_budget"] = 100000
        adset["start_time"] = "2026-01-01T00:00:00Z"
        del adset["end_time"]
        report = lint_stack(t)
        assert "lint-lifetime-budget-no-dates" in _rules_by_id(report)

    def test_warns_when_lifetime_budget_lacks_start_time(self):
        t = _make_template()
        adset = t["campaigns"][0]["ad_sets"][0]
        del adset["daily_budget"]
        adset["lifetime_budget"] = 100000
        # no start_time set
        report = lint_stack(t)
        assert "lint-lifetime-budget-no-dates" in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestNewResourceActive
# ---------------------------------------------------------------------------

class TestNewResourceActive:
    def test_passes_when_existing_campaign_is_active(self):
        """Campaign with fb_id set to ACTIVE is fine — it already exists."""
        report = lint_stack(_make_template())
        assert "lint-new-resource-active" not in _rules_by_id(report)

    def test_warns_when_new_campaign_is_active(self):
        t = _make_template()
        del t["campaigns"][0]["fb_id"]
        t["campaigns"][0]["status"] = "ACTIVE"
        report = lint_stack(t)
        assert "lint-new-resource-active" in _rules_by_id(report)

    def test_passes_when_new_campaign_is_paused(self):
        t = _make_template()
        del t["campaigns"][0]["fb_id"]
        t["campaigns"][0]["status"] = "PAUSED"
        report = lint_stack(t)
        assert "lint-new-resource-active" not in _rules_by_id(report)

    def test_warns_when_new_adset_is_active(self):
        t = _make_template()
        del t["campaigns"][0]["ad_sets"][0]["fb_id"]
        t["campaigns"][0]["ad_sets"][0]["status"] = "ACTIVE"
        report = lint_stack(t)
        assert "lint-new-resource-active" in _rules_by_id(report)

    def test_warns_when_new_ad_is_active(self):
        t = _make_template()
        del t["campaigns"][0]["ad_sets"][0]["ads"][0]["fb_id"]
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["status"] = "ACTIVE"
        report = lint_stack(t)
        assert "lint-new-resource-active" in _rules_by_id(report)

    def test_passes_when_new_ad_is_paused(self):
        t = _make_template()
        del t["campaigns"][0]["ad_sets"][0]["ads"][0]["fb_id"]
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["status"] = "PAUSED"
        report = lint_stack(t)
        assert "lint-new-resource-active" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestDuplicateFbId
# ---------------------------------------------------------------------------

class TestDuplicateFbId:
    def test_passes_when_all_fb_ids_unique(self):
        report = lint_stack(_make_template())
        assert "lint-duplicate-fb-id" not in _rules_by_id(report)

    def test_errors_when_campaign_and_adset_share_fb_id(self):
        t = _make_template()
        t["campaigns"][0]["fb_id"] = "shared_id"
        t["campaigns"][0]["ad_sets"][0]["fb_id"] = "shared_id"
        report = lint_stack(t)
        assert "lint-duplicate-fb-id" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-duplicate-fb-id"].severity == LintSeverity.ERROR

    def test_errors_when_two_campaigns_share_fb_id(self):
        t = _make_template()
        second_campaign = copy.deepcopy(t["campaigns"][0])
        second_campaign["name"] = "Other Campaign"
        second_campaign["fb_id"] = "camp_001"  # same as first
        t["campaigns"].append(second_campaign)
        report = lint_stack(t)
        assert "lint-duplicate-fb-id" in _rules_by_id(report)

    def test_passes_when_no_fb_ids_present(self):
        t = _make_template()
        del t["campaigns"][0]["fb_id"]
        del t["campaigns"][0]["ad_sets"][0]["fb_id"]
        del t["campaigns"][0]["ad_sets"][0]["ads"][0]["fb_id"]
        t["campaigns"][0]["status"] = "PAUSED"
        t["campaigns"][0]["ad_sets"][0]["status"] = "PAUSED"
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["status"] = "PAUSED"
        report = lint_stack(t)
        assert "lint-duplicate-fb-id" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestDuplicateCampaignName
# ---------------------------------------------------------------------------

class TestDuplicateCampaignName:
    def test_passes_with_unique_campaign_names(self):
        report = lint_stack(_make_template())
        assert "lint-duplicate-campaign-name" not in _rules_by_id(report)

    def test_warns_on_duplicate_campaign_names(self):
        t = _make_template()
        second = copy.deepcopy(t["campaigns"][0])
        second["fb_id"] = "camp_002"
        t["campaigns"].append(second)
        report = lint_stack(t)
        assert "lint-duplicate-campaign-name" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-duplicate-campaign-name"].severity == LintSeverity.WARNING

    def test_passes_with_different_campaign_names(self):
        t = _make_template()
        second = copy.deepcopy(t["campaigns"][0])
        second["name"] = "Winter Sale"
        second["fb_id"] = "camp_002"
        t["campaigns"].append(second)
        report = lint_stack(t)
        assert "lint-duplicate-campaign-name" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestDuplicateAdSetName
# ---------------------------------------------------------------------------

class TestDuplicateAdSetName:
    def test_passes_with_unique_adset_names(self):
        report = lint_stack(_make_template())
        assert "lint-duplicate-adset-name" not in _rules_by_id(report)

    def test_warns_on_duplicate_adset_names_within_same_campaign(self):
        t = _make_template()
        second_adset = copy.deepcopy(t["campaigns"][0]["ad_sets"][0])
        second_adset["fb_id"] = "adset_002"
        t["campaigns"][0]["ad_sets"].append(second_adset)
        report = lint_stack(t)
        assert "lint-duplicate-adset-name" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-duplicate-adset-name"].severity == LintSeverity.WARNING

    def test_passes_when_same_name_in_different_campaigns(self):
        """Duplicate ad set name across two different campaigns is fine."""
        t = _make_template()
        second_campaign = copy.deepcopy(t["campaigns"][0])
        second_campaign["name"] = "Winter Sale"
        second_campaign["fb_id"] = "camp_002"
        second_campaign["ad_sets"][0]["fb_id"] = "adset_002"
        # Same ad set name "US 25-54" in both campaigns — should not warn
        t["campaigns"].append(second_campaign)
        report = lint_stack(t)
        assert "lint-duplicate-adset-name" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestIncompleteLinkCreative
# ---------------------------------------------------------------------------

class TestIncompleteLinkCreative:
    def test_passes_with_call_to_action_present(self):
        report = lint_stack(_make_template())
        assert "lint-incomplete-link-creative" not in _rules_by_id(report)

    def test_info_when_call_to_action_missing(self):
        t = _make_template()
        link_data = t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"]
        del link_data["call_to_action"]
        report = lint_stack(t)
        assert "lint-incomplete-link-creative" in _rules_by_id(report)
        assert _rules_by_id(report)["lint-incomplete-link-creative"].severity == LintSeverity.INFO

    def test_passes_with_no_link_data(self):
        """No link_data means a different creative type; don't flag it."""
        t = _make_template()
        t["campaigns"][0]["ad_sets"][0]["ads"][0]["creative"] = {"name": "Video Creative"}
        report = lint_stack(t)
        assert "lint-incomplete-link-creative" not in _rules_by_id(report)


# ---------------------------------------------------------------------------
# TestNonLiveVerification
# ---------------------------------------------------------------------------

class TestNonLiveVerification:
    def test_lint_stack_does_not_use_meta_client(self):
        """Linting must not import or instantiate MetaClient."""
        import src.services.lint as lint_module
        import inspect
        source = inspect.getsource(lint_module)
        assert "MetaClient" not in source
        assert "facebook_business" not in source

    def test_lint_stack_does_not_use_anthropic(self):
        """Linting must not call the AI API."""
        import src.services.lint as lint_module
        import inspect
        source = inspect.getsource(lint_module)
        assert "anthropic" not in source
        assert "messages.create" not in source
