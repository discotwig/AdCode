# Local macOS / Cursor POC

This is a single-owner, bring-your-own-credentials proof of concept, not a production governance platform. Cursor edits visible local campaign JSON; the project MCP starts in server-enforced **planning** mode. No hosted connection, tunnel, code checkout on the recipient's Mac, or live Meta write access is needed for the normal POC workflow.

## Install on a Mac

1. Install Cursor and obtain a trusted AdCode source ZIP or the purpose-built local POC ZIP. Review its provenance before running code.
2. Extract the ZIP locally. In a source ZIP, double-click `scripts/install_macos.command`. The purpose-built bundle is `dist/AdCode-Local-POC.zip`, with `Install AdCode.command` at its root. See the [validation record](local-poc-validation.md) for automated checks. Actual Mac installation still needs the hardware smoke test below.
3. Run as your normal user, never with `sudo`. macOS may require explicit approval through Finder or Privacy & Security for a downloaded unsigned command. Approve only a trusted download using the normal macOS UI; do not disable Gatekeeper or remove quarantine protections. If approval is unavailable, stop and ask the distributor.
4. Allow installation downloads, then restart Cursor to load the global **AdCode-Setup** MCP server.

The installer supports Apple Silicon and Intel macOS. It installs under `~/Library/Application Support/AdCode`, not into system Python. It uses uv **0.13.7**: an existing exact-version uv is reused; otherwise the official architecture-specific archive is downloaded over HTTPS and checked against a pinned SHA-256 before execution. uv installs managed Python **3.13** and a release-specific virtual environment. Runtime dependencies come from the universal Python 3.13 `requirements-local.lock`, using hashes and binary distributions only. These checks do not authenticate the source ZIP itself.

The installed runtime is allowlisted: Python files under `src/`, JSON schemas, policy JSON/YAML, and the runtime lock. It does not recursively copy the repository, customer directories, private documents, tests, or email integration. The bundle builder must enforce its own distribution allowlist as well. MCP startup invokes the installed virtualenv interpreter directly; it does not download dependencies on every connection.

Installation needs network access to the applicable GitHub/managed-Python/package download hosts and uses local disk for releases, Python, and cache. This is a source-based ZIP, not a signed/notarized app or DMG. There is no payment/licensing service, automatic update service, or Meta OAuth onboarding.

## Create and open a workspace

Ask Cursor to use **AdCode-Setup → `create_workspace`**, providing only:

- `customer_name`: a friendly customer name;
- `workspace_name`: an optional friendly workspace name, defaulting to `Campaigns`.

Do not ask the customer for slugs, filesystem roots, MCP setup, account IDs, or secrets in chat. AdCode derives safe directory names internally; path-like, reserved, or colliding names are refused. Enter the actual account identifier later, privately in `.env`, rather than inventing one for the draft.

The default local root is **`~/AdCode Workspaces`**, deliberately outside Documents to avoid common iCloud Documents synchronization. It is not a guarantee against other backup/sync software: check your own settings. The root is host configuration, not an arbitrary per-tool destination. The four global tools are `create_workspace`, `list_workspaces`, `check_workspace`, and `open_workspace`. Creation takes friendly names; check/open take a known `workspace_id` from the returned metadata or list, not an arbitrary path. Listing reads non-secret workspace metadata, checking privately reads local settings and can bind a new draft's account, and opening requests a Cursor window. None contacts providers.

Ask `open_workspace` to open the **returned workspace directory** in Cursor, or open it yourself—not the installer directory or the whole workspace root. A launch request is not proof that its MCP connection is active. It contains:

```text
<customer>/<stack-name>/
  <stack-name>_template.json
  .env
  .env.example
  .adcode-workspace.json
  .gitignore
  .cursorignore
  .cursor/mcp.json
  .cursor/rules/adcode.mdc
  Configure AdCode.command
  README.md
```

The starter is deliberately unfinished: `{"account_id": "", "campaigns": []}`. It is not yet a schema-valid campaign brief, contains no fabricated provider IDs or `state.json`, and has created nothing on Meta. Existing workspaces are never overwritten. Project MCP configuration contains interpreter/source paths, the fixed template path, `--access-mode planning --onboarding`, and no runtime credentials. The blank private `.env` contains setting names but no credentials.

`prepared` and `config_prepared` describe local files and recognized launch configuration only. They do not establish an active MCP connection (`connection_status: not_verified`) or a provider connection (`provider_connection_verified: false`). Even a local check returning `ready` means settings are entered, not authenticated.

## Configure credentials locally

**Open `.env` yourself in your editor and fill it in privately. Manual editing is the primary setup method.** Do not ask an agent to read, edit, or display this file through filesystem or terminal tools. Enter your own:

- Meta ad account (`FB_ACCOUNT_ID`): digits or `act_` followed by digits;

