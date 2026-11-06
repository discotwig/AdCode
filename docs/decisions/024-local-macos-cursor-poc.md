# ADR-024: Local macOS / Cursor POC with Restricted Project MCP

**Date:** 2026-11-05  
**Status:** Accepted for POC; macOS hardware validation pending  
**Builds on:** ADR-014, ADR-020, ADR-021, ADR-022  
**Related:** ADR-004, ADR-016, ADR-018, ADR-019

## Context

A non-developer owner should be able to install AdCode locally, create a private campaign workspace, and ask Cursor to edit visible JSON without cloning a code repository or granting an agent live advertising write access. Credentials must not pass through chat, a hosted bootstrap, installer inputs, or MCP configuration. The existing operator workflow must remain compatible without implying that its approval controls have become a production governance platform.

## Decision

1. Ship a source-based macOS installation workflow, run as the normal user. Install runtime-allowlisted source and release-specific virtualenvs under `~/Library/Application Support/AdCode`; use uv 0.13.7, verified checksums for downloaded uv archives, managed Python 3.13, and a universal hashed runtime dependency lock. Reuse of an existing exact-version uv trusts that local executable. No system Python modification or dependency downloading at MCP startup.
2. Register only a credential-free global **AdCode-Setup** bootstrap in Cursor. Expose four global tools: `create_workspace`, `list_workspaces`, `check_workspace`, and `open_workspace`. Creation accepts friendly `customer_name` and optional `workspace_name` (default `Campaigns`), never account IDs, credentials, or arbitrary destination paths. Check/open select a known `workspace_id`; checking privately reads local settings, while opening only requests a Cursor window. No global tool contacts providers. Merge configuration privately with backups; fail on conflicts rather than overwrite unrelated settings.
3. Default to `~/AdCode Workspaces`, outside Documents to avoid common iCloud Documents synchronization. This is not a general backup/sync exclusion guarantee. Scaffold an intentionally unfinished draft (`account_id: ""`, `campaigns: []`), not a schema-valid campaign or fabricated provider IDs/state. Include a blank private `.env`, `.env.example`, guided workspace manifest, project MCP config, rules/ignore files, and an optional local Configure command. Never overwrite an existing workspace.
4. Make owner-only manual `.env` editing the primary setup path for the account, Meta app ID/secret/token, Anthropic key, whole-currency-unit integer budget cap, and supported uppercase ISO currency code. Never ask an agent to read this file. `check_workspace` reports safe local statuses and, after valid settings, atomically binds only an untouched empty draft's account; refuse mismatches rather than retargeting. Configure via Tk/secure TTY remains an optional helper for unbound guided drafts and bound workspaces, with atomic private `.env` writes and no secret-bearing backups. For an unbound draft it collects the account locally; the subsequent local check binds the untouched empty draft. Account-conflict guards remain in force; this does not permit retargeting. Disable dotenv interpolation. No local setup check authenticates providers.
5. Explicitly configure generated projects with `--access-mode planning --onboarding`; refresh local keys/settings on subsequent stack-tool calls without a restart. `inspect` permits only `show_stack`/`show_state`; `planning` adds `plan_stack`/`document_stack`. Apply the allowlist to both discovery and dispatch, including guessed calls. Restricted modes clear inherited provider/settings environment and require fixed stack configuration. Reject credential/template/state account mismatches and in-session account retargeting.
6. Preserve all original nine operator tools for legacy no-flag invocations and explicit `operator` mode. The installer never enables this mode automatically; changing a generated project's configuration requires deliberate operator action. Local JSON authoring remains a Cursor file-editing workflow, not an extra MCP endpoint. Provider state stays engine-managed.
7. Retain previous releases and roll the active pointer back if Cursor registration fails. Pin existing projects to their original source release and virtualenv. Do not automatically migrate projects or delete old releases. A local check of an older workspace without guided metadata returns `upgrade_required` and leaves existing files unchanged.

The distribution handoff is `scripts/build_local_bundle.py` → `dist/AdCode-Local-POC.zip`, with a root `Install AdCode.command` and a runtime allowlist. See the validation record for automated checks, including real guided stdio tests. Rebuild and verify archive integrity, public-file allowlist, permissions, and checksum after documentation changes. The checked-in source installer is `scripts/install_macos.command`.

## Boundaries and consequences

- Opening the returned workspace asks Cursor to load its project MCP; prepared configuration or a launch request does not prove the connection is active. Local `ready` settings are not provider verification. Generated planning `--onboarding` sessions refresh saved local settings without restarting; older pinned projects keep their original behavior. No code repository checkout is required on the recipient's Mac.
- Preserve Cursor permissions and approval prompts; never bypass them, automatically loosen access mode, or infer advertising approval from onboarding. After the local settings check, ask what the customer is promoting, their budget, and dates; keep new campaigns `PAUSED`.
- Planning/review can send campaign content to Anthropic and incur charges; Cursor's own configured providers can also process campaign data. Local credential storage does not mean all campaign processing is local.
- Planning mode has no live Meta access, MCP template/state mutation, or arbitrary-file Excel tool. It cannot attest to live Facebook state.
- Server tool restrictions do not sandbox Cursor terminal/file tools or the local user. Ignore files and rules reduce mistakes, not adversarial access. A Meta account may be real, not a sandbox; a declared budget cap is not a provider billing limit.
- Durable plans, approval-to-plan binding, production audit records, RBAC, and a platform sandbox are not implemented by this POC. Legacy operator apply/remediation keeps its original guards; human plan review and separate delete confirmation remain necessary.
- The ZIP is not a signed/notarized DMG. Normal macOS user approval may be required; do not bypass Gatekeeper/quarantine. No payment/licensing service, automatic update service, hosted secret store, or Meta OAuth flow is included.
- Global Cursor configuration backups may contain unrelated existing secrets and must remain private. Retiring hosted/local connections requires revocation and cleanup of all copies/backups; deleting files cannot guarantee physical erasure, so rotate exposed keys.

## Validation status

Full Windows `python -m pytest -q`: **563 passed, 25 skipped**. Clean Linux Python **3.13.18**, fresh hash-locked public-bundle runtime: nine selected local/MCP files including guided access and real guided stdio, **249 passed, no skips**, with no provider calls. Linux ran in isolated non-root Docker with read-only public inputs only; container and temporary-tree removal were confirmed. Prior Windows **555/25** and Linux **184** results are historical and separate in the [validation record](../local-poc-validation.md). No Mac is available: installation, Gatekeeper approval, architecture-specific execution, Tk fallback, and Cursor approval/discovery UX remain **unverified**. Automated Linux checks do not establish a successful Mac installation.

## References

- [Local operator runbook](../local-operator.md)
- [Security policy](../../SECURITY.md)
- `src/local_setup.py`, `src/bootstrap_server.py`, `src/services/workspace.py`
- `scripts/install_macos.command`, `requirements-local.in`, `requirements-local.lock`
