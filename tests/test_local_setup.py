"""Local-only setup tests; all credentials below are deliberately fake."""
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import pytest
from dotenv import dotenv_values, load_dotenv

from src import local_setup as setup


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "stack"
    root.mkdir()
    (root / "stack_template.json").write_text(json.dumps({"account_id": "act_123"}), encoding="utf-8")
    return root


@pytest.fixture
def settings():
    return {**{k: "fake-local-test-value" for k in setup.REQUIRED_KEYS},
            "ACCOUNT_BUDGET_CAP": "0", "CURRENCY": "USD"}


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("Local OS does not permit test symlinks")


def test_private_rotation_preserves_comments_unknown_and_no_backups(workspace, settings, capsys):
    env = workspace / ".env"
    env.write_text("# private comment\nUNRELATED=keep\nFB_APP_SECRET='old-fake'\n", encoding="utf-8")
    settings["FB_APP_SECRET"] = "fake'quote\\slash"
    setup.configure_workspace(workspace, settings)
    assert "# private comment\nUNRELATED=keep\n" in env.read_text(encoding="utf-8")
    assert dotenv_values(env)["FB_APP_SECRET"] == settings["FB_APP_SECRET"]
    setup.configure_workspace(workspace, {"FB_ACCESS_TOKEN": "rotated-fake"})
    values = dotenv_values(env)
    assert values["FB_ACCESS_TOKEN"] == "rotated-fake"
    assert values["FB_APP_SECRET"] == settings["FB_APP_SECRET"]
    assert values["FB_ACCOUNT_ID"] == "act_123"
    assert set(p.name for p in workspace.iterdir()) == {".env", "stack_template.json"}
    if os.name != "nt":
        assert env.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key,value", [("CURRENCY", "usd"), ("CURRENCY", "ZZZ"),
    ("CURRENCY", "US"), ("ACCOUNT_BUDGET_CAP", "-1"), ("ACCOUNT_BUDGET_CAP", "1.5"),
    ("ACCOUNT_BUDGET_CAP", "+1"), ("FB_APP_ID", ""), ("FB_APP_SECRET", "fake\nunsafe"),
    ("FB_ACCOUNT_ID", "act_999")])
def test_invalid_settings_never_create_env(workspace, settings, key, value):
    settings[key] = value
    with pytest.raises(ValueError):
        setup.configure_workspace(workspace, settings)
    assert not (workspace / ".env").exists()


def test_budget_cap_is_stored_in_whole_currency_units(workspace, settings):
    settings["ACCOUNT_BUDGET_CAP"] = "500"
    setup.configure_workspace(workspace, settings)
    assert dotenv_values(workspace / ".env", interpolate=False)["ACCOUNT_BUDGET_CAP"] == "500"
    with pytest.raises(ValueError, match="whole currency units.*not cents"):
        setup.configure_workspace(workspace, {"ACCOUNT_BUDGET_CAP": "500.50"})
    assert "whole currency units" in setup.SETTING_LABELS["ACCOUNT_BUDGET_CAP"]


@pytest.mark.parametrize("literal", [
    "fake'quote", r"fake\\path\\token", "$FAKE $$ ${ADCODE_TEST_EXPANSION}",
    r"fake'\\${ADCODE_TEST_EXPANSION}-$VAR-${UNDEFINED:-fallback}",
])
def test_dotenv_literal_roundtrip_and_rotation(workspace, settings, monkeypatch, literal, capsys):
    monkeypatch.setenv("ADCODE_TEST_EXPANSION", "must-not-interpolate")
    env = workspace / ".env"
    original = "# keep unknown comment\nUNRELATED_LITERAL='${ADCODE_TEST_EXPANSION}'\n"
    env.write_text(original, encoding="utf-8")
    settings["FB_APP_SECRET"] = literal
    setup.configure_workspace(workspace, settings)
    assert env.read_text(encoding="utf-8").startswith(original)
    assert setup._env_values(env)["FB_APP_SECRET"] == literal
    assert dotenv_values(env, interpolate=False)["FB_APP_SECRET"] == literal
    # This is the required runtime load contract; single quotes alone do not
    # stop python-dotenv's default ${...} interpolation.
    for key in (*setup.SETTING_KEYS, "UNRELATED_LITERAL"):
        monkeypatch.setenv(key, "preexisting-fake")
    assert load_dotenv(env, override=True, interpolate=False)
    assert os.environ["FB_APP_SECRET"] == literal
    assert os.environ["UNRELATED_LITERAL"] == "${ADCODE_TEST_EXPANSION}"
    setup.configure_workspace(workspace, {"FB_ACCESS_TOKEN": "rotated-fake"})
    assert setup._env_values(env)["FB_APP_SECRET"] == literal
    assert env.read_text(encoding="utf-8").startswith(original)
    assert setup.main(["status", "--workspace", str(workspace)]) == 0
    output = capsys.readouterr()
    assert literal not in output.out + output.err
    assert set(p.name for p in workspace.iterdir()) == {".env", "stack_template.json"}


