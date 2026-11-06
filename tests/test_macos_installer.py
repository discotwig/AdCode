"""Installer contract tests; downloads are mocked and no provider APIs are used."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from src import local_setup as setup

INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install_macos.command"
BASH = shutil.which("bash")


def shell_path(path):
    if os.name == "nt":
        result = subprocess.run([BASH, "-c", 'cygpath -u "$1"', "test", str(path)],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    return str(path)


@pytest.mark.skipif(not BASH, reason="bash unavailable")
def test_shell_syntax():
    subprocess.run([BASH, "-n", shell_path(INSTALLER)], check=True, capture_output=True)


def test_registered_bootstrap_starts_from_arbitrary_cwd(tmp_path):
    """Guard the parent-owned bootstrap's direct-script import-path contract."""
    config = tmp_path / "cursor" / "mcp.json"
    setup.register_cursor(sys.executable, INSTALLER.parents[1], tmp_path / "workspaces", config_path=config)
    entry = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["AdCode-Setup"]
    foreign_cwd = tmp_path / "unrelated-cursor-cwd"
    foreign_cwd.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run([entry["command"], *entry["args"], "--help"], cwd=foreign_cwd,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--root" in result.stdout


def test_pinned_assets_hashes_and_runtime_contract():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "UV_VERSION=0.13.7" in text
    assert "SHA256=81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731" in text
    assert "SHA256=20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7" in text
    assert "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET" in text
    assert text.index("shasum -a 256 -c") < text.index("tar -xzf")
    assert "--require-hashes --only-binary :all:" in text
    assert "python install 3.13" in text
    assert "--managed-python --python 3.13" in text
    assert 'APP="$HOME/Library/Application Support/AdCode"' in text
    assert "curl|bash" not in text and "sudo " not in text
    assert "cp -R" not in text and "cp -r" not in text
    bootstrap_preflight = '(cd -- "$STAGE"; "$PYTHON" "$RELEASE/src/bootstrap_server.py" --help >/dev/null)'
    assert bootstrap_preflight in text
    assert text.index(bootstrap_preflight) < text.index('"$RELEASE/src/local_setup.py" publish-install')
    assert 'mktemp -d "$APP/.stage.' in text
    assert '&& pwd -P)' in text
    assert '[ "$(uname -s)" = Darwin ]' in text


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    for name in ("src/services", "schemas", "policies/builtin", "customers", "private-docs", ".git", "logs"):
        (source / name).mkdir(parents=True)
    for name in ("src/__init__.py", "src/bootstrap_server.py", "src/services/workspace.py", "src/local_setup.py",
                 "schemas/campaign.schema.json", "policies/builtin/safety.json", "requirements-local.lock"):
        (source / name).write_text("{}" if name.endswith("json") else "# runtime\n")
    for name in (".env", "customers/private.json", ".git/config", "private-docs/secret.txt", "logs/live.log",
                 "src/.env", "src/debug.log", "src/credentials.json"):
        (source / name).write_text("fake-private-marker")
    (source / "src/__pycache__").mkdir()
    (source / "src/__pycache__/cached.py").write_text("fake-private-marker")
    return source


def test_explicit_allowlist_excludes_private_checkout_data(source, tmp_path):
    destination = tmp_path / "release"
    destination.mkdir()
    setup.stage_source(source, destination)
    files = {str(p.relative_to(destination)).replace("\\", "/") for p in destination.rglob("*") if p.is_file()}
    assert files == {"src/__init__.py", "src/bootstrap_server.py", "src/local_setup.py", "src/services/workspace.py",
                     "schemas/campaign.schema.json", "policies/builtin/safety.json", "requirements-local.lock"}
    assert all("fake-private-marker" not in p.read_text() for p in destination.rglob("*") if p.is_file())


def test_missing_lock_refuses_unlocked_install(source, tmp_path):
    (source / "requirements-local.lock").unlink()
    destination = tmp_path / "release"
    destination.mkdir()
    with pytest.raises(ValueError, match="lock"):
        setup.stage_source(source, destination)


def test_source_staging_never_overwrites_existing_release(source, tmp_path):
    destination = tmp_path / "release"
    destination.mkdir()
    sentinel = destination / "user-config"
    sentinel.write_text("untouched")
    with pytest.raises(ValueError, match="fresh release"):
        setup.stage_source(source, destination)
    assert sentinel.read_text() == "untouched"
    assert not (destination / "src").exists()


def test_source_link_refused(source, tmp_path):
    link = source / "src" / "linked.py"
    try:
        link.symlink_to(source / "src/__init__.py")
    except OSError:
        pytest.skip("Symlinks unavailable")
    destination = tmp_path / "release"
    destination.mkdir()
    with pytest.raises(ValueError, match="links"):
        setup.stage_source(source, destination)


@pytest.fixture
def installation(tmp_path):
    app = tmp_path / "Application Support" / "AdCode"
    releases = app / "releases"
    releases.mkdir(parents=True)
    for name in ("old", "new"):
        release = releases / name
        (release / "venv/bin").mkdir(parents=True)
        (release / "venv/bin/python").touch()
        (release / "src").mkdir()
        (release / "src/bootstrap_server.py").touch()
    try:
        (app / "current").symlink_to(releases / "old", target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    return app, releases / "new", tmp_path / "Documents" / "AdCode"


def test_publish_retains_previous_and_direct_python_launchers(installation, monkeypatch):
    app, release, root = installation
    calls = []
    monkeypatch.setattr(setup, "register_cursor", lambda *args: calls.append(args))
    setup.publish_install(app, release, root)
    assert (app / "current").resolve() == release
    assert (app / "previous").resolve() == app / "releases/old"
    assert (app / "releases/old").is_dir()
    assert calls == [(app / "current/venv/bin/python", app / "current", root)]
    launcher = (app / "bin/adcode-setup").read_text()
    assert 'exec "$APP/current/venv/bin/python" -m src.local_setup "$@"' in launcher
    assert "uv " not in launcher and "pip " not in launcher
    assert "--workspace" in (app / "bin/Configure AdCode.command").read_text()
    if BASH:
        for path in (app / "bin").iterdir():
            subprocess.run([BASH, "-n", shell_path(path)], check=True, capture_output=True)


def test_registration_failure_rolls_back_current(installation, monkeypatch):
    app, release, root = installation
    def conflict(*_):
        raise ValueError("existing config conflict")
    monkeypatch.setattr(setup, "register_cursor", conflict)
    with pytest.raises(ValueError):
        setup.publish_install(app, release, root)
    assert (app / "current").resolve() == app / "releases/old"
    assert release.is_dir()


def test_launcher_conflict_is_not_overwritten(installation, monkeypatch):
    app, release, root = installation
    (app / "bin").mkdir()
    (app / "bin/adcode-setup").write_text("user-owned")
    with pytest.raises(ValueError, match="conflicts"):
        setup.publish_install(app, release, root)
    assert (app / "bin/adcode-setup").read_text() == "user-owned"
    assert (app / "current").resolve() == app / "releases/old"


@pytest.mark.skipif(not BASH, reason="bash unavailable")
def test_mock_download_checksum_failure_never_extracts_or_activates(source, tmp_path):
    """Exercise real shell control flow with a fake network and failed verification."""
    (source / "scripts").mkdir()
    script = source / "scripts/install_macos.command"
    shutil.copyfile(INSTALLER, script)
    home = tmp_path / "home"
    home.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    trace = tmp_path / "network-trace"
    commands = {
        "uname": '#!/bin/sh\nif [ "$1" = -s ]; then echo Darwin; else echo arm64; fi\n',
        "id": '#!/bin/sh\necho 501\n',
        "uv": '#!/bin/sh\necho "uv not-the-pinned-version"\n',
        "curl": '#!/bin/sh\nprintf "download\\n" >> "$TRACE"\nwhile [ "$#" -gt 0 ]; do if [ "$1" = --output ]; then shift; printf corrupt > "$1"; exit 0; fi; shift; done\nexit 1\n',
        "shasum": '#!/bin/sh\nprintf "verify-failed\\n" >> "$TRACE"\nexit 1\n',
        "tar": '#!/bin/sh\nprintf "UNSAFE-extraction\\n" >> "$TRACE"\nexit 99\n',
    }
    for name, text in commands.items():
        path = tools / name
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o700)
    env = os.environ.copy()
    env.update(HOME=shell_path(home), TRACE=shell_path(trace))
    # Set PATH inside bash so Windows' semicolon-separated PATH is not misinterpreted.
    result = subprocess.run([BASH, "-c", 'export PATH="$1:/usr/bin:/bin"; exec bash "$2"',
                             "test", shell_path(tools), shell_path(script)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert trace.read_text().splitlines() == ["download", "verify-failed"]
    app = home / "Library/Application Support/AdCode"
    assert not (app / "current").exists()
    assert not (app / ".install-lock").exists()
    assert not list(app.glob(".stage.*"))
