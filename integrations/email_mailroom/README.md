# Email Mailroom Integration

The email mailroom is an optional intake adapter for AdCode operators who receive campaign requests by email.

It is not the AdCode execution engine. It does not call Facebook, run `plan_campaigns`, run `apply_campaigns`, or store stack state. It only validates, routes, and seeds templates.

## Responsibilities

Inbound email follows three paths:

- Valid JSON template: reply to the sender and forward the template to the operator.
- Invalid JSON template: reply to the sender with schema errors.
- Excel or plain text: use AI to seed a starter template and reply with the JSON attachment.

## Runtime

```text
Client email
  -> Cloudflare Email Worker
  -> FastAPI /inbound webhook
  -> Resend replies/forwards
```

The FastAPI app is:

```text
integrations.email_mailroom.app:app
```

Run locally:

```bash
uvicorn integrations.email_mailroom.app:app --host 0.0.0.0 --port 8080
```

## Environment

Required for deployment:

- `WEBHOOK_SECRET`
- `OPERATOR_EMAIL`
- `BOT_EMAIL`
- `RESEND_API_KEY`
- `ANTHROPIC_API_KEY`

The mailroom should not receive Facebook credentials.

## Cloudflare Worker

Worker source:

```text
integrations/email_mailroom/worker.js
```

The worker posts raw MIME email to `/inbound` with `X-Webhook-Secret`.

## Fly.io

Deploy from the repository root with the integration config:

```bash
fly deploy --config integrations/email_mailroom/fly.toml
```

The Dockerfile is:

```text
integrations/email_mailroom/Dockerfile
```

There is no customers volume. The mailroom holds no stack templates, state files, or Meta credentials.

## Operator Flow

When the operator receives a valid template:

1. Save it to `customers/<slug>/<stack-name>/<stack-name>_template.json`.
2. Start the local MCP server:

   ```bash
   python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json
   ```

3. Run `plan_campaigns`, review the output, then apply if correct.
4. Commit the template and `state.json` together.
