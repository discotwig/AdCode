# ADR 003 — Excel as Client Artifact, JSON as Operational Source of Truth

**Status:** Accepted

---

## Context

The agency's existing workflow centers on Excel. Client briefs arrive as Excel files. Account managers annotate them. Associates use them as trafficking checklists. Specialists use them for QA. These files are not structured data — they are human dashboards, with merged cells, color coding, notes columns, and layouts that vary by account manager and client.

AdCode needs a single operational source of truth for campaign state. The candidates are:

**Excel as source of truth.** Treat the Excel file as the authoritative definition. Parse it directly and push to Facebook. This preserves the existing workflow exactly but makes the system dependent on inconsistently structured files it does not control. Schema validation becomes impossible. Diff and version control are impractical on binary Excel files.

**JSON as source of truth, Excel eliminated.** Define campaigns in JSON only. Require account managers to write or edit JSON directly. This gives the system a clean, structured, diffable source of truth but imposes a hard requirement on users to learn JSON — a non-starter for the target user.

**JSON as source of truth, Excel as input layer.** Excel remains the client-facing collaboration artifact. JSON is the operational source of truth. AI converts Excel → JSON as part of the ingestion pipeline. The flow is strictly one-directional: Excel informs JSON, never the reverse. Once JSON is committed, Excel is not updated to reflect subsequent changes — JSON is.

---

## Decision

Excel is the client collaboration artifact. JSON is the operational source of truth. The flow is strictly one-directional: Excel informs the initial JSON definition. After that, all changes are made in JSON. Excel is never reverse-engineered from the state file.

---

## Rationale

Clients and account managers will not stop using Excel. It is the language of the client relationship — briefs, revisions, and approvals all happen there. Eliminating it is not realistic; clarifying its role is.

JSON gives the system what it needs: a structured, diffable, versionable, schema-validatable definition that Git can manage. The AI ingestion layer handles the translation from messy Excel to clean JSON, flagging ambiguities for human review. This is a one-time cost per campaign setup, not a recurring one.

One-directional flow is a hard constraint, not a convenience. If the system allowed Excel to be regenerated from the state file (or vice versa), two sources of truth would exist in practice. Ambiguity about which is authoritative would produce errors. The constraint is enforced by design: the system has no export-to-Excel feature and no mechanism to sync them.

---

## The Tension This Creates

Two representations of campaign state will exist in practice: the Excel file that the client and account manager reference, and the JSON + state file that AdCode manages. Over time they will diverge. The client may update their Excel with notes or changes that are not reflected in the JSON. An associate may push a change to JSON that is not communicated back to the account manager's Excel.

This is not a bug — it is an accepted trade-off of having a client-facing layer that is not the operational layer. The tension is managed, not eliminated.

**Drift detection mitigates the operational risk.** `reconcile.py` and `get_drift_report` detect when Facebook's actual state diverges from the JSON state file. If an associate makes a manual change in Facebook Ads Manager (bypassing AdCode), or if a campaign is modified outside the JSON workflow, drift detection surfaces it. The state file is always verifiable against Facebook actuals.

**`get_campaign_json` mitigates the verification risk.** Users who want to know what the system believes is true — without opening GitHub or Facebook — can call `get_campaign_json`. This returns the raw JSON from the state file for a given campaign or account. It is a read-only inspection tool that lets users verify the operational state independently of the Excel file.

**The one-directional rule mitigates the consistency risk.** By prohibiting reverse flow, the system avoids the worst failure mode: an account manager overwriting JSON changes by re-ingesting a stale Excel file. The ingestion pipeline is for initial setup and new campaigns, not ongoing sync.

---

## Consequences

**Positive:**
- JSON is a clean, structured, schema-validatable source of truth. Git diff, PR reviews, and audit trails all work naturally.
- The AI ingestion layer handles messy Excel without requiring account managers to change their workflow.
- Clients and agency staff continue using Excel for communication and collaboration without disruption.
- Drift detection provides a safety net — divergence between JSON and Facebook actuals is always detectable.

**Negative:**
- Excel and JSON will diverge over time. There is no mechanism to keep them in sync, and none will be built. This is a known and accepted condition.
- Account managers may not realize that their Excel file is no longer the operational record after initial setup. Clear communication of the one-directional rule is required.
- The AI ingestion step introduces a human review checkpoint. Someone must verify that the AI correctly interpreted the Excel before committing the JSON. This adds a step to the trafficking workflow.
- Clients who ask "show me what's live in Facebook" cannot be pointed at the Excel file. They must be pointed at the JSON or the Facebook UI directly. This may require workflow adjustments for client communication.
