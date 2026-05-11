import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import jsonschema

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "campaign.schema.json"

with open(SCHEMA_PATH) as _f:
    _CAMPAIGN_SCHEMA = json.load(_f)


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationError:
    field: str
    message: str


@dataclass
class PolicyWarning:
    severity: Severity
    field: str
    message: str
    suggestion: str


@dataclass
class ValidationResult:
    schema_errors: list[ValidationError] = field(default_factory=list)
    policy_warnings: list[PolicyWarning] = field(default_factory=list)

    @property
    def is_pushable(self) -> bool:
        if self.schema_errors:
            return False
        return not any(w.severity == Severity.ERROR for w in self.policy_warnings)

    def summary(self) -> str:
        lines = []
        if not self.schema_errors and not self.policy_warnings:
            lines.append("Validation passed. No issues found.")
        if self.schema_errors:
            lines.append(f"{len(self.schema_errors)} schema error(s):")
            for e in self.schema_errors:
                lines.append(f"  [SCHEMA ERROR] {e.field}: {e.message}")
        if self.policy_warnings:
            lines.append(f"{len(self.policy_warnings)} policy warning(s):")
            for w in self.policy_warnings:
                lines.append(f"  [{w.severity}] {w.field}: {w.message}")
                if w.suggestion:
                    lines.append(f"    Suggestion: {w.suggestion}")
        lines.append(f"Pushable: {self.is_pushable}")
        return "\n".join(lines)


_POLICY_PROMPT = """\
You are a Facebook Ads policy reviewer. Review the following campaign JSON and identify any content
that may violate Facebook's advertising policies or be likely to cause ad rejection.

Check for:
1. Prohibited content categories: financial products with misleading claims, health/medical claims,
   adult content, political content, gambling, weapons, drugs, or tobacco.
2. Special Ad Category triggers: employment, housing, credit, or political content that requires
   declaring a Special Ad Category but has an empty special_ad_categories array.
3. Copy patterns that frequently cause rejection: superlative claims ("best", "#1", "guaranteed"),
   before/after language, personal attribute targeting implications, clickbait.
4. Landing page issues: URLs that appear to lead to prohibited content or are clearly placeholder values.
5. Missing or placeholder fields: page_id set to "REPLACE_WITH_PAGE_ID", account_id "act_000000000".

Respond with a JSON array of policy warnings. Each warning must have these fields:
- severity: "ERROR" (likely rejection), "WARNING" (possible rejection), or "INFO" (note)
- field: the JSON path to the problematic field (e.g. "campaigns[0].ad_sets[0].ads[0].creative.object_story_spec.link_data.message")
- message: a concise description of the issue
- suggestion: what to change to fix it

If there are no issues, return an empty array [].

Campaign JSON:
{campaign_json}

Return only the JSON array, no other text."""


def validate_schema(campaign_json: dict) -> list[ValidationError]:
    validator = jsonschema.Draft7Validator(_CAMPAIGN_SCHEMA)
    errors = []
    for error in validator.iter_errors(campaign_json):
        path = ".".join(str(p) for p in error.absolute_path) or "root"
        errors.append(ValidationError(field=path, message=error.message))
    return errors


def validate_policy(campaign_json: dict, ai_client) -> list[PolicyWarning]:
    prompt = _POLICY_PROMPT.format(campaign_json=json.dumps(campaign_json, indent=2))

    response = ai_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    try:
        warnings_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Policy validator returned non-JSON response; treating as no warnings.")
        return []

    warnings = []
    for item in warnings_data:
        try:
            warnings.append(PolicyWarning(
                severity=Severity(item["severity"]),
                field=item.get("field", "unknown"),
                message=item.get("message", ""),
                suggestion=item.get("suggestion", ""),
            ))
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed policy warning: %s", e)
    return warnings


def validate_all(campaign_json: dict, ai_client) -> ValidationResult:
    result = ValidationResult()
    result.schema_errors = validate_schema(campaign_json)
    if not result.schema_errors:
        result.policy_warnings = validate_policy(campaign_json, ai_client)
    return result
