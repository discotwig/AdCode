# Security Policy

AdCode can operate on live advertising accounts. Treat credentials, state, and apply workflows as sensitive operational infrastructure.

## Supported Versions

AdCode is currently alpha software. Security fixes are made on `main`.

## Reporting A Vulnerability

Please report vulnerabilities privately to the repository owner before opening a public issue. Include:

- affected file or workflow;
- reproduction steps;
- potential impact;
- whether live ad accounts, credentials, or state files are involved.

## Credential Boundaries

Meta credentials belong in stack-local `.env` files:

```text
~/AdCode Workspaces/<customer>/<stack-name>/.env   # macOS/Cursor POC
customers/<slug>/<stack-name>/.env                # legacy repository workflow
```

The POC root is outside Documents to avoid common iCloud Documents synchronization; inspect other sync/backup settings yourself. Credentials remain local by design, but this does not guarantee that campaign data stays local.

Guided workspaces create a blank private `.env`. **Manual editing by the owner is the primary setup path**: enter the actual `FB_ACCOUNT_ID`, Meta app ID/secret/token, Anthropic key, budget cap in **whole currency units, not cents**, and a supported uppercase ISO currency code locally. Never authorize agent filesystem/terminal reads of `.env`. `Configure AdCode.command` is an optional Tk/secure-TTY helper for unbound guided drafts and bound workspaces; it collects an unbound draft's account locally, preserves account-conflict guards, and does not permit retargeting; its writes are atomic and private without secret-bearing `.env` backups. Dotenv parsing disables interpolation to preserve literal secret text.

Global `check_workspace` privately checks settings and returns statuses, never key values. Only after valid settings can it atomically bind an untouched empty draft (`account_id: ""`, `campaigns: []`) to the local account. Conflicts or an altered unbound draft fail closed. This is not provider authentication. Generated planning `--onboarding` projects refresh local settings on subsequent stack-tool calls without restarting; legacy projects retain their original restart requirements and account retargeting remains prohibited.

Never put runtime credentials in MCP JSON, MCP/bootstrap arguments, chats, templates, installer inputs, telemetry, or command-line arguments. Do not commit `.env` files. The repository and generated workspace ignore files exclude them; setup refuses tracked/unignored `.env` inside a Git tree. Ignore rules are not encryption or access control.

The optional email mailroom in `integrations/email_mailroom/` does not need Facebook credentials and should not be given them. It only needs:

- `WEBHOOK_SECRET`
- `OPERATOR_EMAIL`
- `BOT_EMAIL`
- `RESEND_API_KEY`
- `ANTHROPIC_API_KEY`

## State Files

`state.json` contains Facebook object IDs and last-pushed params, not access tokens. Treat it, templates, and review packets as private operational/customer data. If using Git history, commit template and state together only in an appropriately private repository—not this public project. The POC does not initialize state or a Git audit trail when creating a workspace.

Provider state and assigned IDs are engine-managed; do not have an agent invent IDs or hand-author tracking state. In operator mode, prefer controlled state operations such as `import_resource` for supported live objects. Saved state is not live Facebook data; a live comparison requires provider access, which the restricted POC does not expose.

## Execution Safety

AdCode's safety model depends on:

- running one MCP server per active stack;
- reviewing `plan_stack` before `apply_stack`;
- requiring explicit confirmation for deletes;
- keeping Meta credentials local to the operator machine;
- committing template and state changes together.

Use `import_resource` for controlled adoption of supported live resources into a stack in operator mode. Use `draft_stack` only with public-safe or client-approved Excel briefs; it is unavailable in restricted modes.

### Local POC access boundaries

