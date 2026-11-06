"""The shareable bundle must never copy a private working directory wholesale."""
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest

from scripts.build_local_bundle import ROOT, build_bundle


@pytest.fixture
def public_source(tmp_path):
    root = tmp_path / "source"
    for name in ["src/__init__.py", "src/bootstrap_server.py", "src/local_setup.py",
                 "schemas/campaign.schema.json", "policies/builtin/safety.json",
                 "requirements-local.lock", "requirements-local.in", "LICENSE",
                 "scripts/install_macos.command", "docs/local-operator.md", "docs/local-poc-validation.md",
                 "docs/decisions/024-local-macos-cursor-poc.md", "SECURITY.md"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# public fixture\n", encoding="utf-8")
    for name in [".env", "customers/acme/.env", "private-docs/notes.md", ".git/config",
                 "docs/marketer-faq.docx", "tests/fixture.txt", "src/private.json",
                 "src/__pycache__/cached.py", "scripts/not-allowlisted.py"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private-marker-do-not-distribute")
    (root / "scripts/install_macos.command").write_bytes(b"#!/bin/bash\r\nset -eu\r\n")
    return root


def test_bundle_has_only_runtime_and_explicit_public_additions(public_source, tmp_path):
    result = build_bundle(tmp_path / "output.zip", public_source)
    with zipfile.ZipFile(result) as zipped:
        assert set(zipped.namelist()) == {
            "src/__init__.py", "src/bootstrap_server.py", "src/local_setup.py",
            "schemas/campaign.schema.json", "policies/builtin/safety.json",
            "requirements-local.lock", "requirements-local.in", "LICENSE",
            "scripts/install_macos.command", "docs/local-operator.md", "docs/local-poc-validation.md",
            "docs/decisions/024-local-macos-cursor-poc.md", "SECURITY.md",
            "Install AdCode.command", "START_HERE.txt",
        }
        assert zipped.testzip() is None
        assert all(b"private-marker" not in zipped.read(name) for name in zipped.namelist())
        for name in ["Install AdCode.command", "scripts/install_macos.command"]:
            mode = zipped.getinfo(name).external_attr >> 16
            assert stat.S_ISREG(mode)
            assert stat.S_IMODE(mode) == 0o755
            assert b"\r" not in zipped.read(name)
        assert b"scripts/install_macos.command" in zipped.read("Install AdCode.command")


def test_existing_artifact_is_never_overwritten(public_source, tmp_path):
    path = tmp_path / "existing.zip"
    path.write_bytes(b"preserve-this-artifact")
    with pytest.raises(FileExistsError):
        build_bundle(path, public_source)
    assert path.read_bytes() == b"preserve-this-artifact"


def test_real_source_bundle_has_complete_launch_chain(tmp_path):
    result = build_bundle(tmp_path / "real.zip")
    with zipfile.ZipFile(result) as zipped:
        names = set(zipped.namelist())
        assert {"src/mcp_server.py", "src/bootstrap_server.py", "src/local_setup.py",
                "src/services/workspace.py", "requirements-local.lock",
                "schemas/campaign.schema.json"} <= names
        assert not any(p.startswith(("customers/", ".git/", "tests/", "integrations/", "private-docs/")) for p in names)
        assert not any(Path(p).name == ".env" for p in names)
        assert b"--access-mode" in zipped.read("src/mcp_server.py")


def test_builder_script_help_runs_without_source_cwd(tmp_path):
    import sys
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build_local_bundle.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
