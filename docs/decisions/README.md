# Architecture Decision Records

This directory records design decisions made while AdCode evolved. Some older ADRs describe layouts or flows that were later superseded. Prefer the latest accepted ADR when decisions conflict.

## Current High-Signal ADRs

| ADR | Summary |
| --- | --- |
| [004](004-unified-changeset.md) | Plan/apply uses one changeset covering creates, updates, and deletes. Deletes require confirmation. |
| [005](005-import-untracked-adsets.md) | `import_adsets` adopts live Facebook ad sets into template and state. |
| [006](006-facebook-pull-fidelity.md) | Preserve Facebook-returned values carefully when pulling live data. |
| [008](008-contractor-service-model.md) | V1 commercial and operational model is a contractor service, not SaaS. |
| [010](010-mailroom-engine-split.md) | Hosted email bot is a mailroom integration; execution runs locally. |
| [011](011-agnostic-email-bot.md) | Email bot accepts any sender with a valid webhook secret. |
| [012](012-ad-stack-model.md) | State is stack-scoped, not account-scoped. |
| [013](013-terraform-stack-layout.md) | Stack folder co-locates template and state. |
| [014](014-stack-level-env.md) | `--config` points to a stack template and loads stack-local `.env`. |

## Historical ADRs

| ADR | Summary |
| --- | --- |
| [001](001-email-interface.md) | Early email interface direction. |
| [002](002-mcp-first.md) | MCP-first interface decision. |
| [003](003-excel-as-client-artifact.md) | Excel remains a client artifact; JSON is operational source of truth. |
| [007](007-bom-tolerant-json-load.md) | Campaign JSON loading tolerates UTF-8 BOM. |
| [009](009-email-bot-architecture.md) | Earlier email bot architecture, later superseded by mailroom split. |
