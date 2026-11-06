"""Private local workspace onboarding. Never contact providers or return credentials."""

import ctypes
import errno
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import subprocess
import unicodedata


SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ACCOUNT_PATTERN = r"act_[0-9]+"
_RESERVED = {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1, 10)],
             *[f"lpt{i}" for i in range(1, 10)]}


def _slug(value: str) -> bool:
    return (isinstance(value, str) and len(value) <= 63
            and re.fullmatch(SLUG_PATTERN, value) is not None
            and value not in _RESERVED)


def _safe_root(root: Path) -> Path:
    # Inspect the lexical path before resolve() can hide symlinks or traversal.
    path = Path(root).expanduser()
    if ".." in path.parts:
        raise ValueError("Workspace root must not contain '..'.")
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Workspace paths must not contain symlinks or junctions.")
        if part.exists() and not part.is_dir():
            raise ValueError("Workspace root ancestors must be directories.")
    return path


def _check_child(parent: Path, name: str, *, allow_existing: bool = False) -> Path:
    target = parent / name
    if parent.exists():
        matches = [p for p in parent.iterdir() if p.name.casefold() == name.casefold()]
        if matches:
            if len(matches) != 1 or matches[0].name != name:
                raise ValueError("Workspace path has a case-insensitive name collision.")
            if not allow_existing:
                raise FileExistsError("Workspace already exists; nothing was overwritten.")
            child = matches[0]
            if (child.is_symlink() or
                    (hasattr(child, "is_junction") and child.is_junction()) or
                    not child.is_dir()):
                raise ValueError("Workspace paths must be real directories, not links.")
    return target


def _mkdir_private(path: Path, created: list[Path]) -> None:
    if not path.exists():
        _mkdir_private(path.parent, created)
        path.mkdir(mode=0o700)
        created.append(path)


def _publish(stage: Path, target: Path) -> None:
    """Atomically publish without replacing even an existing empty directory."""
    if sys.platform == "win32":
        os.rename(stage, target)  # Windows rename never replaces existing targets.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        args = (os.fsencode(stage), os.fsencode(target), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        args = (-100, os.fsencode(stage), -100, os.fsencode(target), 1)  # NOREPLACE
    else:
        raise OSError("Atomic no-replace workspace publication is unsupported on this OS.")
    rename.restype = ctypes.c_int
    if rename(*args) != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError("Workspace already exists; nothing was overwritten.")
        raise OSError(error, os.strerror(error))


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                 0o700 if executable else 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _metadata(customer: str, stack_name: str, workspace: Path) -> dict:
    return {
        "customer": customer,
        "stack_name": stack_name,
        "workspace": str(workspace),
        "template": str(workspace / f"{stack_name}_template.json"),
    }


def create_workspace(root: Path, customer: str, stack_name: str, account_id: str,
                     *, python_executable=None, source_root=None) -> dict:
    """Legacy explicit scaffolding API; does not create an actual .env."""
    return _create_workspace(root, customer, stack_name, account_id,
                             python_executable=python_executable, source_root=source_root)