def test_existing_binding_not_silently_overridden(workspace, settings):
    env = workspace / ".env"
    original = "FB_ACCOUNT_ID=act_456\n# retain\n"
    env.write_text(original, encoding="utf-8")
    settings["FB_ACCOUNT_ID"] = "act_123"
    with pytest.raises(ValueError, match="differs"):
        setup.configure_workspace(workspace, settings)
    assert env.read_text() == original


def test_invalid_template(workspace, settings):
    (workspace / "stack_template.json").write_text('{"account_id":"123"}')
    with pytest.raises(ValueError, match="account_id"):
        setup.configure_workspace(workspace, settings)


def test_status_and_doctor_never_leak_values(workspace, settings, capsys):
    setup.configure_workspace(workspace, settings)
    for command in ("status", "doctor"):
        assert setup.main([command, "--workspace", str(workspace)]) == 0
        result = capsys.readouterr()
        assert "fake-local-test-value" not in result.out + result.err
        assert json.loads(result.out)["missing"] == []
    assert setup.workspace_status(workspace)["configured"] == list(setup.SETTING_KEYS)


def test_nonterminal_refused_without_echo(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="non-TTY"):
        setup._prompt_settings({}, terminal=True)


def test_friendly_prompts_hide_only_credentials(monkeypatch, settings):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    secret_prompts, public_prompts = [], []
    values = iter(settings[k] for k in setup.REQUIRED_KEYS)
    public_values = iter((settings["ACCOUNT_BUDGET_CAP"], settings["CURRENCY"]))
    def hidden(prompt):
        secret_prompts.append(prompt)
        return next(values)
    def visible(prompt):
        public_prompts.append(prompt)
        return next(public_values)
    monkeypatch.setattr(setup.getpass, "getpass", hidden)
    monkeypatch.setattr("builtins.input", visible)
    assert setup._prompt_settings({}, terminal=True) == settings
    assert secret_prompts == [f"{setup.SETTING_LABELS[k]} (blank keeps existing): " for k in setup.REQUIRED_KEYS]
    assert len(public_prompts) == 2
    assert "whole currency units" in public_prompts[0]
    assert "not cents" in public_prompts[0]
    assert "ISO code" in public_prompts[1]


