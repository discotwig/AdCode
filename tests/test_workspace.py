import json
import os
from pathlib import Path
import shlex
import stat
import sys
from unittest.mock import patch

import jsonschema
import pytest

from src.services import workspace as ws


SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    # macOS temporary directory ancestors can themselves be symlinks.
    return tmp_path.resolve() / "Documents with spaces ü" / "AdCode"


def create(root, **kwargs):
    return ws.create_workspace(root, "customer", "spring-sale", "act_123456", **kwargs)


def test_create_valid_private_starter_and_config(root):
    with patch.dict(os.environ, {"FB_ACCESS_TOKEN": "secret-token", "ANTHROPIC_API_KEY": "secret-key"}):
        result = create(root)
    target = root / "customer" / "spring-sale"
    assert result["workspace"] == str(target)
    assert result["template"] == str(target / "spring-sale_template.json")
    schema = json.loads((SOURCE / "schemas" / "campaign.schema.json").read_text(encoding="utf-8"))
    template = json.loads(Path(result["template"]).read_text(encoding="utf-8"))
    jsonschema.validate(template, schema)
    assert template["campaigns"][0]["status"] == "PAUSED"
    assert template["campaigns"][0]["ad_sets"] == []
    assert "fb_id" not in json.dumps(template)
    assert not (target / "state.json").exists()
    assert not (target / ".env").exists()
    config = json.loads((target / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = config["mcpServers"]["adcode"]
    assert entry == {
        "command": sys.executable,
        "args": [str(SOURCE / "src" / "mcp_server.py"), "--config", result["template"],
                 "--access-mode", "planning"],
    }
    for path in target.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "secret-token" not in text
            assert "secret-key" not in text
    example = (target / ".env.example").read_text(encoding="utf-8")
    assert "FB_ACCESS_TOKEN=\n" in example
    assert "ANTHROPIC_API_KEY=\n" in example
    ignore = (target / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {".env", ".env.*", "!.env.example", "*.bak", "*.tmp", "backups/"} <= set(ignore)
    rules = (target / ".cursor" / "rules" / "adcode.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in rules
    assert "Never read .env" in rules
    assert "NOT live Facebook" in rules
    assert "plan_stack" in rules and "Anthropic" in rules
    assert all("secret" not in key for key in result)
    assert len(result["next_steps"]) == 3
    assert not list(root.rglob(".adcode-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes; Windows requires local ACLs")
def test_private_modes(root):
    target = Path(create(root)["workspace"])
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    for path in [target, *target.rglob("*")]:
        expected = 0o700 if path.is_dir() or path.name.endswith(".command") else 0o600
        assert stat.S_IMODE(path.stat().st_mode) == expected


@pytest.mark.parametrize("name", ["", ".", "..", "../escape", "a/b", "a\\b", "/abs", "a b", "a.b",
                                  "Customer", "café", "a_thing", "-a", "a-", "a--b", "a\n", "a" * 64,
                                  "con", "nul", "com1"])
@pytest.mark.parametrize("field", ["customer", "stack_name"])
def test_invalid_slugs_leave_no_directories(root, name, field):
    args = dict(customer="customer", stack_name="spring-sale", account_id="act_1")
    args[field] = name
    with pytest.raises(ValueError):
        ws.create_workspace(root, **args)
    assert not root.parent.exists()


@pytest.mark.parametrize("account", ["123", "act_", "act_-1", "act_１２３", "act_1\n", " act_1", "act_1/../x", 123, None])
def test_invalid_account_leaves_no_directories(root, account):
    with pytest.raises(ValueError):
        ws.create_workspace(root, "customer", "stack", account)
    assert not root.exists()


def test_existing_target_not_overwritten(root):
    first = create(root)
    target = Path(first["workspace"])
    marker = target / ".env"
    marker.write_text("DO NOT READ OR OVERWRITE", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create(root)
    assert marker.read_text(encoding="utf-8") == "DO NOT READ OR OVERWRITE"
    # Even an empty directory must not be replaced.
    empty = target.parent / "empty"
    empty.mkdir()
    with pytest.raises(FileExistsError):
        ws.create_workspace(root, "customer", "empty", "act_1")
    assert list(empty.iterdir()) == []


@pytest.mark.parametrize("level", ["customer", "stack"])
def test_case_collisions(root, level):
    parent = root if level == "customer" else root / "customer"
    parent.mkdir(parents=True)
    collision = parent / ("Customer" if level == "customer" else "Spring-Sale")
    collision.mkdir()
    with pytest.raises(ValueError, match="collision"):
        create(root)
    assert list(collision.iterdir()) == []
    assert not list(root.rglob(".adcode-*"))


def symlink_or_skip(link, target, *, directory=True):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("Symlink creation unavailable (Windows developer mode/privilege required)")


@pytest.mark.parametrize("level", ["root", "ancestor", "customer", "stack"])
def test_reject_symlinks(tmp_path, level):
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    root = base / "root"
    if level == "root":
        symlink_or_skip(root, outside)
    elif level == "ancestor":
        ancestor = base / "link"
        symlink_or_skip(ancestor, outside)
        root = ancestor / "root"
    else:
        root.mkdir()
        link = root / "customer"
        if level == "stack":
            link.mkdir()
            link = link / "spring-sale"
        symlink_or_skip(link, outside)
    with pytest.raises((ValueError, FileExistsError)):
        create(root)
    assert list(outside.iterdir()) == []


def test_reject_dangling_symlink(root, tmp_path):
    root.mkdir(parents=True)
    symlink_or_skip(root / "customer", tmp_path / "nonexistent")
    with pytest.raises(ValueError):
        create(root)


def test_reject_root_traversal(tmp_path):
    root = tmp_path / "x" / ".." / "escape"
    with pytest.raises(ValueError):
        create(root)
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize("kwargs", [{"python_executable": "python"}, {"source_root": Path("relative")}])
def test_invalid_installation_no_leftovers(root, kwargs):
    with pytest.raises(ValueError):
        create(root, **kwargs)
    assert not root.exists()


def test_safe_quoted_launcher(root, tmp_path):
    source = tmp_path.resolve() / "installed source ü ' ; literal"
    (source / "src").mkdir(parents=True)
    (source / "src" / "mcp_server.py").touch()
    result = create(root, source_root=source)
    lines = (Path(result["workspace"]) / "Configure AdCode.command").read_text(encoding="utf-8").splitlines()
    assert shlex.split(lines[2]) == ["cd", "--", str(source)]
    assert shlex.split(lines[3]) == ["exec", sys.executable, "-m", "src.local_setup", "configure",
                                     "--workspace", result["workspace"]]


@pytest.mark.parametrize("failure", ["write", "publish"])
def test_failure_cleans_all_partial_directories(root, failure):
    func = "_write" if failure == "write" else "_publish"
    with patch.object(ws, func, side_effect=OSError("simulated failure")):
        with pytest.raises(OSError):
            create(root)
    assert not root.parent.exists()


def test_failure_preserves_existing_customer(root):
    parent = root / "customer"
    parent.mkdir(parents=True)
    marker = parent / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with patch.object(ws, "_write", side_effect=OSError("failure")):
        with pytest.raises(OSError):
            create(root)
    assert list(parent.iterdir()) == [marker]
    assert not (root / ".adcode-workspace.lock").exists()


def test_publish_does_not_replace_existing_empty_directory(tmp_path):
    stage = tmp_path / "stage"
    target = tmp_path / "target"
    stage.mkdir()
    target.mkdir()
    (stage / "marker").touch()
    with pytest.raises(FileExistsError):
        ws._publish(stage, target)
    assert (stage / "marker").exists()
    assert list(target.iterdir()) == []


def test_busy_root_not_modified(root):
    root.mkdir(parents=True)
    lock = root / ".adcode-workspace.lock"
    lock.mkdir()
    with pytest.raises(ValueError, match="busy"):
        create(root)
    assert list(root.iterdir()) == [lock]


def test_empty_listing_is_read_only(root):
    assert ws.list_workspaces(root) == []
    assert not root.exists()
    root.mkdir(parents=True)
    assert ws.list_workspaces(root) == []


def test_listing_only_reads_directory_metadata(root):
    first = create(root)
    second = ws.create_workspace(root, "customer", "winter", "act_2")
    (Path(first["workspace"]) / ".env").write_text("never read me", encoding="utf-8")
    (root / "not-a-workspace").mkdir()
    with patch.object(Path, "read_text", side_effect=AssertionError("No file contents should be read")):
        listing = ws.list_workspaces(root)
    assert listing == [{k: v for k, v in item.items() if k != "next_steps"} for item in (first, second)]


def test_listing_skips_linked_templates_and_customers(root, tmp_path):
    result = create(root)
    template = Path(result["template"])
    template.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("secret", encoding="utf-8")
    symlink_or_skip(template, outside, directory=False)
    symlink_or_skip(root / "linked", root / "customer")
    assert ws.list_workspaces(root) == []


def guided(root):
    result = ws.start_workspace(root, 'Café & Friends', 'Summer Campaigns')
    return result, root / 'cafe-friends' / 'summer-campaigns'


def fill_env(target, **overrides):
    values = {'FB_ACCOUNT_ID': '1234567', 'FB_APP_ID': '9876543',
              'FB_APP_SECRET': 'private-app-credential', 'FB_ACCESS_TOKEN': 'private-facebook-credential',
              'ANTHROPIC_API_KEY': 'private-anthropic-credential', 'ACCOUNT_BUDGET_CAP': '0', 'CURRENCY': 'USD'}
    values.update(overrides)
    (target / '.env').write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    return values


def test_guided_draft_and_private_files(root):
    result, target = guided(root)
    assert result['customer_name'] == 'Café & Friends'
    assert result['workspace_name'] == 'Summer Campaigns'
    assert result['schema_version'] == 2
    assert result['workspace_id'] == 'cafe-friends/summer-campaigns'
    assert result['env_uri'] == (target / '.env').as_uri()
    assert result['workspace_uri'] == target.as_uri()
    assert not result['provider_connection_verified']
    template = target / 'summer-campaigns_template.json'
    assert json.loads(template.read_text(encoding='utf-8')) == {'account_id': '', 'campaigns': []}
    assert not (target / 'state.json').exists()
    assert (target / '.env').read_bytes() == (target / '.env.example').read_bytes()
    from src.local_setup import _env_values
    assert _env_values(target / '.env') == dict.fromkeys([
        'FB_ACCOUNT_ID', 'FB_APP_ID', 'FB_APP_SECRET', 'FB_ACCESS_TOKEN',
        'ANTHROPIC_API_KEY', 'ACCOUNT_BUDGET_CAP', 'CURRENCY'], '')
    config = json.loads((target / '.cursor/mcp.json').read_text(encoding='utf-8'))
    assert config['mcpServers']['adcode']['args'][-3:] == ['--access-mode', 'planning', '--onboarding']
    assert ws.list_workspaces(root) == [result]
    if os.name == 'posix':
        for path in [target, *target.rglob('*')]:
            expected = 0o700 if path.is_dir() or path.name.endswith('.command') else 0o600
            assert stat.S_IMODE(path.stat().st_mode) == expected


def test_guided_check_bind_idempotent_and_private(root):
    result, target = guided(root)
    initial = ws.check_workspace(root, result['workspace_id'])
    assert initial['status'] == 'needs_settings'
    assert initial['campaign_status'] == 'brief_incomplete'
    assert not initial['credentials_entered']
    values = fill_env(target)
    original_env = (target / '.env').read_bytes()
    ready = ws.check_workspace(root, result['workspace_id'])
    assert ready['status'] == 'ready'
    assert ready['credentials_entered'] and ready['account_bound']
    assert not ready['connection_active'] and not ready['provider_connection_verified']
    assert ready['campaign_status'] == 'brief_incomplete'
    assert 'promoting' in ready['next_step']
    assert json.loads((target / 'summer-campaigns_template.json').read_text()) == {
        'account_id': 'act_1234567', 'campaigns': []}
    assert ws.check_workspace(root, result['workspace_id']) == ready
    assert (target / '.env').read_bytes() == original_env
    assert not (target / 'state.json').exists()
    output = json.dumps(ready)
    for key in ('FB_APP_SECRET', 'FB_ACCESS_TOKEN', 'ANTHROPIC_API_KEY', 'FB_ACCOUNT_ID'):
        assert values[key] not in output


@pytest.mark.parametrize('key,value,status', [
    ('FB_APP_SECRET', 'your-app-secret', 'placeholder'),
    ('FB_ACCESS_TOKEN', 'CHANGEME', 'placeholder'),
    ('ANTHROPIC_API_KEY', '${PRIVATE_KEY}', 'placeholder'),
    ('FB_ACCOUNT_ID', 'act_１２３', 'invalid'),
    ('FB_ACCOUNT_ID', 'act_123', 'entered'),
    ('FB_APP_ID', 'not-digits', 'invalid'),
    ('ACCOUNT_BUDGET_CAP', '-1', 'invalid'),
    ('ACCOUNT_BUDGET_CAP', '1.5', 'invalid'),
    ('CURRENCY', 'ZZZ', 'invalid'),
    ('CURRENCY', 'usd', 'invalid'),
    ('FB_APP_SECRET', '', 'missing'),
])
def test_guided_setting_validation(root, key, value, status):
    result, target = guided(root)
    fill_env(target, **{key: value})
    checked = ws.check_workspace(root, result['workspace_id'])
    assert status in checked['settings'].values()
    assert checked['credentials_entered'] == (status == 'entered')
    assert not checked['provider_connection_verified']
    if status != 'entered':
        assert json.loads((target / 'summer-campaigns_template.json').read_text())['account_id'] == ''


@pytest.mark.parametrize('kind', ['bound', 'state', 'nonempty', 'extra', 'malformed-env'])
def test_guided_refuses_unsafe_finalization(root, kind):
    result, target = guided(root)
    fill_env(target)
    template = target / 'summer-campaigns_template.json'
    if kind == 'bound':
        template.write_text(json.dumps({'account_id': 'act_999999', 'campaigns': []}))
    elif kind == 'state':
        (target / 'state.json').write_text(json.dumps({'account_id': 'act_999999'}))
    elif kind == 'nonempty':
        template.write_text(json.dumps({'account_id': '', 'campaigns': [{'name': 'Keep â€ name'}]}))
    elif kind == 'extra':
        template.write_text(json.dumps({'account_id': '', 'campaigns': [], 'unknown': 'keep'}))
    else:
        (target / '.env').write_text('FB_APP_SECRET="private-secret-with-no-closing-quote\n')
    before = template.read_bytes()
    checked = ws.check_workspace(root, result['workspace_id'])
    assert 'error' in checked
    assert 'private-secret' not in json.dumps(checked)
    assert template.read_bytes() == before


@pytest.mark.parametrize('name', ['../escape', 'A/B', 'A\\B', 'a\nB', 'CON', 'NUL', '.', '東京', 'a:b'])
def test_guided_rejects_unsafe_names(root, name):
    with pytest.raises(ValueError):
        ws.start_workspace(root, name)
    assert not root.exists()


def test_guided_rejects_slug_and_customer_collisions(root):
    guided(root)
    with pytest.raises(FileExistsError):
        ws.start_workspace(root, 'Café & Friends', 'Summer--Campaigns')
    with pytest.raises(ValueError):
        ws.start_workspace(root, 'Cafe Friends', 'Other')


@pytest.mark.parametrize('workspace_id', ['../escape', 'a/b/c', '/a/b', 'a/..', 'A/b', 'a\\b', 'con/a'])
def test_guided_ids_root_confined(root, workspace_id):
    assert 'error' in ws.check_workspace(root, workspace_id)
    assert not ws.open_workspace(root, workspace_id)['launch_requested']
    assert not root.exists()


@pytest.mark.parametrize('name', ['.env', '.adcode-workspace.json', 'summer-campaigns_template.json', 'state.json'])
def test_guided_rejects_linked_files(root, tmp_path, name):
    result, target = guided(root)
    fill_env(target)
    outside = tmp_path / 'outside.json'
    outside.write_text('private-outside-data')
    path = target / name
    if path.exists():
        path.unlink()
    symlink_or_skip(path, outside, directory=False)
    checked = ws.check_workspace(root, result['workspace_id'])
    assert 'error' in checked
    assert 'private-outside-data' not in json.dumps(checked)


def test_guided_legacy_upgrade_read_only(root):
    created = create(root)
    target = Path(created['workspace'])
    before = (target / 'spring-sale_template.json').read_bytes()
    assert ws.check_workspace(root, 'customer/spring-sale')['status'] == 'upgrade_required'
    assert (target / 'spring-sale_template.json').read_bytes() == before
    assert not (target / '.env').exists()


def test_guided_check_lock(root):
    result, target = guided(root)
    fill_env(target)
    (target / '.adcode-setup.lock').mkdir()
    assert 'error' in ws.check_workspace(root, result['workspace_id'])
    assert json.loads((target / 'summer-campaigns_template.json').read_text())['account_id'] == ''


@pytest.mark.parametrize('failure', [False, True])
def test_guided_opener_safe_argv(root, failure):
    result, target = guided(root)
    with patch.object(ws.sys, 'platform', 'darwin'), patch.object(ws.subprocess, 'run') as launch:
        if failure:
            launch.side_effect = ws.subprocess.CalledProcessError(1, ['secret-command'], stderr='private-secret')
        opened = ws.open_workspace(root, result['workspace_id'])
        launch.assert_called_once_with(['/usr/bin/open', '-a', 'Cursor', str(target)],
                                       shell=False, capture_output=True, timeout=8, check=True)
    assert opened['launch_requested'] is not failure
    assert not opened['connection_active']
    assert 'private-secret' not in json.dumps(opened)


def test_guided_linux_opener_timeout_is_private(root):
    result, target = guided(root)
    with patch.object(ws.sys, 'platform', 'linux'), patch.object(ws.shutil, 'which', return_value='/trusted path/cursor'), patch.object(ws.subprocess, 'run') as launch:
        launch.side_effect = ws.subprocess.TimeoutExpired('private-command', 8, output='private-secret')
        opened = ws.open_workspace(root, result['workspace_id'])
        launch.assert_called_once_with(['/trusted path/cursor', str(target)],
                                       shell=False, capture_output=True, timeout=8, check=True)
    assert not opened['launch_requested']
    assert 'private-secret' not in json.dumps(opened)


def test_guided_check_rejects_linked_customer(root, tmp_path):
    result, target = guided(root)
    outside = tmp_path / 'moved-customer'
    target.parent.rename(outside)
    symlink_or_skip(target.parent, outside)
    assert 'error' in ws.check_workspace(root, result['workspace_id'])
    with patch.object(ws.subprocess, 'run') as launch:
        assert not ws.open_workspace(root, result['workspace_id'])['launch_requested']
        launch.assert_not_called()


@pytest.mark.parametrize('change', ['missing', 'malformed', 'disabled', 'env', 'url', 'args', 'command'])
def test_guided_connection_config_must_match(root, change):
    result, target = guided(root)
    config_path = target / '.cursor' / 'mcp.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    entry = config['mcpServers']['adcode']
    if change == 'missing':
        config_path.unlink()
    elif change == 'malformed':
        config_path.write_text('private-config-not-json', encoding='utf-8')
    else:
        if change == 'disabled':
            entry['disabled'] = True
        elif change == 'env':
            entry['env'] = {'FB_ACCESS_TOKEN': 'private-config-token'}
        elif change == 'url':
            entry['url'] = 'https://example.invalid/private-config-token'
        elif change == 'args':
            entry['args'].remove('--onboarding')
        else:
            entry['command'] = 'missing-interpreter'
        config_path.write_text(json.dumps(config), encoding='utf-8')
    checked = ws.check_workspace(root, result['workspace_id'])
    assert checked['status'] == 'needs_connection_setup'
    assert not checked['config_prepared']
    assert checked['connection_active'] is None
    assert checked['connection_status'] == 'not_verified'
    assert not checked['provider_connection_verified']
    assert 'private-config' not in json.dumps(checked)


def test_guided_explicit_enabled_config_still_prepared(root):
    result, target = guided(root)
    path = target / '.cursor' / 'mcp.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    config['mcpServers']['adcode']['disabled'] = False
    path.write_text(json.dumps(config), encoding='utf-8')
    checked = ws.check_workspace(root, result['workspace_id'])
    assert checked['config_prepared']
    assert checked['connection_active'] is None
    assert checked['connection_status'] == 'not_verified'


def test_guided_atomic_binding_failure_preserves_draft(root):
    result, target = guided(root)
    fill_env(target)
    template = target / 'summer-campaigns_template.json'
    before = template.read_bytes()
    with patch('src.local_setup.os.replace', side_effect=OSError('private-error-value')):
        checked = ws.check_workspace(root, result['workspace_id'])
    assert 'error' in checked
    assert 'private-error-value' not in json.dumps(checked)
    assert template.read_bytes() == before
    assert not (target / '.adcode-setup.lock').exists()
    assert not list(target.glob('.adcode-*tmp*'))
