"""Local terminal setup and installer helpers; never contact provider APIs.

Paths must be user-controlled, not concurrently mutated by another local process.
Credential values are deliberately never included in diagnostics or exceptions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import getpass
import io
import json
import os
from pathlib import Path
import re

import shutil
import subprocess
import sys
import tempfile
import uuid
import warnings

REQUIRED_KEYS = ("FB_APP_ID", "FB_APP_SECRET", "FB_ACCESS_TOKEN", "ANTHROPIC_API_KEY")
SETTING_KEYS = (*REQUIRED_KEYS, "FB_ACCOUNT_ID", "ACCOUNT_BUDGET_CAP", "CURRENCY")
SETTING_LABELS = {
    "FB_APP_ID": "Facebook app ID",
    "FB_APP_SECRET": "Facebook app secret",
    "FB_ACCESS_TOKEN": "Facebook access token",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "FB_ACCOUNT_ID": "Advertising account (digits or act_ followed by digits)",
    "ACCOUNT_BUDGET_CAP": "Account budget cap (whole currency units, e.g. 500 dollars, not cents)",
    "CURRENCY": "Currency (three-letter ISO code, e.g. USD)",
}
# ISO 4217 currency codes (including fund/precious metal/test codes).
CURRENCIES = frozenset("AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG".split())


def safe_path(value, *, directory=False) -> Path:
    path = Path(value).expanduser()
    if ".." in path.parts:
        raise ValueError("Paths must not contain traversal.")
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Paths must not contain symlinks or junctions.")
        if part.exists() and part != path and not part.is_dir():
            raise ValueError("Path ancestors must be directories.")
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        raise ValueError("Unexpected path type.")
    return path


def _atomic_write(path: Path, text: str, mode=0o600) -> None:
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix=".adcode-", dir=path.parent)
    try:
        os.chmod(name, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        safe_path(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _lock(directory: Path, name: str):
    lock = directory / name
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError("Local setup is busy or locked; inspect the setup lock before retrying.") from None
    try:
        yield
    finally:
        lock.rmdir()


def _strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON keys are not supported.")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError("Expected strict JSON with unique keys.") from None


def _workspace(workspace) -> tuple[Path, str | None]:
    root = safe_path(workspace, directory=True)
    if not root.is_dir():
        raise ValueError("Workspace must already exist.")
    templates = list(root.glob("*_template.json"))
    if len(templates) != 1:
        raise ValueError("Workspace must contain exactly one *_template.json.")
    template = safe_path(templates[0])
    data = _strict_json(template.read_text(encoding="utf-8"))
    account = data.get("account_id") if isinstance(data, dict) else None
    if account == "":
        from src.services.workspace import _manifest
        _manifest(root, f"{root.parent.name}/{root.name}")
        return root, None
    if not isinstance(account, str) or not re.fullmatch(r"act_[0-9]{1,60}", account):
        raise ValueError("Template account_id must be act_ followed by digits.")
    return root, account


def _env_values(path: Path) -> dict:
    from dotenv import dotenv_values
    safe_path(path)
    if not path.exists():
        return {}
    # No interpolation from the host environment and no parser warnings containing input.
    from dotenv.parser import parse_stream
    text = path.read_text(encoding="utf-8")
    if any(item.error for item in parse_stream(io.StringIO(text))):
        raise ValueError("Existing .env is malformed; repair it locally before setup.")
    return dict(dotenv_values(stream=io.StringIO(text), interpolate=False))


def _git_private(path: Path) -> None:
    """Refuse tracked files, and require ignore coverage when inside a Git tree."""
    if not any((p / ".git").exists() for p in (path.parent, *path.parent.parents)):
        return
    try:
        tracked = subprocess.run(["git", "--no-pager", "ls-files", "--error-unmatch", "--", path.name],
                                 cwd=path.parent, capture_output=True, timeout=10)
        ignored = subprocess.run(["git", "--no-pager", "check-ignore", "--quiet", "--", path.name],
                                 cwd=path.parent, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Cannot verify that .env is private from Git.") from None
    if tracked.returncode != 1 or ignored.returncode != 0:
        raise ValueError("Refusing .env write: it must be untracked and ignored by Git.")


def configure_workspace(workspace, updates: dict[str, str]) -> None:
    """Atomically rotate settings, preserving comments, unknown keys and literals.

    ACCOUNT_BUDGET_CAP is in whole currency units, never minor units. Runtime
    readers must use load_dotenv(..., interpolate=False) to preserve literal
    credential text such as ${VAR}; quoting alone does not disable interpolation.
    """
    from dotenv.parser import parse_stream
    root, account = _workspace(workspace)
    if set(updates) - set(SETTING_KEYS):
        raise ValueError("Unknown setup setting.")
    if any(not isinstance(v, str) or any(c in v for c in "\r\n\x00") for v in updates.values()):
        raise ValueError("Settings must be single-line text.")
    env = safe_path(root / ".env")
    with _lock(root, ".adcode-setup.lock"):
        _git_private(env)
        existing = _env_values(env)
        values = {**existing, **updates}
        from src.services.workspace import _account
        previous_account = existing.get("FB_ACCOUNT_ID")
        entered_account = values.get("FB_ACCOUNT_ID")
        if account is None:
            account = _account(entered_account)
            if account is None:
                raise ValueError("Enter the advertising account locally before saving.")
        if previous_account not in (None, "") and _account(previous_account) != account:
            raise ValueError("Existing FB_ACCOUNT_ID differs from template; reconcile it locally first.")
        if entered_account not in (None, "") and _account(entered_account) != account:
            raise ValueError("FB_ACCOUNT_ID must match the existing template.")
        if any(not values.get(k) for k in REQUIRED_KEYS):
            raise ValueError("All required credential names must be configured.")
        if not re.fullmatch(r"[0-9]+", values.get("ACCOUNT_BUDGET_CAP", "")):
            raise ValueError("Account budget cap must be a nonnegative integer in whole currency units (e.g. dollars, not cents).")
        if values.get("CURRENCY") not in CURRENCIES:
            raise ValueError("CURRENCY must be an uppercase ISO 4217 code.")
        updates = {**updates, "FB_ACCOUNT_ID": account}
        old = env.read_text(encoding="utf-8") if env.exists() else ""
        pending = dict(updates)
        output = []
        for binding in parse_stream(io.StringIO(old)):
            if binding.key in updates:
                if binding.key in pending:
                    value = pending.pop(binding.key).replace("\\", "\\\\").replace("'", "\\'")
                    output.append(f"{binding.key}='{value}'\n")
            else:
                output.append(binding.original.string)
        text = "".join(output)
        if text and not text.endswith("\n"):
            text += "\n"
        for key, value in pending.items():
            value = value.replace("\\", "\\\\").replace("'", "\\'")
            text += f"{key}='{value}'\n"
        _git_private(env)
        _atomic_write(env, text)


def workspace_status(workspace) -> dict[str, list[str]]:
    root, _ = _workspace(workspace)
    values = _env_values(safe_path(root / ".env"))
    return {"configured": [k for k in SETTING_KEYS if values.get(k)],
            "missing": [k for k in SETTING_KEYS if not values.get(k)]}


def _prompt_settings(existing: dict, *, terminal=False, account_required=False) -> dict:
    keys = ((*REQUIRED_KEYS, "FB_ACCOUNT_ID", "ACCOUNT_BUDGET_CAP", "CURRENCY")
            if account_required else (*REQUIRED_KEYS, "ACCOUNT_BUDGET_CAP", "CURRENCY"))
    if not terminal:
        tk = None
        messagebox = None
        try:
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
        except Exception:
            # Standalone Python commonly lacks Tk; never fall back to echoed input.
            window = None
        if window is not None and tk is not None and messagebox is not None:
            dialogs = messagebox
            window.title("Configure AdCode locally")
            fields = {}
            result = {}
            tk.Label(window, text="Credentials stay on this computer. Blank keeps existing.\nBudget cap: whole currency units (e.g. dollars, not cents); zero is allowed.").grid(row=0, columnspan=2)
            for row, key in enumerate(keys, 1):
                tk.Label(window, text=SETTING_LABELS[key]).grid(row=row, column=0, sticky="w")
                entry = tk.Entry(window, show="*" if key in REQUIRED_KEYS else "", width=44)
                entry.grid(row=row, column=1)
                fields[key] = entry
            def submit():
                result.update({k: e.get() for k, e in fields.items() if e.get()})
                if any(not result.get(k, existing.get(k)) for k in keys):
                    dialogs.showerror("Missing settings", "Enter all missing settings; blank keeps an existing setting.")
                    result.clear()
                    return
                window.destroy()
            tk.Button(window, text="Save locally", command=submit).grid(row=len(keys)+1, column=1)
            window.mainloop()
            if not result:
                raise ValueError("Local setup cancelled.")
            return result
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("Open Configure AdCode.command in a local terminal; non-TTY input is refused.")
    result = {}
    try:
        with warnings.catch_warnings():
            # getpass otherwise falls back to echoed input if terminal control fails.
            warnings.simplefilter("error", getpass.GetPassWarning)
            for key in keys:
                prompt = f"{SETTING_LABELS[key]} (blank keeps existing): "
                value = getpass.getpass(prompt) if key in REQUIRED_KEYS else input(prompt)
                if value:
                    result[key] = value
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        raise ValueError("Secure local terminal input was unavailable or cancelled.") from None
    return result


def register_cursor(python, source, root, *, config_path=None) -> Path | None:
    """Merge only AdCode-Setup; return pre-change backup path, or None for no-op."""
    python, source, root = Path(python), Path(source), Path(root)
    if not all(p.is_absolute() for p in (python, source, root)):
        raise ValueError("Python, source and root must be absolute paths.")
    if not python.is_file() or not (source / "src" / "bootstrap_server.py").is_file():
        raise ValueError("Installed Python and bootstrap source must exist.")
    # Installed paths intentionally traverse the installer-owned current symlink.
    entry = {"command": str(python), "args": [str(source / "src" / "bootstrap_server.py"), "--root", str(root)]}
    config = safe_path(config_path or Path.home() / ".cursor" / "mcp.json")
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _lock(config.parent, ".adcode-register.lock"):
        original = config.read_text(encoding="utf-8") if config.exists() else None
        data = _strict_json(original) if original is not None else {}
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise ValueError("Cursor configuration and mcpServers must be objects.")
        servers = data.setdefault("mcpServers", {})
        if "AdCode-Setup" in servers:
            if servers["AdCode-Setup"] == entry:
                return None
            raise ValueError("AdCode-Setup already exists with different configuration; nothing changed.")
        servers["AdCode-Setup"] = entry
        backup = None
        if original is not None:
            backup = config.with_name("mcp.json.adcode-backup-" + uuid.uuid4().hex)
            # Back up bytes before any modification, with private permissions.
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(config.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        _atomic_write(config, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return backup


def stage_source(source, destination) -> None:
    """Copy runtime data only; no recursive repository copy or linked input."""
    source = safe_path(source, directory=True)
    destination = safe_path(destination, directory=True)
    if not destination.is_dir() or any(p.name != "venv" for p in destination.iterdir()):
        raise ValueError("Source staging requires a fresh release directory (only venv may exist).")
    lock = safe_path(source / "requirements-local.lock")
    if not lock.is_file():
        raise ValueError("requirements-local.lock is required; refusing unlocked installation.")
    allowlist = {"src": {".py"}, "schemas": {".json"}, "policies": {".json", ".yaml", ".yml"}}
    for directory, extensions in allowlist.items():
        base = safe_path(source / directory, directory=True)
        if not base.is_dir():
            raise ValueError("Runtime source directory is missing.")
        for parent, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for name in dirs + files:
                item = Path(parent) / name
                if item.is_symlink():
                    raise ValueError("Runtime source must not contain links.")
            for name in files:
                item = Path(parent) / name
                if name.startswith(".") or item.suffix not in extensions:
                    continue
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(item, target)
                target.chmod(0o600)
    shutil.copyfile(lock, destination / lock.name)


def publish_install(app, release, root) -> None:
    """Activate a complete release; roll current back if Cursor registration fails."""
    app = safe_path(app, directory=True)
    release = safe_path(release, directory=True)
    root = safe_path(root, directory=True)
    if release.parent != app / "releases" or not (release / "venv" / "bin" / "python").is_file():
        raise ValueError("Invalid staged release.")
    with _lock(app, ".publish.lock"):
        current = app / "current"
        previous = app / "previous"
        for link in (current, previous):
            if os.path.lexists(link) and (not link.is_symlink() or link.resolve().parent != app / "releases"):
                raise ValueError("Install pointer conflicts with an existing path.")
        old = os.readlink(current) if current.is_symlink() else None
        bin_dir = safe_path(app / "bin", directory=True)
        bin_dir.mkdir(mode=0o700, exist_ok=True)
        launcher = ('#!/bin/sh\n# AdCode managed local launcher v1\nset -eu\n'
                    'APP=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)\n'
                    'cd -- "$APP/current"\n'
                    'exec "$APP/current/venv/bin/python" -m src.local_setup "$@"\n')
        configure = ('#!/bin/sh\n# AdCode managed local launcher v1\nset -eu\n'
                     'BIN=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)\n'
                     'if [ "$#" -gt 0 ]; then WORKSPACE=$1; else\n'
                     '  printf "Absolute path to your existing AdCode stack workspace: "\n'
                     '  IFS= read -r WORKSPACE\n'
                     'fi\n'
                     'exec "$BIN/adcode-setup" configure --workspace "$WORKSPACE"\n')
        scripts = {"adcode-setup": launcher, "Configure AdCode.command": configure}
        for name, text in scripts.items():
            path = safe_path(bin_dir / name)
            if path.exists() and path.read_text(encoding="utf-8") != text:
                raise ValueError("Stable launcher conflicts with an existing file.")
        for name, text in scripts.items():
            if not (bin_dir / name).exists():
                _atomic_write(bin_dir / name, text, 0o700)
        def point(link, target):
            temporary = app / (".pointer-" + uuid.uuid4().hex)
            try:
                temporary.symlink_to(target, target_is_directory=True)
                os.replace(temporary, link)
            finally:
                if temporary.is_symlink():
                    temporary.unlink()
        point(current, str(release))
        try:
            register_cursor(app / "current" / "venv" / "bin" / "python", app / "current", root)
        except Exception:
            if old is None:
                current.unlink()
            else:
                point(current, old)
            raise
        if old is not None:
            point(previous, old)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AdCode local-only setup (never enter secrets as arguments)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("configure", "status", "doctor"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", required=True)
        if name == "configure":
            p.add_argument("--terminal", action="store_true", help="Use hidden local terminal prompts instead of Tk")
    p = sub.add_parser("register-cursor")
    for name in ("python", "source", "root"):
        p.add_argument("--" + name, required=True)
    p = sub.add_parser("stage-source", help=argparse.SUPPRESS)
    p.add_argument("--source", required=True)
    p.add_argument("--destination", required=True)
    p = sub.add_parser("publish-install", help=argparse.SUPPRESS)
    for name in ("app", "release", "root"):
        p.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "configure":
            root, account = _workspace(args.workspace)
            env = safe_path(root / ".env")
            _git_private(env)
            updates = _prompt_settings(_env_values(env), terminal=args.terminal, account_required=account is None)
            configure_workspace(root, updates)
            print("Your settings are saved locally. Return to Cursor and ask to check your workspace. No provider was contacted.")
        elif args.command in ("status", "doctor"):
            print(json.dumps(workspace_status(args.workspace)))
        elif args.command == "register-cursor":
            register_cursor(args.python, args.source, args.root)
            print("Cursor AdCode-Setup registration is configured.")
        elif args.command == "stage-source":
            stage_source(args.source, args.destination)
        elif args.command == "publish-install":
            publish_install(args.app, args.release, args.root)
    except (ValueError, OSError, UnicodeError):
        # Even OS/codec exceptions can contain input data: don't echo them.
        print("AdCode setup refused the operation. Check paths, template account binding, required settings, Git privacy, and existing Cursor conflicts locally. No secrets are displayed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
