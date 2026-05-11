# AdCode — SaaS Architecture & Multi-Tenancy Design

## Context

AdCode is delivered as a SaaS to marketing agencies. Each customer accesses the service through one of two interfaces — an MCP server or an email bot — both of which perform the same underlying operations. Customer data is segregated by folder within a single GitHub repository, which acts as the operational database.

This document records the design decisions made around tenant isolation, configuration, and routing.

---

## Campaign File Structure

```
campaigns/
  {customer_slug}/
    {account_id}/
      *.json
```

**`customer_slug`** is a stable, human-readable identifier assigned at onboarding (e.g. `acme-marketing`). It groups all accounts belonging to a single customer and makes the repo auditable at a glance.

**`account_id`** is the Facebook ad account ID (e.g. `act_366643171197739`). It is the natural routing key for Facebook API calls. A customer with multiple Facebook accounts gets multiple subfolders under their slug.

The demo/developer account lives at `campaigns/demo/`.

**Why not `account_id` as the top-level key?** A single customer can operate multiple Facebook ad accounts (e.g. separate US and EU accounts). Using only `account_id` at the top level would make customer-level grouping impossible without a separate lookup.

---

## Customer Record

Each customer has a configuration record used by both the MCP server and the email bot:

```json
{
  "customer_id": "acme-marketing",
  "account_ids": ["act_111111", "act_222222"],
  "fb_access_token": "...",
  "fb_page_id": "...",
  "email_addresses": ["media@acme.com", "trafficker@acme.com"],
  "mcp_api_key": "adcode_live_abc123"
}
```

In v1 this registry lives as a config file in the repo or environment variables. It may move to a dedicated store (e.g. a simple KV or secrets manager) as customer count grows.

---

## MCP Server — Multi-Tenancy

The MCP spec has no built-in tenant model. AdCode resolves this by requiring an API key on every MCP request. The server resolves the key to a customer record and scopes all operations to that customer's `campaigns/{slug}/{account_id}/` paths and Facebook credentials.

Customers never interact with GitHub directly. All campaign file writes are committed to the repo by the MCP server via the GitHub API using a single service token. The commit log is the audit trail.

**Authentication flow:**
1. Customer configures their MCP client with the server URL and their API key.
2. MCP server validates the key, loads the customer record.
3. All tool calls operate within that customer's scope.

---

## Email Bot — Multi-Tenancy

The email bot authenticates by sender address. Incoming emails are matched against the `email_addresses` list in the customer registry. Unrecognized senders are rejected with an error reply.

**Routing flow:**
1. Email arrives at the shared inbox.
2. Sender address matched to customer record.
3. Customer's Facebook credentials and campaigns path loaded.
4. Action parsed from subject/body, executed via MCP tools, reply sent.

Both channels (MCP and email) use the same underlying tool layer — the email bot is transport only.

---

## GitHub as the Write Layer

No customer has direct push access to the repo. All writes — creating or updating campaign JSON files — are performed by the MCP server via the GitHub API. This enforces:

- A single audit trail (every change is a commit with a customer-attributable author).
- Access control (customers can only write to their own folder via the API key scope).
- State consistency (pushes to Facebook and commits to GitHub are always paired).

### Required MCP tools for non-repo agents

Two tools are needed to complete the non-filesystem workflow:

**`save_campaign_file(customer_slug, account_id, filename, json_str)`**
Commits a campaign JSON file to `campaigns/{customer_slug}/{account_id}/{filename}.json` via the GitHub API. Used after an agent generates or imports campaign JSON and the user approves it in the conversation.

**`list_campaign_files(customer_slug, account_id)`**
Lists existing JSON files in a customer's folder. Lets an agent present "here are your current templates — which do you want to update?" without requiring repo access.

---

## Onboarding a New Customer

1. Assign `customer_slug`.
2. Collect `account_id(s)`, `fb_access_token`, `fb_page_id`, authorized email addresses.
3. Add customer record to registry.
4. Create `campaigns/{customer_slug}/` folder in the repo.
5. Issue `mcp_api_key` and share MCP server URL + key with customer.
6. Customer configures their AI client (Claude, Gemini, etc.) with the MCP server.

---

## Storage Evolution

The current storage backend is GitHub. If volume or latency requirements change, the campaign files and state files can be migrated to S3 or a similar object store with no change to the tool interface — only the read/write implementation inside the MCP server changes.