def _create_workspace(root: Path, customer: str, stack_name: str, account_id: str,
                      *, python_executable=None, source_root=None, guided=None) -> dict:
    """Create a private stack below root; never overwrite or initialize live state.

    root/source_root/python_executable are trusted host configuration, not MCP inputs.
    A cooperative root lock serializes our writers. The root and its ancestors must
    be controlled by the local user (not concurrently mutated by another process).
    """
    if not _slug(customer) or not _slug(stack_name):
        raise ValueError("Customer and stack_name must be lowercase ASCII slugs (1-63 characters).")
    if guided is None and (not isinstance(account_id, str) or len(account_id) > 64
            or re.fullmatch(ACCOUNT_PATTERN, account_id) is None):
        raise ValueError("account_id must be act_ followed by ASCII digits (at most 64 characters).")
    root = _safe_root(root)
    python = Path(python_executable if python_executable is not None else sys.executable)
    if not python.is_absolute() or not python.is_file():
        raise ValueError("Python executable must be an absolute existing file path.")
    # Do not resolve the interpreter: a virtualenv's symlink must keep its venv path.
    source = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[2]
    if not source.is_absolute() or not (source / "src" / "mcp_server.py").is_file():
        raise ValueError("source_root must be an absolute AdCode source directory.")
    source = source.resolve()
    if python_executable is None:
        # Pin an installed workspace to the same release's interpreter/dependencies,
        # not a moving 'current' symlink that could later run old source with new deps.
        installed_python = source / "venv" / "bin" / "python"
        if installed_python.is_file():
            python = installed_python
    parent = _check_child(root, customer, allow_existing=True)
    target = _check_child(parent, stack_name)
    template = target / f"{stack_name}_template.json"
    config = {"mcpServers": {"adcode": {
        "command": str(python),
        "args": [str(source / "src" / "mcp_server.py"), "--config", str(template),
                 "--access-mode", "planning"],
    }}}
    starter = {"account_id": account_id, "campaigns": [{
        "name": stack_name, "objective": "OUTCOME_TRAFFIC", "status": "PAUSED",
        "special_ad_categories": [], "ad_sets": [],
    }]}
    if guided is not None:
        starter = {'account_id': '', 'campaigns': []}
    created = []
    stage = None
    locked = False
    lock = root / ".adcode-workspace.lock"
    try:
        _mkdir_private(root, created)
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError:
            raise ValueError("Workspace root is busy or locked; retry after checking the local lock.") from None
        locked = True
        # Recheck while holding the cooperative lock, including case collisions.
        _safe_root(root)
        parent = _check_child(root, customer, allow_existing=True)
        _check_child(parent, stack_name)
        if guided is not None and parent.exists():
            for existing in parent.iterdir():
                if not _slug(existing.name):
                    continue
                _check_child(parent, existing.name, allow_existing=True)
                info = _manifest(existing, f'{customer}/{existing.name}')
                if info['customer_name'] != guided['customer_name']:
                    raise ValueError('This customer name collides with an existing workspace. Choose another name.')
        _mkdir_private(parent, created)
        stage = Path(tempfile.mkdtemp(prefix=".adcode-stage-", dir=parent))
        (stage / ".cursor").mkdir(mode=0o700)
        (stage / ".cursor" / "rules").mkdir(mode=0o700)
        _write(stage / template.name, _json(starter))
        _write(stage / ".cursor" / "mcp.json", _json(config))
        _write(stage / ".env.example", "# Configure locally; never share .env or paste secrets into chat.\n"
               "FB_APP_ID=\nFB_APP_SECRET=\nFB_ACCESS_TOKEN=\nANTHROPIC_API_KEY=\n")
        _write(stage / ".gitignore", ".env\n.env.*\n!.env.example\n*.bak\n*.backup\n*.tmp\n"
               "*.temp\n*~\nbackups/\n.tmp/\n.DS_Store\n")
        _write(stage / ".cursorignore", ".env\n.env.*\n*.bak\n*.backup\nbackups/\n")
        _write(stage / ".cursor" / "rules" / "adcode.mdc", f"""---
description: Local AdCode workspace safety and workflow
alwaysApply: true
---
Edit `{template.name}` from the user's plain-language campaign requests; preserve
schema validity and keep new campaigns PAUSED unless explicitly approved otherwise.
Never read .env, .env backups, or credential values; never request secrets in chat.
Use Configure AdCode.command for local setup; credentials stay in this stack's .env.
Saved state is tracking history, NOT live Facebook data. Use live tools for live claims.
Always run plan_stack and review the changeset before any apply. Apply requires
explicit user approval; deletions require separate confirmation. Never infer approval.
Planning sends campaign data to Anthropic; obtain consent before planning sensitive data.
The project MCP enforces planning mode at tool discovery and execution. Write tools,
live provider reads and arbitrary-file Excel tools are unavailable in this mode.
Do not change its mode to obtain write access without the operator's explicit action.
The global bootstrap only scaffolds/lists workspaces. Cursor ignore rules reduce
accidental secret indexing; they do not sandbox terminal commands or the local user.
""")
        command = ("#!/bin/sh\nset -eu\n"
                   f"cd -- {shlex.quote(str(source))}\n"
                   f"exec {shlex.quote(str(python))} -m src.local_setup configure "
                   f"--workspace {shlex.quote(str(target))}\n")
        _write(stage / "Configure AdCode.command", command, executable=True)
        _write(stage / "README.md", f"""# Private AdCode workspace: {customer}/{stack_name}

Open this directory in Cursor to load its project .cursor/mcp.json. The global
bootstrap MCP remains separate: it only creates and lists local workspaces.

Run `Configure AdCode.command` locally to configure this stack's .env. The command
uses the installed Python and source checkout; keep both installed at their current
paths. Local setup requires `python -m src.local_setup configure --workspace <dir>`.
Do not paste keys into chat, templates, MCP configuration, or source control.
Only .env.example is created here; no credentials are provisioned or uploaded.

Ask the agent in plain language to edit `{template.name}`. The starter is PAUSED
with no ad sets, no live IDs and no state file; review and complete it before use.
Saved state is not live Facebook data. Plan before apply; review costs and changes,
explicitly approve writes, and separately confirm deletions. Planning sends campaign
data to Anthropic and requires locally configured credentials and network access.

The project MCP uses server-enforced `--access-mode planning`: inspection, planning
and review packets only, with no mutation, live provider reads or arbitrary-file
Excel tools. Cursor can still edit your local template. This is not an OS sandbox;
keep tool approvals enabled and never let the agent read .env through a terminal.
Restart the project's MCP connection after running local credential setup.

Files are private on POSIX, but .gitignore is not encryption or a backup policy.
Do not publish this workspace or credential backups. No hosted secret store is used.
""")
        if guided is not None:
            _guided_files(stage, target, customer, stack_name, guided, config)
        _check_child(parent, stack_name)
        _publish(stage, target)
        stage = None
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        if locked:
            lock.rmdir()
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass  # Successful workspaces or other existing contents must survive.
    if guided is not None:
        return _guided_result(target, guided)
    result = _metadata(customer, stack_name, target)
    result["next_steps"] = [
        "Open the returned workspace directory in Cursor to load its project MCP.",
        "Run Configure AdCode.command locally to configure stack-local .env secrets; never send them to the bootstrap or chat.",
        "Edit the template, then review plan_stack before any approved apply. Planning sends campaign data to Anthropic.",
    ]
    return result


