# AdCode — Product Brief

## Problem Statement

A digital ad agency traffics ad campaigns entirely by hand. An associate reads an Excel spreadsheet, manually enters campaigns into Facebook Ads Manager, and then a specialist logs in separately to QA the work. There is no audit trail beyond email threads and file versioning in SharePoint or local drives. All tracking and collaboration happens in heavily customized Excel files used as human dashboards — multi-sheet, non-structured, owned by the person who built them.

The result is slow throughput, error-prone data entry, and a QA process that requires a second human to log into Facebook and verify what the first human did.

## Solution Overview

AdCode applies the infrastructure-as-code mental model to ad campaign trafficking. Campaign definitions live as JSON files in a GitHub repository. A script reads the JSON, calls the Facebook Marketing API, and writes a state file with returned IDs back to the repo. The Git history is the audit trail. Pull requests are the review mechanism. No one needs to log into Facebook Ads Manager for routine trafficking or QA.

The system does not replace Excel as a client collaboration artifact — it clarifies Excel's role. Excel is where clients and account managers communicate campaign intent. JSON is the operational source of truth. The flow is strictly one-directional: Excel informs JSON, never the reverse.

## Core Principles

**Declarative definitions.** Campaign state is expressed as JSON describing what should exist, not a sequence of API calls describing how to create it. The apply engine is responsible for reconciling declared state with actual state.

**Git as source of truth.** GitHub is the database. Campaign definitions, state files, and the complete history of every change live in the repository. No separate storage layer.

**Idempotent applies.** Running `apply_stack` twice with the same input produces the same result. `plan_stack` prevents blind overwrites by surfacing what will change before any API call is made.

**Desired state reconciliation.** The system can pull current actuals from Facebook and diff them against the local state file. Drift — where Facebook's actual state diverges from what the state file says — is detected, reported, and resolved explicitly rather than silently overwritten.

## Target Users

Digital advertising agency staff: associates who traffic campaigns and specialists who QA them. These users are not technical. They work in Excel, email, and browser-based ad platforms. The system must meet them where they already operate — the primary interface is email, not a CLI or web app.

## Interface Strategy

The core functionality is exposed as an MCP (Model Context Protocol) server. MCP tools wrap the core scripts and expose them to AI models. The agency already uses Gemini; they bring their own model and attach it to the MCP server rather than learning a new interface.

The email interface sits on top of the MCP server. A bot watches an inbox, accepts Excel attachments with natural language instructions in the email body, replies with validation results and approval requests, and dispatches a push report on completion. From the user's perspective, the interface is email. From the system's perspective, it is a model call with the MCP server attached and email transport wrapped around it.

**Interface build order:**
1. MCP server + core scripts
2. Email bot (v2)

## AI Touchpoints

**Excel → JSON ingestion.** AI reads the client-provided Excel file and extracts campaign definitions against the JSON schema. Because Excel files are non-structured and inconsistent across clients, the AI flags ambiguities in its output for human review before the JSON is committed.

**Pre-push policy validation.** Before any API call, AI reviews the proposed JSON against Facebook ad policies. Known rejection patterns (prohibited content categories, missing required fields, policy edge cases) are surfaced as warnings so issues can be communicated to the client proactively rather than discovered post-rejection.

**Pre-push drift diff.** Before applying, the system pulls current Facebook actuals and diffs them against the proposed JSON. AI interprets the diff and surfaces intentional drift — cases where Facebook's state diverges from the state file for a known reason — that should not be silently overwritten.

**Post-apply reconciliation.** After `apply_stack` completes, the system can pull actuals again and compare them to the updated state file. AI interprets the raw diff into a human-readable memo. The QA specialist reads the report instead of logging into Facebook.

**`show_state` inspection.** Read-only. Returns raw JSON from the active stack state file. Used for troubleshooting and data validation — lets users verify what the system believes is true without touching GitHub or the Facebook UI.

## MCP Tool Surface

```
# IaC actions
show_stack()
validate_stack()
plan_stack()
apply_stack(confirm_deletes?)
drift_stack()
show_state(filter?)

# Controlled import
search_import_candidates(resource_type)
import_resource(resource_type, names?)

# Template generation
generate_stack_from_excel(excel_path)
```

## V1 Scope

- JSON schema for Facebook campaigns
- `traffic.py` — apply engine (reads JSON, calls Facebook Marketing API, writes state file)
- `reconcile.py` — drift detection (pulls actuals, diffs against state file, produces report)
- AI-assisted Excel ingestion
- Pre-push policy validation
- MCP server wrapping all of the above

## Out of Scope for V1

- Email bot interface
- Google Ads integration
- Web application UI
- Multi-agency or multi-tenant support
- Campaign performance reporting (separate concern from trafficking)
