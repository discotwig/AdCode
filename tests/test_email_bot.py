"""Tests for src/email_bot.py — mailroom mode.

All external calls (Resend, Anthropic, ingest) are mocked.
Tests cover the three routing paths and the unknown-sender rejection.
"""
import email as email_lib
import json
import textwrap
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.email_bot import app, _bare_email, _find_customer, _parse_raw_email


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

DEMO_CONFIG = {
    "customer_slug": "demo",
    "account_id": "act_123",
    "state_dir": "state",
    "campaigns_dir": "campaigns",
    "email_addresses": ["client@example.com"],
    "operator_email": "operator@example.com",
    "bot_email": "traffic@ryanbishop.me",
    "_config_dir": Path("/fake/customers/demo"),
    "_env": {
        "ANTHROPIC_API_KEY": "anth_key",
        "RESEND_API_KEY": "re_key",
    },
}

VALID_TEMPLATE = {
    "account_id": "act_123",
    "campaigns": [
        {
            "name": "Summer Sale",
            "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED",
            "special_ad_categories": [],
            "ad_sets": [
                {
                    "name": "US 25-54",
                    "status": "PAUSED",
                    "daily_budget": 1000,
                    "billing_event": "LINK_CLICKS",
                    "optimization_goal": "LINK_CLICKS",
                    "targeting": {
                        "age_min": 25,
                        "age_max": 54,
                        "geo_locations": {"countries": ["US"]},
                    },
                    "ads": [],
                }
            ],
        }
    ],
}

INVALID_TEMPLATE = {
    "account_id": "act_123",
    "campaigns": [
        {
            "name": "Bad Campaign",
            # missing required fields: objective, status, special_ad_categories, ad_sets
        }
    ],
}


def _make_raw_plain(from_addr="client@example.com", subject="Test", body="Hello"):
    """Build a raw plain-text email string."""
    return textwrap.dedent(f"""\
        From: {from_addr}
        To: traffic@ryanbishop.me
        Subject: {subject}
        Message-ID: <test123@mail.example.com>
        Content-Type: text/plain; charset=utf-8

        {body}
    """)


def _make_raw_with_json_attachment(json_data: dict, from_addr="client@example.com", subject="Campaign update"):
    """Build a raw multipart email with a JSON file attached."""
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = "traffic@ryanbishop.me"
    msg["Subject"] = subject
    msg["Message-ID"] = "<json123@mail.example.com>"
    msg.attach(MIMEText("Please process the attached template.", "plain"))
    json_bytes = json.dumps(json_data).encode("utf-8")
    attachment = MIMEApplication(json_bytes, Name="campaign.json")
    attachment["Content-Disposition"] = 'attachment; filename="campaign.json"'
    msg.attach(attachment)
    return msg.as_string()


def _make_raw_with_xlsx_attachment(xlsx_bytes: bytes, from_addr="client@example.com", subject="Brief"):
    """Build a raw multipart email with an xlsx file attached."""
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = "traffic@ryanbishop.me"
    msg["Subject"] = subject
    msg["Message-ID"] = "<xlsx123@mail.example.com>"
    msg.attach(MIMEText("Please create campaigns from the attached brief.", "plain"))
    attachment = MIMEApplication(xlsx_bytes, Name="brief.xlsx")
    attachment["Content-Disposition"] = 'attachment; filename="brief.xlsx"'
    msg.attach(attachment)
    return msg.as_string()


def _post(client: TestClient, raw: str, from_addr="client@example.com") -> dict:
    response = client.post(
        "/inbound",
        json={"from": from_addr, "raw": raw},
    )
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------

def test_bare_email_plain():
    assert _bare_email("client@example.com") == "client@example.com"


def test_bare_email_display_name():
    assert _bare_email("Alice Smith <alice@example.com>") == "alice@example.com"


def test_find_customer_approved_sender():
    customer = _find_customer("client@example.com", [DEMO_CONFIG])
    assert customer is not None
    assert customer["customer_slug"] == "demo"


def test_find_customer_operator_sender():
    customer = _find_customer("operator@example.com", [DEMO_CONFIG])
    assert customer is not None


def test_find_customer_unknown_returns_none():
    assert _find_customer("unknown@other.com", [DEMO_CONFIG]) is None


def test_parse_raw_email_plain_text():
    raw = _make_raw_plain(body="Hello world")
    parsed = _parse_raw_email(raw)
    assert "Hello world" in parsed["body"]
    assert parsed["json_bytes"] is None
    assert parsed["xlsx_bytes"] is None


def test_parse_raw_email_json_attachment():
    raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
    parsed = _parse_raw_email(raw)
    assert parsed["json_bytes"] is not None
    assert parsed["json_filename"] == "campaign.json"
    recovered = json.loads(parsed["json_bytes"].decode("utf-8"))
    assert recovered["account_id"] == "act_123"


def test_parse_raw_email_xlsx_attachment():
    raw = _make_raw_with_xlsx_attachment(b"fakexlsxbytes")
    parsed = _parse_raw_email(raw)
    assert parsed["xlsx_bytes"] == b"fakexlsxbytes"
    assert parsed["xlsx_filename"] == "brief.xlsx"
    assert parsed["json_bytes"] is None


# ---------------------------------------------------------------------------
# Integration tests — webhook routing
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_configs():
    with patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG]):
        yield


@pytest.fixture
def mock_send_email():
    with patch("src.email_bot.send_email") as mock:
        yield mock


