# ADR-017: Feature Roadmap — Governance, Reporting, and IaC Maturity

**Date:** 2026-05-18  
**Status:** Accepted — Phase 23 (Policy as Code) complete; Phase 24 (Cost Estimation) in progress

---

## Context

AdCode's core IaC model is established: declarative JSON stacks, plan/apply/drift, stack-local state, MCP tools for AI-assisted operation. The immediate commercial target is a marketing manager who hires offshore contractors to traffic campaigns and has no systematic visibility into what they set up or whether it is running correctly.

The triggering pain points:

- Contractor-configured campaigns with broadmatch targeting (no interest, audience, or geo constraints) — invisible until spend is already wasted.
- Campaigns that fail to deliver despite declared budgets — no lightweight way to surface this without opening Ads Manager.
- No reviewable artifact between template submission and Facebook push — the contractor applies and the client finds out afterward.

The IaC toolchain for infrastructure (Terraform, CloudFormation) has a mature ecosystem of complementary tools. A brainstorm mapped those patterns onto the ads domain and produced a candidate feature list. This ADR records which features were selected, how they were prioritized, and why others were deferred.

---

## Prioritization Framework

Every candidate feature was evaluated against two questions:

1. **Does it deepen the IaC core?** — Does it fit naturally inside the plan/validate/apply/drift workflow, keeping the tool coherent and the mental model intact?
2. **Does it produce a visible artifact for the marketing manager?** — Does it generate something she can inspect as proof the system is working, without requiring her to use the tool directly?

Features that score high on both axes are built first. Features that score high on one are secondary. Features that score low on both are deferred regardless of technical interest.

This filter is motivated by the buyer/user distinction: the marketing manager is the buyer, not the operator. She never opens a terminal. The question is not "what makes the tool more powerful" but "what makes the operator's output trustworthy enough that she stops relying on Ads Manager screenshots from a contractor."

---

## Candidate Feature Inventory

| Feature | IaC Analog | Deepens IaC core | Visible to buyer | Tier |
| --- | --- | --- | --- | --- |
| Policy as code | OPA/Conftest, Sentinel, cfn-guard | Yes | Yes — policy doc is a reviewable artifact | 1 |
| Cost estimation | Infracost | Yes | Yes — budget delta before apply | 1 |
| PR-driven plan/apply | Atlantis | Yes | Yes — plan visible in PR before merge | 1 |
| Stack documentation / reporting | terraform-docs | Yes | Yes — human-readable campaign summary | 1 |
| Schema linting | cfn-lint, TFLint | Yes | No — operator-facing only | 2 |
| Global variables / budget enforcement | Terragrunt | Yes | Partially — budget caps visible | 2 |
| Delivery snapshot | — | Partially | Yes — is the campaign spending? | 2 |
| Scheduled drift monitoring | — | Yes | Partially — operator alert, not buyer-facing | 2 |
| Stack rollback | — | Yes | No | 3 |
| Environment promotion | Terraform workspaces | Yes | No | 3 |
| Slack / webhook notifications | — | No | No | 3 |
| Full account import | `terraform import` | Yes | No | 3 |
| Client ambiguity reply loop | — | No | No | 3 |
| Stack status digest | — | No | Partially | 3 |
| Contractor submission workflow | — | No | No | 3 |
| Template formatter | `terraform fmt` | No | No | Defer |
| Dependency graph | `terraform graph` | No | No | Defer |
| Template unit tests | Terratest | No | No | Defer |
| Template diff | — | No | No | Defer |
| Variable files per stack | `.tfvars` | — | — | Already solved via stack `.env` |

---

## Decision

### Tier 1 — Build first

These four features are prioritized because they score high on both axes and together tell a complete story to a marketing manager: here is what was planned, here is what it costs, here is who approved it, here is what launched.

**Policy as code**

Introduce a `policies/` directory at the stack or operator level containing declarative rules evaluated at `validate_stack` and `plan_stack` time. Rules are files — versioned, reviewable, and composable. Initial rule library targets the known contractor failure modes: broadmatch targeting detection, missing spend caps, required flight dates, prohibited objective/billing event combinations. The AI policy review in `validate_stack` remains as a second pass for things rules cannot catch.

**Cost estimation**