- Meta app ID (`FB_APP_ID`);
- Meta app secret (`FB_APP_SECRET`);
- Meta access token (`FB_ACCESS_TOKEN`);
- Anthropic API key (`ANTHROPIC_API_KEY`);
- required `ACCOUNT_BUDGET_CAP`: a nonnegative integer in **whole currency units**, e.g. `500` means 500 dollars with `USD`, **not 500 cents**; zero is allowed;
- required `CURRENCY`: an uppercase three-letter ISO 4217 code, e.g. `USD`.

**`Configure AdCode.command` is an optional local helper**, not a required onboarding step. It uses a Tk form if available, otherwise a real local TTY with hidden credential prompts. Managed Python may lack Tk; the terminal fallback is expected. It refuses non-TTY or insecure echoed credential input. Blank inputs keep existing settings. Never supply secrets as command-line arguments, MCP arguments, chat messages, installer inputs, telemetry, templates, or MCP JSON.

After saving `.env`, ask global `check_workspace` to check the known workspace. It returns safe per-setting statuses (`missing`, `placeholder`, `invalid`, `entered`), never credential values. Only after all required local settings pass does it atomically bind the untouched empty draft to the normalized `FB_ACCOUNT_ID`. It refuses conflicting accounts, incompatible state, or a modified unbound draft rather than silently retargeting it. This local validation does not authenticate credentials with Meta or Anthropic.

The optional Configure helper supports both unbound guided drafts and already-bound templates. For an unbound draft it collects the account locally and saves settings; then use `check_workspace` to bind the untouched empty draft after valid settings. For a bound template it requires a matching account. It does not authorize account changes. The helper writes stack-local `.env` atomically with private POSIX permissions, without secret-bearing `.env` backups. When inside a Git tree, `.env` must be untracked and ignored. Existing comments, unknown settings, and literal credential text are preserved. `.env` parsing uses `interpolate=False`; host environment substitutions must not rewrite secrets.

Generated **planning `--onboarding`** projects refresh local keys/settings on subsequent stack-tool calls, so saving settings and completing the local check does **not** require a project MCP restart. This does not permit changing a bound account during a session. Older projects without `--onboarding` retain their original behavior and may require a restart after configuration. Neither saving nor checking verifies provider access.

For local troubleshooting, the installed helper can report configured/missing key names without values:

```sh
~/Library/"Application Support"/AdCode/bin/adcode-setup status --workspace /absolute/path/to/stack
```

Replace `/absolute/path/to/stack` with your stack's actual path, quoting it if it contains spaces. Alternatively, use the stable `Configure AdCode.command` in the installation's `bin/` directory; it asks for the existing stack's absolute path. Do not paste `.env` contents into support requests.

## Author and review

1. After the local check, tell Cursor what you are promoting, your budget, and your dates. Ask it to edit the local `<stack-name>_template.json`, keeping new objects `PAUSED`. An empty draft remains `brief_incomplete`; settings alone do not make it ready to plan.
2. Inspect the actual JSON yourself. Supply real required business identifiers locally, not invented provider IDs. The schema, lint, and policy checks are feedback, not a substitute for review.
3. Consent to sending campaign data to Anthropic before requesting `plan_stack` or `document_stack`. These may incur API charges. Cursor's configured model/service may also process campaign content and incur costs under its own settings.
4. Review the changeset, budget information, and Campaign Review Packet. Edit and plan again as needed.

The owner can inspect files directly; desired state remains visible JSON. Provider tracking (`state.json` and assigned `fb_id` correlation) is engine-managed, not agent-authored. No state file is created merely by scaffolding. Saved state is **not** current Facebook data. Restricted modes cannot answer live Meta questions; do not present a local state read as a live comparison.

## Enforced MCP access modes

| Invocation | Exposed and callable tools | Boundary |
| --- | --- | --- |
| `--access-mode inspect` | `show_stack`, `show_state` | Local metadata/state only; does not load stack `.env`. |
| `--access-mode planning` | Inspect tools plus `plan_stack`, `document_stack` | No template/state writes through MCP, live Meta reads/writes, import, drift, remediation, or arbitrary-file Excel tool. Planning/review may call Anthropic. |
| `--access-mode operator`, or legacy invocation without the flag | Original nine tools: `show_stack`, `show_state`, `plan_stack`, `document_stack`, `draft_stack`, `apply_stack`, `drift_stack`, `remediate_drift`, `import_resource` | Legacy operator capabilities and guards, including live Meta operations and local writes. |

The same allowlist gates discovery **and dispatch**, including guessed calls to hidden tools. Restricted modes require a fixed `--config` template, clear inherited provider/settings environment values, and bind tools to that stack. Planning loads only its local `.env`; generated `--onboarding` projects refresh settings on subsequent stack-tool calls. Account mismatches between configured credentials and template fail closed. Template account changes during a session and mismatched state account IDs are refused rather than silently retargeting operations.

