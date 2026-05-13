# Roadmap

AdCode is alpha infrastructure tooling. The core Meta plan/apply/state workflow works, but the public project should prioritize operational confidence before hosted product work.

## Now

- Improve first-run examples and docs.
- Keep the local stack workflow simple and explicit.
- Expand tests around state, drift, deletes, and renames.
- Keep the hosted email mailroom as an optional integration only.
- Gather real agency workflow feedback.

## Next

- Define a provider interface around campaign hierarchy operations.
- Add a partial second provider to prove the abstraction.
- Add import workflows for existing campaigns, not just ad sets.
- Improve local CLI ergonomics around plan, apply, and drift.
- Add richer example plans and drift reports.
- Add lint/type-check tooling once the current test baseline is stable.

## Later

- Scheduled drift checks.
- Approval history beyond Git commits.
- Hosted state backend.
- RBAC and workspace management.
- Cloud execution runners.
- Audit dashboard.
- Enterprise integrations.

## Explicitly Deferred

A hosted apply platform is deferred until real usage proves the requirements. Moving execution into the cloud changes the credential, state, approval, and liability model. The current architecture keeps Facebook credentials local and state in Git by design.