def list_workspaces(root: Path) -> list[dict]:
    """List path metadata only; never read templates, state, .env, or backups."""
    root = _safe_root(root)
    if not root.exists():
        return []
    result = []
    for customer in sorted(root.iterdir()):
        if not _slug(customer.name):
            continue
        try:
            _check_child(root, customer.name, allow_existing=True)
        except ValueError:
            continue
        for stack in sorted(customer.iterdir()):
            if not _slug(stack.name):
                continue
            try:
                _check_child(customer, stack.name, allow_existing=True)
            except ValueError:
                continue
            template = stack / f"{stack.name}_template.json"
            if not template.is_symlink() and template.is_file():
                if (stack / ".adcode-workspace.json").exists():
                    try:
                        manifest = _manifest(stack, f"{customer.name}/{stack.name}")
                        result.append(_guided_result(stack, manifest))
                    except (ValueError, OSError):
                        continue
                else:
                    result.append(_metadata(customer.name, stack.name, stack))
    return result


def _display_slug(value: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 160
            or any(c in value for c in '/\\:') or '..' in value
            or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError("Choose a simple customer or workspace name without path characters.")
    ascii_name = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.lower()).strip('-')
    if not _slug(slug):
        raise ValueError("Choose a shorter name containing letters or numbers, not a reserved name.")
    return slug


