from dataclasses import dataclass

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

_BUDGET_FIELDS = ("daily_budget", "lifetime_budget")


@dataclass
class BudgetDelta:
    added: int  # dollars added by creates / update increases
    removed: int  # dollars removed by deletes / update decreases
    net: int  # added - removed; negative means net reduction


@dataclass
class CapResult:
    exceeded: bool
    cap: int | None  # dollars; None = no cap configured
    projected: int  # total declared spend in template, dollars
    overage: int  # max(0, projected - cap)


def estimate_delta(plan: Plan, state: StateFile, template: dict) -> BudgetDelta:
    added = 0
    removed = 0

    for op in plan.operations:
        if isinstance(op, CreateCampaign):
            added += _cents_to_dollars(op.campaign.get("daily_budget", 0))

        elif isinstance(op, CreateAdSet):
            adset = op.adset
            added += _cents_to_dollars(
                _budget_cents(adset, "daily_budget")
                + _budget_cents(adset, "lifetime_budget")
            )

        elif isinstance(op, DeleteCampaign):
            params = state.get_campaign_params(op.campaign_name) or {}
            removed += _cents_to_dollars(_budget_cents(params, "daily_budget"))

        elif isinstance(op, DeleteAdSet):
            params = state.get_adset_params(op.campaign_name, op.adset_name) or {}
            removed += _cents_to_dollars(
                _budget_cents(params, "daily_budget")
                + _budget_cents(params, "lifetime_budget")
            )

        elif isinstance(op, UpdateCampaign):
            old_params = state.get_campaign_params(op.campaign_name) or {}
            for field in _BUDGET_FIELDS:
                if field in op.changed_fields:
                    diff = int(op.changed_fields[field]) - _budget_cents(
                        old_params, field
                    )
                    if diff > 0:
                        added += _cents_to_dollars(diff)
                    else:
                        removed += _cents_to_dollars(-diff)

        elif isinstance(op, UpdateAdSet):
            old_params = state.get_adset_params(op.campaign_name, op.adset_name) or {}
            for field in _BUDGET_FIELDS:
                if field in op.changed_fields:
                    diff = int(op.changed_fields[field]) - _budget_cents(
                        old_params, field
                    )
                    if diff > 0:
                        added += _cents_to_dollars(diff)
                    else:
                        removed += _cents_to_dollars(-diff)

    return BudgetDelta(added=added, removed=removed, net=added - removed)


def check_cap(delta: BudgetDelta, template: dict, cap: int | None) -> CapResult:
    projected = _total_declared_dollars(template)
    if cap is None:
        return CapResult(exceeded=False, cap=None, projected=projected, overage=0)
    overage = max(0, projected - cap)
    return CapResult(
        exceeded=projected > cap, cap=cap, projected=projected, overage=overage
    )


def format_budget_section(
    delta: BudgetDelta, cap_result: CapResult, currency: str
) -> str:
    def fmt(dollars: int) -> str:
        if currency == "USD":
            return f"${dollars:,}"
        return f"{dollars:,} {currency}"

    sign = "+" if delta.net >= 0 else ""
    lines = [
        f"Budget delta: +{fmt(delta.added)} added, {fmt(delta.removed)} removed, net {sign}{fmt(delta.net)}",
        f"Projected total declared spend: {fmt(cap_result.projected)}",
    ]

    if cap_result.cap is None:
        lines.append("Budget cap: none configured")
    elif cap_result.exceeded:
        lines.append(
            f"Budget cap: EXCEEDED — {fmt(cap_result.projected)} projected vs "
            f"{fmt(cap_result.cap)} cap ({fmt(cap_result.overage)} over)"
        )
    else:
        lines.append(
            f"Budget cap: {fmt(cap_result.projected)} of {fmt(cap_result.cap)} limit"
        )

    return "\n".join(lines)


def _budget_cents(params: dict, field: str) -> int:
    value = params.get(field, 0)
    if value in (None, ""):
        return 0
    return int(value)


def _cents_to_dollars(cents: int | str) -> int:
    if cents in (None, ""):
        return 0
    return int(cents) // 100


def _total_declared_dollars(template: dict) -> int:
    total = 0
    for campaign in template.get("campaigns", []):
        total += _cents_to_dollars(campaign.get("daily_budget", 0))
        for adset in campaign.get("ad_sets", []):
            total += _cents_to_dollars(adset.get("daily_budget", 0))
            total += _cents_to_dollars(adset.get("lifetime_budget", 0))
    return total
