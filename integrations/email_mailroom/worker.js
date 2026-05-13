/**
 * Cloudflare Email Worker — receives inbound email at traffic@ryanbishop.me
 * and forwards it to the AdCode webhook server.
 *
 * Environment variables (set via Cloudflare dashboard or wrangler secret):
 *   WEBHOOK_URL    — e.g. https://api.ryanbishop.me/inbound
 *   WEBHOOK_SECRET — shared secret checked by the Python server
 *
 * Deploy: wrangler deploy integrations/email_mailroom/worker.js
 */
export default {
  async email(message, env, ctx) {
    const rawEmail = await new Response(message.raw).text();

    const response = await fetch(env.WEBHOOK_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Secret": env.WEBHOOK_SECRET,
      },
      body: JSON.stringify({
        from: message.from,
        to: message.to,
        subject: message.headers.get("subject") || "",
        raw: rawEmail,
      }),
    });

    if (!response.ok) {
      const body = await response.text().catch(() => "");
      console.error(`Webhook failed: ${response.status} ${body}`);
      message.setReject("Delivery failed — please try again.");
    }
  },
};
