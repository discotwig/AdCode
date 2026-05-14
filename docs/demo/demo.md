# AdCode Demo Guide

A step-by-step walkthrough for testing and demonstrating AdCode through an MCP client such as Cursor. All demo campaigns should be created as `PAUSED`, so no ads serve and no budget is spent.

AdCode follows the infrastructure-as-code model: the active Ad Stack file is the desired state, and AdCode makes Facebook match it. `plan_stack` is the equivalent of `terraform plan`; `apply_stack` is the equivalent of `terraform apply`.

The MCP server is scoped to one stack at startup. Prompts should refer to "this stack" or "the active stack" rather than passing file paths into each tool call. This is intentional: the AI can only operate on the stack selected by the local operator.

## Before You Start

Start the MCP server with the stack you want to test:

```bash
python src/mcp_server.py --config customers/<slug>/<stack-name>/<stack-name>_template.json
```

The stack folder should contain:

```text
customers/<slug>/<stack-name>/
  <stack-name>_template.json
  .env
  state.json
```

The template contains `account_id`. The `.env` file contains provider and AI credentials. Startup only loads local configuration; Facebook is contacted only when a provider-backed tool runs.

## Test 1: Show The Active Stack

**What it shows:** The MCP server is scoped to the expected stack.

Prompt:

```text
Show me the active AdCode stack.
```

**Expected result:** The response shows the active template path, stack directory, state path, account ID, and whether `.env` exists. It must not print credential values.

**Talking point:** The operator chooses the stack at server startup. The AI does not get to browse or choose an arbitrary ad account.

## Test 2: Validate Without Facebook

**What it shows:** Schema and policy checks happen before provider calls.

Prompt:

```text
Validate this stack.
```

**Expected result:** The response summarizes JSON Schema validation and AI policy review. No Facebook API call should be required.

**Talking point:** Problems are caught before anything touches the ad platform.

## Test 3: Preview The Plan

**What it shows:** The full changeset before any write.

Prompt:

```text
Plan this stack and summarize exactly what would change.
```

**Expected result:** The response shows creates, updates, deletes, or a no-op message.

Example:

```text
Plan: 4 CreateCampaign, 1 CreateAdSet, 1 CreateAd

  CreateCampaign: AdCode Demo - Brand Awareness
  CreateAdSet: AdCode Demo - Brand Awareness
  CreateAd: AdCode Demo - Brand Awareness
```

**Talking point:** This is the review gate. The operator sees what will happen before Facebook changes.

## Test 4: Apply The Stack

**What it shows:** The reviewed plan is applied to Facebook and local state is updated.

Prompt, if the plan has no deletes:

```text
Apply this stack.
```

Prompt, only if the reviewed plan includes intentional deletes:

```text
Apply this stack with confirm_deletes=true.
```

**Expected result:** The response summarizes applied creates, updates, and deletes. New Facebook IDs are persisted into the template and `state.json`.

**Talking point:** Applies are deterministic and stateful. Running the same stack again should not create duplicates.

## Test 5: Confirm Idempotency

**What it shows:** Reapplying unchanged desired state is a no-op.

Prompt:

```text
Plan this stack again and confirm whether anything would change.
```

**Expected result:**

```text
No changes detected.
```

or equivalent no-op language.

**Talking point:** The state file lets AdCode distinguish managed objects from new objects.

## Test 6: Inspect Local State

**What it shows:** The stack state can be inspected without calling Facebook.

Prompt:

```text
Show me the local state for this stack.
```

**Expected result:** The response returns tracked campaigns, ad sets, ads, Facebook IDs, and last-pushed params from `state.json`.

**Talking point:** Git plus state gives an audit trail that is available without rate limits or browser access.

## Test 7: Check Managed Drift

**What it shows:** AdCode detects when managed objects differ from Facebook.

Optional setup: manually change a managed campaign or ad set in Facebook Ads Manager.

Prompt:

```text
Check drift for this stack.
```

**Expected result:** The response reports missing managed objects or field mismatches. It should not report unrelated campaigns or ad sets elsewhere in the account.

Example:

```text
[FIELD_MISMATCH] CAMPAIGN: AdCode Demo - Brand Awareness
    status: expected='PAUSED' actual='ACTIVE'
```

**Talking point:** Drift is stack-scoped. The tool is not a general live account scanner.

## Test 8: Search Import Candidates

**What it shows:** The AI can discover supported live resources that belong under campaigns declared in the active stack.

Prompt:

```text
Search for ad set import candidates for this stack.
```

**Expected result:** The response lists unmanaged live ad sets only if they sit under campaigns declared in the active stack template.

**Talking point:** This is the controlled import path. It is useful for adopting objects created manually without turning the MCP server into a broad account console.

## Test 9: Import A Specific Ad Set

**What it shows:** A supported live object can be adopted into the template and state without pushing changes to Facebook.

Prompt:

```text
Import the ad set named "<AD SET NAME>" into this stack.
```

**Expected result:** The response says the ad set was imported into the stack template and state. The template now contains the imported ad set with Facebook-returned fields, and `state.json` tracks its `fb_id`.

Then re-plan:

```text
Plan this stack again and confirm whether the import created any spurious changes.
```

**Expected result:** The plan should be clean or limited to intentional differences you can explain.

**Talking point:** Import is local read-then-write. It does not change Facebook; it brings live objects under source control.

## Test 10: Negative Tool Surface Tests

**What it shows:** The public MCP surface is intentionally not a general ad account console.

Prompts:

```text
List all campaigns in the ad account.
```

```text
Pause all campaigns matching Black Friday.
```

**Expected result:** The MCP server should not expose old broad live tools such as `list_campaigns`, `get_campaign_status`, `get_campaign_export`, `find_duplicates`, or `pause_campaigns`.

**Talking point:** This is the safety boundary. The contractor can see and change only what the active stack manages, except for narrow import discovery under declared campaigns.

## Optional: Email Intake Demo

The email mailroom is separate from the execution engine. It receives client briefs, validates or seeds templates, and forwards them to the operator. It does not hold Facebook credentials, run `plan_stack`, run `apply_stack`, or store stack state.

Demo flow:

1. Client sends a JSON, Excel, or plain-text brief by email.
2. The mailroom replies with validation feedback or a starter template.
3. The operator saves the reviewed template into a stack folder.
4. The operator starts the MCP server with `--config`.
5. The operator runs the stack prompts above.

## Cleanup

To tear down a demo stack, remove the campaigns from the active stack template, then run:

```text
Plan this stack and summarize exactly what would change.
```

If the delete plan is correct:

```text
Apply this stack with confirm_deletes=true.
```

Commit the updated template and `state.json` together after the apply.

## Key Messages

1. **The stack is the contract.** The AI operates on the active stack, not the whole ad account.
2. **Plan before apply.** Every provider write should be previewed.
3. **State prevents duplicates.** Facebook IDs are tracked after apply and import.
4. **Drift is managed-object drift.** Unrelated live account objects are not part of the stack.
5. **Import is controlled.** Today, import supports ad sets under declared campaigns.
6. **The email bot is intake only.** Execution stays in the local stack-scoped MCP server.