- Global **AdCode-Setup** exposes only `create_workspace`, `list_workspaces`, `check_workspace`, and `open_workspace`. Creation accepts friendly `customer_name` and optional `workspace_name`, never account IDs, secrets, or arbitrary roots. Check/open accept a known `workspace_id`. Checking privately reads local settings and can bind the account; no global tool contacts providers or returns credentials.
- `prepared`/`config_prepared` mean local files/recognized launch configuration only. A launch request or `ready` settings status does not establish that MCP is active or provider access is verified; local checks report the connection as not verified.
- Generated projects explicitly request `--access-mode planning`: `show_stack`, `show_state`, `plan_stack`, and `document_stack`. `inspect` permits only the first two and does not load `.env`. Neither mode exposes live Meta reads/writes, import/drift/remediation, or arbitrary-file Excel tools; planning/review does not mutate template/state through MCP.
- The access allowlist is enforced at discovery and dispatch, including guessed calls. Restricted modes clear inherited provider/settings environment values and require a fixed stack config. Credential/template account conflicts, in-session template account changes, and mismatched state account IDs fail closed.
- No-flag invocations and explicit `operator` preserve the original nine-tool surface for compatibility. Removing the flag enables those capabilities; the installer does not do this automatically. Live access requires deliberate owner configuration and the original operator precautions.
- **Durable plan records and approval-to-plan binding are not implemented.** Chat approval and a review packet are not production authorization/audit controls. Operator apply/remediation retains its original guards, not a new POC approval system.
- The required cap is a declared-budget guard, not a Meta spending/billing limit. A real Meta account can incur real charges; it may not be a sandbox.

Cursor's own file tools, terminal, other MCP servers, and local processes are outside AdCode's MCP boundary. `.cursorignore`, workspace rules, and POSIX private permissions reduce accidental exposure but do not provide a platform sandbox or protect against a compromised local user. Keep Cursor permissions and tool approval prompts enabled; never bypass them, infer spending approval from setup, or automatically loosen access mode. Never authorize terminal/agent reads of credential files.

### Data processing and costs

`plan_stack` and `document_stack` may send campaign content to Anthropic. Cursor's configured providers can also process campaign data. Obtain approval before using sensitive client content and review provider retention/privacy settings and API costs. Keeping API keys in local `.env` does not make planning offline or prevent campaign data from leaving the machine.

### Installer and configuration trust

The macOS installer runs as the normal user under `~/Library/Application Support/AdCode`. It uses uv 0.13.7, verifies downloaded uv archives against pinned SHA-256 values, installs managed Python 3.13, and requires hash-locked runtime dependencies. An existing exact-version uv is trusted locally. A checksum check does not sign/authenticate the source ZIP or establish that dependencies are vulnerability-free.

This is not a signed/notarized app or DMG. Use only trusted source/bundle downloads and normal macOS user approval if Gatekeeper prompts. Never disable Gatekeeper or remove quarantine as an installation step. There is no payment/licensing service, automatic update service, or Meta OAuth flow.

Global Cursor configuration is merged, not blindly replaced. Pre-change backups have private permissions; conflicting AdCode-Setup entries and malformed configuration fail rather than overwrite. Those backups may contain unrelated existing server secrets and must not be shared. AdCode runtime credentials never belong in this configuration.

Updates retain old releases and can restore the active pointer if registration fails. Existing projects remain pinned to their original release and virtualenv; there is no automatic migration or old-release deletion. Local checks of older workspaces without guided metadata return `upgrade_required` and leave their files unchanged. Retained releases/backups require local lifecycle management. See the [local operator runbook](docs/local-operator.md).

### Retirement and credential exposure

Stop retired hosted/local connections, revoke access, and remove all secret/private-data copies, including backups, archives, configuration snapshots, logs, and retained storage where possible. Review synchronization and backup destinations, not just the active file. Physical erasure cannot be guaranteed on SSDs, cloud storage, or retained backups; rotate exposed keys even after cleanup. Keep hostnames, addresses, actual account IDs, customer data, and cleanup inventories out of public documentation and issues.

Do not add hosted apply behavior without a clear credential, state, approval, and audit design. The local POC is not production-audited. No Mac is available: actual macOS hardware validation remains unverified. Automated results are full Windows `python -m pytest -q`: **563 passed, 25 skipped**, and clean Linux Python **3.13.18** with a fresh hash-locked bundle runtime: **249 passed, no skips** across nine selected local/MCP files including guided access and real guided stdio, without provider calls. The non-root isolated Docker run used read-only public inputs only, and container/temporary-tree cleanup was confirmed. These are not actual Cursor UI/approval or provider-authentication checks. Rebuild and verify archive integrity, public-file allowlist, permissions, and checksum after documentation changes. Earlier Windows 555/25 and Linux 184 results remain historical. See the [validation record](docs/local-poc-validation.md).
