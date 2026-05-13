# Cloudflare Email Worker — Runbook

Worker name: `adcode-inbound`  
Source file: `integrations/email_mailroom/worker.js`  
Integration docs: `integrations/email_mailroom/README.md`  
Receives: inbound email at `traffic@ryanbishop.me`  
Forwards to: `https://api.ryanbishop.me/inbound`

---

## Update the worker code

When `integrations/email_mailroom/worker.js` changes:

1. Go to **dash.cloudflare.com** → **Workers & Pages** → `adcode-inbound`
2. Click **Edit code**
3. Replace all code with the contents of `integrations/email_mailroom/worker.js`
4. Click **Deploy**

---

## Update worker secrets

Secrets are set per-worker and never appear in code.

1. Go to **dash.cloudflare.com** → **Workers & Pages** → `adcode-inbound`
2. Click **Settings** → **Variables and Secrets**
3. To add or rotate a secret: click **Add variable**, set type to **Secret**, enter name and value, click **Deploy**

| Secret name | Value |
|---|---|
| `WEBHOOK_URL` | `https://api.ryanbishop.me/inbound` |
| `WEBHOOK_SECRET` | Random 32-char string — must match `WEBHOOK_SECRET` on Fly.io |

To rotate `WEBHOOK_SECRET`: generate a new value, update it here **and** in Fly.io secrets (`flyctl secrets set WEBHOOK_SECRET=<new>`) before deploying either side.

---

## Wire Email Routing route (one-time, or if route is deleted)

1. Go to **dash.cloudflare.com** → **ryanbishop.me** → **Email** → **Email Routing**
2. Click **Routing rules** → **Custom addresses** → **Create address**
   - Custom address: `traffic`
   - Action: `Send to a Worker`
   - Worker: `adcode-inbound`
3. Click **Save**

---

## View worker logs (live tail)

1. Go to **dash.cloudflare.com** → **Workers & Pages** → `adcode-inbound`
2. Click **Logs** → **Begin log stream**
3. Send a test email to `traffic@ryanbishop.me` — the request and any `console.error` lines appear in real time

---

## Test the worker manually

Send a POST directly to the webhook to verify the Python server is reachable without going through email:

```bash
curl -X POST https://api.ryanbishop.me/inbound \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <your-secret>" \
  -d '{"from":"client@example.com","to":"traffic@ryanbishop.me","subject":"test","raw":""}'
```

Expected response: `{"status":"rejected","reason":"unknown sender"}` (because `raw` is empty and the from address isn't in any customer config) — this confirms the server is up and the secret is accepted.

---

## If email is not arriving at the worker

1. Check Email Routing is enabled: **ryanbishop.me** → **Email** → **Email Routing** → status should be **Active**
2. Check the `traffic` route exists under **Routing rules** → **Custom addresses**
3. Check MX records are present: **DNS** → look for MX records pointing to `route1.mx.cloudflare.net` etc.
4. Check worker logs for errors (see above)
5. Check Fly.io logs: `flyctl logs --app adcode`
