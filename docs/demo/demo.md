# AdCode Demo Guide

A step-by-step walkthrough to demonstrate AdCode to a client. All campaigns are created as `PAUSED` — no ads serve, no budget is spent.

AdCode follows the same model as AWS CloudFormation: **the Ad Stack file is the desired state, and AdCode makes Facebook match it exactly.** Campaigns are created when you add them to the file, updated when you change a field, and deleted when you remove them. `plan_campaigns` is `terraform plan`. `apply_campaigns` is `terraform apply`.

Each Ad Stack (`campaigns/<name>.json`) has its own isolated state file (`state/<name>.json`). Applying one stack can never affect campaigns tracked by another stack — even in the same Facebook account.

The email bot (Tests 1–2 below, or jump to Test 9) lets clients submit briefs by email without any logins or dashboards.

## Before you start

The demo account ID (`act_366643171197739`) is already set in both Ad Stack files. The only placeholder you may need to replace is `REPLACE_WITH_PAGE_ID` in `demo_v2.json` if you run Tests 5–6 (it's pre-filled in `demo_v1.json`).

| Placeholder | Where to find it |
|---|---|
| `REPLACE_WITH_PAGE_ID` | Facebook Business Manager → Business Settings → Pages. Numeric ID shown under the page name. |

---

## Demo files

| File | Purpose |
|---|---|
| `customers/demo/demo_v1/demo_v1.json` | Ad Stack v1: 4 campaigns — one fully built (1 ad set, 1 ad, $10/day), three stub campaigns with no ad sets |
| `customers/demo/demo_v2/demo_v2.json` | Ad Stack v2: only the primary campaign, with a budget increase and a second ad set added — the 3 stubs are intentionally removed |

State is written to `customers/demo/demo_v1/state.json` (or `demo_v2/state.json`) — co-located with the template, like `terraform.tfstate`.

---

## Test 1 — AI policy validation (no API calls)

**What it shows:** Pre-flight checks catch problems before anything touches Facebook.

Ask Claude:
> *"Validate customers/demo/demo_v1/demo_v1.json"*

**Expected result:** Schema passes. AI policy review runs and confirms the creative and targeting are within policy.

**Talking point for client:** *"Before we ever call the API, the system validates the JSON against Facebook's ad policies using AI. Traffickers get feedback in seconds instead of waiting for Facebook to reject the creative."*

---

## Test 2 — Preview the diff (no API calls)

**What it shows:** The full changeset before any API call. This is `terraform plan`.

Ask Claude:
> *"Preview the diff for customers/demo/demo_v1/demo_v1.json"*

**Expected result:**
```
Plan: 4 CreateCampaign, 1 CreateAdSet, 1 CreateAd

  CreateCampaign: AdCode Demo — Brand Awareness
  CreateAdSet: AdCode Demo — Brand Awareness
  CreateAd: AdCode Demo — Brand Awareness
  CreateCampaign: My campaign 1017
  CreateCampaign: Test API Campaign 1
  CreateCampaign: Atlanta Debut
```

**Talking point for client:** *"This is the equivalent of* `terraform plan`*. You see exactly what will be created, updated, or deleted — zero surprises. Nothing has happened yet."*

---

## Test 3 — Push to Facebook (creates PAUSED objects)

**What it shows:** End-to-end push to the live Facebook API.

Ask Claude:
> *"Push customers/demo/demo_v1/demo_v1.json"*

**Expected result:** 4 campaigns created (one with an ad set and ad, three stubs). A stack state file is written to `customers/demo/demo_v1/state.json` containing the Facebook-assigned IDs.

Open Facebook Ads Manager side-by-side to show the campaigns appear in real time.

**Talking point for client:** *"The campaigns are live in Ads Manager — but PAUSED, so nothing runs until you're ready. The stack state file in Git is now the source of truth for Facebook IDs. That file is what makes idempotency and safe deletes possible."*

---

## Test 4 — Idempotent re-push (no-op)

**What it shows:** Running it twice doesn't create duplicates.

Ask Claude:
> *"Push customers/demo/demo_v1/demo_v1.json again"*

**Expected result:**
```
No changes detected.
```

**Talking point for client:** *"Safe to run any time. If nothing changed in the JSON, nothing changes on Facebook. There's no risk of accidental duplicates — the state file tracks every object by ID."*

---

## Test 5 — Unified changeset: update + delete in one operation

**What it shows:** Removing campaigns from the Ad Stack causes them to be deleted from Facebook — the same way deleting a resource from a CloudFormation template removes it from AWS.

Ask Claude:
> *"Preview the diff for customers/demo/demo_v2/demo_v2.json"*

**Expected result:**
```
Plan: 1 UpdateAdSet, 1 CreateAdSet, 1 CreateAd, 3 DeleteCampaign

  UpdateAdSet: AdCode Demo — Brand Awareness — fields: ['daily_budget']
  CreateAdSet: AdCode Demo — Brand Awareness
  CreateAd: AdCode Demo — Brand Awareness
  DELETE campaign: "My campaign 1017"  (fb_id: <id>)
  DELETE campaign: "Test API Campaign 1"  (fb_id: <id>)
  DELETE campaign: "Atlanta Debut"  (fb_id: <id>)
```

Because the plan includes deletions, pushing requires explicit confirmation. Ask Claude:
> *"Push customers/demo/demo_v2/demo_v2.json with confirm_deletes=true"*

**Expected result:** Budget updated to $20/day, new ad set (US 45-64) created, 3 stub campaigns deleted. Verify in Ads Manager.

**Talking point for client:** *"Creates, updates, and deletes all happen in a single operation from a single file. Removing a campaign from the Ad Stack is the only way to delete it — AdCode will never delete something you didn't explicitly remove. And any plan that includes deletions requires you to confirm before it runs."*

---

## Test 6 — Drift detection

**What it shows:** AdCode detects when someone makes a manual change in Ads Manager.

1. Go into Facebook Ads Manager and manually rename the campaign or change its status.
2. Ask Claude:
   > *"Get the drift report for customers/demo/demo_v2/demo_v2.json"*

**Expected result:**
```
FIELD_MISMATCH  campaign  AdCode Demo — Brand Awareness
  name: expected "AdCode Demo — Brand Awareness", got "My Manual Edit"
```

**Talking point for client:** *"If anyone goes rogue in Ads Manager, the drift report catches it immediately. You always know when the live account has diverged from what's in Git. The fix is to push the Ad Stack again — AdCode restores the desired state."*

---

## Test 7 — Drift remediation: import untracked ad sets

**What it shows:** Once drift is detected, AdCode can adopt untracked ad sets from Facebook into the Ad Stack and state file in one step — no manual transcription from Ads Manager.

*(Run Test 6 first so there is drift to remediate.)*

Ask Claude:
> *"Import the untracked ad sets into customers/demo/demo_v1/demo_v1.json"*

**Expected result:**
```
Imported 3 ad set(s) into demo_v1.json and state:
  + My campaign 1017 / My Ad Set  (fb_id: 23848811670940718)
  + Test API Campaign 1 / Test API AdSet 1  (fb_id: 23845817916220718)
  + Atlanta Debut / Atlanta Debut  (fb_id: 23845815648140718)

Run plan_campaigns to verify no spurious changes before committing.
```

Then confirm nothing would be pushed:
> *"Validate customers/demo/demo_v1/demo_v1.json"*

**Expected result:** `No changes — Facebook already matches this configuration.`

Commit the updated JSON to lock the imported ad sets into source control.

**Talking point for client:** *"Anything created outside AdCode — by another trafficker, a legacy script, or an agency — can be adopted into the managed stack in one command. From that point on, it's fully tracked: changes go through Git, drift is detected, and deletions require an explicit JSON edit."*

---

## Test 8 — Read state without hitting the API

**What it shows:** Instant read-only inspection from the stack state file.

Ask Claude:
> *"Show me the local state for customers/demo/demo_v1/demo_v1.json"*

**Expected result:** Full stack state JSON with all Facebook IDs, returned instantly with no API call.

**Talking point for client:** *"Auditing what's deployed costs zero API calls. The stack state file in Git is always available — no rate limits, no latency."*

---

## Test 9 — Email bot: client submits brief by email

**What it shows:** The full client-facing workflow — no MCP, no Claude Code, just email.

**Prerequisites:** Email bot deployed to Fly.io; `BOT_EMAIL` and `OPERATOR_EMAIL` environment variables set.

1. Send an email to `traffic@ryanbishop.me` with a plain-text brief:

   > *Create a brand awareness campaign called "Summer Launch" with a $5,000 daily budget targeting US adults 25–45. Run June 1 to August 31. Page ID: 123456789.*

2. Within ~30 seconds, the operator (`bishopryant@gmail.com`) receives a forwarded email with the validated Ad Stack template attached.

3. Operator downloads the template, saves it to the appropriate customer folder, and runs `apply_campaigns` via the local MCP server.

**Talking point for client:** *"You email us a brief. We validate the template and apply it. Your campaigns are live. You never log into Ads Manager."*

---

## Cleanup after the demo

The stack state file now tracks the remaining campaign from `demo_v2/demo_v2.json`. To tear it down, remove all campaigns from the Ad Stack (or delete `demo_v2/state.json` manually) and push with an empty campaigns list.

Ask Claude:
> *"Push customers/demo/demo_v2/demo_v2.json with an empty campaigns array and confirm_deletes=true"*

Or delete the objects directly in Ads Manager — AdCode won't recreate anything that isn't in the Ad Stack.

---

## Key messages for the client

1. **The Ad Stack is the desired state.** Add a campaign to create it. Change a field to update it. Remove it to delete it. AdCode makes Facebook match the file — exactly.
2. **Git is the audit trail.** Every change is a commit. Who changed what and when is always answerable.
3. **PRs are the review mechanism.** Budget changes, targeting updates, copy edits — all reviewed before they go live.
4. **No one needs to log into Ads Manager for routine trafficking.** The MCP tools handle it via natural language.
5. **AI policy review before every push.** Catch rejections before Facebook does.
6. **Drift detection keeps the account honest.** Manual changes in Ads Manager are surfaced immediately. The fix is always to push the Ad Stack.
7. **Stack isolation.** Each Ad Stack is a strict contract — AdCode can only see and touch the campaigns declared in that stack. No risk of touching campaigns that belong to another stack.
