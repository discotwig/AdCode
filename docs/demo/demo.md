# AdCode Customer Demo Guide

AdCode is an open-source campaign governance and QA layer for agencies that use contractors to traffic paid media campaigns. This guide is for the operator running the demo — either for internal validation or for a buyer conversation with a marketing manager, media director, or agency leader who does not use a terminal or GitHub.

The demo story: a contractor submitted a Meta campaign setup. AdCode catches broad targeting, a missing flight date, and budget exposure before the campaign spends money. The output is a Campaign Review Packet the manager can read, forward, and approve.

---

## Part A — 10-Minute Buyer Demo

**No live Meta account required.** This demo runs entirely offline using the `examples/contractor-mistakes/` stack and your Anthropic API key.

### Setup

```bash
# One-time: copy the env template and fill in ANTHROPIC_API_KEY
cp examples/contractor-mistakes/.env.example examples/contractor-mistakes/.env
# Open the file and replace REPLACE_WITH_ANTHROPIC_API_KEY
# Leave all FB_* values as-is — they are not used in this demo

# Start the MCP server pointed at the demo stack
python src/mcp_server.py \
  --config examples/contractor-mistakes/contractor_mistakes.json \
  --skip-connection-check
```

**What this stack contains:**

A contractor submitted two campaigns. One is problematic — the other is intentionally clean, to show contrast.

| Campaign | Issue |
| --- | --- |
| Q3 Brand Awareness | Ad set "All US — No Targeting": no interests, behaviors, or audiences; no end date; no spend cap on campaign |
| Retargeting — Site Visitors | Clean: custom audience, end date, spend cap in place |

The account budget cap is set to $400/day. The template declares $450/day total — a cap overage.

---

### Step 1 — Show the active stack

**Prompt:**
```
Show me the active AdCode stack.
```

**Expected output:** Template path, account ID, .env confirmed.

**Talk track:**
> "The operator starts the server pointed at one stack — the contractor's submission. The AI can only operate on the stack the operator opened. This is not a general ad account console."

---

### Step 2 — Validate the stack

**Prompt:**
```
Validate this stack.
```

**Expected output:** 2 ERRORs (broad targeting, missing end date), 1 WARNING (no spend cap). JSON Schema passes.

**Talk track:**
> "Policy checks run before anything touches Facebook. AdCode found that one ad set will reach an unconstrained US audience — 18 to 65, all placements, no interests or audiences. It also has no end date. These are the contractor mistakes that go live and spend money before anyone notices."

**Pause here.** Let the buyer read the violations. Ask:
> "Has something like this happened on your account?"

---

### Step 3 — Plan the stack

**Prompt:**
```
Plan this stack and show what it would cost.
```

**Expected output:** 2 campaign creates + 2 ad set creates, budget delta ($450/day added), cap exceeded warning.

**Talk track:**
> "Before anything touches Facebook, AdCode shows the exact changeset and the budget exposure. This stack declares $300/day for the broad campaign and $150/day for retargeting — $450 total. That exceeds the $400 account cap. The apply would be blocked automatically. The contractor can't accidentally push this as-is."

---

### Step 4 — Generate the Campaign Review Packet

**Prompt:**
```
Generate the Campaign Review Packet for this stack.
```

**Expected output:** A full Markdown report with status **BLOCKED**, including:
- Executive Summary (2 campaigns, 2 errors, overall status)
- Approval Recommendation (plain-English blocking statement)
- Budget Impact ($450/day declared, cap exceeded by $50)
- Policy Results (error/warning table with fix guidance)
- Campaign Hierarchy (campaign → ad set → ad with budgets and objectives)
- Targeting Summary (broad targeting flag on "All US — No Targeting")
- Flight Dates (missing end date flagged)
- Human Review Checklist (4 action items)
- Next Action (fix blocking issues before apply)

**Talk track:**
> "This is the artifact. Everything the manager needs to review is in one place — what will launch, what it costs, what failed QA, and a checklist of what has to be fixed before anyone approves apply. No terminal. No JSON. This can be forwarded by email or attached to a PR. The reviewer signs off on this, not on a screenshot from a contractor."

