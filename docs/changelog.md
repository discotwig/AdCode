# Changelog

All notable changes to AdCode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

## [0.1.0] — 2026-05-10

### Added

**Project design and documentation seed.**

- `docs/product-brief.md` — problem statement, solution overview, core principles, v1 scope, and interface strategy.

- `docs/decisions/001-email-interface.md` — ADR establishing email as the primary human interface. Rationale: meets non-technical agency staff where they already operate; the email bot is architecturally a thin wrapper over MCP tools with email transport, not a separate system.

- `docs/decisions/002-mcp-first.md` — ADR establishing MCP server + core scripts as the first build target, before any interface layer. Rationale: decouples core logic from interface; provides immediate value to the agency via their existing Gemini workflow; defers interface decisions until the tool surface is stable.

- `docs/decisions/003-excel-as-client-artifact.md` — ADR establishing Excel as the client collaboration artifact and JSON as the operational source of truth, with strictly one-directional flow. Describes the tension created by two representations of campaign state and how drift detection and `get_campaign_json` mitigate it.

- `docs/api-research/meta.md` — Facebook Marketing API research: campaign object model (campaign → ad set → ad hierarchy), known pain points (ad rejection, objective immutability, rate limits), how pre-push AI validation addresses rejections, `facebook-business` Python SDK overview, and a working list of required fields for the campaign JSON schema.

### Architecture established

- **Platform:** Meta (Facebook) first. 150 campaigns is the immediate need. Google Ads deferred to v2.
- **Storage:** No database. GitHub is the database. State files live in the repository.
- **Interface protocol:** MCP (Model Context Protocol). Agency brings their own model (Gemini).
- **AI touchpoints:** Excel → JSON ingestion, pre-push policy validation, pre-push drift diff, post-push reconciliation memo, `get_campaign_json` inspection.
- **V1 deliverables:** JSON schema, `traffic.py` (apply engine), `reconcile.py` (drift detection), MCP server.
- **V2 scope (deferred):** Email bot, Google Ads integration.