The installer never automatically enables operator mode. Enabling live operations requires the owner to deliberately edit project MCP configuration, then restart the connection. Removing the access-mode flag also restores legacy operator behavior; it is **not** a safe way to fix a connection problem. Do not ask the agent to loosen the mode.

Review a plan before any separately authorized operator apply; deletions require their own confirmation. **Durable plan records and approval-to-plan binding are not implemented.** Legacy operator apply/remediation retains its existing guards; a chat approval or review packet is not a cryptographically bound authorization or production audit record. The budget cap is a declared-spend guard, not a Meta billing limit or guarantee against real charges. A Meta account is not necessarily a sandbox, even for a POC.

These restrictions apply to the AdCode MCP server, not all Cursor capabilities. Cursor file editing, terminal tools, other MCP servers, and the local user can bypass file-level conventions. `.cursorignore`, rules, permissions, and `.gitignore` reduce mistakes; they are not encryption, a platform sandbox, or protection from a compromised local user/process. Keep Cursor permissions and approval prompts enabled; never bypass them, automatically change access mode, or infer spending approval from setup. Do not authorize agent reads of `.env`.

## Updates, rollback, and removal

Re-running the installer stages a new versioned release and virtualenv before activation. It retains old releases, updates `current`, and records the formerly active release as `previous`. If Cursor registration fails during publication, it restores the old `current` pointer. Completed releases remain available for inspection even on publication failure.

Global `~/.cursor/mcp.json` is merged, preserving unrelated entries; a pre-change copy is saved privately as `mcp.json.adcode-backup-<unique-id>` when needed. An identical AdCode-Setup entry is a no-op; conflicting entries, malformed JSON, duplicate keys, or conflicting launchers stop installation rather than overwriting them. Backups can contain other servers' existing secrets—keep them private. AdCode's own runtime credentials must never be added there.

**Existing projects remain pinned to their original release and its virtualenv**, including their Configure command. Updating the global bootstrap does not migrate those projects. `check_workspace` reports `upgrade_required` for older workspaces without the guided manifest and leaves their files unchanged; this status is not an automatic upgrade. There is currently no automatic project migration or deletion of old releases. Keep all referenced releases and managed Python in place. `previous` is an operator recovery reference, not a one-click rollback UI; inspect paths/configuration locally before manually changing anything, and restart Cursor after changes. Installer pointer rollback does not undo campaign operations.

To retire an installation, stop its MCP connections, remove only its global AdCode-Setup entry and relevant project connections, and inspect release references before deleting local files. Preserve unrelated Cursor configuration and any campaign records you need. Revoke credentials no longer needed and review local backups and synchronization destinations.

If retiring a previous hosted connection, stop it, revoke its access, and remove **all** credential/private-data copies, including configuration backups, archives, logs, and snapshots where possible. File deletion cannot guarantee physical erasure on SSDs, cloud storage, or retained backups; rotate exposed keys regardless. Do not publish hostnames, network addresses, account IDs, or private cleanup inventories.

## Maintainer packaging and validation

`requirements-local.in` is the runtime-only input; email intake and test dependencies are not shipped. Regenerate the universal hash lock with the pinned uv version and review the resulting changes:

```sh
uv pip compile requirements-local.in --universal --python-version 3.13 --generate-hashes --output-file requirements-local.lock
```

Run `python scripts/build_local_bundle.py` to produce `dist/AdCode-Local-POC.zip` with a root `Install AdCode.command` and a runtime allowlist. The builder refuses to overwrite an existing artifact; choose a new `--output` path for subsequent builds. It normalizes public text to Unix line endings and records executable permissions for command files. Never package a whole working directory or customer/private files. Packaging and installation are separate from signing/notarization.

Validation status:

- Full Windows `python -m pytest -q`: **563 passed, 25 skipped**.
- Fresh clean Linux Python **3.13.18**, hash-locked public-bundle runtime: nine selected local/MCP test files, including guided access and real guided stdio, **249 passed, no skips**; no provider calls. The isolated non-root Docker run used read-only inputs and only public bundle/test/fixture/build inputs; container and temporary-tree cleanup was confirmed.
- Rebuild and verify archive integrity, public-file allowlist, permissions, and checksum after documentation changes.
- Earlier Windows **555/25** and Linux **184** results are historical and separate in the validation record. These results do not verify actual UI approvals or provider authentication.
- Actual macOS hardware: **unavailable; installation, Finder/Gatekeeper approval, managed-Python/Tk fallback, Cursor approval/discovery UX, and Intel/Apple Silicon runtime behavior remain unverified**.

See [the validation record](local-poc-validation.md) for the checks and remaining Mac acceptance steps. Linux validation is not evidence that macOS application approval, UI, or architecture-specific installation passed. See [ADR-024](decisions/024-local-macos-cursor-poc.md) and [SECURITY.md](../SECURITY.md) for the decision and threat boundaries.
