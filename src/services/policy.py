import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BUILTIN_DIR = Path(__file__).resolve().parents[2] / "policies" / "builtin"


@dataclass
class PolicyRule:
    id: str
    description: str
    severity: str  # "ERROR" | "WARNING"
    condition: dict


@dataclass
class PolicyViolation:
    rule_id: str
    severity: str
    field: str
    message: str


def load_policies(stack_dir: Path | None) -> list[PolicyRule]:
    rules: dict[str, PolicyRule] = {}

    for rule_file in sorted(_BUILTIN_DIR.glob("*.json")):
        try:
            rule = _load_rule_file(rule_file)
            rules[rule.id] = rule
        except Exception as e:
            logger.warning("Failed to load builtin rule %s: %s", rule_file.name, e)

    if stack_dir is not None:
        stack_policy_dir = stack_dir / "policies"
        if stack_policy_dir.is_dir():
            for rule_file in sorted(stack_policy_dir.glob("*.json")):
                try:
                    rule = _load_rule_file(rule_file)
                    rules[rule.id] = rule
                except Exception as e:
                    logger.warning("Failed to load stack rule %s: %s", rule_file.name, e)

    return list(rules.values())


def evaluate(template: dict, rules: list[PolicyRule]) -> list[PolicyViolation]:
    violations = []
    campaigns = template.get("campaigns", [])
    for i, campaign in enumerate(campaigns):
        for rule in rules:
            if rule.condition.get("scope") == "campaign":
                violations.extend(_check_condition(rule, campaign, {}, f"campaigns[{i}]"))

        for j, ad_set in enumerate(campaign.get("ad_sets", [])):
            ctx = {"campaign": campaign}
            loc = f"campaigns[{i}].ad_sets[{j}]"
            for rule in rules:
                if rule.condition.get("scope") == "ad_set":
                    violations.extend(_check_condition(rule, ad_set, ctx, loc))

    return violations


def _load_rule_file(path: Path) -> PolicyRule:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return PolicyRule(
        id=data["id"],
        description=data["description"],
        severity=data["severity"],
        condition=data["condition"],
    )


def _resolve_path(obj: dict, dot_path: str) -> Any:
    parts = dot_path.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _check_condition(
    rule: PolicyRule,
    obj: dict,
    ctx: dict,
    location: str,
) -> list[PolicyViolation]:
    cond = rule.condition
    cond_type = cond.get("type")
    name = obj.get("name", location)
    raw_msg = cond.get("message", rule.description)
    message = raw_msg.replace("{name}", str(name))

    if cond_type == "field_required":
        field = cond.get("field", "")
        value = _resolve_path(obj, field)
        if value is None:
            return [PolicyViolation(
                rule_id=rule.id,
                severity=rule.severity,
                field=f"{location}.{field}",
                message=message,
            )]

    elif cond_type == "any_field_nonempty":
        fields = cond.get("fields", [])
        for field in fields:
            value = _resolve_path(obj, field)
            if isinstance(value, list) and len(value) > 0:
                return []
        return [PolicyViolation(
            rule_id=rule.id,
            severity=rule.severity,
            field=f"{location}.targeting",
            message=message,
        )]

    elif cond_type == "compatibility_matrix":
        allowed = cond.get("allowed", [])
        row_field = cond.get("row_field", "")
        col_field = cond.get("col_field", "")
        third_field = cond.get("third_field", "")

        if row_field.startswith("campaign."):
            campaign = ctx.get("campaign", {})
            row_val = _resolve_path(campaign, row_field[len("campaign."):])
        else:
            row_val = _resolve_path(obj, row_field)

        col_val = _resolve_path(obj, col_field)
        third_val = _resolve_path(obj, third_field)

        if row_val is None or col_val is None or third_val is None:
            return []

        combo = [row_val, col_val, third_val]
        if combo not in allowed:
            return [PolicyViolation(
                rule_id=rule.id,
                severity=rule.severity,
                field=f"{location}.{col_field}",
                message=message,
            )]

    return []
