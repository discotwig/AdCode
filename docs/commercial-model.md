# Commercial Model

AdCode should be treated as open-source infrastructure tooling with paid services and managed governance layered around it.

The core product is not "AI for Facebook Ads." The stronger category is:

- infrastructure-as-code for digital advertising;
- GitOps for paid media;
- a deterministic control plane for AI-assisted ad operations.

## Open Source Boundary

The open-source project should include the pieces a technical team needs to inspect, self-host, and extend the execution model:

- stack schema;
- local state engine;
- plan/apply engine;
- drift detection;
- MCP server;
- CLI workflows;
- provider clients;
- email mailroom;
- examples and tests.

The goal is adoption and trust. Agencies and growth teams are more likely to use infrastructure tooling when they can inspect state handling, API calls, and reconciliation behavior.

## Paid Boundary

The paid product should avoid charging for the local engine itself. Better monetization candidates are the operational layers teams do not want to run themselves:

- implementation and onboarding;
- migration from manual trafficking workflows;
- custom provider integrations;
- GitHub or CI/CD workflow setup;
- governance and policy design;
- support and SLAs;
- hosted state backend;
- hosted drift monitoring;
- scheduled reconciliation;
- approvals and RBAC;
- cloud execution runners;
- secrets management;
- audit dashboards;
- enterprise integrations.

This mirrors the Terraform/Terraform Cloud split: the local engine drives adoption, and the managed control plane monetizes operational convenience and governance.

## Near-Term Offer

The most practical V1 offer is a contractor service:

1. Client submits a structured campaign template or brief.
2. The mailroom validates or seeds a template.
3. The operator saves the template into a stack folder.
4. The operator runs `plan_stack`.
5. The operator reviews and applies the plan.
6. The operator commits template and state to Git.
7. The client receives a confirmation summary.

This fits how agencies already buy trafficking labor. It avoids SaaS procurement friction while proving that the engine can run real workflows.

## Validation Milestones

1. One agency uses AdCode operationally for real campaign trafficking.
2. The repository has a clean first-run experience for a technical evaluator.
3. A second provider boundary exists, even if the second provider is partial.
4. External contributors can add examples, tests, docs, or provider work without needing private context.
5. Repeated operational pain identifies the right hosted product surface.

## What Not To Build Yet

Do not build the hosted platform before there is production usage. The current architecture deliberately keeps Meta credentials and state off the hosted server. A cloud control plane should only be introduced when user demand proves which hosted capabilities are worth the security and operational burden.

Likely triggers for the hosted product:

- operators need scheduled drift checks;
- teams need approval history beyond GitHub reviews;
- multiple operators need RBAC;
- customers want a dashboard for audit and status;
- agencies want managed execution runners rather than local MCP processes.

## Positioning

Use:

- "Terraform for digital advertising"
- "Infrastructure-as-code for paid media"
- "GitOps for ad operations"
- "AI-safe deployment infrastructure for advertising systems"

Avoid:

- "AI marketing tool"
- "Facebook Ads automation"
- "campaign bot"

The moat is not MCP or CRUD wrappers. The defensible work is provider maturity, state correctness, reconciliation reliability, safe execution, rollback confidence, and operational trust.