def test_getpass_echo_fallback_is_refused(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    def insecure(_):
        warnings.warn("Cannot control terminal echo", setup.getpass.GetPassWarning)
        pytest.fail("Must not reach echoed input")
    monkeypatch.setattr(setup.getpass, "getpass", insecure)
    with pytest.raises(ValueError, match="Secure local terminal"):
        setup._prompt_settings({}, terminal=True)


@pytest.mark.parametrize("kind", ["env", "template", "workspace", "ancestor"])
def test_symlinks_refused(workspace, settings, tmp_path, kind):
    if kind == "env":
        target = tmp_path / "secret-target"
        target.write_text("untouched")
        symlink_or_skip(workspace / ".env", target)
    elif kind == "template":
        target = tmp_path / "template.json"
        (workspace / "stack_template.json").rename(target)
        symlink_or_skip(workspace / "stack_template.json", target)
    else:
        link = tmp_path / "linked"
        symlink_or_skip(link, workspace if kind == "workspace" else tmp_path, directory=True)
        workspace = link if kind == "workspace" else link / "stack"
    with pytest.raises(ValueError, match="symlink"):
        setup.configure_workspace(workspace, settings)


def test_directory_env_and_traversal_refused(workspace, settings):
    (workspace / ".env").mkdir()
    with pytest.raises(ValueError):
        setup.configure_workspace(workspace, settings)
    with pytest.raises(ValueError):
        setup.configure_workspace(workspace / ".." / "stack", settings)


def test_tracked_or_unignored_env_refused(workspace, settings):
    subprocess.run(["git", "init", "--quiet", str(workspace)], check=True, capture_output=True)
    with pytest.raises(ValueError, match="untracked and ignored"):
        setup.configure_workspace(workspace, settings)
    (workspace / ".gitignore").write_text(".env\n")
    setup.configure_workspace(workspace, settings)
    subprocess.run(["git", "add", "--force", ".env"], cwd=workspace, check=True, capture_output=True)
    original = (workspace / ".env").read_bytes()
    with pytest.raises(ValueError, match="untracked and ignored"):
        setup.configure_workspace(workspace, {"FB_APP_SECRET": "new-fake"})
    assert (workspace / ".env").read_bytes() == original


def test_atomic_failure_removes_secret_temporary_file(workspace, settings, monkeypatch):
    monkeypatch.setattr(setup.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fake")))
    with pytest.raises(OSError):
        setup.configure_workspace(workspace, settings)
    assert [p.name for p in workspace.iterdir()] == ["stack_template.json"]


@pytest.fixture
def registration(tmp_path):
    source = tmp_path / "installed"
    (source / "src").mkdir(parents=True)
    (source / "src" / "bootstrap_server.py").touch()
    config = tmp_path / "cursor" / "mcp.json"
    config.parent.mkdir()
    return dict(python=sys.executable, source=str(source), root=str(tmp_path / "workspaces"), config_path=config)


def test_cursor_merge_and_backup_before_write(registration, monkeypatch):
    config = registration["config_path"]
    original = b'{"mcpServers":{"AdCode":{"command":"keep"},"other":{"url":"local"}},"extra":true}\n'
    config.write_bytes(original)
    real_write = setup._atomic_write
    def check_backup(path, text, mode=0o600):
        backups = list(config.parent.glob("mcp.json.adcode-backup-*"))
        assert len(backups) == 1 and backups[0].read_bytes() == original
        assert config.read_bytes() == original
        real_write(path, text, mode)
    monkeypatch.setattr(setup, "_atomic_write", check_backup)
    backup = setup.register_cursor(**registration)
    assert backup.read_bytes() == original
    data = json.loads(config.read_text())
    assert data["extra"] is True
    assert data["mcpServers"]["AdCode"] == {"command": "keep"}
    assert data["mcpServers"]["AdCode-Setup"]["args"][-2:] == ["--root", registration["root"]]
    assert setup.register_cursor(**registration) is None
    assert len(list(config.parent.glob("mcp.json.adcode-backup-*"))) == 1


@pytest.mark.parametrize("text", ["not json", "[]", "null", '{"mcpServers":[]}',
    '{"mcpServers":null}', '{"mcpServers":{"AdCode-Setup":{}}}',
    '{"mcpServers":{},"mcpServers":{}}', '{"x":NaN}'])
def test_cursor_invalid_or_conflicting_untouched(registration, text):
    config = registration["config_path"]
    config.write_text(text)
    with pytest.raises(ValueError):
        setup.register_cursor(**registration)
    assert config.read_text() == text
    assert list(config.parent.glob("*backup*")) == []


def test_cursor_symlink_refused(registration, tmp_path):
    target = tmp_path / "other.json"
    target.write_text("{}")
    symlink_or_skip(registration["config_path"], target)
    with pytest.raises(ValueError):
        setup.register_cursor(**registration)
    assert target.read_text() == "{}"


def test_cursor_absolute_paths_required(registration):
    registration["source"] = "relative"
    with pytest.raises(ValueError, match="absolute"):
        setup.register_cursor(**registration)


def test_cli_suppresses_input_bearing_exception(workspace, monkeypatch, capsys):
    def bad(*_, **__):
        raise ValueError("fake-secret-never-display")
    monkeypatch.setattr(setup, "workspace_status", bad)
    assert setup.main(["status", "--workspace", str(workspace)]) == 1
    assert "fake-secret" not in str(capsys.readouterr())
