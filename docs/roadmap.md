# Roadmap

AdCode is alpha infrastructure tooling. The core Meta plan/apply/state workflow works, but the public project should prioritize operational confidence before hosted product work.

Roadmap decisions should be evaluated against AdCode's product pillars: operational safety, speed, governance, explainability, and integration. See [ADR-019](decisions/019-product-pillars.md).

## Now

- Improve first-run examples and docs.
- Keep the local stack workflow simple and explicit.
- Expand tests around state, drift, deletes, and renames.
- Keep the hosted email mailroom as an optional integration only.
- Gather real agency workflow feedback.
- Keep new feature work tied to the product pillars.

## Next

- Add a workspace/registered-stack model so users and agents select approved stacks by ID instead of arbitrary file/account combinations.
- Add read-only stack discovery tools such as `list_stacks` and `describe_stack`.
- Add durable plan records and `plan_id` as a review artifact.
- Move organizational apply workflows toward `apply_plan(plan_id, ...)` instead of ambient direct apply.
- Add a local audit log for mutating operations and important live reads.
- Add richer plan, drift, import, and risk summaries for non-technical review.
- Improve local CLI ergonomics around plan, apply, and drift.
- Add lint/type-check tooling once the current test baseline is stable.

## Later

- Define a provider interface around campaign hierarchy operations.
- Add a partial second provider after the Meta governance model is stronger.
- Add import workflows for existing campaigns, not just ad sets.
- Scheduled drift checks.
- Approval history beyond Git commits.
- Hosted state backend.
- RBAC and workspace management.
- Cloud execution runners.
- Audit dashboard.
- Enterprise integrations.

## Explicitly Deferred

A hosted apply platform is deferred until real usage proves the requirements. Moving execution into the cloud changes the credential, state, approval, and liability model. The current architecture keeps Facebook credentials local and state in Git by design.
