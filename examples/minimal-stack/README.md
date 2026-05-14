# Minimal Stack Example

This example is a complete AdCode stack template. It is safe as a reference fixture because all account, page, link, and `fb_id` values are placeholders.

To try the shape locally, copy the template into a stack folder created by `scripts/new_customer.py`, replace placeholders, and run:

```bash
python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json --skip-connection-check
```

Then ask your MCP client to run `plan_stack`.
