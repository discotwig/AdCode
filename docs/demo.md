# AdCode Demo Guide

A step-by-step walkthrough to demonstrate AdCode to a client. All campaigns are created as `PAUSED` — no ads serve, no budget is spent.

## Before you start

**One-time setup in the demo files:**

Open `campaigns/demo_v1.json` and `campaigns/demo_v2.json` and replace both placeholder values:

| Placeholder | Where to find it |
|---|---|
| `REPLACE_WITH_ACCOUNT_ID` | Facebook Business Manager → Business Settings → Ad Accounts. Prefix with `act_`, e.g. `act_366643171197739` |
| `REPLACE_WITH_PAGE_ID` | Facebook Business Manager → Business Settings → Pages. It's the numeric ID shown under the page name. |

Save both files. You can commit them — the placeholders are the only thing you need to change.

---

## Demo files

| File | Purpose |
|---|---|
| `campaigns/demo_v1.json` | Initial campaign: 1 campaign, 1 ad set (US 25-44), $10/day budget |
| `campaigns/demo_v2.json` | Updated campaign: budget raised to $20/day + a second ad set added (US 45-64) |

---

## Test 1 — AI policy validation (no API calls)

**What it shows:** Pre-flight checks catch problems before anything touches Facebook.

Ask Claude:
> *"Validate campaigns/demo_v1.json"*

**Expected result:** A summary with schema status (pass) and AI policy review. If `REPLACE_WITH_PAGE_ID` is still in the file, it flags it as an error — demonstrating the guard rail works.

**Talking point for client:** *"Before we ever call the API, the system checks the JSON against Facebook's ad policies using AI. Traffickers get feedback in seconds instead of waiting for Facebook to reject the creative."*

---

## Test 2 — Preview the diff (no API calls)

**What it shows:** Safe dry-run before committing to any changes.

Ask Claude:
> *"Preview the diff for campaigns/demo_v1.json"*

**Expected result:**
```
Plan: 3 operations
  CREATE campaign  AdCode Demo — Brand Awareness
  CREATE ad set    US 25-44 — Broad
  CREATE ad        Demo Ad — Headline v1
```

**Talking point for client:** *"This is the equivalent of `terraform plan`. You see exactly what will be created or updated — zero surprises."*

---

## Test 3 — Push to Facebook (creates PAUSED objects)

**What it shows:** End-to-end push to the live Facebook API.

Ask Claude:
> *"Push campaigns/demo_v1.json"*

**Expected result:** 3 objects created (campaign, ad set, ad). A state file is written to `state/act_XXXXXXXXX.json` containing the Facebook-assigned IDs.

Open Facebook Ads Manager side-by-side to show the campaign appear in real time.

**Talking point for client:** *"The campaign is live in Ads Manager — but PAUSED, so nothing runs until you're ready. The state file in Git is now the source of truth for IDs."*

---

## Test 4 — Idempotent re-push (no-op)

**What it shows:** Running it twice doesn't create duplicates.

Ask Claude:
> *"Push campaigns/demo_v1.json again"*

**Expected result:**
```
Plan: 0 operations — nothing to do.
```

**Talking point for client:** *"Safe to run any time. If nothing changed in the JSON, nothing changes on Facebook."*

---

## Test 5 — Apply a change (budget + new ad set)

**What it shows:** Updating a campaign by editing the JSON file.

Ask Claude:
> *"Preview the diff for campaigns/demo_v2.json"*

**Expected result:**
```
Plan: 2 operations
  UPDATE ad set    US 25-44 — Broad  (daily_budget: 1000 → 2000)
  CREATE ad set    US 45-64 — Broad
  CREATE ad        Demo Ad — Headline v1
```

Then ask:
> *"Push campaigns/demo_v2.json"*

**Expected result:** Budget updated, new ad set created. Verify in Ads Manager.

**Talking point for client:** *"Budget changes, new ad sets, copy updates — all done by editing a file and pushing. The diff shows exactly what changed before it happens. The PR history is your audit trail."*

---

## Test 6 — Drift detection

**What it shows:** AdCode detects when someone makes a manual change in Ads Manager.

1. Go into Facebook Ads Manager and manually rename the campaign or change its status.
2. Ask Claude:
   > *"Get the drift report for my account"*

**Expected result:**
```
FIELD_MISMATCH  campaign  AdCode Demo — Brand Awareness
  name: expected "AdCode Demo — Brand Awareness", got "My Manual Edit"
```

**Talking point for client:** *"If anyone goes rogue in Ads Manager, the drift report catches it immediately. You always know when your live account has diverged from what's in Git."*

---

## Test 7 — Read state without hitting the API

**What it shows:** Instant read-only inspection from the state file.

Ask Claude:
> *"Show me the campaign JSON for my account"*

**Expected result:** Full state file JSON with all Facebook IDs, returned instantly with no API call.

**Talking point for client:** *"Auditing what's deployed costs zero API calls. The state file in Git is always available."*

---

## Cleanup after the demo

Delete the test campaigns to keep your ad account clean:

Ask Claude:
> *"Pause all campaigns with 'AdCode Demo' in the name"*

Then delete them manually in Ads Manager, or ask me to add a `delete_campaigns` tool if you want it automated.

---

## Key messages for the client

1. **Git is the audit trail.** Every change is a commit. Who changed what and when is always answerable.
2. **PRs are the review mechanism.** Budget changes, targeting updates, copy edits — all reviewed before they go live.
3. **No one needs to log into Ads Manager for routine trafficking.** The MCP tools handle it via natural language.
4. **AI policy review before every push.** Catch rejections before Facebook does.
5. **Drift detection keeps the account honest.** Manual changes in Ads Manager are surfaced immediately.
