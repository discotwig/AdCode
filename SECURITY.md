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
customers/<slug>/<stack-name>/.env
```

Do not commit `.env` files. The repository `.gitignore` excludes stack credential files.

The optional email mailroom in `integrations/email_mailroom/` does not need Facebook credentials and should not be given them. It only needs:

- `WEBHOOK_SECRET`
- `OPERATOR_EMAIL`
- `BOT_EMAIL`
- `RESEND_API_KEY`
- `ANTHROPIC_API_KEY`

## State Files

`state.json` files are committed intentionally. They contain Facebook object IDs and last-pushed params, not access tokens. They should still be treated as operationally sensitive because they describe managed campaign infrastructure.

Do not edit `state.json` by hand unless you are intentionally performing a state operation. Prefer tools like `import_resource` when adopting supported live objects.

## Execution Safety

AdCode's safety model depends on:

- running one MCP server per active stack;
- reviewing `plan_stack` before `apply_stack`;
- requiring explicit confirmation for deletes;
- keeping Meta credentials local to the operator machine;
- committing template and state changes together.

Use `import_resource` for controlled adoption of supported live resources into a stack. Use `generate_stack_from_excel` only to seed templates from public-safe or client-approved briefs.

Do not add hosted apply behavior without a clear credential, state, approval, and audit design.
