# Contractor Mistakes Demo Stack

This example demonstrates AdCode catching real contractor trafficking errors before a campaign spends money.

## Intentional issues in `contractor_mistakes.json`

| Issue | Affected Object | Policy Rule | Severity |
| --- | --- | --- | --- |
| No interests, behaviors, or custom audiences | Ad set "All US — No Targeting" | `broadmatch` | ERROR |
| Missing flight end date | Ad set "All US — No Targeting" | `end-time-required` | ERROR |
| No spend cap on campaign | Campaign "Q3 Brand Awareness" | `spend-cap-required` | WARNING |
| Budget cap exceeded ($450/day declared vs $400 cap) | Account-level | `ACCOUNT_BUDGET_CAP` env var | BLOCKED |

The second campaign ("Retargeting — Site Visitors") is intentionally clean to show the contrast: proper targeting with a custom audience, a defined end date, and a spend cap.

## Demo flow

This demo requires no live Meta account. Set `--skip-connection-check` and use `document_stack` to generate the review packet locally.

### 1. Set up the stack

```bash
cp examples/contractor-mistakes/.env.example examples/contractor-mistakes/.env
# Fill in ANTHROPIC_API_KEY (required for AI policy pass)
# Leave FB_* values as placeholders — they are not used for document_stack
```

### 2. Start the MCP server

```bash
python src/mcp_server.py \
  --config examples/contractor-mistakes/contractor_mistakes.json \
  --skip-connection-check
```

### 3. Run the demo sequence

From your MCP client:

```
validate_stack     # Shows policy errors and warnings
plan_stack         # Shows planned changes and budget delta
document_stack     # Generates the full Campaign Review Packet
```

### What the review packet shows

- **Executive Summary**: 2 campaigns, 2 ad sets, 2 ads — status BLOCKED
- **Approval Recommendation**: blocking issues prevent apply
- **Budget Impact**: $450/day declared, exceeds $400 cap
- **Policy Results**: 2 errors (broadmatch, end-time-required), 1 warning (spend-cap-required)
- **Targeting Summary**: broad targeting flag on "All US — No Targeting"
- **Flight Dates**: missing end date on "All US — No Targeting"
- **Human Review Checklist**: 4 action items before this stack can be applied
