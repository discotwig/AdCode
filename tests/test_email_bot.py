"""Tests for src/email_bot.py — all external calls mocked."""
import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.email_bot import app, _bare_email, _find_customer, _parse_raw_email

# ---------------------------------------------------------------------------
# Helpers
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
        "FB_APP_ID": "app_id",
        "FB_APP_SECRET": "app_secret",
        "FB_ACCESS_TOKEN": "token",
        "ANTHROPIC_API_KEY": "anth_key",
        "RESEND_API_KEY": "re_key",
    },
}

RAW_EMAIL_PLAIN = textwrap.dedent("""\
    From: client@example.com
    To: traffic@ryanbishop.me
    Subject: Q3 campaign
    Message-ID: <abc123@mail.example.com>
    Content-Type: text/plain; charset=utf-8

    Please create a brand awareness campaign with $5000 budget for Q3.
""")

RAW_OPERATOR_GO = textwrap.dedent("""\
    From: operator@example.com
    To: traffic@ryanbishop.me
    Subject: Re: [AdCode Review] abc12345 | Q3 campaign
    Message-ID: <op456@mail.example.com>
    Content-Type: text/plain; charset=utf-8

    GO
""")

RAW_OPERATOR_HOLD = textwrap.dedent("""\
    From: operator@example.com
    To: traffic@ryanbishop.me
    Subject: Re: [AdCode Review] abc12345 | Q3 campaign
    Message-ID: <op789@mail.example.com>
    Content-Type: text/plain; charset=utf-8

    HOLD
""")

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


def test_find_customer_operator():
    customer = _find_customer("Operator <operator@example.com>", [DEMO_CONFIG])
    assert customer is not None


def test_find_customer_unknown_returns_none():
    assert _find_customer("unknown@example.com", [DEMO_CONFIG]) is None


def test_parse_raw_email_plain():
    parsed = _parse_raw_email(RAW_EMAIL_PLAIN)
    assert parsed["subject"] == "Q3 campaign"
    assert "brand awareness" in parsed["body"]
    assert parsed["xlsx_bytes"] is None
    assert parsed["message_id"] == "<abc123@mail.example.com>"


# ---------------------------------------------------------------------------
# Integration tests — POST /inbound (mocked pipeline)
# ---------------------------------------------------------------------------

client = TestClient(app)


def _make_body(raw: str, from_addr: str = "client@example.com") -> dict:
    return {"from": from_addr, "to": "traffic@ryanbishop.me", "raw": raw}


@patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG])
@patch("src.email_bot.send_email")
@patch("src.email_bot.extract_from_text")
@patch("src.email_bot.validate_all")
@patch("src.email_bot.StateFile")
@patch("src.email_bot.plan")
@patch("src.email_bot.MetaClient")
@patch("src.email_bot.anthropic.Anthropic")
def test_inbound_client_email_sends_plan_to_operator(
    mock_anth, mock_meta_cls, mock_plan, mock_state_cls,
    mock_validate, mock_extract, mock_send, mock_configs,
    tmp_path,
):
    # Wire mocks
    mock_extract.return_value = MagicMock(campaigns=[{"name": "Q3"}], ambiguities=[], confidence=0.9)
    mock_validate.return_value = MagicMock(is_pushable=True, summary=lambda: "OK")
    mock_plan.return_value = MagicMock(operations=[], summary=lambda: "1 create", has_deletes=False)
    mock_state_cls.load.return_value = MagicMock()

    # Redirect state_dir to tmp so pending file can be written
    DEMO_CONFIG["_config_dir"] = tmp_path
    (tmp_path / "state").mkdir()

    resp = client.post("/inbound", json=_make_body(RAW_EMAIL_PLAIN))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Operator should receive a plan email
    calls = mock_send.call_args_list
    assert any("[AdCode Review]" in call.args[0].subject for call in calls)


@patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG])
@patch("src.email_bot.send_email")
@patch("src.email_bot.extract_from_text")
@patch("src.email_bot.validate_all")
@patch("src.email_bot.StateFile")
@patch("src.email_bot.plan")
@patch("src.email_bot.MetaClient")
@patch("src.email_bot.anthropic.Anthropic")
def test_inbound_with_ambiguities_replies_to_client(
    mock_anth, mock_meta_cls, mock_plan, mock_state_cls,
    mock_validate, mock_extract, mock_send, mock_configs,
    tmp_path,
):
    from src.services.ingest import Ambiguity
    mock_extract.return_value = MagicMock(
        campaigns=[{"name": "Q3"}],
        ambiguities=[Ambiguity("field", "", "", "val", "What budget?")],
        confidence=0.5,
    )
    mock_anth.return_value.messages.create.return_value.content = [
        MagicMock(text="A. Budget\na) $10/day (suggested)\nb) $20/day")
    ]
    DEMO_CONFIG["_config_dir"] = tmp_path
    (tmp_path / "state").mkdir(exist_ok=True)

    resp = client.post("/inbound", json=_make_body(RAW_EMAIL_PLAIN))
    assert resp.status_code == 200

    # No plan email; client gets ambiguity reply
    calls = mock_send.call_args_list
    assert len(calls) == 1
    assert "Q3 campaign" in calls[0].args[0].subject
    assert "[Clarify-" in calls[0].args[0].subject
    mock_plan.assert_not_called()


@patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG])
def test_unknown_sender_rejected(mock_configs):
    resp = client.post("/inbound", json=_make_body(RAW_EMAIL_PLAIN, from_addr="hacker@spam.com"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG])
@patch("src.email_bot.send_email")
@patch("src.email_bot.StateFile")
@patch("src.email_bot.plan")
@patch("src.email_bot.apply_plan")
@patch("src.email_bot.MetaClient")
@patch("src.email_bot.anthropic.Anthropic")
def test_operator_go_applies_and_confirms(
    mock_anth, mock_meta_cls, mock_apply, mock_plan,
    mock_state_cls, mock_send, mock_configs,
    tmp_path,
):
    DEMO_CONFIG["_config_dir"] = tmp_path
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)

    # Write a pending file matching the pending_id in RAW_OPERATOR_GO subject
    pending = {
        "pending_id": "abc12345",
        "message_id": "<abc123@mail.example.com>",
        "client_from": "client@example.com",
        "client_subject": "Q3 campaign",
        "campaign_json": {"account_id": "act_123", "campaigns": []},
        "created_at": "2026-05-12T00:00:00+00:00",
    }
    (state_dir / ".pending_abc12345.json").write_text(json.dumps(pending), encoding="utf-8")

    mock_plan.return_value = MagicMock(operations=[], has_deletes=False)
    mock_state_cls.load.return_value = MagicMock()
    mock_apply.return_value = MagicMock(summary=lambda: "1 created")

    resp = client.post("/inbound", json=_make_body(RAW_OPERATOR_GO, from_addr="operator@example.com"))
    assert resp.status_code == 200

    mock_apply.assert_called_once()
    # Client should get confirmation
    calls = mock_send.call_args_list
    assert any("Q3 campaign" in call.args[0].subject for call in calls)
    assert not (state_dir / ".pending_abc12345.json").exists()


@patch("src.email_bot._load_all_configs", return_value=[DEMO_CONFIG])
@patch("src.email_bot.send_email")
@patch("src.email_bot.apply_plan")
@patch("src.email_bot.anthropic.Anthropic")
def test_operator_hold_discards_without_apply(
    mock_anth, mock_apply, mock_send, mock_configs,
    tmp_path,
):
    DEMO_CONFIG["_config_dir"] = tmp_path
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)

    pending = {
        "pending_id": "abc12345",
        "message_id": "<abc123@mail.example.com>",
        "client_from": "client@example.com",
        "client_subject": "Q3 campaign",
        "campaign_json": {"account_id": "act_123", "campaigns": []},
        "created_at": "2026-05-12T00:00:00+00:00",
    }
    (state_dir / ".pending_abc12345.json").write_text(json.dumps(pending), encoding="utf-8")

    resp = client.post("/inbound", json=_make_body(RAW_OPERATOR_HOLD, from_addr="operator@example.com"))
    assert resp.status_code == 200

    mock_apply.assert_not_called()
    assert not (state_dir / ".pending_abc12345.json").exists()
    calls = mock_send.call_args_list
    assert len(calls) == 1
    assert "on hold" in calls[0].args[0].html.lower()


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
