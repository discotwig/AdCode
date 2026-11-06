# Local distribution POC — validation record

## Evidence scope and current status

Current guided-onboarding validation: full Windows `python -m pytest -q` — **563 passed, 25 skipped**; selected Linux local/MCP tests — **249 passed, no skips**. No provider calls were made. Prior Windows **555 passed, 25 skipped** and Linux **184 passed** results below remain historical and separate.

Current source review confirms friendly `customer_name`/optional `workspace_name`, four global create/list/check/open tools, a blank private `.env` with manual owner editing primary, an unfinished draft (`account_id: ""`, `campaigns: []`), local-check account binding, and planning `--onboarding` settings refresh without restart. Source review is not execution evidence. The optional Configure helper also supports an unbound guided draft by collecting the account locally; `check_workspace` still performs draft binding after valid settings. This does not allow account retargeting or replace manual editing as the primary onboarding path.

### Current guided-onboarding automated validation

- **Windows:** full `python -m pytest -q` — **563 passed, 25 skipped**.
- **Linux:** clean Python **3.13.18**, fresh hash-locked public-bundle runtime; nine selected test files, including `test_guided_access`, — **249 passed, no skips**. This is the selected local/MCP suite, not a full Linux repository-suite result.
- The Linux run used isolated, non-root Docker with read-only inputs. Only the public bundle, selected tests, and public fixture/build script were copied; container and temporary-tree removal were confirmed afterward. No private host identifiers or cleanup inventories are included here.
- Real guided stdio tests were included; no provider calls were made. Automated coverage is not a visual Cursor UI/approval test or provider authentication.
- Rebuild and verify archive integrity, public-file allowlist, permissions, and checksum after documentation changes.
- Actual macOS installation, Gatekeeper/Finder behavior, Cursor discovery and UI approval behavior remain **unverified**; no Mac is available.

## Historical automated checks

### Windows development environment — historical

- Command: `python -m pytest -q`
- Prior result: **555 passed, 25 skipped**; not rerun for current guided onboarding.
- Includes the existing engine/email tests and new local workspace, setup, installer, bundle, access-mode and stdio tests.
- Skips include provider integration and POSIX/symlink cases that cannot run on this host. No real provider calls were made.
- An actual configured local Cursor entry was exercised through the MCP Python SDK: bootstrap discovery, fixed-stack planning discovery, local stack inspection, and a rejected apply call. This validates the registered command, not a visual Cursor UI test.

### Clean Linux Python 3.13 runtime — historical

A disposable, non-root container installed the public bundle into a fresh virtualenv. No customer files, real `.env`, Git history, provider credentials, host sockets or application ports were supplied. The container and temporary source files were removed afterward; production services were not modified.

Runtime installation:

```sh
uv venv --python /usr/local/bin/python /tmp/venv
uv pip sync --python /tmp/venv/bin/python --require-hashes --only-binary :all: /workspace/requirements-local.lock
```

- Python: **3.13.18**; MCP SDK: **1.30.0**.
- **55 runtime packages** installed from the universal hash lock, without system site packages.
- Test-only pytest dependencies were installed separately; they are not in the distribution runtime lock.
- Ran `test_local_access`, `test_workspace`, `test_bootstrap_server`, `test_local_setup`, `test_macos_installer`, `test_local_bundle`, `test_local_stdio`, and the existing `test_mcp_server` with the cache plugin disabled on the read-only public source mount.
- Result: **184 passed**, including the POSIX permission/symlink/publication cases skipped on Windows.
- The test runtime uses an executable temporary filesystem because Python native-extension wheels cannot load from a no-exec mount. This does not change deployed service settings.

### Bundle and launch chain — historical

- Build: `python scripts/build_local_bundle.py`.
- Artifact: `dist/AdCode-Local-POC.zip` (generated and Git-ignored).
- ZIP integrity, explicit public-file allowlist, absence of private fixture markers, executable command-file permissions and refusal to overwrite existing output are tested.
- Public text is normalized to LF. Clean Linux testing caught and fixed an earlier Windows CRLF packaging issue; the regression test deliberately supplies a CRLF installer.
- Runtime startup does not download dependencies. Bootstrap is tested from an arbitrary working directory.
- Real stdio test: initialize bootstrap, create a private workspace, read its project MCP configuration, initialize that stack, list the four planning tools, inspect local configuration/state, and reject guessed apply/import calls.
- The earlier scaffold test used a `PAUSED` starter with no ad sets, fabricated Facebook object IDs, credentials, or state file. That is historical behavior, not the current guided starter: current creation produces an unfinished empty draft and blank private `.env`. Current guided stdio tests are included in the fresh results above.
- Setup tests cover private atomic writes, account binding, literal secret preservation, Git exclusions, local prompt behavior, safe Cursor JSON merges/backups, conflicts and rollback.
- Both pinned macOS uv archive SHA-256 values were checked against the official uv 0.13.7 release checksum assets. This verifies the expected download hashes, not execution of the macOS binaries on a Mac.

## Still requires an actual Mac

Linux tests and shell syntax checks are **not** a substitute for the following acceptance test. No Mac was accessible during this implementation.

- [ ] On Apple Silicon and Intel, extract the ZIP and open `Install AdCode.command` through normal macOS approval. Do not bypass Gatekeeper or remove quarantine protections.
- [ ] Verify managed Python download and binary wheel installation, including paths containing spaces.
- [ ] Restart Cursor and confirm the global AdCode-Setup connection is active.
- [ ] Discover all four global tools. Create using friendly `customer_name` and optional `workspace_name`; confirm the empty unfinished draft and blank private `.env`, then use `open_workspace` for the known workspace. Independently confirm the project connection is active and planning-only; a launch request/prepared configuration is not evidence.
- [ ] Manually edit `.env` privately, then use `check_workspace`; verify safe statuses and account binding only after valid settings. Do not expose values to chat or agent tools. Confirm this does not claim provider verification.
- [ ] Without restarting the generated planning `--onboarding` MCP, confirm local settings refresh and inspection work, the empty brief prompts for promotion/budget/dates, and mutation tools remain unavailable. Keep Cursor permissions/approval prompts enabled; do not bypass them.
- [ ] Optionally run Configure AdCode.command on an unbound guided draft and an already-bound workspace; verify local account entry, Tk or secure Terminal fallback without echoing credentials, and rejection of conflicting accounts. The helper saves settings; use `check_workspace` to bind an untouched empty draft.
- [ ] After explicitly consenting to API costs/data processing, test a plan/review packet against approved provider credentials. This was not done automatically.
- [ ] Re-run installation to check retained project pins, unrelated Cursor settings and rollback behavior on macOS. Check that older workspaces without guided metadata report `upgrade_required` and remain unchanged, rather than being silently migrated.

This is an unsigned source-installer POC, not a signed/notarized application, a validated commercial distribution, an OS sandbox, or an approval-bound execution platform. No live advertising changes, credential rotation or provider validation were performed.
