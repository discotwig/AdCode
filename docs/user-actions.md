# AdCode — End-User Action Inventory

Realistic actions a user (associate, specialist, or client) might ask AdCode to perform. Grouped by category. Not all are currently supported — this is the goal list for alignment on direction.

---

## Campaign Creation

- [x] **Create campaigns from an Excel attachment** — client emails an Excel media plan; system ingests it and creates campaigns on Facebook.
- [ ] **Create campaigns from a plain-text brief** — client emails a paragraph describing what they want; system extracts intent and creates campaigns.
- [x] **Create campaigns from a JSON file** — operator drops a hand-authored or template JSON into the repo and applies it.
- [ ] **Duplicate an existing campaign** — create a new campaign using another as a template, with specified field overrides (new name, new budget, new dates).
- [ ] **Create a seasonal variant of a campaign** — copy an active campaign and adjust flight dates, budgets, and creative for a holiday or event.
- [ ] **Create campaigns in bulk from a multi-tab Excel** — each tab is a different campaign or market; ingest all in one pass.

---

## Campaign Updates

- [ ] **Update budgets across a set of campaigns** — "increase daily budget by 20% on all campaigns tagged Q2."
- [ ] **Update flight dates** — extend or shorten end dates on campaigns matching a name pattern or label.
- [ ] **Swap creative on an existing ad** — replace the image URL or copy in an ad without touching campaign or ad-set settings.
- [ ] **Update targeting on an ad set** — change geographic, demographic, or interest targeting via a JSON patch or natural-language instruction.
- [ ] **Rename a campaign** — update the campaign name in JSON and have the system reconcile via `fb_id` so no duplicate is created.
- [ ] **Apply a template change to many campaigns at once** — e.g., add a UTM parameter to every ad's landing page URL.
- [ ] **Update bid strategy or optimization goal** — change from lowest cost to cost cap, or switch optimization goal, across a set of ad sets.

---

## Campaign Lifecycle

- [x] **Pause campaigns matching a filter** — "pause everything with 'Black Friday' in the name."
- [ ] **Resume (un-pause) campaigns** — reactivate paused campaigns by name, tag, or fb_id.
- [ ] **Archive campaigns** — move campaigns to archived state once a flight ends.
- [ ] **Delete campaigns** — remove campaigns and their ad sets/ads from Facebook (currently requires `confirm_deletes=true`).
- [ ] **Schedule a campaign to go live at a future date** — set `start_time` in the JSON; system applies immediately and Facebook activates on schedule.

---

## Inspection & Reporting

- [x] **"What's currently live?"** — list all active campaigns on the account with status, budget, and flight dates.
- [x] **"What does the system think is live?"** — read the local state file to see what AdCode last pushed, without hitting the API.
- [x] **Check if a specific campaign is live** — look up a campaign by name or fb_id and return its current status.
- [x] **Get a drift report** — compare local state to Facebook actuals and surface anything that has changed outside AdCode.
- [x] **Export the full campaign hierarchy** — return campaigns, ad sets, and ads in a single structured response (currently `get_campaign_export`).
- [ ] **Explain what changed since the last push** — summarize the diff between the current JSON and the last applied state.
- [x] **Find duplicate campaigns** — detect campaigns with identical names created outside AdCode or via double-apply (currently `find_duplicates`).

---

## Approval & Review Workflow

- [x] **Preview a plan before applying** — show creates, updates, and deletes that would result from applying a JSON, without touching Facebook.
- [ ] **Approve a pending plan** — operator replies GO to a plan email; system applies and notifies the client.
- [ ] **Hold a pending plan** — operator replies HOLD; system notifies the client and discards the pending brief.
- [ ] **Re-request a held or expired brief** — operator asks the client to resubmit; system tracks no state for this (manual today).
- [ ] **Request changes before approval** — operator replies with questions or edits; system routes clarifications back to the client.

---

## Ingestion & Ambiguity Resolution

- [ ] **Resolve flagged ambiguities in an Excel brief** — client replies to an ambiguity email with answers; system re-extracts and proceeds.
- [ ] **Override an AI interpretation** — operator corrects an extracted field value before the plan is applied.
- [x] **Adopt untracked ad sets from Facebook** — import ad sets created directly in Ads Manager into the JSON and state file (`import_adsets`).
- [ ] **Handle a malformed Excel** — system returns a structured error listing what is missing or unreadable, rather than silently failing.

---

## Policy & Validation

- [x] **Validate a JSON before pushing** — run schema validation and AI policy checks; return errors and warnings without touching Facebook.
- [ ] **Flag a special ad category** — warn when the campaign content triggers HOUSING, EMPLOYMENT, or CREDIT category requirements.
- [ ] **Detect prohibited content** — AI flags copy or creative patterns that frequently cause Facebook rejection before the push is attempted.

---

## Multi-Campaign / Account Operations

- [ ] **Apply changes across multiple campaigns in one command** — batch update a set of campaigns defined in one JSON file.
- [ ] **Pause all campaigns on an account** — emergency stop across the entire account.
- [ ] **Compare two campaigns** — show field-by-field diff between two campaign definitions (local JSON or Facebook actuals).
- [ ] **Copy a campaign to a different account** — export a campaign from one account's state and apply it to another. *(not supported; multi-account is V2)*

---

## Onboarding & Setup

- [ ] **Set up a new customer** — create the directory scaffold, config, and `.env` for a new client account.
- [ ] **Connect an existing Facebook account** — link a `FB_ACCOUNT_ID` and credentials without losing existing campaigns.
- [ ] **Import all existing Facebook campaigns into state** — bootstrap the state file from what's already live, without overwriting anything.

---

## Currently Supported (reference)

| Action | MCP Tool |
| --- | --- |
| Ingest Excel brief | `ingest_excel` |
| Validate + preview plan | `plan_campaigns` |
| Apply a plan to Facebook | `apply_campaigns` |
| List live campaigns | `list_campaigns` |
| Pause campaigns | `pause_campaigns` |
| Get local state | `get_local_state` |
| Get campaign status | `get_campaign_status` |
| Get drift report | `get_drift_report` |
| Export full hierarchy | `get_campaign_export` |
| Find duplicates | `find_duplicates` |
| Adopt untracked ad sets | `import_adsets` |
