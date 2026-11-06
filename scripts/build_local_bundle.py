#!/usr/bin/env python3
"""Build a credential-free macOS POC source installer ZIP; no network or signing."""
import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.local_setup import safe_path, stage_source


START_HERE = """AdCode Local Operator POC — macOS / Cursor

1. Extract this whole ZIP to a local folder; do not run individual files inside it.
2. Review scripts/install_macos.command and docs/local-operator.md. This POC is unsigned.
3. Open Install AdCode.command using macOS's normal script approval flow.
   Do not disable Gatekeeper or run as root. No Python/Git installation is needed.
4. Restart Cursor and ask AdCode-Setup to create a workspace for your business.
   Use a friendly business name; the assistant prepares the app connection for you.
5. Ask to open the workspace, approving Cursor's normal prompts. Open its .env
   yourself and paste your account, keys, spending limit and currency locally.
   Never paste secrets into a conversation or ask an agent to read .env.
6. Save and ask to check the workspace. New guided connections pick up settings
   without restarting. This local check does not verify a provider connection.
7. Describe what you are promoting, your budget and dates. The draft starts empty,
   not with dummy campaigns. Files and .env remain on this computer.
   The initial project connection allows inspection/planning only, not live writes.

Installation downloads verified uv, managed Python 3.13 and hash-locked dependencies.
Planning and Cursor's model may process campaign data externally and incur API charges.
Keep approval prompts enabled. Read the guide before enabling any operator capability.
An actual Mac/Cursor smoke test is required before distributing this as a supported app.
"""

LAUNCHER = '''#!/bin/sh
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec /bin/bash "$SOURCE/scripts/install_macos.command"
'''


def build_bundle(output: Path, source: Path = ROOT) -> Path:
    """Publish a new archive without overwriting an existing artifact."""
    source = safe_path(source, directory=True)
    output = safe_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="adcode-bundle-") as temporary:
        staged = Path(temporary).resolve() / "runtime"
        staged.mkdir()
        stage_source(source, staged)
        # These exact public files are the only additions to the runtime allowlist.
        additions = {
            "scripts/install_macos.command": source / "scripts/install_macos.command",
            "docs/local-operator.md": source / "docs/local-operator.md",
            "docs/local-poc-validation.md": source / "docs/local-poc-validation.md",
            "docs/decisions/024-local-macos-cursor-poc.md": source / "docs/decisions/024-local-macos-cursor-poc.md",
            "SECURITY.md": source / "SECURITY.md",
            "requirements-local.in": source / "requirements-local.in",
            "LICENSE": source / "LICENSE",
        }
        # A bundle built on Windows must still contain Unix shell scripts. All
        # allowlisted inputs are UTF-8 text; normalize public source, not user data.
        content = {p.relative_to(staged).as_posix(): p.read_text(encoding="utf-8").encode("utf-8")
                   for p in staged.rglob("*") if p.is_file()}
        for name, path in additions.items():
            path = safe_path(path)
            content[name] = path.read_text(encoding="utf-8").encode("utf-8")
        content["Install AdCode.command"] = LAUNCHER.encode("utf-8")
        content["START_HERE.txt"] = START_HERE.encode("utf-8")
        # Construct completely before creating the final destination with O_EXCL.
        archive = Path(temporary) / "bundle.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, data in sorted(content.items()):
                item = zipfile.ZipInfo(name)
                item.create_system = 3
                permissions = 0o755 if name.endswith(".command") else 0o644
                item.external_attr = (stat.S_IFREG | permissions) << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                zipped.writestr(item, data)
        with archive.open("rb") as incoming:
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as target:
                    while chunk := incoming.read(1024 * 1024):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/AdCode-Local-POC.zip")
    args = parser.parse_args(argv)
    try:
        result = build_bundle(args.output)
    except (OSError, ValueError):
        print("Bundle build refused: check public source files and choose a new output path.", file=sys.stderr)
        return 1
    print(f"Built local installer bundle: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