def start_workspace(root: Path, customer_name: str, workspace_name: str = 'Campaigns',
                    *, python_executable=None, source_root=None) -> dict:
    """Start an unfinished local draft without accepting account IDs or secrets."""
    customer = _display_slug(customer_name)
    stack = _display_slug(workspace_name)
    manifest = {'schema_version': 2, 'customer_name': customer_name,
                'workspace_name': workspace_name, 'workspace_id': f'{customer}/{stack}'}
    return _create_workspace(root, customer, stack, '', guided=manifest,
                             python_executable=python_executable, source_root=source_root)


def _connection_prepared(target: Path) -> bool:
    from src.local_setup import safe_path
    try:
        data = _read_json(safe_path(target / '.cursor' / 'mcp.json'))
        entry = data['mcpServers']['adcode']
        args = entry['args']
        expected = ['--config', str(target / f'{target.name}_template.json'),
                    '--access-mode', 'planning', '--onboarding']
        return (set(entry) <= {'command', 'args', 'disabled'}
                        and entry.get('disabled', False) is False
                and isinstance(entry['command'], str)
                and Path(entry['command']).is_absolute() and Path(entry['command']).is_file()
                and isinstance(args, list) and len(args) == 6 and args[1:] == expected
                and isinstance(args[0], str) and Path(args[0]).is_absolute()
                and Path(args[0]).name == 'mcp_server.py' and Path(args[0]).is_file())
    except Exception:
        return False


def _guided_result(target: Path, manifest: dict) -> dict:
    return {
        **manifest,
        'message': 'Your private campaign draft is prepared. Add your keys locally, never in chat.',
        'workspace_uri': target.as_uri(), 'env_uri': (target / '.env').as_uri(),
        'config_prepared': _connection_prepared(target), 'prepared': True,
        'connection_active': None, 'connection_status': 'not_verified',
        'provider_connection_verified': False,
        'next_actions': ['open_workspace', 'check_workspace'],
    }


def _guided_files(stage, target, customer, stack, manifest, config):
    def replace(name, text):
        path = stage / name
        if path.exists():
            path.unlink()
        _write(path, text)

    replace(f'{stack}_template.json', _json({'account_id': '', 'campaigns': []}))
    config['mcpServers']['adcode']['args'].append('--onboarding')
    replace('.cursor/mcp.json', _json(config))
    _write(stage / '.adcode-workspace.json', _json(manifest))
    env = ('# Fill in these values here, privately. Never paste keys into chat.\n'
           '# Facebook account: digits or act_ followed by digits.\n'
           'FB_ACCOUNT_ID=\nFB_APP_ID=\nFB_APP_SECRET=\nFB_ACCESS_TOKEN=\n'
           'ANTHROPIC_API_KEY=\n'
           '# Spending limit in whole currency units (zero is allowed).\n'
           'ACCOUNT_BUDGET_CAP=\n# Three-letter currency, for example USD.\nCURRENCY=\n')
    replace('.env.example', env)
    _write(stage / '.env', env)
    guide = '''This is an unfinished draft, not a live campaign or verified connection.
Open .env yourself in your editor and enter your account, keys, spending limit and
currency. Never paste secrets into chat or let an agent read .env. Manual editing
is the primary setup method; Configure AdCode.command is an optional local helper.
After saving, ask to check the workspace. A local check does not verify a provider
connection. Then tell the assistant what you are promoting, your budget and dates.
Use friendly names in conversation; do not ask for roots, slugs or MCP setup.
Preserve Cursor permissions and approvals. Never change access mode automatically.
Keep new campaigns PAUSED. Review plan_stack before any explicitly approved apply;
confirm deletions separately. Planning sends campaign data to Anthropic: obtain
consent for sensitive data. Saved state is NOT live Facebook data. Never normalize
existing campaign names. No provider connection has been verified by setup.
Ignore rules reduce accidental indexing, not terminal access: never read .env,
credential backups or secrets with filesystem/terminal tools. Use check_workspace
for safe setup statuses. Keep this folder and backups private.
'''
    replace('README.md', '# Your private campaign workspace\n\n' + guide)
    replace('.cursor/rules/adcode.mdc', '---\ndescription: Private campaign workspace\nalwaysApply: true\n---\n' + guide)


