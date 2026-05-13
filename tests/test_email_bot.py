"""Tests for src/email_bot.py — mailroom mode, sender-agnostic.

All external calls (Resend, Anthropic, ingest) are mocked.
Global env vars (OPERATOR_EMAIL, BOT_EMAIL, etc.) are patched per test.
"""
import email as email_lib
import json
import textwrap
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.email_bot import app, _bare_email, _parse_raw_email, ACCOUNT_ID_PLACEHOLDER


# ---------------------------------------------------------------------------
# Email building helpers
# ---------------------------------------------------------------------------

def _make_raw_plain(from_addr="anyone@example.com", subject="Test", body="Hello"):
    return textwrap.dedent(f"""\
        From: {from_addr}
        To: traffic@ryanbishop.me
        Subject: {subject}
        Message-ID: <test123@mail.example.com>
        Content-Type: text/plain; charset=utf-8

        {body}
    """)


def _make_raw_with_json_attachment(json_data: dict, from_addr="anyone@example.com", subject="Campaign update"):
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


def _make_raw_with_xlsx_attachment(xlsx_bytes: bytes, from_addr="anyone@example.com", subject="Brief"):
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


def _post(client: TestClient, raw: str, from_addr="anyone@example.com") -> dict:
    response = client.post("/inbound", json={"from": from_addr, "raw": raw})
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Shared env var patch
# ---------------------------------------------------------------------------

ENV_PATCH = {
    "src.email_bot.OPERATOR_EMAIL": "operator@example.com",
    "src.email_bot.BOT_EMAIL": "traffic@ryanbishop.me",
    "src.email_bot.RESEND_API_KEY": "re_test_key",
    "src.email_bot.ANTHROPIC_API_KEY": "anth_test_key",
}


def _env_patches():
    return [patch(k, v) for k, v in ENV_PATCH.items()]


# ---------------------------------------------------------------------------
# Valid and invalid template fixtures
# ---------------------------------------------------------------------------

VALID_TEMPLATE = {
    "account_id": "act_123456789",
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
    "campaigns": [{"name": "Bad Campaign"}],  # missing required fields
}


# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------

def test_bare_email_plain():
    assert _bare_email("client@example.com") == "client@example.com"


def test_bare_email_display_name():
    assert _bare_email("Alice Smith <alice@example.com>") == "alice@example.com"


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
    assert recovered["account_id"] == "act_123456789"


def test_parse_raw_email_xlsx_attachment():
    raw = _make_raw_with_xlsx_attachment(b"fakexlsxbytes")
    parsed = _parse_raw_email(raw)
    assert parsed["xlsx_bytes"] == b"fakexlsxbytes"
    assert parsed["xlsx_filename"] == "brief.xlsx"
    assert parsed["json_bytes"] is None


def test_account_id_placeholder_format():
    assert ACCOUNT_ID_PLACEHOLDER.startswith("act_")


# ---------------------------------------------------------------------------
# Any sender is accepted
# ---------------------------------------------------------------------------

class TestAnySenderAccepted:
    def test_unknown_sender_returns_ok(self):
        with patch("src.email_bot.send_email"):
            patches = _env_patches()
            for p in patches:
                p.start()
            try:
                with TestClient(app) as client:
                    result = _post(client, _make_raw_with_json_attachment(VALID_TEMPLATE), from_addr="stranger@unknown.com")
            finally:
                for p in patches:
                    p.stop()
        assert result["status"] == "ok"

    def test_any_email_address_is_processed(self):
        """The bot does not maintain an allowlist — all senders are handled."""
        sent = []
        with patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
            patches = _env_patches()
            for p in patches:
                p.start()
            try:
                with TestClient(app) as client:
                    _post(client, _make_raw_with_json_attachment(VALID_TEMPLATE), from_addr="random@whoever.com")
            finally:
                for p in patches:
                    p.stop()
        assert len(sent) == 2  # ack to sender + forward to operator


# ---------------------------------------------------------------------------
# Path 1 — Valid template
# ---------------------------------------------------------------------------

class TestPath1ValidTemplate:
    def _run(self, from_addr="client@example.com"):
        sent = []
        patches = _env_patches()
        for p in patches:
            p.start()
        try:
            with patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
                with TestClient(app) as client:
                    result = _post(client, _make_raw_with_json_attachment(VALID_TEMPLATE, from_addr=from_addr))
        finally:
            for p in patches:
                p.stop()
        return result, sent

    def test_returns_ok(self):
        result, _ = self._run()
        assert result["status"] == "ok"

    def test_sends_two_emails(self):
        _, sent = self._run()
        assert len(sent) == 2

    def test_client_ack_sent_to_sender(self):
        _, sent = self._run(from_addr="client@example.com")
        ack = sent[0]
        assert _bare_email(ack.to) == "client@example.com"
        assert "received" in ack.html.lower() or "submitted" in ack.html.lower()

    def test_operator_email_has_attachment(self):
        _, sent = self._run()
        op = sent[1]
        assert op.to == "operator@example.com"
        assert op.attachment_bytes is not None
        assert op.attachment_filename == "campaign.json"

    def test_operator_subject_contains_adcode_tag(self):
        _, sent = self._run()
        assert "[AdCode]" in sent[1].subject

    def test_no_operator_email_when_operator_not_configured(self):
        sent = []
        patches = _env_patches() + [patch("src.email_bot.OPERATOR_EMAIL", "")]
        for p in patches:
            p.start()
        try:
            with patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
                with TestClient(app) as client:
                    _post(client, _make_raw_with_json_attachment(VALID_TEMPLATE))
        finally:
            for p in patches:
                p.stop()
        assert len(sent) == 1  # only the ack, no forward


