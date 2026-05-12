"""Tests for expired pending brief sweep in src/email_bot.py."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.email_bot import _scan_expired_pending, PENDING_EXPIRY_HOURS

DEMO_CONFIG = {
    "customer_slug": "demo",
    "account_id": "act_123",
    "state_dir": "state",
    "bot_email": "traffic@ryanbishop.me",
    "operator_email": "operator@example.com",
    "_env": {"RESEND_API_KEY": "re_key"},
}


def _make_pending(state_dir: Path, pending_id: str, created_at: datetime) -> Path:
    path = state_dir / f".pending_{pending_id}.json"
    path.write_text(json.dumps({
        "pending_id": pending_id,
        "message_id": "<msg@example.com>",
        "client_from": "client@example.com",
        "client_subject": "Q3 brief",
        "campaign_json": {},
        "created_at": created_at.isoformat(),
    }), encoding="utf-8")
    return path


@patch("src.email_bot._load_all_configs")
@patch("src.email_bot.send_email")
def test_expired_pending_notifies_operator_and_deletes(mock_send, mock_configs, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cfg = {**DEMO_CONFIG, "_config_dir": tmp_path}
    mock_configs.return_value = [cfg]

    expired_at = datetime.now(timezone.utc) - timedelta(hours=PENDING_EXPIRY_HOURS + 1)
    pending_path = _make_pending(state_dir, "abc123", expired_at)

    _scan_expired_pending()

    mock_send.assert_called_once()
    msg = mock_send.call_args.args[0]
    assert "Expired brief" in msg.subject
    assert "Q3 brief" in msg.subject
    assert msg.to == "operator@example.com"
    assert not pending_path.exists()


@patch("src.email_bot._load_all_configs")
@patch("src.email_bot.send_email")
def test_fresh_pending_is_left_alone(mock_send, mock_configs, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cfg = {**DEMO_CONFIG, "_config_dir": tmp_path}
    mock_configs.return_value = [cfg]

    fresh_at = datetime.now(timezone.utc) - timedelta(hours=1)
    pending_path = _make_pending(state_dir, "fresh01", fresh_at)

    _scan_expired_pending()

    mock_send.assert_not_called()
    assert pending_path.exists()


@patch("src.email_bot._load_all_configs")
@patch("src.email_bot.send_email")
def test_mixed_pending_only_expires_old(mock_send, mock_configs, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cfg = {**DEMO_CONFIG, "_config_dir": tmp_path}
    mock_configs.return_value = [cfg]

    old_at = datetime.now(timezone.utc) - timedelta(hours=PENDING_EXPIRY_HOURS + 2)
    new_at = datetime.now(timezone.utc) - timedelta(hours=2)
    old_path = _make_pending(state_dir, "old001", old_at)
    new_path = _make_pending(state_dir, "new001", new_at)

    _scan_expired_pending()

    assert not old_path.exists()
    assert new_path.exists()
    mock_send.assert_called_once()


@patch("src.email_bot._load_all_configs")
@patch("src.email_bot.send_email")
def test_no_pending_files_does_nothing(mock_send, mock_configs, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cfg = {**DEMO_CONFIG, "_config_dir": tmp_path}
    mock_configs.return_value = [cfg]

    _scan_expired_pending()

    mock_send.assert_not_called()


@patch("src.email_bot._load_all_configs")
@patch("src.email_bot.send_email")
def test_missing_state_dir_does_not_crash(mock_send, mock_configs, tmp_path):
    cfg = {**DEMO_CONFIG, "_config_dir": tmp_path}
    mock_configs.return_value = [cfg]
    # state_dir does not exist — glob returns nothing

    _scan_expired_pending()

    mock_send.assert_not_called()
