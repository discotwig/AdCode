"""Campaign Review Packet generator.

Produces a human-readable Markdown document from a stack template, state,
policy violations, and budget data. Designed for non-technical reviewers
(marketing managers, media directors) who do not read JSON or terminals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.budget import BudgetDelta, CapResult
    from src.services.policy import PolicyViolation
    from src.services.state import StateFile
    from src.traffic import Plan


# Plain-English fix guidance keyed by rule_id.
_FIX_GUIDANCE: dict[str, str] = {
    "broadmatch": "Add at least one interest, behavior, or custom audience to narrow targeting.",
    "spend-cap-required": "Add a spend_cap to the campaign to limit total account exposure.",
    "end-time-required": "Add an end_time to the ad set to define a safe flight end date.",
    "objective-billing-compatibility": (
        "Check that the campaign objective, billing event, and optimization goal "
        "are a valid combination."
    ),
}

_LONG_FLIGHT_DAYS = 90


def _cents_to_dollars(cents: int | None) -> int | None:
    if cents is None:
        return None
    return cents // 100


def _fmt_dollars(amount: int | None, currency: str) -> str:
    if amount is None:
        return "—"
    return f"{currency} {amount:,}"


def _count_objects(template: dict) -> tuple[int, int, int]:
    campaigns = template.get("campaigns", [])
    total_adsets = sum(len(c.get("ad_sets", [])) for c in campaigns)
    total_ads = sum(
        len(s.get("ads", []))
        for c in campaigns
        for s in c.get("ad_sets", [])
    )
    return len(campaigns), total_adsets, total_ads


def _overall_status(violations: list[PolicyViolation], cap_result: CapResult | None) -> str:
    has_error = any(v.severity == "ERROR" for v in violations)
    cap_exceeded = cap_result is not None and cap_result.exceeded
    if has_error or cap_exceeded:
        return "BLOCKED"
    if any(v.severity == "WARNING" for v in violations):
        return "WARNINGS PRESENT"
    return "READY FOR REVIEW"


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "Not set"
    try:
        dt = datetime.fromisoformat(iso.rstrip("Z"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso


def _flight_duration_days(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start.rstrip("Z"))
        e = datetime.fromisoformat(end.rstrip("Z"))
        return max(0, (e - s).days)
    except ValueError:
        return None


def _is_broad(targeting: dict) -> bool:
    return (
        not targeting.get("interests")
        and not targeting.get("behaviors")
        and not targeting.get("custom_audiences")
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_header(template: dict) -> str:
    account_id = template.get("account_id", "Unknown")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "# Campaign Review Packet\n\n"
        f"**Account:** {account_id}  \n"
        f"**Generated:** {generated}\n"
    )


def _section_executive_summary(
    template: dict,
    violations: list[PolicyViolation],
    cap_result: CapResult | None,
) -> str:
    n_campaigns, n_adsets, n_ads = _count_objects(template)
    status = _overall_status(violations, cap_result)
    n_errors = sum(1 for v in violations if v.severity == "ERROR")
    n_warnings = sum(1 for v in violations if v.severity == "WARNING")

    lines = ["## Executive Summary\n"]
    lines.append("| Item | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Account | {template.get('account_id', '—')} |")
    lines.append(f"| Campaigns | {n_campaigns} |")
    lines.append(f"| Ad Sets | {n_adsets} |")
    lines.append(f"| Ads | {n_ads} |")
    lines.append(f"| Policy Errors | {n_errors} |")
    lines.append(f"| Policy Warnings | {n_warnings} |")
    lines.append(f"| **Overall Status** | **{status}** |")
    return "\n".join(lines)


def _section_approval_recommendation(
    violations: list[PolicyViolation],
    cap_result: CapResult | None,
) -> str:
    status = _overall_status(violations, cap_result)
    n_errors = sum(1 for v in violations if v.severity == "ERROR")
    n_warnings = sum(1 for v in violations if v.severity == "WARNING")

    lines = ["## Approval Recommendation\n"]
    if status == "BLOCKED":
        reasons = []
        if n_errors:
            reasons.append(f"{n_errors} blocking policy issue(s)")
        if cap_result and cap_result.exceeded:
            reasons.append("budget cap exceeded")
        lines.append(
            "**This stack cannot be applied.** "
            f"Resolve {' and '.join(reasons)} before running apply_stack. "
            "See Policy Results and Budget Impact below for details."
        )
    elif status == "WARNINGS PRESENT":
        lines.append(
            f"This stack can be applied, but {n_warnings} warning(s) require review. "
            "Confirm the flagged items below before approving."
        )
    else:
        lines.append(
            "No blocking issues or warnings detected. "
            "This stack is ready to apply after completing the Human Review Checklist."
        )
    return "\n".join(lines)


def _section_planned_changes(plan: Plan) -> str:
    from src.traffic import (
        CreateCampaign, CreateAdSet, CreateAd,
        UpdateCampaign, UpdateAdSet, UpdateAd,
        DeleteCampaign, DeleteAdSet, DeleteAd,
    )

    lines = ["## Planned Changes\n"]
    if not plan or not plan.operations:
        lines.append("No changes planned (stack matches current state).")
        return "\n".join(lines)

    creates, updates, deletes = [], [], []
    for op in plan.operations:
        if isinstance(op, (CreateCampaign, CreateAdSet, CreateAd)):
            creates.append(op)
        elif isinstance(op, (UpdateCampaign, UpdateAdSet, UpdateAd)):
            updates.append(op)
        elif isinstance(op, (DeleteCampaign, DeleteAdSet, DeleteAd)):
            deletes.append(op)

    total = len(plan.operations)
    noops = 0  # noops are implicit — objects not in the operations list

    lines.append(
        f"**{len(creates)} create(s), {len(updates)} update(s), "
        f"{len(deletes)} delete(s)**  "
    )

    if creates:
        lines.append("\n**Creates:**")
        for op in creates:
            if isinstance(op, CreateCampaign):
                lines.append(f"- Campaign: {op.campaign.get('name', '—')}")
            elif isinstance(op, CreateAdSet):
                lines.append(f"- Ad Set: {op.adset.get('name', '—')} (under {op.campaign_name})")
            elif isinstance(op, CreateAd):
                lines.append(f"- Ad: {op.ad.get('name', '—')} (under {op.adset_name})")

    if updates:
        lines.append("\n**Updates:**")
        for op in updates:
            if isinstance(op, UpdateCampaign):
                fields = ", ".join(op.changed_fields.keys())
                lines.append(f"- Campaign: {op.campaign_name} — changed: {fields}")
            elif isinstance(op, UpdateAdSet):
                fields = ", ".join(op.changed_fields.keys())
                lines.append(f"- Ad Set: {op.adset_name} — changed: {fields}")
            elif isinstance(op, UpdateAd):
                fields = ", ".join(op.changed_fields.keys())
                lines.append(f"- Ad: {op.ad_name} — changed: {fields}")

    if deletes:
        lines.append("\n**Deletes:**")
        for op in deletes:
            if isinstance(op, DeleteCampaign):
                lines.append(f"- Campaign: {op.campaign_name}")
            elif isinstance(op, DeleteAdSet):
                lines.append(f"- Ad Set: {op.adset_name} (under {op.campaign_name})")
            elif isinstance(op, DeleteAd):
                lines.append(f"- Ad: {op.ad_name} (under {op.adset_name})")

    return "\n".join(lines)


def _section_budget_impact(
    template: dict,
    delta: BudgetDelta | None,
    cap_result: CapResult | None,
    currency: str,
) -> str:
    lines = ["## Budget Impact\n"]

    if delta is None:
        lines.append("No budget data available.")
        return "\n".join(lines)

    lines.append("| | Amount |")
    lines.append("| --- | --- |")
    lines.append(f"| Added | {_fmt_dollars(delta.added, currency)} |")
    lines.append(f"| Removed | {_fmt_dollars(delta.removed, currency)} |")
    lines.append(f"| Net change | {_fmt_dollars(delta.net, currency)} |")

    if cap_result is not None:
        status_label = "EXCEEDED" if cap_result.exceeded else "OK"
        lines.append(f"| Account cap | {_fmt_dollars(cap_result.cap, currency)} |")
        lines.append(f"| Projected total | {_fmt_dollars(cap_result.projected, currency)} |")
        if cap_result.exceeded:
            lines.append(
                f"| Cap status | **{status_label}** (+{_fmt_dollars(cap_result.overage, currency)} over cap) |"
            )
        else:
            lines.append(f"| Cap status | {status_label} |")

    # Per-object budget breakdown
    lines.append("\n**Declared budgets by campaign/ad set:**\n")
    campaigns = template.get("campaigns", [])
    for c in campaigns:
        c_budget = _cents_to_dollars(c.get("daily_budget") or c.get("lifetime_budget"))
        budget_label = _fmt_dollars(c_budget, currency)
        budget_type = "daily" if c.get("daily_budget") else "lifetime" if c.get("lifetime_budget") else ""
        lines.append(f"- **{c['name']}**: {budget_label}/day ({budget_type})" if budget_type == "daily" else f"- **{c['name']}**: {budget_label}")
        for s in c.get("ad_sets", []):
            s_budget = _cents_to_dollars(s.get("daily_budget") or s.get("lifetime_budget"))
            s_budget_label = _fmt_dollars(s_budget, currency)
            s_budget_type = "daily" if s.get("daily_budget") else "lifetime" if s.get("lifetime_budget") else ""
            lines.append(f"  - {s['name']}: {s_budget_label}/day ({s_budget_type})" if s_budget_type == "daily" else f"  - {s['name']}: {s_budget_label}")

    return "\n".join(lines)


def _section_policy_results(violations: list[PolicyViolation]) -> str:
    lines = ["## Policy Results\n"]
    errors = [v for v in violations if v.severity == "ERROR"]
    warnings = [v for v in violations if v.severity == "WARNING"]
    passed = len(violations) == 0

    summary_parts = []
    if errors:
        summary_parts.append(f"{len(errors)} error(s)")
    if warnings:
        summary_parts.append(f"{len(warnings)} warning(s)")
    if passed:
        lines.append("All built-in policy checks passed.")
        return "\n".join(lines)

    lines.append(", ".join(summary_parts) + "\n")
    lines.append("| Severity | Rule | Affected Object | Issue | Fix |")
    lines.append("| --- | --- | --- | --- | --- |")
    for v in violations:
        fix = _FIX_GUIDANCE.get(v.rule_id, "Review and correct manually.")
        lines.append(f"| {v.severity} | {v.rule_id} | {v.field} | {v.message} | {fix} |")

    return "\n".join(lines)


def _section_campaign_hierarchy(template: dict, currency: str) -> str:
    lines = ["## Campaign Hierarchy\n"]
    campaigns = template.get("campaigns", [])
    if not campaigns:
        lines.append("No campaigns defined.")
        return "\n".join(lines)

    for c in campaigns:
        c_budget = _cents_to_dollars(c.get("daily_budget") or c.get("lifetime_budget"))
        budget_str = _fmt_dollars(c_budget, currency)
        budget_type = "daily" if c.get("daily_budget") else "lifetime" if c.get("lifetime_budget") else ""
        budget_display = f"{budget_str}/{budget_type}" if budget_type else budget_str
        lines.append(
            f"### {c['name']}\n"
            f"- **Objective:** {c.get('objective', '—')}\n"
            f"- **Status:** {c.get('status', '—')}\n"
            f"- **Budget:** {budget_display}\n"
        )
        for s in c.get("ad_sets", []):
            s_budget = _cents_to_dollars(s.get("daily_budget") or s.get("lifetime_budget"))
            s_budget_str = _fmt_dollars(s_budget, currency)
            s_type = "daily" if s.get("daily_budget") else "lifetime" if s.get("lifetime_budget") else ""
            s_budget_display = f"{s_budget_str}/{s_type}" if s_type else s_budget_str
            lines.append(
                f"  - **Ad Set:** {s['name']} | Status: {s.get('status', '—')} | "
                f"Budget: {s_budget_display} | "
                f"Optimization: {s.get('optimization_goal', '—')}"
            )
            for a in s.get("ads", []):
                lines.append(f"    - Ad: {a.get('name', '—')} | Status: {a.get('status', '—')}")

    return "\n".join(lines)


def _section_targeting_summary(template: dict) -> str:
    lines = ["## Targeting Summary\n"]
    campaigns = template.get("campaigns", [])

    any_adset = False
    for c in campaigns:
        for s in c.get("ad_sets", []):
            any_adset = True
            targeting = s.get("targeting", {})
            broad = _is_broad(targeting)

            lines.append(f"### {s['name']} (under {c['name']})\n")

            # Geography
            geo = targeting.get("geo_locations", {})
            countries = geo.get("countries", [])
            regions = geo.get("regions", [])
            geo_parts = countries + [r.get("name", str(r)) for r in regions if isinstance(r, dict)]
            geo_str = ", ".join(geo_parts) if geo_parts else "Not specified"
            lines.append(f"- **Geography:** {geo_str}")

            # Age
            age_min = targeting.get("age_min")
            age_max = targeting.get("age_max")
            if age_min or age_max:
                lines.append(f"- **Age:** {age_min or '—'}–{age_max or '—'}")
            else:
                lines.append("- **Age:** Not specified")

            # Interests
            interests = targeting.get("interests", [])
            if interests:
                names = [i.get("name", str(i)) if isinstance(i, dict) else str(i) for i in interests]
                lines.append(f"- **Interests:** {', '.join(names)}")
            else:
                lines.append("- **Interests:** None")

            # Behaviors
            behaviors = targeting.get("behaviors", [])
            if behaviors:
                names = [b.get("name", str(b)) if isinstance(b, dict) else str(b) for b in behaviors]
                lines.append(f"- **Behaviors:** {', '.join(names)}")
            else:
                lines.append("- **Behaviors:** None")

            # Custom audiences
            audiences = targeting.get("custom_audiences", [])
            if audiences:
                names = [a.get("name", a.get("id", str(a))) if isinstance(a, dict) else str(a) for a in audiences]
                lines.append(f"- **Custom Audiences:** {', '.join(names)}")
            else:
                lines.append("- **Custom Audiences:** None")

            if broad:
                lines.append("\n**⚠ Broad targeting** — no interests, behaviors, or custom audiences. "
                             "This ad set will reach an unconstrained audience.")

            lines.append("")

    if not any_adset:
        lines.append("No ad sets defined.")

    return "\n".join(lines)


def _section_flight_dates(template: dict) -> str:
    lines = ["## Flight Dates\n"]
    campaigns = template.get("campaigns", [])

    rows = []
    for c in campaigns:
        for s in c.get("ad_sets", []):
            start = s.get("start_time")
            end = s.get("end_time")
            duration = _flight_duration_days(start, end)

            flags = []
            if not end:
                flags.append("⚠ No end date")
            elif duration is not None and duration > _LONG_FLIGHT_DAYS:
                flags.append(f"⚠ Long flight ({duration} days)")

            rows.append((
                s["name"],
                _fmt_date(start),
                _fmt_date(end),
                f"{duration} days" if duration is not None else "—",
                " ".join(flags),
            ))

    if not rows:
        lines.append("No ad sets defined.")
        return "\n".join(lines)

    lines.append("| Ad Set | Start | End | Duration | Notes |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, start, end, dur, flags in rows:
        lines.append(f"| {name} | {start} | {end} | {dur} | {flags} |")

    return "\n".join(lines)


def _section_human_review_checklist(
    template: dict,
    violations: list[PolicyViolation],
    cap_result: CapResult | None,
) -> str:
    lines = ["## Human Review Checklist\n"]
    lines.append("Confirm each item before approving this stack for apply:\n")

    # Always-present items
    lines.append("- [ ] Creative copy reviewed and approved")
    lines.append("- [ ] Landing page URL(s) are live and correct")
    lines.append("- [ ] Ad account billing is active")
    lines.append("- [ ] Campaign objectives match the media plan")

    # Conditional on violations
    for v in violations:
        if v.severity == "ERROR":
            fix = _FIX_GUIDANCE.get(v.rule_id, "Review and correct manually.")
            lines.append(f"- [ ] **[BLOCKING]** {fix} ({v.rule_id} on {v.field})")
        elif v.severity == "WARNING":
            lines.append(f"- [ ] Review: {v.message} ({v.rule_id})")

    # Broad targeting
    for c in template.get("campaigns", []):
        for s in c.get("ad_sets", []):
            if _is_broad(s.get("targeting", {})):
                lines.append(
                    f"- [ ] Confirm targeting is intentionally broad for ad set \"{s['name']}\""
                )

    # Missing end dates
    for c in template.get("campaigns", []):
        for s in c.get("ad_sets", []):
            if not s.get("end_time"):
                lines.append(
                    f"- [ ] Confirm flight end date before approving ad set \"{s['name']}\""
                )

    # Cap exceeded
    if cap_result and cap_result.exceeded:
        lines.append("- [ ] **[BLOCKING]** Resolve budget cap overage before running apply_stack")

    return "\n".join(lines)


def _section_next_action(
    violations: list[PolicyViolation],
    cap_result: CapResult | None,
) -> str:
    status = _overall_status(violations, cap_result)
    lines = ["## Next Action\n"]
    if status == "BLOCKED":
        lines.append("Fix the blocking issues listed above, then re-run `plan_stack` and `document_stack` before applying.")
    elif status == "WARNINGS PRESENT":
        lines.append("Review the warnings above. When ready, run `apply_stack` to push this stack to Facebook.")
    else:
        lines.append("Run `apply_stack` to push this stack to Facebook.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(
    template: dict,
    state: StateFile,
    violations: list[PolicyViolation],
    delta: BudgetDelta | None,
    plan: Plan | None = None,
    cap_result: CapResult | None = None,
    currency: str = "USD",
) -> str:
    sections = [
        _section_header(template),
        _section_executive_summary(template, violations, cap_result),
        _section_approval_recommendation(violations, cap_result),
    ]

    if plan is not None:
        sections.append(_section_planned_changes(plan))

    sections += [
        _section_budget_impact(template, delta, cap_result, currency),
        _section_policy_results(violations),
        _section_campaign_hierarchy(template, currency),
        _section_targeting_summary(template),
        _section_flight_dates(template),
        _section_human_review_checklist(template, violations, cap_result),
        _section_next_action(violations, cap_result),
    ]

    return "\n\n---\n\n".join(sections)