# ---------------------------------------------------------------------------
# Path 2 — Invalid template
# ---------------------------------------------------------------------------

class TestPath2InvalidTemplate:
    def _run(self):
        sent = []
        patches = _env_patches()
        for p in patches:
            p.start()
        try:
            with patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
                with TestClient(app) as client:
                    result = _post(client, _make_raw_with_json_attachment(INVALID_TEMPLATE))
        finally:
            for p in patches:
                p.stop()
        return result, sent

    def test_returns_ok(self):
        result, _ = self._run()
        assert result["status"] == "ok"

    def test_sends_one_email_only(self):
        _, sent = self._run()
        assert len(sent) == 1  # error reply only, no operator forward

    def test_error_reply_goes_to_sender(self):
        _, sent = self._run()
        assert _bare_email(sent[0].to) == "anyone@example.com"

    def test_error_reply_mentions_issues(self):
        _, sent = self._run()
        assert "issue" in sent[0].html.lower() or "found" in sent[0].html.lower()

    def test_no_attachment_on_error_reply(self):
        _, sent = self._run()
        assert sent[0].attachment_bytes is None


# ---------------------------------------------------------------------------
# Path 3 — Dirty Excel / plain text seeding
# ---------------------------------------------------------------------------

class TestPath3Seeding:
    def _mock_ingest_result(self):
        from src.services.ingest import IngestionResult
        return IngestionResult(campaigns=VALID_TEMPLATE["campaigns"], ambiguities=[], confidence=0.9)

    def _run_xlsx(self):
        sent = []
        patches = _env_patches()
        for p in patches:
            p.start()
        try:
            with patch("src.email_bot.read_excel", return_value={}), \
                 patch("src.email_bot.extract_campaigns", return_value=self._mock_ingest_result()), \
                 patch("src.email_bot.anthropic.Anthropic"), \
                 patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
                with TestClient(app) as client:
                    result = _post(client, _make_raw_with_xlsx_attachment(b"fakexlsx"))
        finally:
            for p in patches:
                p.stop()
        return result, sent

    def test_returns_ok(self):
        result, _ = self._run_xlsx()
        assert result["status"] == "ok"

    def test_sends_one_email(self):
        _, sent = self._run_xlsx()
        assert len(sent) == 1

    def test_reply_has_json_attachment(self):
        _, sent = self._run_xlsx()
        assert sent[0].attachment_bytes is not None
        assert sent[0].attachment_filename == "campaign_template.json"

    def test_seeded_template_contains_placeholder(self):
        _, sent = self._run_xlsx()
        seeded = json.loads(sent[0].attachment_bytes.decode("utf-8"))
        assert seeded["account_id"] == ACCOUNT_ID_PLACEHOLDER

    def test_reply_instructs_to_replace_account_id(self):
        _, sent = self._run_xlsx()
        assert ACCOUNT_ID_PLACEHOLDER in sent[0].html

    def test_reply_instructs_to_review_and_resubmit(self):
        _, sent = self._run_xlsx()
        assert "review" in sent[0].html.lower() or "resubmit" in sent[0].html.lower()

    def test_plain_text_also_seeds_template(self):
        from src.services.ingest import IngestionResult
        ingest_result = IngestionResult(campaigns=VALID_TEMPLATE["campaigns"], ambiguities=[], confidence=0.85)
        sent = []
        patches = _env_patches()
        for p in patches:
            p.start()
        try:
            with patch("src.email_bot.extract_from_text", return_value=ingest_result), \
                 patch("src.email_bot.anthropic.Anthropic"), \
                 patch("src.email_bot.send_email", side_effect=lambda msg, key: sent.append(msg)):
                with TestClient(app) as client:
                    _post(client, _make_raw_plain(body="Create a brand awareness campaign."))
        finally:
            for p in patches:
                p.stop()
        assert sent[0].attachment_bytes is not None
        seeded = json.loads(sent[0].attachment_bytes.decode("utf-8"))
        assert seeded["account_id"] == ACCOUNT_ID_PLACEHOLDER


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