**Point out the Human Review Checklist specifically.** These are the blocking action items.

---

### Closing pitch

After Step 4, deliver this:

> "AdCode can start as QA-only. You don't need to give it write access to Facebook on day one. The first pilot is proving whether this review packet catches mistakes your current process misses — and produces a better approval artifact than screenshots or manual checklists. We can set this up for one client account in two to three weeks."

---

## Part B — Live Meta Demo

**Requires live Meta credentials** in the stack `.env`. Use a customer stack or a test account with real `FB_APP_ID`, `FB_APP_SECRET`, `FB_ACCESS_TOKEN`, and `FB_ACCOUNT_ID`.

Start the server without `--skip-connection-check`:

```bash
python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json
```

All demo campaigns should be created as `PAUSED` — no ads serve and no budget is spent.

---

### Step 5 — Apply the stack

If the plan has no deletes:

```
Apply this stack.
```

If the plan includes intentional deletes:

```
Apply this stack with confirm_deletes=true.
```

**Expected result:** Creates, updates, and deletes execute in order. New Facebook IDs are written back to the template and `state.json`.

**Talking point:** Applies are deterministic and stateful. Running the same stack again will not create duplicates.

---

### Step 6 — Confirm idempotency

```
Plan this stack again and confirm whether anything would change.
```

**Expected result:** `No changes detected.` or equivalent.

**Talking point:** The state file lets AdCode distinguish managed objects from new objects. Reapplying the same desired state is always safe.

---

### Step 7 — Inspect local state

```
Show me the local state for this stack.
```

**Expected result:** Tracked campaigns, ad sets, ads, Facebook IDs, and last-pushed params from `state.json`.

**Talking point:** Git plus state gives an audit trail available without rate limits or browser access.

---

### Step 8 — Check managed drift

Optional setup: manually change a managed campaign or ad set in Facebook Ads Manager.

```
Check drift for this stack.
```

**Expected result:** Field mismatches or missing managed objects reported. Unrelated campaigns in the account are not mentioned.

Example:
```
[FIELD_MISMATCH] CAMPAIGN: Q3 Brand Awareness
    status: expected='PAUSED' actual='ACTIVE'
```

**Talking point:** Drift is stack-scoped. It is not a general account scan. AdCode only reports changes to objects it manages.

---

### Step 9 — Search import candidates

```
Search for ad set import candidates for this stack.
```

**Expected result:** Unmanaged live ad sets under campaigns declared in the stack template.

**Talking point:** The controlled import path for adopting manually created objects without turning the MCP server into a broad account console.

---

### Step 10 — Import a specific ad set

```
Import the ad set named "<AD SET NAME>" into this stack.
```

**Expected result:** The ad set is added to the template and `state.json` with its Facebook ID. Then:

```
Plan this stack again and confirm whether the import created any spurious changes.
```

**Expected result:** Plan is clean or limited to intentional differences.

**Talking point:** Import is a local read-then-write. It does not change Facebook. It brings live objects under source control.

---

### Step 11 — Negative surface tests

```
List all campaigns in the ad account.
```

```
Pause all campaigns matching Black Friday.
```

**Expected result:** Neither command should work. The MCP server does not expose `list_campaigns`, `pause_campaigns`, `get_campaign_status`, or other broad live account tools.

**Talking point:** This is the safety boundary. The AI operates only on the active stack.

---

## Key Messages

1. **The stack is the contract.** The AI operates on the active stack, not the whole ad account.
2. **Policy checks run before Facebook does.** Schema validation and agency rules fire against the template.
3. **Plan before apply.** Every provider write is previewed and must be reviewed.
4. **State prevents duplicates.** Facebook IDs are tracked after apply and import.
5. **Drift is managed-object drift.** Unrelated live account objects are never part of the stack.
6. **Import is controlled.** Adopting unmanaged objects requires an explicit operator step.
7. **The review packet is the output.** `document_stack` produces a buyer-readable artifact before any campaign spends money.
8. **AdCode can start as QA-only.** No write access to Facebook is needed for the first pilot.