def _file(path: Path) -> Path:
    if (path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
            or (path.exists() and not path.is_file())):
        raise ValueError('Workspace files must be regular local files.')
    return path


def _read_json(path):
    from src.local_setup import _strict_json
    return _strict_json(_file(path).read_text(encoding='utf-8'))


def _known_workspace(root, workspace_id):
    if (not isinstance(workspace_id, str) or len(workspace_id.split('/')) != 2
            or not all(_slug(part) for part in workspace_id.split('/'))):
        raise ValueError('Choose a workspace from the workspace list.')
    root = _safe_root(root)
    customer, stack = workspace_id.split('/')
    parent = _check_child(root, customer, allow_existing=True)
    target = _check_child(parent, stack, allow_existing=True)
    if not target.is_dir():
        raise ValueError('Workspace not found. Choose one from the workspace list.')
    return target


def _manifest(target, workspace_id):
    manifest = _read_json(target / '.adcode-workspace.json')
    if (not isinstance(manifest, dict) or set(manifest) != {
            'schema_version', 'customer_name', 'workspace_name', 'workspace_id'}
            or manifest['schema_version'] != 2 or manifest['workspace_id'] != workspace_id
            or _display_slug(manifest['customer_name']) != workspace_id.split('/')[0]
            or _display_slug(manifest['workspace_name']) != workspace_id.split('/')[1]):
        raise ValueError('Workspace information needs repair locally; no files were changed.')
    return manifest


def _account(value):
    if isinstance(value, str) and re.fullmatch(r'(?:act_)?[0-9]{1,60}', value):
        return 'act_' + value.removeprefix('act_')
    return None


def _placeholder(value):
    text = value.strip().lower()
    compact = re.sub(r'[^a-z0-9]', '', text)
    return (not text or text.startswith(('<', '${')) or compact in {
        'placeholder', 'changeme', 'replaceme', 'todo', 'example', 'xxx', 'xxxxx',
        'yourkey', 'yourtoken', 'yourappid', 'yourappsecret', 'youraccesstoken',
        'youranthropicapikey', 'youraccountid', 'secret', 'token', 'key', 'none', 'null'}
        or compact.startswith(('your', 'replace', 'paste', 'insert', 'example'))
        or 'placeholder' in compact or 'yourkey' in compact or 'yourtoken' in compact
        or (bool(compact) and set(compact) == {'x'}))


def check_workspace(root: Path, workspace_id: str) -> dict:
    """Privately validate local settings, never test a provider or return values."""
    try:
        return _check_workspace(root, workspace_id)
    except Exception:
        # Neither JSON/dotenv exceptions nor OS errors may expose supplied values.
        return {'error': 'Could not check this workspace safely. Review its local files and permissions; no connection was verified.',
                'provider_connection_verified': False, 'connection_active': None,
                'connection_status': 'not_verified'}


