"""Deterministic template linting for AdCode stack templates.

Catches valid-but-suspicious templates: placeholder IDs, unsafe launch status,
budget sanity issues, duplicate names, and fb_id hygiene problems.

No I/O, no Facebook API calls, no AI. Designed to run inside plan_stack,
document_stack, and draft_stack as a fast, local feedback layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LintSeverity(str, Enum):
    ERROR = "error"      # deterministic, high-confidence (e.g. duplicate fb_id)
    WARNING = "warning"  # suspicious or incomplete (most rules)
    INFO = "info"        # best-practice hint (creative completeness)


@dataclass
class LintFinding:
    rule_id: str
    severity: LintSeverity
    path: str
    message: str
    suggestion: str
    docs_ref: str | None = None


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == LintSeverity.ERROR]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == LintSeverity.WARNING]

    @property
    def infos(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == LintSeverity.INFO]

    def is_empty(self) -> bool:
        return not self.findings

    def summary(self) -> str:
        if not self.findings:
            return ""
        n_err = len(self.errors)
        n_warn = len(self.warnings)
        n_info = len(self.infos)
        header = (
            f"Lint: {len(self.findings)} finding(s) "
            f"({n_err} error(s), {n_warn} warning(s), {n_info} info)"
        )
        lines = [header]
        for f in self.findings:
            label = f.severity.value.upper()[:4]
            lines.append(f"  [{label}] {f.rule_id} @ {f.path}: {f.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Placeholder constants
# ---------------------------------------------------------------------------

_PLACEHOLDER_ACCOUNT_IDS = {"act_000000000"}
_PLACEHOLDER_PAGE_IDS = {"000000000000000", "PAGE_ID", "REPLACE_WITH_PAGE_ID"}
_PLACEHOLDER_IMAGE_HASH_SUBSTRINGS = {"IMAGE_HASH"}
_PLACEHOLDER_URL_SUBSTRINGS = {"example.com"}
_PLACEHOLDER_EXACT_NAMES = {"TODO", "TBD"}


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

def _check_placeholder_account_id(template: dict, report: LintReport) -> None:
    account_id = template.get("account_id", "")
    if account_id in _PLACEHOLDER_ACCOUNT_IDS:
        report.findings.append(LintFinding(
            rule_id="lint-placeholder-account-id",
            severity=LintSeverity.WARNING,
            path="account_id",
            message=f"Placeholder account ID detected: {account_id!r}.",
            suggestion="Replace with your real Meta ad account ID (e.g. act_123456789).",
        ))


def _check_new_resource_active(obj: dict, path: str, report: LintReport) -> None:
    if obj.get("status") == "ACTIVE" and not obj.get("fb_id"):
        report.findings.append(LintFinding(
            rule_id="lint-new-resource-active",
            severity=LintSeverity.WARNING,
            path=path,
            message="New resource (no fb_id) is set to ACTIVE before its first apply.",
            suggestion='Consider starting new resources as PAUSED and activating after review.',
        ))


def _check_dual_budget(adset: dict, path: str, report: LintReport) -> None:
    if adset.get("daily_budget") and adset.get("lifetime_budget"):
        report.findings.append(LintFinding(
            rule_id="lint-dual-budget",
            severity=LintSeverity.WARNING,
            path=path,
            message="Ad set declares both daily_budget and lifetime_budget.",
            suggestion="Use one budget type per ad set. Facebook requires either daily or lifetime, not both.",
        ))


def _check_lifetime_budget_no_dates(adset: dict, path: str, report: LintReport) -> None:
    if adset.get("lifetime_budget") and not adset.get("daily_budget"):
        if not adset.get("start_time") or not adset.get("end_time"):
            missing = []
            if not adset.get("start_time"):
                missing.append("start_time")
            if not adset.get("end_time"):
                missing.append("end_time")
            report.findings.append(LintFinding(
                rule_id="lint-lifetime-budget-no-dates",
                severity=LintSeverity.WARNING,
                path=path,
                message=f"Ad set uses lifetime_budget but is missing {' and '.join(missing)}.",
                suggestion="Add both start_time and end_time when using a lifetime budget.",
            ))


def _check_duplicate_adset_names(campaign: dict, campaign_idx: int, report: LintReport) -> None:
    names: list[str] = []
    seen: set[str] = set()
    for adset in campaign.get("ad_sets", []):
        name = adset.get("name", "")
        if name in seen and name not in [f.message for f in report.findings]:
            report.findings.append(LintFinding(
                rule_id="lint-duplicate-adset-name",
                severity=LintSeverity.WARNING,
                path=f"campaigns[{campaign_idx}]",
                message=f'Duplicate ad set name "{name}" within campaign "{campaign.get("name", "")}".',
                suggestion="Give each ad set a unique name within its parent campaign.",
            ))
        seen.add(name)
        names.append(name)


def _check_creative(creative: dict, path_ad: str, report: LintReport) -> None:
    spec = creative.get("object_story_spec", {})
    page_id = spec.get("page_id", "")
    if page_id in _PLACEHOLDER_PAGE_IDS:
        report.findings.append(LintFinding(
            rule_id="lint-placeholder-page-id",
            severity=LintSeverity.WARNING,
            path=f"{path_ad}.creative",
            message=f"Placeholder page_id detected: {page_id!r}.",
            suggestion="Replace with your real Facebook Page ID.",
        ))

    link_data = spec.get("link_data", {})

    # Placeholder URL
    link = link_data.get("link", "")
    if link and any(s in link for s in _PLACEHOLDER_URL_SUBSTRINGS):
        report.findings.append(LintFinding(
            rule_id="lint-placeholder-url",
            severity=LintSeverity.WARNING,
            path=f"{path_ad}.creative.object_story_spec.link_data.link",
            message=f"Placeholder URL detected: {link!r}.",
            suggestion="Replace with the real destination URL for this ad.",
        ))

    # Placeholder image hash
    image_hash = link_data.get("image_hash", "")
    if image_hash and any(s in image_hash for s in _PLACEHOLDER_IMAGE_HASH_SUBSTRINGS):
        report.findings.append(LintFinding(
            rule_id="lint-placeholder-image-hash",
            severity=LintSeverity.WARNING,
            path=f"{path_ad}.creative.object_story_spec.link_data",
            message=f"Placeholder image_hash detected: {image_hash!r}.",
            suggestion="Replace with the real image hash from your Meta media library.",
        ))

    # Incomplete link creative — missing call_to_action
    if link_data and not link_data.get("call_to_action"):
        report.findings.append(LintFinding(
            rule_id="lint-incomplete-link-creative",
            severity=LintSeverity.INFO,
            path=f"{path_ad}.creative.object_story_spec.link_data",
            message="Link creative is missing a call_to_action.",
            suggestion='Add a call_to_action such as {"type": "SHOP_NOW"} or {"type": "LEARN_MORE"}.',
        ))


def _check_placeholder_text_on_name(name: str, path: str, report: LintReport) -> None:
    if name in _PLACEHOLDER_EXACT_NAMES:
        report.findings.append(LintFinding(
            rule_id="lint-placeholder-text",
            severity=LintSeverity.WARNING,
            path=path,
            message=f"Placeholder name detected: {name!r}.",
            suggestion="Replace with a descriptive name for this object.",
        ))


def _check_duplicate_campaign_names(template: dict, report: LintReport) -> None:
    seen: set[str] = set()
    flagged: set[str] = set()
    for campaign in template.get("campaigns", []):
        name = campaign.get("name", "")
        if name in seen and name not in flagged:
            report.findings.append(LintFinding(
                rule_id="lint-duplicate-campaign-name",
                severity=LintSeverity.WARNING,
                path="campaigns",
                message=f'Duplicate campaign name: "{name}".',
                suggestion="Give each campaign a unique name to avoid confusion during plan/apply.",
            ))
            flagged.add(name)
        seen.add(name)


def _collect_fb_ids(template: dict) -> dict[str, list[str]]:
    """Return a dict mapping fb_id → [path, ...] for all objects in the template."""
    result: dict[str, list[str]] = {}

    def _add(fb_id: str, path: str) -> None:
        result.setdefault(fb_id, []).append(path)

    for i, campaign in enumerate(template.get("campaigns", [])):
        if fid := campaign.get("fb_id"):
            _add(fid, f"campaigns[{i}]")
        for j, adset in enumerate(campaign.get("ad_sets", [])):
            if fid := adset.get("fb_id"):
                _add(fid, f"campaigns[{i}].ad_sets[{j}]")
            for k, ad in enumerate(adset.get("ads", [])):
                if fid := ad.get("fb_id"):
                    _add(fid, f"campaigns[{i}].ad_sets[{j}].ads[{k}]")

    return result


def _check_duplicate_fb_ids(template: dict, report: LintReport) -> None:
    fb_id_paths = _collect_fb_ids(template)
    for fb_id, paths in fb_id_paths.items():
        if len(paths) > 1:
            report.findings.append(LintFinding(
                rule_id="lint-duplicate-fb-id",
                severity=LintSeverity.ERROR,
                path=", ".join(paths),
                message=f'fb_id "{fb_id}" appears on multiple objects: {", ".join(paths)}.',
                suggestion="Each fb_id must be unique. Remove the duplicate or correct the wrong value.",
            ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint_stack(template: dict) -> LintReport:
    """Run all lint rules against a campaign template.

    Deterministic, local, and fast. No Facebook API calls, no AI, no I/O.
    Returns a LintReport with zero or more findings.
    """
    report = LintReport()

    _check_placeholder_account_id(template, report)

    for i, campaign in enumerate(template.get("campaigns", [])):
        path_camp = f"campaigns[{i}]"
        _check_new_resource_active(campaign, path_camp, report)
        _check_placeholder_text_on_name(campaign.get("name", ""), path_camp + ".name", report)
        _check_duplicate_adset_names(campaign, i, report)

        for j, adset in enumerate(campaign.get("ad_sets", [])):
            path_adset = f"campaigns[{i}].ad_sets[{j}]"
            _check_new_resource_active(adset, path_adset, report)
            _check_placeholder_text_on_name(adset.get("name", ""), path_adset + ".name", report)
            _check_dual_budget(adset, path_adset, report)
            _check_lifetime_budget_no_dates(adset, path_adset, report)

            for k, ad in enumerate(adset.get("ads", [])):
                path_ad = f"campaigns[{i}].ad_sets[{j}].ads[{k}]"
                _check_new_resource_active(ad, path_ad, report)
                _check_placeholder_text_on_name(ad.get("name", ""), path_ad + ".name", report)
                _check_creative(ad.get("creative", {}), path_ad, report)

    _check_duplicate_campaign_names(template, report)
    _check_duplicate_fb_ids(template, report)

    return report
