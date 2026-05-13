# Getting Started

This guide gets you from a fresh clone to a local, reviewable AdCode workflow. It does not require live Facebook credentials until the final apply step.

## 1. Install

```bash
git clone <repo>
cd AdCode
pip install -r requirements.txt
```

Run the local tests:

```bash
pytest tests/
```

## 2. Inspect The Minimal Example

Open:

```text
examples/minimal-stack/minimal_stack_template.json
```

It declares:

- one account;
- one campaign;
- one ad set;
- one ad;
- one creative.

Validate it against the schema:

```bash
python scripts/validate_example.py
```

If you have `make` installed:

```bash
make validate-example
```

## 3. Create A Local Stack

```bash
python scripts/new_customer.py demo-agency act_123456789
```

This creates:

```text
customers/demo-agency/demo-agency_v1/
  .env.example
  demo-agency_v1_template.json
```

Copy the minimal example into that stack if you want a populated template:

```bash
copy examples\minimal-stack\minimal_stack_template.json customers\demo-agency\demo-agency_v1\demo-agency_v1_template.json
```

On macOS or Linux:

```bash
cp examples/minimal-stack/minimal_stack_template.json customers/demo-agency/demo-agency_v1/demo-agency_v1_template.json
```

Then update `account_id` and placeholder creative fields for your account when you are ready to use live credentials.

## 4. Configure Credentials

Copy the stack environment file:

```bash
copy customers\demo-agency\demo-agency_v1\.env.example customers\demo-agency\demo-agency_v1\.env
```

On macOS or Linux:

```bash
cp customers/demo-agency/demo-agency_v1/.env.example customers/demo-agency/demo-agency_v1/.env
```

Fill in:

- `FB_APP_ID`
- `FB_APP_SECRET`
- `FB_ACCESS_TOKEN`
- `ANTHROPIC_API_KEY`

The account ID stays in the stack template.

## 5. Start The MCP Server

For offline inspection:

```bash
python src/mcp_server.py --config customers/demo-agency/demo-agency_v1/demo-agency_v1_template.json --skip-connection-check
```

For live use:

```bash
python src/mcp_server.py --config customers/demo-agency/demo-agency_v1/demo-agency_v1_template.json
```

The server is now scoped to that stack. To switch stacks, stop the process and start a new one with another `--config` path.

## 6. Plan, Review, Apply

From an MCP-compatible client:

```text
Plan this stack.
```

Review the changeset. If it is correct:

```text
Apply this stack.
```

If the plan includes deletes, the tool returns the plan and requires `confirm_deletes=true`.

## 7. Commit The Audit Trail

After apply, commit the template and state together:

```bash
git status
git add customers/demo-agency/demo-agency_v1/demo-agency_v1_template.json customers/demo-agency/demo-agency_v1/state.json
git commit -m "Apply demo agency stack"
```

This commit is the audit record of what was intended and what Facebook IDs were recorded after apply.