def _check_workspace(root, workspace_id):
    from src.local_setup import _env_values, REQUIRED_KEYS, CURRENCIES, _lock, _atomic_write, _git_private
    target = _known_workspace(root, workspace_id)
    manifest_path = _file(target / '.adcode-workspace.json')
    if not manifest_path.exists():
        return {'status': 'upgrade_required', 'provider_connection_verified': False,
                'connection_active': None, 'connection_status': 'not_verified',
                'next_step': 'This older workspace needs a local upgrade; existing files were left unchanged.'}
    _manifest(target, workspace_id)
    with _lock(target, '.adcode-setup.lock'):
        _known_workspace(root, workspace_id)
        _manifest(target, workspace_id)
        _git_private(_file(target / '.env'))
        values = _env_values(_file(target / '.env'))
        labels = {'FB_ACCOUNT_ID': 'Facebook account', 'FB_APP_ID': 'Facebook app ID',
                  'FB_APP_SECRET': 'Facebook app secret', 'FB_ACCESS_TOKEN': 'Facebook access token',
                  'ANTHROPIC_API_KEY': 'Anthropic key', 'ACCOUNT_BUDGET_CAP': 'Spending limit',
                  'CURRENCY': 'Currency'}
        statuses = {}
        keys = tuple(dict.fromkeys((*REQUIRED_KEYS, *labels)))
        for key in keys:
            value = values.get(key) or ''
            status = 'entered'
            if not value.strip():
                status = 'missing'
            elif _placeholder(value):
                status = 'placeholder'
            elif (any(unicodedata.category(c).startswith('C') for c in value)
                  or (key == 'FB_ACCOUNT_ID' and not _account(value))
                  or (key == 'FB_APP_ID' and not re.fullmatch(r'[0-9]+', value))
                  or (key == 'ACCOUNT_BUDGET_CAP' and not re.fullmatch(r'[0-9]+', value))
                  or (key == 'CURRENCY' and value not in CURRENCIES)):
                status = 'invalid'
            statuses[labels.get(key, 'Required setting')] = status
        ready = all(status == 'entered' for status in statuses.values())
        template_path = _file(target / f'{target.name}_template.json')
        template = _read_json(template_path)
        if (not isinstance(template, dict) or not isinstance(template.get('campaigns'), list)
                or not isinstance(template.get('account_id'), str)):
            raise ValueError('Invalid draft.')
        account = _account(values.get('FB_ACCOUNT_ID'))
        bound = template['account_id']
        state_file = _file(target / 'state.json')
        state_paths = [state_file] if state_file.exists() else []
        for path in state_paths:
            state = _read_json(path)
            if not isinstance(state, dict) or not account or _account(state.get('account_id')) != account:
                raise ValueError('Account mismatch.')
        if bound and account and _account(bound) != account:
            raise ValueError('Account mismatch.')
        finalized = False
        if ready and not bound:
            if state_paths or template != {'account_id': '', 'campaigns': []}:
                raise ValueError('Draft needs review.')
            template['account_id'] = account
            _atomic_write(template_path, _json(template))
            finalized = True
        configured = _connection_prepared(target)
        return {'workspace_id': workspace_id,
                'status': ('needs_connection_setup' if not configured else 'ready' if ready else 'needs_settings'),
                'settings': statuses, 'credentials_entered': ready,
                'config_prepared': configured, 'prepared': True,
                'connection_active': None, 'connection_status': 'not_verified',
                'provider_connection_verified': False, 'account_bound': bool(bound) or finalized,
                'campaign_status': 'brief_incomplete' if not template['campaigns'] else 'brief_entered',
                'next_step': ('Your files are safe, but the app connection needs repair. Reinstall AdCode or ask the operator to check it.'
                              if not configured else 'What are you promoting, what is your budget, and what dates should it run?'
                              if ready else 'Open .env privately, fill in the missing or invalid settings, save, then check again.')}


def open_workspace(root: Path, workspace_id: str) -> dict:
    """Request a Cursor window, not an MCP or provider connection."""
    try:
        target = _known_workspace(root, workspace_id)
        _manifest(target, workspace_id)
        if sys.platform == 'darwin':
            argv = ['/usr/bin/open', '-a', 'Cursor', str(target)]
        elif sys.platform == 'win32':
            local = os.environ.get('LOCALAPPDATA')
            executable = Path(local) / 'Programs' / 'cursor' / 'Cursor.exe' if local else None
            if executable is None or not executable.is_absolute() or not _file(executable).is_file():
                raise OSError('Cursor unavailable.')
            _safe_root(executable.parent)
            argv = [str(executable), str(target)]
        else:
            executable = shutil.which('cursor')
            if not executable:
                raise OSError('Cursor unavailable.')
            argv = [executable, str(target)]
        subprocess.run(argv, shell=False, capture_output=True, timeout=8, check=True)
        return {'workspace_id': workspace_id, 'launch_requested': True,
                'connection_active': None, 'connection_status': 'not_verified',
                                'provider_connection_verified': False,
                'message': 'Cursor was asked to open your workspace. No connection has been verified.'}
    except Exception:
        return {'launch_requested': False, 'connection_active': None,
                        'connection_status': 'not_verified',
                'provider_connection_verified': False,
                'error': 'Could not open Cursor automatically. Open your workspace in Cursor yourself.'}