Before `apply_stack` executes, compute the declared budget delta — how much total spend the stack change adds or removes — and display it as part of the plan output. Support an optional global budget cap per account, defined in global variables, that blocks apply if the stack would exceed it. The data is fully derivable from the template; no Facebook API call is required for the estimate.

**PR-driven plan/apply (Atlantis pattern)**

When a stack template changes in a pull request, automatically run `plan_stack` and post the output as a PR comment. The PR is the review checkpoint: the marketing manager sees the plan before approving the merge, and merge triggers apply. This closes the gap where today the contractor applies first and the client finds out afterward. Implementation is a CI workflow or lightweight webhook; it does not require changes to the core engine.

**Stack documentation / reporting**

`document_stack` generates a human-readable summary of the active stack: campaign hierarchy, declared budgets, flight dates, targeting per ad set, and applied policy results. Output is Markdown formatted for a PR description or client-facing email attachment. This is the "something pretty to look at" artifact — confirmation that what the operator applied matches what the client expects.

### Tier 2 — Build next

**Schema linting**

Provider-aware rules beyond JSON Schema: valid objective/optimization goal/billing event combinations, pixel requirement for conversion objectives, placement and targeting field constraints. Runs at `validate_stack` time before the AI pass. Implemented as a deterministic rule set, not AI-generated, so failures are actionable and reproducible.

**Global variables / budget enforcement**

An operator-level `globals.json` (or `.env`-style file) that supplies shared values — default audience IDs, page IDs, account-level budget caps — injected into stacks at plan time via a `${VAR}` interpolation syntax. Complements the existing stack-level `.env` without replacing it: `.env` handles credentials and stack-specific runtime values; globals handle policy-level shared configuration.

**Delivery snapshot**

`delivery_stack` pulls spend-to-date, impressions, and delivery status for each managed campaign via the Facebook API and compares against declared budget and flight dates. Not a pacing dashboard — a lightweight "is this thing actually running" check scoped to the active stack. Surfaces the specific failure mode (zero spend despite active status) that prompted this roadmap.

**Scheduled drift monitoring**

Run `drift_stack` on a configurable cron schedule and email the operator a summary of out-of-band changes. Catches contractor edits made directly in Ads Manager between plan/apply cycles. Low implementation cost given the drift engine already exists.

### Tier 3 — Consider later

Stack rollback, environment promotion, Slack/webhook notifications, full account import, client ambiguity reply loop, stack status digest, and contractor submission workflow enhancements are real use cases but address problems the target buyer does not have yet. Revisit when the tier 1 and 2 features are in use.

### Deferred

Template formatter, dependency graph, template unit tests (Terratest pattern), and template diff are developer ergonomics tools. They score low on both prioritization axes and are invisible to the buyer. Deferred indefinitely unless a developer-operator persona emerges as a distinct target.

### Already solved

Per-stack variable files (`.tfvars` equivalent) are already handled by the stack-local `.env` file per ADR-014. The stack checkout model — switching stacks by switching config — was designed specifically to support this. Global variables (tier 2) are additive, not a replacement.

---

## Consequences

### Positive

- Tier 1 features together form a complete pitch to the marketing manager persona: governance, cost control, review checkpoint, and confirmation artifact.
- Policy as code makes the broadmatch contractor failure mode detectable at plan time rather than post-spend.
- PR-driven plan/apply adds a human review checkpoint without changing the core engine.
- The prioritization framework gives a clear test for evaluating future feature requests: does it deepen the IaC core, produce a buyer-visible artifact, or both?

### Negative

- Tier 1 build commitment delays tier 2 features, particularly schema linting, which is foundational for policy quality.
- PR-driven plan/apply requires CI infrastructure that operators must configure per-stack; it is not zero-setup.
- Delivery snapshot introduces the first live Facebook read tool that is observability-oriented rather than IaC-oriented, which slightly tensions ADR-015's strict IaC boundary. Acceptable because it is scoped to managed stack objects only.

---

## Deferred

- Google Ads, TikTok, LinkedIn provider support — roadmap item, not blocked by this ADR.
- Hosted state and remote runs — SaaS V2 scope per ADR-008.
- RBAC and multi-operator approval flows — requires tenancy model not yet defined.