class TestUnknownSenderRejected:
    def test_unknown_sender_returns_rejected(self, mock_configs):
        with TestClient(app) as client:
            response = client.post(
                "/inbound",
                json={"from": "stranger@unknown.com", "raw": _make_raw_plain(from_addr="stranger@unknown.com")},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_unknown_sender_does_not_send_email(self, mock_configs, mock_send_email):
        with TestClient(app) as client:
            client.post(
                "/inbound",
                json={"from": "stranger@unknown.com", "raw": _make_raw_plain(from_addr="stranger@unknown.com")},
            )
        mock_send_email.assert_not_called()


class TestPath1ValidTemplate:
    """Valid JSON template → ack client + forward to operator."""

    def test_returns_ok(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
        with TestClient(app) as client:
            result = _post(client, raw)
        assert result["status"] == "ok"

    def test_sends_two_emails(self, mock_configs, mock_send_email):
        """One ack to client, one forward to operator."""
        raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        assert mock_send_email.call_count == 2

    def test_client_ack_contains_received_language(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        client_call = mock_send_email.call_args_list[0]
        msg = client_call[0][0]
        assert _bare_email(msg.to) == "client@example.com"
        assert "received" in msg.html.lower() or "submitted" in msg.html.lower()

    def test_operator_email_has_attachment(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        operator_call = mock_send_email.call_args_list[1]
        msg = operator_call[0][0]
        assert msg.to == "operator@example.com"
        assert msg.attachment_bytes is not None
        assert msg.attachment_filename == "campaign.json"

    def test_operator_email_subject_contains_adcode_tag(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(VALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        operator_call = mock_send_email.call_args_list[1]
        msg = operator_call[0][0]
        assert "[AdCode]" in msg.subject


class TestPath2InvalidTemplate:
    """JSON attachment fails schema → reply with errors, no operator email."""

    def test_returns_ok(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(INVALID_TEMPLATE)
        with TestClient(app) as client:
            result = _post(client, raw)
        assert result["status"] == "ok"

    def test_sends_one_email_only(self, mock_configs, mock_send_email):
        """Only the client error reply — no operator forward."""
        raw = _make_raw_with_json_attachment(INVALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        assert mock_send_email.call_count == 1

    def test_error_reply_goes_to_client(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(INVALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert _bare_email(msg.to) == "client@example.com"

    def test_error_reply_mentions_issues(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(INVALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert "issue" in msg.html.lower() or "error" in msg.html.lower() or "found" in msg.html.lower()

    def test_no_attachment_on_error_reply(self, mock_configs, mock_send_email):
        raw = _make_raw_with_json_attachment(INVALID_TEMPLATE)
        with TestClient(app) as client:
            _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert msg.attachment_bytes is None


class TestPath3DirtyExcelSeeding:
    """xlsx attachment → seed template → reply client with template."""

    def _mock_ingest_result(self):
        from src.services.ingest import IngestionResult
        return IngestionResult(
            campaigns=VALID_TEMPLATE["campaigns"],
            ambiguities=[],
            confidence=0.9,
        )

    def test_seeds_template_and_replies(self, mock_configs, mock_send_email):
        with patch("src.email_bot.read_excel", return_value={}), \
             patch("src.email_bot.extract_campaigns", return_value=self._mock_ingest_result()), \
             patch("src.email_bot.anthropic.Anthropic"):
            raw = _make_raw_with_xlsx_attachment(b"fakexlsx")
            with TestClient(app) as client:
                result = _post(client, raw)
        assert result["status"] == "ok"
        assert mock_send_email.call_count == 1

    def test_reply_has_json_attachment(self, mock_configs, mock_send_email):
        with patch("src.email_bot.read_excel", return_value={}), \
             patch("src.email_bot.extract_campaigns", return_value=self._mock_ingest_result()), \
             patch("src.email_bot.anthropic.Anthropic"):
            raw = _make_raw_with_xlsx_attachment(b"fakexlsx")
            with TestClient(app) as client:
                _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert msg.attachment_bytes is not None
        assert msg.attachment_filename == "campaign_template.json"

    def test_reply_instructs_client_to_review(self, mock_configs, mock_send_email):
        with patch("src.email_bot.read_excel", return_value={}), \
             patch("src.email_bot.extract_campaigns", return_value=self._mock_ingest_result()), \
             patch("src.email_bot.anthropic.Anthropic"):
            raw = _make_raw_with_xlsx_attachment(b"fakexlsx")
            with TestClient(app) as client:
                _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert "review" in msg.html.lower() or "resubmit" in msg.html.lower()

    def test_reply_goes_to_client_not_operator(self, mock_configs, mock_send_email):
        with patch("src.email_bot.read_excel", return_value={}), \
             patch("src.email_bot.extract_campaigns", return_value=self._mock_ingest_result()), \
             patch("src.email_bot.anthropic.Anthropic"):
            raw = _make_raw_with_xlsx_attachment(b"fakexlsx")
            with TestClient(app) as client:
                _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert _bare_email(msg.to) == "client@example.com"

    def test_plain_text_also_seeds_template(self, mock_configs, mock_send_email):
        from src.services.ingest import IngestionResult
        ingest_result = IngestionResult(
            campaigns=VALID_TEMPLATE["campaigns"],
            ambiguities=[],
            confidence=0.85,
        )
        with patch("src.email_bot.extract_from_text", return_value=ingest_result), \
             patch("src.email_bot.anthropic.Anthropic"):
            raw = _make_raw_plain(body="Create a brand awareness campaign with $5000 budget.")
            with TestClient(app) as client:
                _post(client, raw)
        msg = mock_send_email.call_args[0][0]
        assert msg.attachment_bytes is not None
        assert msg.attachment_filename == "campaign_template.json"


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
