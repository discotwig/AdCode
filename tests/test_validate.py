import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.services.validate import (
    validate_schema, validate_policy, validate_all,
    ValidationResult, ValidationError, PolicyWarning, Severity,
)

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


@pytest.fixture
def example_campaign():
    with open(CAMPAIGNS_DIR / "example.json") as f:
        return json.load(f)


def _make_ai_client(warnings: list[dict]) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    content = MagicMock()
    content.text = json.dumps(warnings)
    message.content = [content]
    client.messages.create.return_value = message
    return client


class TestValidateSchema:
    def test_valid_campaign_returns_no_errors(self, example_campaign):
        errors = validate_schema(example_campaign)
        assert errors == []

    def test_missing_required_field_returns_error(self, example_campaign):
        del example_campaign["campaigns"][0]["objective"]
        errors = validate_schema(example_campaign)
        assert len(errors) > 0
        assert any("objective" in e.message or "objective" in e.field for e in errors)

    def test_invalid_status_returns_error(self, example_campaign):
        example_campaign["campaigns"][0]["status"] = "RUNNING"
        errors = validate_schema(example_campaign)
        assert len(errors) > 0

    def test_empty_campaigns_array_returns_error(self, example_campaign):
        example_campaign["campaigns"] = []
        errors = validate_schema(example_campaign)
        assert len(errors) > 0

    def test_returns_list_of_validation_error_objects(self, example_campaign):
        del example_campaign["campaigns"][0]["name"]
        errors = validate_schema(example_campaign)
        assert all(isinstance(e, ValidationError) for e in errors)

    def test_error_field_contains_path(self, example_campaign):
        del example_campaign["campaigns"][0]["ad_sets"][0]["billing_event"]
        errors = validate_schema(example_campaign)
        assert any("billing_event" in e.message or "0" in e.field for e in errors)


class TestValidatePolicy:
    def test_no_warnings_returns_empty_list(self, example_campaign):
        ai_client = _make_ai_client([])
        warnings = validate_policy(example_campaign, ai_client)
        assert warnings == []

    def test_returns_policy_warning_objects(self, example_campaign):
        raw_warnings = [
            {
                "severity": "WARNING",
                "field": "campaigns[0].ad_sets[0].ads[0].creative.object_story_spec.link_data.message",
                "message": "Copy contains superlative claim.",
                "suggestion": "Remove or qualify the claim.",
            }
        ]
        ai_client = _make_ai_client(raw_warnings)
        warnings = validate_policy(example_campaign, ai_client)
        assert len(warnings) == 1
        assert isinstance(warnings[0], PolicyWarning)
        assert warnings[0].severity == Severity.WARNING

    def test_error_severity_parsed_correctly(self, example_campaign):
        raw_warnings = [{"severity": "ERROR", "field": "campaigns[0]", "message": "Prohibited.", "suggestion": "Remove."}]
        ai_client = _make_ai_client(raw_warnings)
        warnings = validate_policy(example_campaign, ai_client)
        assert warnings[0].severity == Severity.ERROR

    def test_non_json_response_returns_empty_list(self, example_campaign):
        ai_client = MagicMock()
        content = MagicMock()
        content.text = "Sorry, I cannot review this."
        ai_client.messages.create.return_value.content = [content]
        warnings = validate_policy(example_campaign, ai_client)
        assert warnings == []

    def test_malformed_warning_items_are_skipped(self, example_campaign):
        raw_warnings = [
            {"severity": "INVALID_SEVERITY", "field": "x", "message": "y", "suggestion": "z"},
            {"severity": "INFO", "field": "a", "message": "b", "suggestion": "c"},
        ]
        ai_client = _make_ai_client(raw_warnings)
        warnings = validate_policy(example_campaign, ai_client)
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.INFO

    def test_ai_client_is_called_with_campaign_json(self, example_campaign):
        ai_client = _make_ai_client([])
        validate_policy(example_campaign, ai_client)
        ai_client.messages.create.assert_called_once()


class TestValidateAll:
    def test_valid_campaign_is_pushable(self, example_campaign):
        ai_client = _make_ai_client([])
        result = validate_all(example_campaign, ai_client)
        assert result.is_pushable

    def test_schema_errors_make_not_pushable(self, example_campaign):
        example_campaign["campaigns"] = []
        ai_client = _make_ai_client([])
        result = validate_all(example_campaign, ai_client)
        assert not result.is_pushable

    def test_policy_error_severity_makes_not_pushable(self, example_campaign):
        raw_warnings = [{"severity": "ERROR", "field": "x", "message": "Prohibited.", "suggestion": "Fix it."}]
        ai_client = _make_ai_client(raw_warnings)
        result = validate_all(example_campaign, ai_client)
        assert not result.is_pushable

    def test_policy_warning_severity_still_pushable(self, example_campaign):
        raw_warnings = [{"severity": "WARNING", "field": "x", "message": "Risk.", "suggestion": "Consider."}]
        ai_client = _make_ai_client(raw_warnings)
        result = validate_all(example_campaign, ai_client)
        assert result.is_pushable

    def test_schema_errors_skip_policy_check(self, example_campaign):
        example_campaign["campaigns"] = []
        ai_client = _make_ai_client([])
        validate_all(example_campaign, ai_client)
        ai_client.messages.create.assert_not_called()

    def test_result_summary_non_empty(self, example_campaign):
        ai_client = _make_ai_client([])
        result = validate_all(example_campaign, ai_client)
        assert len(result.summary()) > 0

    def test_result_contains_schema_errors(self, example_campaign):
        example_campaign["campaigns"][0]["status"] = "DELETED"
        ai_client = _make_ai_client([])
        result = validate_all(example_campaign, ai_client)
        assert len(result.schema_errors) > 0

    def test_result_contains_policy_warnings(self, example_campaign):
        raw_warnings = [{"severity": "INFO", "field": "x", "message": "Note.", "suggestion": ""}]
        ai_client = _make_ai_client(raw_warnings)
        result = validate_all(example_campaign, ai_client)
        assert len(result.policy_warnings) == 1
